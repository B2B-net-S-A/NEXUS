"""M3-ACT-01 — every stage-creating path snapshots the CV + audits.

The single-assign endpoint (recommendations.assign_candidate_to_job) creates the
CandidateStage, flushes, and calls create_original_cv_snapshot — one
CandidateStageCV + one ``snapshot_created`` Activity, the evidence of what was
sent. Two sibling paths skipped it, so what the system remembered about an
assignment depended on which button was pressed (a client dispute could lack the
sent CV): ``proposals_bulk.bulk_add_proposals`` and
``job_shortlist.promote_shortlist_entry``. Both now hold the invariant.

Bulk-add is verified behaviourally (real Postgres); both wirings are also pinned
structurally so a future edit can't silently drop them.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import func, select

from app.api.proposals_bulk import BulkProposalsRequest, bulk_add_proposals
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.client import Client
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User, UserRole

BACKEND = Path(__file__).resolve().parents[1]


async def test_bulk_add_snapshots_each_candidate_cv() -> None:
    u = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"snap-{u}@example.com",
            password_hash=hash_password("x"),
            name="Rec",
            role=UserRole.recruiter,
            is_active=True,
        )
        client = Client(name=f"Snap {u}")
        c1 = Candidate(name="A", lastname=f"One-{u}")
        c2 = Candidate(name="B", lastname=f"Two-{u}")
        db.add_all([user, client, c1, c2])
        await db.flush()
        # Rekruter musi należeć do zespołu oferty — `bulk_add_proposals` ma
        # teraz tę samą bramkę zakresu co shortlista. Ten test sprawdza
        # inwariant snapshotu CV, więc aktor jest właścicielem rekrutacji,
        # a nie osobą z zewnątrz.
        job = Job(title=f"Snap Job {u}", client_id=client.id, recruiter_id=user.id)
        db.add(job)
        await db.commit()
        job_id, uid, ids = job.id, user.id, [c1.id, c2.id]

    async with AsyncSessionLocal() as db:
        user = await db.get(User, uid)
        # Trasa od 23.09.2026 bierze `request` (integracja = bez blokady 12 h).
        resp = await bulk_add_proposals(
            request=SimpleNamespace(state=SimpleNamespace()),
            job_id=job_id,
            body=BulkProposalsRequest(candidate_ids=ids),
            current_user=user,
            db=db,
        )
    assert set(resp.added) == set(ids), resp

    async with AsyncSessionLocal() as db:
        # one CandidateStageCV snapshot per created stage for this job
        stage_ids = (
            (
                await db.execute(
                    select(CandidateStage.id).where(
                        CandidateStage.job_id == job_id,
                        CandidateStage.candidate_id.in_(ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        snaps = await db.scalar(
            select(func.count(CandidateStageCV.id)).where(
                CandidateStageCV.candidate_stage_id.in_(stage_ids)
            )
        )
    assert len(stage_ids) == 2 and snaps == 2, (
        f"expected one CV snapshot per bulk-added stage, got {snaps} for "
        f"{len(stage_ids)} stages (M3-ACT-01)"
    )


def _fn_calls(module_rel: str, func_name: str) -> set[str]:
    text = (BACKEND / module_rel).read_text(encoding="utf-8")
    tree = ast.parse(text)
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == func_name
    )
    return {
        n.func.id
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }


def test_both_assign_paths_wire_the_snapshot() -> None:
    # Od 17.09.2026 bulk-add i auto-dopasowanie dzielą rdzeń
    # `add_candidates_to_job` — to on musi robić snapshot, a oba wejścia muszą
    # przez niego przechodzić.
    for module_rel, fn in (
        ("app/api/proposals_bulk.py", "add_candidates_to_job"),
        ("app/api/job_shortlist.py", "promote_shortlist_entry"),
    ):
        assert "create_original_cv_snapshot" in _fn_calls(module_rel, fn), (
            f"{fn} no longer snapshots the assignment CV (M3-ACT-01 regressed)"
        )
    for module_rel, fn in (
        ("app/api/proposals_bulk.py", "bulk_add_proposals"),
        ("app/services/auto_match_service.py", "_apply_decisions"),
    ):
        assert "add_candidates_to_job" in _fn_calls(module_rel, fn), (
            f"{fn} bypasses the shared add path that snapshots the CV (M3-ACT-01)"
        )
