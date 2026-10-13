"""Import z Traffita zapisuje datę dodania osoby (`source_created_at`, 0436) — prawdziwy Postgres.

„W bazie od”: `created_at` to chwila wstawienia do NEXUSA, więc data dodania
w Traffit musi trafić do osobnej kolumny przy INSERT-cie, przy aktualizacji
i przy adopcji wiersza dopasowanego po mailu. Brak daty w payloadzie nie może
skasować zapisanej. Każdy test zakłada własne wiersze — baza CI jest wspólna.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import text

import app.services.traffit.importer as importer_mod
from app.core.database import AsyncSessionLocal
from app.services.traffit.importer import TraffitImporter

UTC = timezone.utc
IN_TRAFFIT = datetime(2019, 5, 11, 22, 0, tzinfo=UTC)


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


async def _source_created_at(db, *, ext: str | None = None, cid: int | None = None):
    if cid is not None:
        row = await db.execute(
            text("SELECT source_created_at FROM candidates WHERE id = :i"), {"i": cid}
        )
    else:
        row = await db.execute(
            text(
                "SELECT source_created_at FROM candidates "
                "WHERE external_source = 'traffit' AND external_id = :e"
            ),
            {"e": ext},
        )
    return row.scalar_one()


@pytest.mark.asyncio
async def test_new_person_gets_the_traffit_added_date(db, monkeypatch) -> None:
    tag = uuid.uuid4().hex[:10]
    ext, email = f"sca{tag}", f"sca-{tag}@example.test"

    progress = await _import(
        db,
        [ext],
        {ext: _payload(ext, email, source_created_at=IN_TRAFFIT.isoformat())},
        monkeypatch,
    )

    assert progress.errors == 0, progress.error_samples
    assert await _source_created_at(db, ext=ext) == IN_TRAFFIT


@pytest.mark.asyncio
async def test_payload_without_the_key_still_imports(db, monkeypatch) -> None:
    """Ręcznie zbudowany payload (stary kształt) nie może wywrócić zapisu."""
    tag = uuid.uuid4().hex[:10]
    ext, email = f"scb{tag}", f"scb-{tag}@example.test"

    progress = await _import(db, [ext], {ext: _payload(ext, email)}, monkeypatch)

    assert progress.errors == 0, progress.error_samples
    assert await _source_created_at(db, ext=ext) is None


@pytest.mark.asyncio
async def test_update_sets_the_date_and_a_missing_one_does_not_erase_it(
    db, monkeypatch
) -> None:
    tag = uuid.uuid4().hex[:10]
    ext, email = f"scc{tag}", f"scc-{tag}@example.test"
    await _import(db, [ext], {ext: _payload(ext, email)}, monkeypatch)
    assert await _source_created_at(db, ext=ext) is None

    # Zmiana u źródła (telefon) przepuszcza DO UPDATE; data dochodzi.
    changed = _payload(
        ext, email, phone="600000001", source_created_at=IN_TRAFFIT.isoformat()
    )
    progress = await _import(db, [ext], {ext: changed}, monkeypatch)
    assert progress.errors == 0, progress.error_samples
    assert await _source_created_at(db, ext=ext) == IN_TRAFFIT

    # Kolejna zmiana bez daty w payloadzie zostawia zapisaną.
    again = _payload(ext, email, phone="600000002")
    progress = await _import(db, [ext], {ext: again}, monkeypatch)
    assert progress.errors == 0, progress.error_samples
    assert await _source_created_at(db, ext=ext) == IN_TRAFFIT


@pytest.mark.asyncio
async def test_adopted_row_gets_the_traffit_date(db, monkeypatch) -> None:
    """Wiersz z innego źródła z tym samym mailem jest adoptowany — data też."""
    tag = uuid.uuid4().hex[:10]
    ext, email = f"scd{tag}", f"scd-{tag}@example.test"
    cid = await db.scalar(
        text(
            """
            INSERT INTO candidates (
                external_source, name, lastname, email, custom_fields,
                created_at, updated_at
            ) VALUES (
                'talent_radar', 'Jan', 'Kowalski', :email, CAST(:cf AS JSONB),
                NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days'
            ) RETURNING id
            """
        ),
        {"email": email, "cf": json.dumps({})},
    )
    await db.commit()

    progress = await _import(
        db,
        [ext],
        {ext: _payload(ext, email, source_created_at=IN_TRAFFIT.isoformat())},
        monkeypatch,
    )

    assert progress.errors == 0, progress.error_samples
    assert await _source_created_at(db, cid=cid) == IN_TRAFFIT
