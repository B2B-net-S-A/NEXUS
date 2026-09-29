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

import pytest
import pytest_asyncio
from sqlalchemy import text

import app.services.traffit.importer as importer_mod
from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.job import Job
from app.services import traffit_notes_repair as repair
from app.services.note_mention_render import (
    STORED_UNKNOWN_LABEL,
    rewrite_traffit_mentions,
)
from app.services.traffit.importer import TraffitImporter
from app.services.traffit.mappers import traffit_activity_to_activity

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


def test_mapper_takes_activity_date_as_warsaw_time() -> None:
    payload = traffit_activity_to_activity(
        {
            "id": 1,
            "employee": {"id": 7},
            "type": {"value": "Notatka"},
            "activity_date": TRAFFIT_DATE,
            "content": "x",
        },
        {"7": 70},
    )
    assert payload is not None
    assert payload["created_at"] == TRAFFIT_DATE_UTC


def test_mapper_without_activity_date_leaves_it_empty() -> None:
    payload = traffit_activity_to_activity(
        {"id": 1, "employee": {"id": 7}, "type": {"value": "Notatka"}},
        {"7": 70},
    )
    assert payload is not None
    assert payload["created_at"] is None


def test_rewrite_mentions_uses_the_map_and_marks_unknown_accounts() -> None:
    out = rewrite_traffit_mentions(
        "Dzwonił $$user_40$$, CC $$user_99$$", {"40": "Klaudia Uliasz"}
    )
    assert out == f"Dzwonił @Klaudia Uliasz, CC @{STORED_UNKNOWN_LABEL}"


def test_rewrite_mentions_without_user_list_changes_nothing() -> None:
    """Bez listy `/users/` nie wiemy, czy konto istnieje — nie ruszamy."""
    content = "Dzwonił $$user_40$$"
    assert rewrite_traffit_mentions(content, {}) == content


def test_user_labels_come_from_the_traffit_user_list() -> None:
    importer = TraffitImporter(object(), object())  # type: ignore[arg-type]
    importer._traffit_users = [
        {"id": 40, "name": "Klaudia", "lastname": "Uliasz"},
        {"id": 41, "email": "jan.kowalski@example.test"},
        {"id": 42, "name": 'Zły"znak{}'},
    ]
    assert importer.traffit_user_labels() == {
        "40": "Klaudia Uliasz",
        "41": "Jan Kowalski",
        "42": "Złyznak",
    }


def test_repair_author_prefers_the_current_email_mapping() -> None:
    assert repair.resolve_author("42", 5, {"42": 32}) == 32
    assert repair.resolve_author("42", 5, {}) == 5
    assert repair.resolve_author(None, None, {"42": 32}) is None


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


@pytest.mark.asyncio
async def test_promotion_uses_traffit_date_and_rewrites_mentions(db) -> None:
    cid, _ = await _mk_candidate(db)
    ext = uuid.uuid4().hex[:12]
    await _mk_activity(
        db,
        cid,
        ext=ext,
        content="Rozmowa, CC $$user_40$$",
        created_at=datetime.now(UTC),
    )
    await db.commit()

    await TraffitImporter(object(), db).promote_notes(
        mention_labels={"40": "Klaudia Uliasz"}
    )

    [note] = await _notes_of(db, cid)
    assert note["created_at"] == TRAFFIT_DATE_UTC
    assert note["source_created_at"] == TRAFFIT_DATE_UTC
    assert note["content"] == "Rozmowa, CC @Klaudia Uliasz"
    assert note["source_ref"] == f"traffit:activity:{ext}"


@pytest.mark.asyncio
async def test_delta_promotes_a_backdated_activity_touched_in_this_run(db) -> None:
    """Notatka wpisana dziś z datą rozmowy sprzed tygodni: data aktywności
    jest starsza niż okno delty, ale sam zapis — nie."""
    cid, _ = await _mk_candidate(db)
    ext = uuid.uuid4().hex[:12]
    now = datetime.now(UTC)
    await _mk_activity(db, cid, ext=ext, content="Wsteczna", created_at=now)
    await db.execute(
        text("UPDATE activities SET created_at = :old WHERE external_id = :e"),
        {"old": TRAFFIT_DATE_UTC, "e": ext},
    )
    await db.commit()

    await TraffitImporter(object(), db).promote_notes(since=now)

    [note] = await _notes_of(db, cid)
    assert note["created_at"] == TRAFFIT_DATE_UTC


