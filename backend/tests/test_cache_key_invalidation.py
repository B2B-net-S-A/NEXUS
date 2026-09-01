"""AI-P0-06 — cache invalidation on the dimensions the key ignores.

The match-score cache key is (candidate, job, profile) + a global
``scoring_algorithm_version()`` string. That string tracks the scoring contract
flag but not: per-profile weights, a candidate's re-embedding, or the embedding
model. Three gaps closed:

(a) editing a weight profile in place → ``mark_stale_for_profile`` invalidates
    every cached score for that profile_id (else old-weight scores keep serving);
(b) an outbox re-embed of a candidate → ``mark_stale_for_candidate`` (else the
    cached semantic layer goes stale);
(c) the embedding model is folded into ``scoring_algorithm_version()`` so a
    VOYAGE_MODEL swap invalidates everything.

The invalidation mechanism is proven behaviourally against a real Postgres; the
three call-sites are pinned structurally so a future edit can't silently drop
them.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job
from app.models.match_score import CandidateJobMatchScore
from app.services.match_score_cache import mark_stale_for_profile
from app.services.scoring_service import scoring_algorithm_version

BACKEND = Path(__file__).resolve().parents[1]


def test_scoring_version_includes_embedding_model() -> None:
    """A VOYAGE_MODEL swap must change the version → full cache invalidation."""
    from app.core.config import settings

    assert f"emb-{settings.VOYAGE_MODEL}" in scoring_algorithm_version(), (
        "embedding model no longer folded into the scoring version (AI-P0-06 c)"
    )


async def test_mark_stale_for_profile_flips_only_that_profile() -> None:
    u = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Inv Client {u}")
        cand = Candidate(name="Inv", lastname=f"Alid-{u}")
        db.add_all([client, cand])
        await db.flush()
        job = Job(title=f"Inv Job {u}", client_id=client.id)
        db.add(job)
        await db.flush()

        pid_target, pid_other = 700100 + int(u[:4], 16) % 1000, 800100
        for pid in (pid_target, pid_other):
            db.add(
                CandidateJobMatchScore(
                    candidate_id=cand.id,
                    job_id=job.id,
                    profile_id=pid,
                    total_score=50.0,
                    breakdown={},
                    scoring_algorithm_version="test",
                    stale=False,
                )
            )
        await db.commit()

        n = await mark_stale_for_profile(db, pid_target)
        await db.commit()
        assert n >= 1

        rows = (
            await db.execute(
                select(
                    CandidateJobMatchScore.profile_id, CandidateJobMatchScore.stale
                ).where(CandidateJobMatchScore.candidate_id == cand.id)
            )
        ).all()
    by_pid = {r.profile_id: r.stale for r in rows}
    assert by_pid[pid_target] is True, "target profile's score not invalidated"
    assert by_pid[pid_other] is False, "sibling profile wrongly invalidated"


from tests._ast_calls import calls_in as _calls_in


def test_update_and_delete_profile_invalidate_cache() -> None:
    for func in ("update_profile", "delete_profile"):
        calls = _calls_in("app/api/scoring_weights.py", func)
        assert "mark_stale_for_profile" in calls, (
            f"{func} no longer invalidates cached scores on weight change (AI-P0-06 a)"
        )


def test_reembed_success_marks_candidate_scores_stale() -> None:
    """The outbox re-index success path must invalidate the candidate's scores."""
    path = BACKEND / "app/services/index_outbox_service.py"
    src = path.read_text(encoding="utf-8")
    assert "mark_stale_for_candidate" in src, (
        "outbox re-embed no longer invalidates cached match scores (AI-P0-06 b)"
    )
    # And it is guarded to the candidate-upsert branch, not fired blindly.
    assert "ev.entity_type == CANDIDATE" in src
