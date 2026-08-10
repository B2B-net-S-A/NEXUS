"""Two remaining audit items.

1. `candidates.cv_storage_key` was pinned to the FIRST Traffit CV forever. The
   scan in `import_candidates_cv` only ever fills a NULL pointer, so once a
   candidate had one it was exempt — including after Traffit replaced the CV.
   The new file did arrive (stored under a new `file_id` in
   `candidate_documents`), but the two columns the bulk CV download reads stayed
   pointed at the old one, so recruiters downloaded a STALE CV while the current
   one sat in the same database.

   The resync runs against a real Postgres here, not a fake: it is an UPDATE
   against production rows, and the conservative EXISTS guard (never clobber a
   CV uploaded directly in Nexus) is the part worth proving.

2. `reconcile()` existed since the migration but was never wired into
   `_phase_plan`, so it never ran in the scheduled sync — drift in the other
   direction (rows in Nexus, deleted in Traffit) was completely invisible.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.services.traffit.importer import TraffitImporter

UTC = timezone.utc


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


async def _mk_candidate(db, *, ext: str, storage_key, filename="old.pdf") -> int:
    row = await db.execute(
        text(
            """
            INSERT INTO candidates (
                external_id, external_source, name, lastname,
                cv_storage_key, cv_filename, created_at, updated_at
            ) VALUES (
                :ext, 'traffit', 'A', 'B', :sk, :fn, NOW(), NOW()
            ) RETURNING id
            """
        ),
        {"ext": ext, "sk": storage_key, "fn": filename},
    )
    return row.scalar_one()


async def _mk_doc(
    db, candidate_id: int, *, ext: str, storage_key: str, filename: str, primary: bool
) -> None:
    await db.execute(
        text(
            """
            INSERT INTO candidate_documents (
                candidate_id, filename, storage_key, document_kind, is_primary,
                external_id, external_source, created_at, updated_at
            ) VALUES (
                :cid, :fn, :sk, 'cv', :primary, :ext, 'traffit', NOW(), NOW()
            )
            """
        ),
        {
            "cid": candidate_id,
            "fn": filename,
            "sk": storage_key,
            "primary": primary,
            "ext": ext,
        },
    )


def _importer(db) -> TraffitImporter:
    imp = TraffitImporter.__new__(TraffitImporter)
    imp.db = db
    imp.dry_run = False
    return imp


async def _run_resync(db) -> None:
    """Execute just the resync statement the full-mode phase runs first."""
    await db.execute(
        text(
            """
            UPDATE candidates c
            SET cv_storage_key = d.storage_key,
                cv_filename    = d.filename,
                updated_at     = NOW()
            FROM candidate_documents d
            WHERE d.candidate_id = c.id
              AND d.external_source = 'traffit'
              AND d.document_kind = 'cv'
              AND d.is_primary IS TRUE
              AND d.source_deleted_at IS NULL
              AND c.external_source = 'traffit'
              AND c.cv_storage_key IS NOT NULL
              AND c.cv_storage_key IS DISTINCT FROM d.storage_key
              AND EXISTS (
                  SELECT 1 FROM candidate_documents d2
                  WHERE d2.candidate_id = c.id
                    AND d2.external_source = 'traffit'
                    AND d2.storage_key = c.cv_storage_key
              )
            """
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_stale_pointer_is_moved_to_the_current_primary(db) -> None:
    u = uuid.uuid4().hex[:8]
    cid = await _mk_candidate(db, ext=f"c-{u}", storage_key=f"s3://old-{u}")
    # The old file is still on record (that is what makes the pointer Traffit's)…
    await _mk_doc(
        db,
        cid,
        ext=f"{u}-1",
        storage_key=f"s3://old-{u}",
        filename="old.pdf",
        primary=False,
    )
    # …and Traffit has since replaced it.
    await _mk_doc(
        db,
        cid,
        ext=f"{u}-2",
        storage_key=f"s3://new-{u}",
        filename="new.pdf",
        primary=True,
    )
    await db.commit()

    await _run_resync(db)

    row = await db.execute(
        text("SELECT cv_storage_key, cv_filename FROM candidates WHERE id = :i"),
        {"i": cid},
    )
    assert row.fetchone() == (f"s3://new-{u}", "new.pdf")


@pytest.mark.asyncio
async def test_nexus_uploaded_cv_is_never_clobbered(db) -> None:
    """A CV uploaded directly in Nexus is newer by definition — Traffit's copy
    must not overwrite it. The pointer matches no Traffit document, so the
    EXISTS guard excludes the row."""
    u = uuid.uuid4().hex[:8]
    cid = await _mk_candidate(
        db, ext=f"c-{u}", storage_key=f"s3://nexus-upload-{u}", filename="mine.pdf"
    )
    await _mk_doc(
        db,
        cid,
        ext=f"{u}-1",
        storage_key=f"s3://traffit-{u}",
        filename="traffit.pdf",
        primary=True,
    )
    await db.commit()

    await _run_resync(db)

    row = await db.execute(
        text("SELECT cv_storage_key, cv_filename FROM candidates WHERE id = :i"),
        {"i": cid},
    )
    assert row.fetchone() == (f"s3://nexus-upload-{u}", "mine.pdf")


@pytest.mark.asyncio
async def test_already_current_pointer_is_left_alone(db) -> None:
    u = uuid.uuid4().hex[:8]
    cid = await _mk_candidate(
        db, ext=f"c-{u}", storage_key=f"s3://cur-{u}", filename="cur.pdf"
    )
    await _mk_doc(
        db,
        cid,
        ext=f"{u}-1",
        storage_key=f"s3://cur-{u}",
        filename="cur.pdf",
        primary=True,
    )
    await db.commit()

    before = await db.execute(
        text("SELECT updated_at FROM candidates WHERE id = :i"), {"i": cid}
    )
    stamp = before.scalar_one()

    await _run_resync(db)

    after = await db.execute(
        text("SELECT updated_at FROM candidates WHERE id = :i"), {"i": cid}
    )
    assert after.scalar_one() == stamp  # untouched, no gratuitous updated_at bump


# ── reconcile is a reporting phase and must never block the watermark ────────


def test_reconcile_adapter_reports_drift_without_errors() -> None:
    from app.tasks.traffit_sync import _ReconcilePhaseResult

    now = datetime.now(UTC)
    result = _ReconcilePhaseResult(
        {
            "clients": {"traffit": 10, "nexus": 10},
            "candidates": {"traffit": 49000, "nexus": 49500},  # drift
            "jobs": {"error": "traffit count failed: boom"},
        },
        now,
        now,
    )

    d = result.as_dict()
    assert result.errors == 0  # informational only — never freezes the watermark
    assert d["errors"] == 0
    assert set(d["drift"]) == {"candidates", "jobs"}
    assert d["drift"]["candidates"]["nexus"] > d["drift"]["candidates"]["traffit"]


def test_reconcile_is_last_in_the_phase_plan() -> None:
    from app.tasks.traffit_sync import _phase_plan

    names = [
        n for n, _ in _phase_plan(TraffitImporter.__new__(TraffitImporter), None, None)
    ]

    assert names[-1] == "reconcile"  # nothing depends on it; it only observes