@pytest.mark.asyncio
async def test_promotion_without_activity_date_keeps_the_activity_timestamp(
    db,
) -> None:
    cid, _ = await _mk_candidate(db)
    ext = uuid.uuid4().hex[:12]
    await _mk_activity(
        db, cid, ext=ext, content="Bez daty", created_at=IMPORTED_AT, activity_date=None
    )
    await db.commit()

    await TraffitImporter(object(), db).promote_notes()

    [note] = await _notes_of(db, cid)
    assert note["created_at"] == IMPORTED_AT
    assert note["source_created_at"] is None


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


def _stub_side_phases(importer: TraffitImporter, monkeypatch) -> None:
    async def none(*_a, **_kw):
        return None

    async def zero(*_a, **_kw):
        return 0

    for name in ("_read_mode_cursor", "_write_mode_cursor", "_clear_mode_cursor"):
        monkeypatch.setattr(importer, name, none)
    monkeypatch.setattr(importer_mod, "backfill_rejection_notes_from_activities", zero)
    monkeypatch.setattr(
        importer_mod, "backfill_rejection_descriptions_from_activities", zero
    )


@pytest.mark.asyncio
async def test_import_keeps_timestamps_legacy_notes_are_matched_by(
    db, monkeypatch
) -> None:
    """Notatka z 0077 (bez `source_ref`) jest dopasowywana do aktywności po
    znaczniku czasu. Przesunięcie go w imporcie zrobiłoby z niej duplikat."""
    cid, emp = await _mk_candidate(db)
    legacy_ext = uuid.uuid4().hex[:12]
    other_ext = uuid.uuid4().hex[:12]
    await _mk_activity(db, cid, ext=legacy_ext, content="Stara", created_at=IMPORTED_AT)
    await _mk_activity(
        db, cid, ext=other_ext, content="Inna", created_at=IMPORTED_AT.replace(hour=11)
    )
    legacy_note = await _mk_note(
        db, cid, content="Stara", created_at=IMPORTED_AT, author_id=None
    )
    # Notatka z syncu dla drugiej aktywności — jej dopasowanie idzie po źródle.
    await _mk_note(
        db,
        cid,
        content="Inna",
        created_at=IMPORTED_AT.replace(hour=11),
        author_id=None,
        source_ref=f"traffit:activity:{other_ext}",
    )
    await db.commit()

    raw = [
        {
            "id": ext,
            "employee": {"id": emp},
            "type": {"value": "Notatka"},
            "activity_date": TRAFFIT_DATE,
            "content": content,
        }
        for ext, content in ((legacy_ext, "Stara"), (other_ext, "Inna"))
    ]
    importer = TraffitImporter(_FakeTraffit(raw, [], {}), db)
    _stub_side_phases(importer, monkeypatch)
    await importer.import_candidate_activities(since=None)

    rows = await db.execute(
        text(
            "SELECT external_id, created_at FROM activities WHERE external_id = ANY(:e)"
        ),
        {"e": [legacy_ext, other_ext]},
    )
    created = {r.external_id: r.created_at for r in rows}
    assert created[legacy_ext] == IMPORTED_AT
    assert created[other_ext] == TRAFFIT_DATE_UTC
    notes = await _notes_of(db, cid)
    assert len(notes) == 2, "promocja założyła duplikat notatki z 0077"
    assert any(n["id"] == legacy_note for n in notes)


