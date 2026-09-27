"""Runda 10 audytu (R10-N11) na prawdziwym Postgresie.

Każdy test zakłada własne wiersze (losowe numery Traffita i maile) i asertuje
wyłącznie po nich — baza CI jest wspólna.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select, text

import app.services.traffit.importer as importer_mod
from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.contact import Contact
from app.services.contact_duplicate_merge import add_deleted_traffit_contact
from app.services.traffit.importer import TraffitImporter, _UPSERT_USER


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


class _Employees:
    def __init__(self, ids: list[str]):
        self.ids = ids

    async def total_count(self, path):
        return len(self.ids)

    async def get_paginated(self, path, *, page_size=100, **kw):
        return
        yield  # pragma: no cover

    async def get_pages(self, path, *, page_size=100, start_page=1, **kw):
        yield 1, [{"id": i} for i in self.ids]


def _payload(ext: str, email: str, **over) -> dict:
    base = {
        "external_id": ext,
        "external_source": "traffit",
        "name": "Jan",
        "lastname": "Kowalski",
        "traffit_raw_name": "Jan",
        "traffit_raw_lastname": "Kowalski",
        "traffit_source_updated_at": None,
        "email": email,
        "phone": "500000000",
        "linkedin": None,
        "city": None,
        "country": None,
        "location": None,
        "status": "active",
        "profile_about": None,
        "languages": [],
        "cv_filename": None,
        "cv_extracted_data": {},
        "source": "traffit",
        "created_by": None,
    }
    base.update(over)
    return base


async def _import(db, ids: list[str], payloads: dict[str, dict], monkeypatch):
    imp = TraffitImporter(_Employees(ids), db, dry_run=False, batch_size=10)
    imp.build_user_id_map = AsyncMock(return_value={})
    imp._record_new_candidate_index_intent = AsyncMock(return_value=None)
    monkeypatch.setattr(
        importer_mod,
        "traffit_employee_to_candidate",
        lambda raw, m: dict(payloads[str(raw["id"])]),
    )
    return await imp.import_candidates(since=None)


async def _mk_candidate(db, *, ext, email, status="active", phone=None, meta=None):
    row = await db.execute(
        text(
            """
            INSERT INTO candidates (
                external_id, external_source, name, lastname, email, phone,
                status, custom_fields, created_at, updated_at
            ) VALUES (
                :ext, 'traffit', 'Jan', 'Kowalski', :email, :phone,
                CAST(:status AS candidatestatus), CAST(:cf AS JSONB),
                NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days'
            ) RETURNING id
            """
        ),
        {
            "ext": ext,
            "email": email,
            "phone": phone,
            "status": status,
            "cf": json.dumps({"_nexus_identity": meta or {}}),
        },
    )
    return row.scalar_one()


async def _row(db, cid: int):
    return (
        await db.execute(
            text(
                "SELECT status::text, phone, external_id, updated_at "
                "FROM candidates WHERE id = :i"
            ),
            {"i": cid},
        )
    ).fetchone()


@pytest.mark.asyncio
async def test_email_match_does_not_restamp_another_live_traffit_record(
    db, monkeypatch
) -> None:
    """R10-N11-1: dwie kartoteki Traffita z jednym mailem nie przejmują wiersza."""
    tag = uuid.uuid4().hex[:10]
    first, second = f"r10a{tag}", f"r10b{tag}"
    email = f"r10-dup-{tag}@example.test"
    cid = await _mk_candidate(db, ext=first, email=email)
    await db.commit()

    progress = await _import(
        db,
        [second],
        {second: _payload(second, email, name="Anna")},
        monkeypatch,
    )

    _, _, external_id, _ = await _row(db, cid)
    assert external_id == first, "tożsamość przeskoczyła na drugi rekord Traffita"
    assert any(
        m.startswith(f"email_collision candidate ext={second}")
        for m in progress.error_samples
    )
    assert f"candidate:{second}" in progress.error_refs


@pytest.mark.asyncio
async def test_blacklist_lifted_in_nexus_is_not_restored(db, monkeypatch) -> None:
    """R10-N11-2: marker w imieniu w Traffit nie przywraca zdjętej blacklisty."""
    tag = uuid.uuid4().hex[:10]
    ext = f"r10bl{tag}"
    email = f"r10-bl-{tag}@example.test"
    cid = await _mk_candidate(
        db, ext=ext, email=email, status="active", meta={"status_manual": True}
    )
    await db.commit()

    progress = await _import(
        db, [ext], {ext: _payload(ext, email, status="blacklisted")}, monkeypatch
    )
    assert progress.errors == 0, progress.error_samples

    status, *_ = await _row(db, cid)
    assert status == "active"


@pytest.mark.asyncio
async def test_phone_corrected_in_nexus_survives_the_full_run(db, monkeypatch) -> None:
    """R10-N11-3: telefon ze znacznikiem ręcznej edycji zostaje."""
    tag = uuid.uuid4().hex[:10]
    ext = f"r10ph{tag}"
    email = f"r10-ph-{tag}@example.test"
    cid = await _mk_candidate(
        db, ext=ext, email=email, phone="600000001", meta={"phone_manual": True}
    )
    await db.commit()

    progress = await _import(
        db, [ext], {ext: _payload(ext, email, phone="500000000")}, monkeypatch
    )
    assert progress.errors == 0, progress.error_samples

    _, phone, _, _ = await _row(db, cid)
    assert phone == "600000001"


@pytest.mark.asyncio
async def test_second_run_without_changes_does_not_touch_the_row(
    db, monkeypatch
) -> None:
    """R10-N11-9: bez zmiany u źródła nie ma zapisu (ani `updated_at`)."""
    tag = uuid.uuid4().hex[:10]
    ext = f"r10nc{tag}"
    email = f"r10-nc-{tag}@example.test"
    cid = await _mk_candidate(db, ext=ext, email=email)
    await db.commit()
    payloads = {ext: _payload(ext, email)}

    first = await _import(db, [ext], payloads, monkeypatch)
    assert first.errors == 0, first.error_samples
    _, _, _, stamped = await _row(db, cid)

    second = await _import(db, [ext], payloads, monkeypatch)
    assert second.errors == 0, second.error_samples
    assert second.unchanged == 1
    assert second.updated == 0
    _, _, _, again = await _row(db, cid)
    assert again == stamped

    changed = await _import(
        db, [ext], {ext: _payload(ext, email, phone="700000000")}, monkeypatch
    )
    assert changed.updated == 1
    _, phone, _, _ = await _row(db, cid)
    assert phone == "700000000"


class _Persons:
    def __init__(self, persons: list[dict]):
        self.persons = persons

    async def total_count(self, path):
        return len(self.persons)

    async def get_paginated(self, path, *, page_size=100, filter_=None, **kw):
        for person in self.persons:
            yield person


@pytest.mark.asyncio
async def test_contact_import_keeps_nexus_owned_fields_and_tombstones() -> None:
    """R10-N11-4: decydent, nazwa i klient z NEXUSA zostają; usunięty nie wraca."""
    tag = uuid.uuid4().hex[:8]
    kept_ext, deleted_ext = f"r10k{tag}", f"r10d{tag}"
    async with AsyncSessionLocal() as db:
        client = Client(name=f"R10Client-{tag}")
        db.add(client)
        await db.flush()
        contact = Contact(
            client_id=client.id,
            name=f"Poprawione Nazwisko{tag}",
            external_source="traffit",
            external_id=kept_ext,
            is_decision_maker=True,
        )
        db.add(contact)
        await db.flush()
        contact_id, client_id = contact.id, client.id
        await add_deleted_traffit_contact(db, deleted_ext)
        await db.commit()

    persons = [
        {"id": kept_ext, "name": "Stare", "lastname": f"Nazwisko{tag}"},
        {"id": deleted_ext, "name": "Usunięty", "lastname": f"Kontakt{tag}"},
    ]
    async with AsyncSessionLocal() as db:
        progress = await TraffitImporter(
            _Persons(persons), db, dry_run=False, batch_size=10
        ).import_contacts()
        assert progress.errors == 0, progress.error_samples

    async with AsyncSessionLocal() as db:
        kept = await db.get(Contact, contact_id)
        assert kept.is_decision_maker is True
        assert kept.name == f"Poprawione Nazwisko{tag}"
        assert kept.client_id == client_id
        recreated = await db.scalar(
            select(Contact.id).where(
                Contact.external_source == "traffit",
                Contact.external_id == deleted_ext,
            )
        )
        assert recreated is None


@pytest.mark.asyncio
async def test_user_upsert_leaves_a_real_account_alone(db) -> None:
    """R10-N11-11: konto z prawdziwym hasłem nie traci roli ani aktywności."""
    tag = uuid.uuid4().hex[:10]
    ext = f"r10u{tag}"
    uid = (
        await db.execute(
            text(
                """
                INSERT INTO users (
                    external_id, external_source, email, name, role, is_active,
                    password_hash, profile_completed, created_at, updated_at
                ) VALUES (
                    :ext, 'traffit', :email, 'Konto NEXUS',
                    CAST('sourcer' AS userrole), true, :pwd, true, NOW(), NOW()
                ) RETURNING id
                """
            ),
            {
                "ext": ext,
                "email": f"r10-real-{tag}@example.test",
                "pwd": "hash-ustawiony-w-nexusie",
            },
        )
    ).scalar_one()
    await db.execute(
        _UPSERT_USER,
        {
            "external_id": ext,
            "external_source": "traffit",
            "email": f"r10-changed-{tag}@example.test",
            "name": "Konto NEXUS",
            "role": "recruiter",
            "is_active": False,
            "password_hash": "!imported-from-traffit-no-login!",
        },
    )
    await db.commit()
    role, active = (
        await db.execute(
            text("SELECT role::text, is_active FROM users WHERE id = :i"), {"i": uid}
        )
    ).fetchone()
    await db.execute(text("DELETE FROM users WHERE id = :i"), {"i": uid})
    await db.commit()
    assert (role, active) == ("sourcer", True)


class _Content503Traffit:
    """Lista plików działa, pobranie treści daje 503 (chwilowa awaria)."""

    class _Resp:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload
            self.content = b""
            self.headers = {}

        def json(self):
            return self._payload

    def __init__(self):
        outer = self

        class _Http:
            async def get(self, url, headers=None):
                return outer._Resp(503)

        self._http = _Http()
        self.config = type("Cfg", (), {"api_base": "https://traffit.test"})()

    async def _get_raw(self, path, page=1, page_size=50):
        return self._Resp(200, [{"id": 7, "name": "cv.pdf"}])

    async def _ensure_token(self):
        return "token"

    async def _throttle(self):
        return None


@pytest.mark.asyncio
async def test_unchanged_candidate_is_retried_by_the_files_phase(
    db, monkeypatch
) -> None:
    """R10-N11-9 (po przeglądzie): niezmieniony rekord nie wypada z delty plików.

    Bieg 1: kandydat wchodzi, pobranie treści pliku daje 503 — błąd wiersza,
    `__daily__` stoi. Bieg 2: Traffit oddaje ten sam rekord (bez zmian, więc
    bez stempla `updated_at`), a faza plików i tak musi go znowu wziąć.
    """
    from datetime import datetime, timedelta, timezone

    tag = uuid.uuid4().hex[:10]
    ext = f"r10f{tag}"
    email = f"r10-f-{tag}@example.test"
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=2)
    payloads = {
        ext: _payload(
            ext,
            email,
            traffit_source_updated_at=(now - timedelta(minutes=30)).isoformat(),
        )
    }

    first = await _import(db, [ext], payloads, monkeypatch)
    assert first.errors == 0, first.error_samples
    cid = (
        await db.execute(
            text(
                "SELECT id FROM candidates WHERE external_source='traffit' "
                "AND external_id = :e"
            ),
            {"e": ext},
        )
    ).scalar_one()
    files_1 = await TraffitImporter(
        _Content503Traffit(), db, dry_run=False
    ).import_candidate_files(since=now, source_since=since)
    assert f"candidate:{ext}" in files_1.error_refs

    run_2 = datetime.now(timezone.utc) + timedelta(seconds=1)
    second = await _import(db, [ext], payloads, monkeypatch)
    assert second.unchanged == 1

    importer = TraffitImporter(_Content503Traffit(), db, dry_run=False)
    only_stamp = {row.id for row in await importer._delta_file_targets(run_2)}
    assert cid not in only_stamp, "warunek samego `updated_at` gubi kandydata"
    with_source = {row.id for row in await importer._delta_file_targets(run_2, since)}
    assert cid in with_source
    files_2 = await importer.import_candidate_files(since=run_2, source_since=since)
    assert f"candidate:{ext}" in files_2.error_refs
