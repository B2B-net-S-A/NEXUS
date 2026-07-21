"""AI-P0-04 — editing a candidate's profile re-embeds it.

The durable outbox existed but was wired into only the CV-ingest paths
(create_from_cv, upload_cv, invite-apply). The interactive profile-edit PATCH
``update_candidate`` mutated embedding-text fields (skills, verified_tech, tags,
experience, …) and even invalidated the score cache, but never re-embedded — so
a candidate curated by hand stayed searchable on months-stale vector content.

Fix: ``update_candidate`` now calls ``schedule_or_embed_candidate`` when any
``_EMBEDDING_TEXT_FIELDS`` field changed (outbox-on → fast enqueue; off → inline
embed), and NOT when only a non-text field (e.g. salary_expectation) changed.

Behavioural against a real Postgres, patching the re-embed call so no Voyage /
Qdrant network is needed; plus an AST guard on the wiring.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.api.candidates import update_candidate
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.user import User, UserRole
from app.schemas.candidate import CandidateUpdate

BACKEND = Path(__file__).resolve().parents[1]


async def _seed(db) -> tuple[int, int]:
    """Return (candidate_id, user_id) — a real user is needed for the audit
    Activity's FK."""
    u = uuid.uuid4().hex[:8]
    user = User(
        email=f"reembed-{u}@example.com",
        password_hash=hash_password("x"),
        name="Editor",
        role=UserRole.recruiter,
        is_active=True,
    )
    cand = Candidate(name="Reembed", lastname=f"Test-{u}")
    db.add_all([user, cand])
    await db.flush()
    ids = (cand.id, user.id)
    await db.commit()
    return ids


async def test_patch_reembeds_when_skills_change(monkeypatch) -> None:
    import app.services.index_outbox_service as outbox

    embed = AsyncMock(return_value=True)
    monkeypatch.setattr(outbox, "schedule_or_embed_candidate", embed)

    async with AsyncSessionLocal() as db:
        cid, uid = await _seed(db)
        await update_candidate(
            cid,
            CandidateUpdate(skills=[{"name": "Python"}]),
            current_user=SimpleNamespace(id=uid),
            db=db,
        )
    embed.assert_awaited_once()
    assert embed.await_args.args[0] == cid


async def test_patch_does_not_reembed_on_nontext_field(monkeypatch) -> None:
    import app.services.index_outbox_service as outbox

    embed = AsyncMock(return_value=True)
    monkeypatch.setattr(outbox, "schedule_or_embed_candidate", embed)

    async with AsyncSessionLocal() as db:
        cid, uid = await _seed(db)
        # salary_expectation invalidates the score cache but is NOT embedding text.
        await update_candidate(
            cid,
            CandidateUpdate(salary_expectation=12000),
            current_user=SimpleNamespace(id=uid),
            db=db,
        )
    embed.assert_not_awaited()


def test_update_candidate_wires_reembed() -> None:
    """Structural guard: the PATCH must call schedule_or_embed_candidate,
    gated on the embedding-text field set."""
    src = (BACKEND / "app/api/candidates.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "update_candidate"
    )
    body = ast.get_source_segment(src, fn) or ""
    assert "schedule_or_embed_candidate" in body, (
        "update_candidate no longer re-embeds on profile edit (AI-P0-04 regressed)"
    )
    assert "_EMBEDDING_TEXT_FIELDS" in body, (
        "re-embed is no longer gated on the embedding-text field set"
    )
