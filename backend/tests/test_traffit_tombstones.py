"""Kandydat skasowany w Traffitcie zostaje w Nexusie, ale oznaczony.

Do tej pory 404/410 z Traffita było wyłącznie LICZONE (`gone_upstream`).
Licznik żyje tyle, co statystyki biegu, więc informacja „tej osoby już u
źródła nie ma" nie docierała nigdzie: rekruter widział zwykły profil,
`reconcile` pokazywał rozjazd bez wyjaśnienia, a każdy kolejny sweep pytał
Traffita o tego samego nieistniejącego kandydata.

Trzy rzeczy, których ten mechanizm CELOWO nie robi i które pilnują tu testy:

1. **Nie kasuje wiersza.** Profil w Nexusie ma własną wartość niezależną od
   Traffita — notatki, etapy, ślady RODO. Usunięcie rekordu u źródła nie jest
   zgodą na usunięcie naszych danych.
2. **Nie stawia nagrobka za brakujący PLIK.** 404 na `/employees/{id}/files`
   to odpowiedź o osobie; 404 na pobraniu pojedynczego pliku — tylko o pliku.
   Pomylenie tych dwóch oznaczałoby oznaczanie profili jako usunięte z powodu
   jednego nieudanego załącznika.
3. **Nie utrwala pomyłki.** Gdy kandydat wróci w żywym feedzie `/employees/`,
   znacznik znika. Bez tego pojedyncze 404 (chwilowa awaria Traffita, rekord
   przywrócony z kosza) zostawiałoby trwałe kłamstwo na żywym profilu.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.services.traffit.importer import TraffitImporter

UTC_NOW = "NOW()"


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


async def _mk_candidate(db, ext: str, *, deleted: bool = False) -> int:
    row = await db.execute(
        text(
            f"""
            INSERT INTO candidates (
                external_id, external_source, name, lastname,
                external_deleted_at, created_at, updated_at
            ) VALUES (
                :e, 'traffit', 'Jan', 'Kowalski',
                {UTC_NOW if deleted else "NULL"}, NOW(), NOW()
            ) RETURNING id
            """
        ),
        {"e": ext},
    )
    return row.scalar_one()


async def _tombstone(db, cid: int):
    row = await db.execute(
        text("SELECT external_deleted_at FROM candidates WHERE id = :i"), {"i": cid}
    )
    return row.scalar_one()


class _FilesStatus:
    """Odpowiada zadanym kodem na LISTĘ plików kandydata."""

    def __init__(self, by_emp: dict[str, int]):
        self.by_emp = by_emp
        self._http = self

    async def _get_raw(self, path, page=1, page_size=50):
        emp = path.split("/")[2]
        code = self.by_emp.get(emp, 200)

        class _R:
            status_code = code

            @staticmethod
            def json():
                return []

        return _R()


class _ContentGone:
    """Listing zwraca plik, ale POBRANIE tego pliku daje 404 — czyli nie ma
    pliku, a nie osoby."""

    def __init__(self):
        self.config = type("C", (), {"api_base": "https://traffit.test/api"})()
        self._http = self

    async def _get_raw(self, path, page=1, page_size=50):
        class _R:
            status_code = 200

            @staticmethod
            def json():
                return [{"id": "f1", "name": "cv.pdf"}]

        return _R()

    async def _ensure_token(self):
        return "t"

    async def _throttle(self):
        return None

    async def get(self, url, headers=None):
        class _R:
            status_code = 404
            content = b""
            headers: dict[str, str] = {}

        return _R()


def _imp(traffit, db) -> TraffitImporter:
    return TraffitImporter(traffit, db, dry_run=False, batch_size=100)


@pytest.mark.asyncio
async def test_gone_candidate_gets_a_tombstone_but_keeps_the_row(
    db, monkeypatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "TRAFFIT_SYNC_FULL_FILES_LIMIT", 5000)
    ext = f"t{uuid.uuid4().hex[:10]}"
    cid = await _mk_candidate(db, ext)
    await db.commit()

    progress = await _imp(_FilesStatus({ext: 404}), db).import_candidate_files(
        since=None
    )

    assert progress.gone_upstream >= 1
    assert progress.tombstoned >= 1
    assert await _tombstone(db, cid) is not None

    # Wiersz ZOSTAJE — to jest cała różnica między nagrobkiem a kasowaniem.
    row = await db.execute(
        text("SELECT name, lastname FROM candidates WHERE id = :i"), {"i": cid}
    )
    assert row.fetchone() == ("Jan", "Kowalski")


@pytest.mark.asyncio
async def test_410_tombstones_the_same_way(db, monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "TRAFFIT_SYNC_FULL_FILES_LIMIT", 5000)
    ext = f"t{uuid.uuid4().hex[:10]}"
    cid = await _mk_candidate(db, ext)
    await db.commit()

    await _imp(_FilesStatus({ext: 410}), db).import_candidate_files(since=None)

    assert await _tombstone(db, cid) is not None


@pytest.mark.asyncio
async def test_a_missing_FILE_does_not_tombstone_the_person(db, monkeypatch) -> None:
    """Najważniejszy strażnik: nieudane pobranie załącznika NIE jest dowodem,
    że osoba zniknęła."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "TRAFFIT_SYNC_FULL_FILES_LIMIT", 5000)
    ext = f"t{uuid.uuid4().hex[:10]}"
    cid = await _mk_candidate(db, ext)
    await db.commit()

    progress = await _imp(_ContentGone(), db).import_candidate_files(since=None)

    assert progress.gone_upstream >= 1, "brak pliku ma być nadal policzony"
    assert progress.tombstoned == 0, "ale NIE jako zniknięcie osoby"
    assert await _tombstone(db, cid) is None