@pytest.mark.asyncio
async def test_import_sets_date_author_mentions_and_recruitment(
    db, monkeypatch
) -> None:
    cid, emp = await _mk_candidate(db)
    author, email = await _mk_user(db, "import")
    tag = uuid.uuid4().hex[:8]
    client = Client(name=f"Notatki klient {tag}")
    db.add(client)
    await db.flush()
    job_ext = f"rec-{tag}"
    job = Job(
        title=f"Notatki rekrutacja {tag}",
        client_id=client.id,
        external_source="traffit",
        external_id=job_ext,
    )
    db.add(job)
    await db.commit()

    ext = uuid.uuid4().hex[:12]
    raw = [
        {
            "id": ext,
            "employee": {"id": emp},
            "type": {"value": "Notatka"},
            "activity_date": TRAFFIT_DATE,
            "content": "Po rozmowie z $$user_9001$$",
            "created_by": {"id": 9001},
        }
    ]
    users = [{"id": 9001, "email": email, "name": "Anna", "lastname": "Nowak"}]
    per_candidate = {
        f"/employees/{emp}/activities": [{"id": ext, "recruitment": {"id": job_ext}}]
    }
    importer = TraffitImporter(_FakeTraffit(raw, users, per_candidate), db)
    _stub_side_phases(importer, monkeypatch)
    progress = await importer.import_candidate_activities(since=None)

    [note] = await _notes_of(db, cid)
    assert note["created_at"] == TRAFFIT_DATE_UTC
    assert note["author_id"] == author
    assert note["content"] == "Po rozmowie z @Anna Nowak"
    assert note["job_id"] == job.id
    assert progress.note_recruitments["linked"] == 1


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


@pytest.mark.asyncio
async def test_repair_dry_run_writes_nothing(db) -> None:
    fx = await _repair_fixture(db)
    before = await _notes_of(db, fx["cid"])

    report = await repair.dry_run(db, fx["user_map"], fx["labels"])

    assert await _notes_of(db, fx["cid"]) == before
    assert report["changes"]["dates"] >= 2
    assert report["changes"]["authors"] >= 1
    assert report["changes"]["mentions"] >= 1
    assert report["changes"]["source_refs"] >= 1
    assert report["ambiguous"] >= 1
    assert report["tombstoned"] >= 1
    sampled = {s["note_id"] for s in report["samples"]["authors"]}
    assert len(report["samples"]["authors"]) <= repair.SAMPLE_SIZE
    # Raport nie niesie treści notatek.
    assert "Rozmowa" not in json.dumps(report, default=str)
    assert fx["legacy"] in sampled or len(sampled) == repair.SAMPLE_SIZE


@pytest.mark.asyncio
async def test_repair_apply_fixes_date_author_mentions_and_is_idempotent(
    db,
) -> None:
    fx = await _repair_fixture(db)
    amb_before = await _note(db, fx["ambiguous"])
    tomb_before = await _note(db, fx["tombstoned"])

    await repair.apply(db, fx["user_map"], fx["labels"])

    legacy = await _note(db, fx["legacy"])
    assert legacy["created_at"] == TRAFFIT_DATE_UTC
    assert legacy["source_created_at"] == TRAFFIT_DATE_UTC
    assert legacy["author_id"] == fx["right"]
    assert legacy["content"] == f"Rozmowa z @Anna Nowak i @{STORED_UNKNOWN_LABEL}"
    assert legacy["source_ref"] == f"traffit:activity:{fx['legacy_ext']}"
    # `updated_at` = odcisk nocnej analizy AI — nietknięty.
    assert legacy["updated_at"] == UPDATED_AT

    sync = await _note(db, fx["sync"])
    assert sync["created_at"] == TRAFFIT_DATE_UTC
    assert sync["author_id"] == fx["right"]
    assert sync["updated_at"] == UPDATED_AT

    assert await _note(db, fx["ambiguous"]) == amb_before
    assert await _note(db, fx["tombstoned"]) == tomb_before

    after_first = await _notes_of(db, fx["cid"])
    await repair.apply(db, fx["user_map"], fx["labels"])
    assert await _notes_of(db, fx["cid"]) == after_first


@pytest.mark.asyncio
async def test_repaired_legacy_note_is_not_promoted_again(db) -> None:
    """Po naprawie data notatki ≠ data aktywności — dopasowanie idzie już po
    nadanym `source_ref`, więc następny sync nie zakłada duplikatu."""
    fx = await _repair_fixture(db)
    await repair.apply(db, fx["user_map"], fx["labels"])
    before = len(await _notes_of(db, fx["cid"]))

    await TraffitImporter(object(), db).promote_notes()

    assert len(await _notes_of(db, fx["cid"])) == before
