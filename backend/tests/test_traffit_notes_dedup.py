"""`promote_notes` deduped on the wrong key.

The phase exists so a Traffit note/email/call reaches the candidate "Notatki"
UI on every sync — CLAUDE.md calls it out as the "no notatka missing"
guarantee. It deduped with `NOT EXISTS (candidate_id, created_at)`, which is
not the identity of the source row, and that was wrong in both directions:

* **Notes lost.** When a second activity sharing a candidate's `created_at`
  arrived in a LATER sync — a reply logged the next day, a backfilled row, an
  activity the delta window only now reached — the note already promoted for
  the first one made it look already-present. Permanently: nothing about that
  activity will ever change, so no later sync can rescue it. (Within a single
  run both still land, because promotion is one `INSERT ... SELECT` and
  `NOT EXISTS` reads the pre-statement snapshot — which is exactly why the
  fault stayed invisible.)
* **Notes duplicated.** An activity whose `created_at` was edited in Traffit
  stopped matching its own note and got promoted again on the next sync.

`source_ref` ('traffit:activity:<external_id>') is the real identity and was
already being written. It cannot be the ONLY key, though: migration 0077
promoted the historical backlog WITHOUT a `source_ref`, so keying purely on it
would re-promote every note 0077 created — a duplicate for all ~49k
candidates. Hence the compound clause, with the timestamp arm scoped to rows
that carry no `source_ref`.

Real Postgres: the whole change is one SQL predicate, so a fake DB would prove
nothing at all.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

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


async def _mk_candidate(db) -> int:
    row = await db.execute(
        text(
            """
            INSERT INTO candidates (
                external_id, external_source, name, lastname,
                created_at, updated_at
            ) VALUES (:e, 'traffit', 'A', 'B', NOW(), NOW())
            RETURNING id
            """
        ),
        {"e": f"n-{uuid.uuid4().hex[:10]}"},
    )
    return row.scalar_one()


async def _mk_activity(db, candidate_id: int, *, ext: str, content: str, at) -> None:
    await db.execute(
        text(
            """
            INSERT INTO activities (
                external_id, external_source, action, entity_type, entity_id,
                details, created_at, updated_at
            ) VALUES (
                :ext, 'traffit', 'traffit:Notatka', 'candidate', :cid,
                CAST(:d AS jsonb), :at, :at
            )
            """
        ),
        {
            "ext": ext,
            "cid": candidate_id,
            "d": f'{{"content": "{content}"}}',
            "at": at,
        },
    )


async def _notes(db, candidate_id: int) -> list[tuple]:
    rows = await db.execute(
        text(
            "SELECT content, source_ref FROM notes "
            "WHERE candidate_id = :c ORDER BY content"
        ),
        {"c": candidate_id},
    )
    return [tuple(r) for r in rows]


def _importer(db) -> TraffitImporter:
    return TraffitImporter(object(), db, dry_run=False, batch_size=100)


@pytest.mark.asyncio
async def test_second_activity_sharing_a_timestamp_is_not_suppressed(db) -> None:
    """The lost-note case, and it needs TWO runs to show up.

    Promotion is one `INSERT ... SELECT`, so `NOT EXISTS` sees the table as it
    was at statement start: two same-timestamp activities present together are
    both inserted, and the old key looks fine. The loss happens when the second
    activity arrives LATER — a reply logged the next day, a backfilled row, an
    activity the delta window only now reached. By then the first note exists,
    the timestamp matches, and the second activity is suppressed permanently:
    no later sync can ever promote it, because nothing about it will change.
    """
    cid = await _mk_candidate(db)
    at = datetime.now(UTC).replace(microsecond=0)
    u = uuid.uuid4().hex[:8]

    await _mk_activity(db, cid, ext=f"{u}-1", content="Mail do kandydata", at=at)
    await db.commit()
    await _importer(db).promote_notes()

    # Next sync brings the reply, logged against the same instant.
    await _mk_activity(db, cid, ext=f"{u}-2", content="Odpowiedz kandydata", at=at)
    await db.commit()
    await _importer(db).promote_notes()

    assert await _notes(db, cid) == [
        ("Mail do kandydata", f"traffit:activity:{u}-1"),
        ("Odpowiedz kandydata", f"traffit:activity:{u}-2"),
    ]


@pytest.mark.asyncio
async def test_promotion_is_idempotent_across_syncs(db) -> None:
    """Runs on every sync — a second pass must add nothing."""
    cid = await _mk_candidate(db)
    at = datetime.now(UTC)
    await _mk_activity(db, cid, ext=uuid.uuid4().hex[:10], content="Jedna", at=at)
    await db.commit()

    await _importer(db).promote_notes()
    first = await _notes(db, cid)
    await _importer(db).promote_notes()

    assert await _notes(db, cid) == first
    assert len(first) == 1


@pytest.mark.asyncio
async def test_edited_timestamp_does_not_duplicate_the_note(db) -> None:
    """The duplicate case. Keyed on the timestamp, an activity edited in
    Traffit no longer matched its own note and was promoted a second time."""
    cid = await _mk_candidate(db)
    ext = uuid.uuid4().hex[:10]
    at = datetime.now(UTC)
    await _mk_activity(db, cid, ext=ext, content="Tresc", at=at)
    await db.commit()

    await _importer(db).promote_notes()

    # Traffit edits the activity; its timestamp moves.
    await db.execute(
        text("UPDATE activities SET created_at = :t WHERE external_id = :e"),
        {"t": at + timedelta(hours=3), "e": ext},
    )
    await db.commit()

    await _importer(db).promote_notes()

    assert len(await _notes(db, cid)) == 1


@pytest.mark.asyncio
async def test_note_promoted_by_migration_0077_is_not_promoted_again(db) -> None:
    """0077 wrote no `source_ref`. Keying purely on it would re-promote the
    entire historical backlog — one duplicate per note, ~49k candidates."""
    cid = await _mk_candidate(db)
    at = datetime.now(UTC)
    await _mk_activity(db, cid, ext=uuid.uuid4().hex[:10], content="Stara", at=at)
    # …exactly as 0077 left it: right content and timestamp, NULL source_ref.
    await db.execute(
        text(
            """
            INSERT INTO notes (
                candidate_id, content, note_type, source_ref,
                created_at, updated_at
            ) VALUES (:c, 'Stara', 'general', NULL, :at, :at)
            """
        ),
        {"c": cid, "at": at},
    )
    await db.commit()

    await _importer(db).promote_notes()

    assert await _notes(db, cid) == [("Stara", None)]
