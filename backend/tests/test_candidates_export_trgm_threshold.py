"""Eksport z tekstem ``q`` pobiera wiersze z progiem trygramów listy (audyt r4, 24.11.2026).

``prepare_literal_text`` ustawia ``pg_trgm.similarity_threshold`` przez
``SET LOCAL`` — tylko do końca transakcji. Eksport liczył ``total`` z progiem
listy (0,2 / 0,5), commitował wpis audytu, a wiersze pobierał już w nowej
transakcji (XLSX) albo w osobnej sesji (CSV) z progiem domyślnym 0,3. Plik miał
więc inny zbiór niż ekran i niż ``row_count`` w audycie. Tu bez bazy: sesja
pobierająca wiersze ustawia próg, zanim zacznie strumień. Pełna ścieżka
z Postgresem: ``test_candidates_export_v2.py``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.api import candidates as candidates_api
from app.models.candidate import Candidate


class _EmptyStream:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class _Session:
    def __init__(self, log: list) -> None:
        self.log = log

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def execute(self, statement, params=None):
        self.log.append(("execute", str(statement), dict(params or {})))

    async def stream_scalars(self, _query):
        self.log.append(("stream",))
        return _EmptyStream()


def _assert_threshold_before_stream(log: list, value: str) -> None:
    assert log[0][0] == "execute"
    assert "pg_trgm.similarity_threshold" in log[0][1]
    assert value in log[0][2].values()
    assert log[1] == ("stream",)


@pytest.mark.asyncio
async def test_csv_stream_session_sets_threshold_before_rows(monkeypatch):
    from app.core import database

    log: list = []
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _Session(log))

    chunks = [
        chunk
        async for chunk in candidates_api._stream_candidate_csv(
            select(Candidate), trgm_threshold="0.2"
        )
    ]

    assert chunks  # nagłówek CSV
    _assert_threshold_before_stream(log, "0.2")


@pytest.mark.asyncio
async def test_xlsx_sets_threshold_again_after_audit_commit():
    log: list = []

    await candidates_api._candidate_xlsx(
        _Session(log), select(Candidate), trgm_threshold="0.5"
    )

    _assert_threshold_before_stream(log, "0.5")


@pytest.mark.asyncio
async def test_without_text_no_threshold_is_set(monkeypatch):
    from app.core import database

    log: list = []
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _Session(log))

    _ = [c async for c in candidates_api._stream_candidate_csv(select(Candidate))]

    assert log == [("stream",)]
