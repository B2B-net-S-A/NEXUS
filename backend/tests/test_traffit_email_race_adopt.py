"""Kandydat z tym samym mailem powstaje w Nexusie W TRAKCIE fazy `candidates`.

Produkcja 24.09.2026: rekruterka wgrała to samo CV do Traffita i do Nexusa
w odstępie ~2 s (`source='cv_upload'`, `external_source='manual'`, bez
`external_id`). Faza `candidates` zbudowała `email_to_id` minutę wcześniej,
więc nie znała nowego wiersza, poszła gałęzią INSERT i trafiła w UNIQUE
`ix_candidates_email`. Dwa takie rekordy (ext 65050, 65051) zamroziły watermark
`__daily__` i `/api/health` pokazał `traffit=degraded`.

Mapa jest migawką; wiersz z tym mailem, który pojawi się później, trzeba
zaadoptować tak samo, jak ten znany z mapy — nie zapisywać błędu i nie
zakładać drugiego kandydata.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import text

import app.services.traffit.importer as importer_mod
from app.core.database import AsyncSessionLocal
from app.services.traffit.importer import TraffitImporter


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


async def _insert_candidate(
    *, email: str, external_source: str, external_id: str | None
) -> int:
    """Zapis z OSOBNEJ sesji — jak równoległe wgranie CV przez rekrutera."""
    async with AsyncSessionLocal() as other:
        row = await other.execute(
            text(
                """
                INSERT INTO candidates (
                    external_id, external_source, name, lastname, email,
                    status, source, cv_extracted_data, created_at, updated_at
                ) VALUES (
                    :ext, :src, 'Marek', 'Nowak', :email,
                    CAST('active' AS candidatestatus), 'cv_upload',
                    CAST('{}' AS jsonb), NOW(), NOW()
                ) RETURNING id
                """
            ),
            {"ext": external_id, "src": external_source, "email": email},
        )
        cid = row.scalar_one()
        await other.commit()
        return cid


class _OneEmployee:
    def __init__(self, ext: str):
        self.ext = ext

    async def total_count(self, path):
        return 1

    async def get_paginated(self, path, *, page_size=100, **kw):
        return
        yield  # pragma: no cover — czyni z tego generator

    async def get_pages(self, path, *, page_size=100, start_page=1, **kw):
        yield 1, [{"id": self.ext}]


def _payload(ext: str, email: str) -> dict:
    return {
        "external_id": ext,
        "external_source": "traffit",
        "name": "Marek",
        "lastname": "Nowak",
        "traffit_raw_name": "Marek",
        "traffit_raw_lastname": "Nowak",
        "traffit_source_updated_at": None,
        "email": email,
        "phone": "796 802 951",
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


async def _run_import(db, ext: str, email: str, *, created_late: dict):
    """Import jednego pracownika; `created_late` wstawia wiersz PO migawce maili.

    `_build_candidate_external_id_map` jest wołane zaraz po zbudowaniu
    `email_to_id`, więc wiersz dopisany w jego trakcie jest dokładnie tym
    z produkcji: istnieje w bazie, ale nie ma go w mapie.
    """
    imp = TraffitImporter(_OneEmployee(ext), db, dry_run=False, batch_size=10)
    imp.build_user_id_map = AsyncMock(return_value={})
    imp._record_new_candidate_index_intent = AsyncMock(return_value=None)
    real_ext_map = imp._build_candidate_external_id_map

    async def ext_map_after_concurrent_write():
        created_late["id"] = await _insert_candidate(
            email=email, external_source="manual", external_id=None
        )
        return await real_ext_map()

    imp._build_candidate_external_id_map = ext_map_after_concurrent_write
    original = importer_mod.traffit_employee_to_candidate
    importer_mod.traffit_employee_to_candidate = lambda raw, m: _payload(
        str(raw["id"]), email
    )
    try:
        return await imp.import_candidates(since=None)
    finally:
        importer_mod.traffit_employee_to_candidate = original


@pytest.mark.asyncio
async def test_row_created_after_email_snapshot_is_adopted_not_errored(db) -> None:
    ext = f"t{uuid.uuid4().hex[:10]}"
    email = f"race-{uuid.uuid4().hex[:10]}@example.test"
    created_late: dict = {}

    progress = await _run_import(db, ext, email, created_late=created_late)

    assert progress.errors == 0, progress.error_samples
    rows = (
        await db.execute(
            text(
                "SELECT id, external_source, external_id, "
                "cv_extracted_data->>'legacy_source' "
                "FROM candidates WHERE email = :e OR external_id = :x"
            ),
            {"e": email, "x": ext},
        )
    ).fetchall()
    assert len(rows) == 1, f"kandydat zdublowany: {rows}"
    cid, source, external_id, legacy = rows[0]
    assert cid == created_late["id"], "adopcja miała trafić w wiersz z Nexusa"
    assert (source, external_id) == ("traffit", ext)
    assert legacy == "manual", "pochodzenie wiersza zgubione przy adopcji"


@pytest.mark.asyncio
async def test_email_conflict_on_existing_ext_owner_is_not_resolved_by_theft(
    db,
) -> None:
    """Gdy `external_id` ma już właściciela, konflikt maila zostaje błędem.

    Traffit zmienił mail pracownika na adres, który w Nexusie ma INNY wiersz.
    Przepięcie `external_id` na ten wiersz odebrałoby tożsamość właścicielowi —
    to decyzja dedupu, nie importera. Wiersz ma trafić do kwarantanny.
    """
    ext = f"t{uuid.uuid4().hex[:10]}"
    email = f"race-{uuid.uuid4().hex[:10]}@example.test"
    owner_id = await _insert_candidate(
        email=f"old-{uuid.uuid4().hex[:10]}@example.test",
        external_source="traffit",
        external_id=ext,
    )
    created_late: dict = {}

    progress = await _run_import(db, ext, email, created_late=created_late)

    assert progress.errors == 1
    assert f"ext={ext}" in progress.error_samples[0]
    owner = (
        await db.execute(
            text("SELECT external_id FROM candidates WHERE id = :i"),
            {"i": owner_id},
        )
    ).scalar_one()
    late = (
        await db.execute(
            text("SELECT external_source, external_id FROM candidates WHERE id = :i"),
            {"i": created_late["id"]},
        )
    ).one()
    assert owner == ext
    assert tuple(late) == ("manual", None)
