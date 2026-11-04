"""Import z pliku nie gubi czarnej listy (audyt 13.10.2026, pkt 22) — bez bazy.

„Testowy (czarna lista)” z CSV albo z `/bulk-import` zapisywał się jako
„Testowy” ze statusem `active`: dopisek znikał, a system zaczynał proponować
osobę. Tak jak korekta 0436 i mapper Traffita: czarna lista z SUROWEGO imienia
idzie do `status = blacklisted`, dopiero potem dopisek znika.

Sesja bazy jest atrapą (lista dodanych obiektów); trasa z prawdziwą bazą jest
w `test_candidate_name_marker_api.py`. Imiona są wymyślone.
"""

from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import UploadFile

from app.api import import_export
from app.api.candidates import bulk_import_candidates
from app.models.candidate import Candidate, CandidateStatus


class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    """Tyle sesji, ile potrzebuje pętla importu: add, flush (nadaje id), savepoint."""

    def __init__(self) -> None:
        self.added: list = []
        self._next_id = 9000

    async def scalar(self, *_a, **_kw):
        return None  # brak duplikatu po e-mailu

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            if hasattr(obj, "id") and getattr(obj, "id", None) is None:
                obj.id = self._next_id
                self._next_id += 1

    def begin_nested(self) -> _Nested:
        return _Nested()

    async def commit(self) -> None:
        return None

    def candidates(self) -> list[Candidate]:
        return [obj for obj in self.added if isinstance(obj, Candidate)]


@pytest.fixture(autouse=True)
def _no_index_queue(monkeypatch):
    from app.services import index_outbox_service

    monkeypatch.setattr(index_outbox_service, "record_bulk_reindex", AsyncMock())


def _csv(rows: list[tuple[str, str, str]]) -> UploadFile:
    lines = ["name,lastname,email"] + [",".join(row) for row in rows]
    data = ("\n".join(lines) + "\n").encode("utf-8")
    return UploadFile(file=io.BytesIO(data), filename="kandydaci.csv")


@pytest.mark.asyncio
async def test_csv_import_keeps_the_blacklist_as_status():
    db = _FakeSession()
    result = await import_export.import_candidates(
        current_user=SimpleNamespace(id=7),
        db=db,
        file=_csv(
            [
                ("Jan", "Testowy (czarna lista)", "jan.testowy@example.com"),
                ("[czarna lista] Ola", "Przykładowa", "ola.przyk@example.com"),
                ("Piotr", "Zwyczajny", "piotr.zw@example.com"),
            ]
        ),
    )
    assert result["imported"] == 3, result
    by_lastname = {c.lastname: c for c in db.candidates()}
    assert by_lastname["Testowy"].name == "Jan"
    assert by_lastname["Testowy"].status == CandidateStatus.blacklisted
    assert by_lastname["Przykładowa"].name == "Ola"
    assert by_lastname["Przykładowa"].status == CandidateStatus.blacklisted
    assert by_lastname["Zwyczajny"].status == CandidateStatus.active


@pytest.mark.asyncio
async def test_bulk_import_keeps_the_blacklist_as_status():
    db = _FakeSession()
    result = await bulk_import_candidates(
        data=[
            {"name": "Jan", "lastname": "Testowy (czarna lista)"},
            {"name": "(black list) Ola", "lastname": "Przykładowa"},
            {"name": "Piotr", "lastname": "Zwyczajny"},
            # Jawny status z pliku nie zdejmuje czarnej listy z imienia.
            {"name": "Ewa", "lastname": "Wzorcowa [czarna lista]", "status": "active"},
        ],
        current_user=SimpleNamespace(id=7),
        db=db,
    )
    assert result["created"] == 4, result
    by_lastname = {c.lastname: c for c in db.candidates()}
    assert by_lastname["Testowy"].status == CandidateStatus.blacklisted
    assert by_lastname["Przykładowa"].name == "Ola"
    assert by_lastname["Przykładowa"].status == CandidateStatus.blacklisted
    assert by_lastname["Wzorcowa"].status == CandidateStatus.blacklisted
    assert by_lastname["Zwyczajny"].status == CandidateStatus.active
