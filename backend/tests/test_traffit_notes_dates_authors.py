"""Notatki z Traffita: data, autor, wzmianki i rekrutacja (29.09.2026).

Zmierzone na produkcji (odczyt, 29.09.2026): aktywność dostawała
`created_at = NOW()`, a promocja kopiowała go do notatki — notatka z lutego
wyglądała na majową (dzień importu). Do tego 7 752 notatek z migracji 0077
miało autora innego niż `created_by` aktywności, 23 331 niosło surowe
`$$user_NN$$`, a żadna nie miała rekrutacji (globalny feed jej nie niesie).

Prawdziwy Postgres — zmiana siedzi w SQL-u promocji, upsercie aktywności
i naprawie, więc atrapa bazy nie dowiodłaby niczego.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest_asyncio
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.services.note_mention_render import (
    STORED_UNKNOWN_LABEL,
    rewrite_traffit_mentions,
)

UTC = timezone.utc

# Czas lokalny Traffita (zima, CET = UTC+1) i jego odpowiednik w UTC.
TRAFFIT_DATE = "2026-02-19 15:32:00"
TRAFFIT_DATE_UTC = datetime(2026, 2, 19, 14, 32, tzinfo=UTC)
# Chwila importu z maja (0077) — stała, żeby nie liczyć dat przy imporcie.
IMPORTED_AT = datetime(2026, 5, 5, 10, 0, 0, tzinfo=UTC)
UPDATED_AT = datetime(2026, 5, 6, 8, 0, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


# ── Czyste funkcje ───────────────────────────────────────────────────────────


def test_rewrite_mentions_uses_the_map_and_marks_unknown_accounts() -> None:
    out = rewrite_traffit_mentions(
        "Dzwonił $$user_40$$, CC $$user_99$$", {"40": "Klaudia Uliasz"}
    )
    assert out == f"Dzwonił @Klaudia Uliasz, CC @{STORED_UNKNOWN_LABEL}"


def test_rewrite_mentions_without_user_list_changes_nothing() -> None:
    """Bez listy `/users/` nie wiemy, czy konto istnieje — nie ruszamy."""
    content = "Dzwonił $$user_40$$"
    assert rewrite_traffit_mentions(content, {}) == content


# ── Pomocniki bazy ───────────────────────────────────────────────────────────


async def _mk_user(db, tag: str) -> tuple[int, str]:
    email = f"notes-{tag}-{uuid.uuid4().hex[:8]}@example.test"
    uid = await db.scalar(
        text("INSERT INTO users (email, name) VALUES (:e, :n) RETURNING id"),
        {"e": email, "n": f"Autor {tag}"},
    )
    return int(uid), email


async def _mk_candidate(db) -> tuple[int, str]:
    ext = f"nd-{uuid.uuid4().hex[:10]}"
    cid = await db.scalar(
        text(
            """
            INSERT INTO candidates (
                external_id, external_source, name, lastname, created_at, updated_at
            ) VALUES (:e, 'traffit', 'A', 'B', NOW(), NOW())
            RETURNING id
            """
        ),
        {"e": ext},
    )
    return int(cid), ext


async def _mk_activity(
    db,
    candidate_id: int,
    *,
    ext: str,
    content: str,
    created_at: datetime,
    activity_date: str | None = TRAFFIT_DATE,
    created_by: str | None = None,
    user_id: int | None = None,
) -> None:
    details: dict = {"content": content}
    if activity_date is not None:
        details["activity_date"] = activity_date
    if created_by is not None:
        details["traffit_created_by_id"] = created_by
    await db.execute(
        text(
            """
            INSERT INTO activities (
                external_id, external_source, action, entity_type, entity_id,
                details, user_id, created_at, updated_at
            ) VALUES (
                :ext, 'traffit', 'traffit:Notatka', 'candidate', :cid,
                CAST(:d AS jsonb), :u, :at, :at
            )
            """
        ),
        {
            "ext": ext,
            "cid": candidate_id,
            "d": json.dumps(details),
            "u": user_id,
            "at": created_at,
        },
    )


async def _mk_note(
    db,
    candidate_id: int,
    *,
    content: str,
    created_at: datetime,
    author_id: int | None,
    source_ref: str | None = None,
) -> int:
    nid = await db.scalar(
        text(
            """
            INSERT INTO notes (
                candidate_id, content, note_type, author_id, source_ref,
                created_at, updated_at
            ) VALUES (:c, :content, 'general', :a, :sr, :at, :upd)
            RETURNING id
            """
        ),
        {
            "c": candidate_id,
            "content": content,
            "a": author_id,
            "sr": source_ref,
            "at": created_at,
            "upd": UPDATED_AT,
        },
    )
    return int(nid)


async def _note(db, note_id: int) -> dict:
    row = await db.execute(
        text(
            "SELECT created_at, source_created_at, author_id, content, source_ref, "
            "updated_at, job_id FROM notes WHERE id = :i"
        ),
        {"i": note_id},
    )
    return dict(row.mappings().one())


async def _notes_of(db, candidate_id: int) -> list[dict]:
    rows = await db.execute(
        text(
            "SELECT id, created_at, source_created_at, author_id, content, "
            "source_ref, updated_at, job_id FROM notes "
            "WHERE candidate_id = :c ORDER BY id"
        ),
        {"c": candidate_id},
    )
    return [dict(r) for r in rows.mappings().all()]


# ── Promocja ─────────────────────────────────────────────────────────────────


# ── Import aktywności (upsert + rekrutacja) ──────────────────────────────────


class _FakeTraffit:
    def __init__(self, items, users, per_candidate) -> None:
        self.items = items
        self.users = users
        self.per_candidate = per_candidate

    async def total_count(self, path: str) -> int:
        return len(self.items)

    async def get_pages(self, path: str, **_kw):
        yield 1, list(self.items)

    async def get_paginated(self, path: str, **_kw):
        source = self.users if path == "/users/" else self.per_candidate.get(path, [])
        for item in source:
            yield item


# ── Naprawa ──────────────────────────────────────────────────────────────────


async def _repair_fixture(db) -> dict:
    cid, _ = await _mk_candidate(db)
    wrong, _ = await _mk_user(db, "wrong")
    right, _ = await _mk_user(db, "right")
    traffit_uid = str(900000 + int(uuid.uuid4().int % 99999))
    e_legacy, e_sync, e_amb1, e_amb2, e_tomb = (uuid.uuid4().hex[:12] for _ in range(5))
    legacy_content = f"Rozmowa z $$user_{traffit_uid}$$ i $$user_1$$"
    await _mk_activity(
        db,
        cid,
        ext=e_legacy,
        content=legacy_content,
        created_at=IMPORTED_AT,
        created_by=traffit_uid,
        user_id=wrong,
    )
    legacy = await _mk_note(
        db, cid, content=legacy_content, created_at=IMPORTED_AT, author_id=wrong
    )
    sync_at = IMPORTED_AT.replace(minute=5)
    await _mk_activity(
        db,
        cid,
        ext=e_sync,
        content="Z syncu",
        created_at=sync_at,
        created_by=traffit_uid,
        user_id=right,
    )
    sync = await _mk_note(
        db,
        cid,
        content="Z syncu",
        created_at=sync_at,
        author_id=right,
        source_ref=f"traffit:activity:{e_sync}",
    )
    amb_at = IMPORTED_AT.replace(minute=10)
    for e in (e_amb1, e_amb2):
        await _mk_activity(
            db,
            cid,
            ext=e,
            content="Dwa razy",
            created_at=amb_at,
            created_by=traffit_uid,
        )
    ambiguous = await _mk_note(
        db, cid, content="Dwa razy", created_at=amb_at, author_id=wrong
    )
    tomb_at = IMPORTED_AT.replace(minute=15)
    await _mk_activity(
        db,
        cid,
        ext=e_tomb,
        content="Z nagrobkiem",
        created_at=tomb_at,
        created_by=traffit_uid,
    )
    tombstoned = await _mk_note(
        db, cid, content="Z nagrobkiem", created_at=tomb_at, author_id=wrong
    )
    await db.execute(
        text("INSERT INTO deleted_note_sources (source_ref) VALUES (:r)"),
        {"r": f"traffit:activity:{e_tomb}"},
    )
    await db.commit()
    return {
        "cid": cid,
        "wrong": wrong,
        "right": right,
        "user_map": {traffit_uid: right},
        "labels": {traffit_uid: "Anna Nowak"},
        "legacy": legacy,
        "legacy_ext": e_legacy,
        "sync": sync,
        "ambiguous": ambiguous,
        "tombstoned": tombstoned,
    }