@pytest.mark.asyncio
async def test_tombstone_is_cleared_when_the_candidate_comes_back(db) -> None:
    """Samoleczenie. Bez tego pojedyncze 404 zostawiałoby trwałe „usunięty u
    źródła" na profilu, który znów jest w żywym feedzie."""
    from unittest.mock import AsyncMock

    import app.services.traffit.importer as importer_mod

    ext = f"t{uuid.uuid4().hex[:10]}"
    cid = await _mk_candidate(db, ext, deleted=True)
    await db.commit()
    assert await _tombstone(db, cid) is not None

    class _OneEmployee:
        async def total_count(self, path):
            return 1

        async def get_paginated(self, path, *, page_size=100, **kw):
            return
            yield  # pragma: no cover — czyni z tego generator

        async def get_pages(self, path, *, page_size=100, start_page=1, **kw):
            yield 1, [{"id": ext}]

    imp = TraffitImporter(_OneEmployee(), db, dry_run=False, batch_size=10)
    imp.build_user_id_map = AsyncMock(return_value={})
    imp._record_new_candidate_index_intent = AsyncMock(return_value=None)
    orig = importer_mod.traffit_employee_to_candidate
    importer_mod.traffit_employee_to_candidate = lambda raw, m: {
        "external_id": str(raw["id"]),
        "external_source": "traffit",
        "name": "Jan",
        "lastname": "Kowalski",
        "traffit_raw_name": "Jan",
        "traffit_raw_lastname": "Kowalski",
        "traffit_source_updated_at": None,
        "email": None,
        "phone": None,
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
    try:
        progress = await imp.import_candidates(since=None)
    finally:
        importer_mod.traffit_employee_to_candidate = orig

    assert progress.errors == 0, progress.error_samples
    assert await _tombstone(db, cid) is None, "nagrobek przetrwał powrót kandydata"


@pytest.mark.asyncio
async def test_second_run_does_not_move_the_date(db, monkeypatch) -> None:
    """Znacznik zapamiętuje PIERWSZĄ obserwację zniknięcia. Gdyby przesuwał się
    przy każdym biegu, mówiłby „kiedy ostatnio sprawdzaliśmy", a nie „od kiedy
    nie ma" — a licznik `tombstoned` rósłby w nieskończoność i przestał
    odpowiadać na pytanie, czy zniknęło coś NOWEGO."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "TRAFFIT_SYNC_FULL_FILES_LIMIT", 5000)
    ext = f"t{uuid.uuid4().hex[:10]}"
    cid = await _mk_candidate(db, ext)
    await db.commit()

    traffit = _FilesStatus({ext: 404})
    await _imp(traffit, db).import_candidate_files(since=None)
    first = await _tombstone(db, cid)

    second = await _imp(traffit, db).import_candidate_files(since=None)

    assert await _tombstone(db, cid) == first
    assert second.tombstoned == 0


def test_tombstoned_reaches_sync_status() -> None:
    from app.services.traffit.importer import PhaseProgress
    from app.tasks.traffit_sync import _summarize

    p = PhaseProgress(phase="candidate_files")
    p.tombstoned = 3
    assert _summarize(p.as_dict())["tombstoned"] == 3


def test_the_index_is_partial_in_all_three_places() -> None:
    """Indeks jest CZĘŚCIOWY i musi być taki w każdym z trzech miejsc, które go
    opisują: metadanych ORM, migracji `0221` i lustra DDL w `entrypoint.sh`.

    Pierwsza wersja tego PR-a deklarowała go na kolumnie przez `index=True`,
    co rejestruje w metadanych indeks PEŁNY — o dokładnie tej samej nazwie,
    którą migracja nadaje częściowemu. Taka para nie wybucha: baza dostaje
    poprawny indeks, testy przechodzą, a rozjazd siedzi cicho w katalogu, aż
    `/api/admin/schema-drift` zacznie go raportować na prodzie albo
    `alembic --autogenerate` wystawi DROP + CREATE gubiący predykat — czyli
    zamieni indeks na pełny na ~57 tys. wierszy, po cichu i bez błędu.

    Rozjazd między metadanymi a DDL jest niewidoczny dla każdego testu
    zachowania, bo obie strony *działają*. Dlatego jest osobno przypięty tutaj.
    """
    import re
    from pathlib import Path

    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex

    from app.models.candidate import Candidate

    name = "ix_candidates_external_deleted_at"
    predicate = "where external_deleted_at is not null"

    def _flat(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip().lower()

    idx = [i for i in Candidate.__table__.indexes if i.name == name]
    assert len(idx) == 1, f"ORM nie zna indeksu {name}"
    orm_ddl = _flat(str(CreateIndex(idx[0]).compile(dialect=postgresql.dialect())))
    assert predicate in orm_ddl, f"metadane ORM opisują indeks PEŁNY: {orm_ddl}"

    backend = Path(__file__).resolve().parents[1]
    for path in (
        backend / "alembic/versions/0221_candidate_external_deleted.py",
        backend / "entrypoint.sh",
    ):
        body = _flat(path.read_text(encoding="utf-8"))
        assert name in body, f"{path.name} nie tworzy {name}"
        assert predicate in body, f"{path.name} tworzy indeks PEŁNY, nie częściowy"
