"""Ochrony, które istniały TYLKO w jednej z dwóch ścieżek zapisu kandydata.

Importer Traffita ma dwie gałęzie: `_UPSERT_CANDIDATE` (po
`(external_source, external_id)`) i `_UPDATE_CANDIDATE_ADOPT` (po MAILU, dla
wierszy założonych wcześniej gdzie indziej). Dwie ochrony — lepka blacklista
i czyszczenie nagrobka — dopisano wyłącznie do pierwszej.

**Produkcja chodzi drugą.** `email_to_id` jest budowane BEZ filtra
`external_source`, więc kandydat już zaimportowany dopasowuje się sam do siebie
po mailu i każdy kolejny sync idzie gałęzią adopcji. Skutki zmierzone
18.09.2026:

* 74 nagrobki, których nic nie zdejmowało — w tym dwóch PRACUJĄCYCH
  konsultantów (kandydaci 154325 i 32903) niewidocznych dla automatu zamówień
  z maila, który filtruje `external_deleted_at IS NULL`. Pierwszy nie miał ani
  jednego widocznego imiennika (automat założyłby drugiego kandydata i drugi
  kontrakt osobie, która już pracuje), drugi miał dokładnie jednego
  (zamówienie trafiłoby pod niewłaściwą osobę);
* blacklista założona w NEXUSIE byłaby cicho zdejmowana przy najbliższym
  syncu — dziś bez ofiary (wszystkie 32 żywe blacklisty mają marker
  w nazwisku, a blacklist spoza Traffita jest zero), ale zadziała przy
  pierwszej założonej ręcznie.

Jeden test na obie: to ten sam wzorzec błędu, a nie dwa niezależne.
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


async def _mk_candidate(
    db, *, email: str, status: str, deleted: bool, external_id: str | None
) -> int:
    row = await db.execute(
        text(
            """
            INSERT INTO candidates (
                external_id, external_source, name, lastname, email, status,
                external_deleted_at, created_at, updated_at
            ) VALUES (
                :ext, 'traffit', 'Jan', 'Kowalski', :email,
                CAST(:status AS candidatestatus),
                CASE WHEN :deleted THEN NOW() ELSE NULL END,
                NOW(), NOW()
            ) RETURNING id
            """
        ),
        {
            "ext": external_id,
            "email": email,
            "status": status,
            "deleted": deleted,
        },
    )
    return row.scalar_one()


async def _row(db, cid: int):
    result = await db.execute(
        text(
            "SELECT status::text, external_deleted_at, external_id "
            "FROM candidates WHERE id = :i"
        ),
        {"i": cid},
    )
    return result.fetchone()


class _OneEmployee:
    """Feed `/employees/` z dokładnie jednym, ŻYWYM kandydatem."""

    def __init__(self, ext: str):
        self.ext = ext

    async def total_count(self, path):
        return 1

    async def get_paginated(self, path, *, page_size=100, **kw):
        return
        yield  # pragma: no cover — czyni z tego generator

    async def get_pages(self, path, *, page_size=100, start_page=1, **kw):
        yield 1, [{"id": self.ext}]


async def _run_import(db, ext: str, email: str):
    imp = TraffitImporter(_OneEmployee(ext), db, dry_run=False, batch_size=10)
    imp.build_user_id_map = AsyncMock(return_value={})
    imp._record_new_candidate_index_intent = AsyncMock(return_value=None)
    original = importer_mod.traffit_employee_to_candidate
    importer_mod.traffit_employee_to_candidate = lambda raw, m: {
        "external_id": str(raw["id"]),
        "external_source": "traffit",
        "name": "Jan",
        "lastname": "Kowalski",
        "traffit_raw_name": "Jan",
        "traffit_raw_lastname": "Kowalski",
        "traffit_source_updated_at": None,
        "email": email,
        "phone": None,
        "linkedin": None,
        "city": None,
        "country": None,
        "location": None,
        # Traffit nie zna naszej blacklisty — zawsze przysyła `active`.
        "status": "active",
        "profile_about": None,
        "languages": [],
        "cv_filename": None,
        "cv_extracted_data": {},
        "source": "traffit",
        "created_by": None,
    }
    try:
        return await imp.import_candidates(since=None)
    finally:
        importer_mod.traffit_employee_to_candidate = original


@pytest.mark.asyncio
async def test_adopt_path_clears_the_tombstone_and_keeps_the_blacklist(db) -> None:
    """Kandydat dopasowany PO MAILU dostaje obie ochrony.

    `external_id` celowo puste: wtedy upsert nie ma po czym trafić i importer
    idzie gałęzią adopcji — tą samą, którą na produkcji idzie każdy kolejny
    sync już zaimportowanego kandydata.
    """
    ext = f"t{uuid.uuid4().hex[:10]}"
    email = f"adopt-{uuid.uuid4().hex[:10]}@example.test"
    cid = await _mk_candidate(
        db, email=email, status="blacklisted", deleted=True, external_id=None
    )
    await db.commit()

    progress = await _run_import(db, ext, email)
    assert progress.errors == 0, progress.error_samples

    status, tombstone, external_id = await _row(db, cid)
    assert external_id == ext, "wiersz miał zostać zaadoptowany, nie zdublowany"
    assert tombstone is None, "nagrobek przetrwał powrót kandydata w żywym feedzie"
    assert status == "blacklisted", (
        "sync zdjął blacklistę założoną w NEXUSIE — Traffit nie zna tego stanu, "
        "więc przysyła `active`"
    )


@pytest.mark.asyncio
async def test_adopt_path_still_applies_an_ordinary_status_from_traffit(db) -> None:
    """Lepkość dotyczy WYŁĄCZNIE blacklisty — reszta statusów idzie ze źródła.

    Bez tego testu „ochrona" łatwo urosłaby do zamrożenia całej kolumny, czyli
    do syncu, który przestaje synchronizować.
    """
    ext = f"t{uuid.uuid4().hex[:10]}"
    email = f"adopt-{uuid.uuid4().hex[:10]}@example.test"
    cid = await _mk_candidate(
        db, email=email, status="passive", deleted=False, external_id=None
    )
    await db.commit()

    progress = await _run_import(db, ext, email)
    assert progress.errors == 0, progress.error_samples

    status, _, _ = await _row(db, cid)
    assert status == "active"
