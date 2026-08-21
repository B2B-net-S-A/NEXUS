"""Wywołanie AI nie może trzymać otwartej transakcji wołającego.

`ai_feature` zapisuje wiersz `ai_usage_logs` w sesji WOŁAJĄCEGO i świadomie nie
commituje („The increment lives in the caller's session"). Jeśli wywołanie do
Claude'a leci wewnątrz tej otwartej transakcji, to przez cały round-trip —
do ~273 s przy trzech próbach po 90 s timeoutu — `AsyncSession` trzyma
wypożyczone połączenie z puli (20+40 na JEDNYM workerze uvicorna) oraz blokadę
wiersza na `(feature, user_id, period_start)`.

Dwa skutki, oba mierzalne:

* kilkunastu rekruterów na zakładce „Dopasowanie" podczas przeciążenia
  Anthropica zjada pulę, po czym KAŻDE inne żądanie — lista kandydatów,
  logowanie, ruch w pipelinie — czeka `pool_timeout` i wywala 500 bez nagłówków
  CORS („Network Error" we froncie);
* transakcja otwarta przez minuty przypina horyzont xmin, więc autovacuum nie
  odzyskuje martwych krotek w CAŁYM klastrze.

Ścieżka, która zrobiła to dobrze (czat interaktywnego CV), commituje przed
wywołaniem LLM. Ten test pilnuje, żeby uzasadnienie dopasowania też.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import match_justification_service as mjs

BACKEND = Path(__file__).resolve().parents[1]


class _RecordingSession:
    """Sesja, która pamięta, czy w chwili wywołania LLM była w transakcji."""

    def __init__(self, scalars: list | None = None) -> None:
        self.in_txn = False
        self.commits = 0
        self.added: list = []
        self._scalars = list(scalars or [])

    async def scalar(self, _stmt):
        self.in_txn = True  # każdy odczyt otwiera transakcję
        return self._scalars.pop(0) if self._scalars else None

    async def execute(self, _stmt):
        self.in_txn = True
        return SimpleNamespace(fetchone=lambda: None)

    async def commit(self):
        self.in_txn = False
        self.commits += 1

    async def rollback(self):
        self.in_txn = False

    def add(self, obj):
        self.added.append(obj)

    async def refresh(self, _obj):
        return None

    def in_transaction(self) -> bool:
        return self.in_txn


@pytest.mark.asyncio
async def test_provider_is_called_with_no_open_transaction(monkeypatch) -> None:
    candidate = SimpleNamespace(id=1, ai_summary="x", skills=[], raw_cv_text="cv")
    job = SimpleNamespace(id=10, title="DevOps")
    # Kolejność odczytów w `get_or_generate`: kandydat, oferta, wiersz cache.
    db = _RecordingSession([candidate, job, None])

    async def _breakdown(_c, _j, _db):
        return SimpleNamespace(as_dict=lambda: {"total": 70.0})

    monkeypatch.setattr(mjs, "_compute_breakdown", _breakdown)
    monkeypatch.setattr(mjs, "_input_hash", lambda *_a: "hash")

    seen: dict[str, bool] = {}

    async def _fake_prose(_c, _j, _b):
        seen["in_txn"] = db.in_transaction()
        return {"summary": "s", "pros": [], "watchouts": []}

    monkeypatch.setattr(mjs, "generate_prose", _fake_prose)

    class _Gate:
        async def __aenter__(self):
            db.in_txn = True  # `check_and_increment` robi INSERT ... ON CONFLICT
            return None

        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr(mjs, "ai_feature", lambda *_a, **_k: _Gate())

    await mjs.get_or_generate(1, 10, db, user_id=7)

    assert seen["in_txn"] is False, (
        "w chwili wejścia do wywołania LLM sesja MUSI być poza transakcją — "
        "inaczej połączenie z puli i blokada wiersza kwoty są trzymane przez "
        "cały round-trip do providera"
    )
    assert db.commits >= 1


def test_commit_sits_between_the_quota_gate_and_the_provider_call() -> None:
    """Strukturalnie, bo kolejność dwóch linii jest tu całym mechanizmem."""
    src = (BACKEND / "app/services/match_justification_service.py").read_text(
        encoding="utf-8"
    )
    gate = src.index("async with ai_feature(db, AIFeatureKey.scoring")
    prose = src.index("prose = await generate_prose(", gate)
    commit = src.index("await db.commit()", gate)
    assert gate < commit < prose, (
        "commit musi stać MIĘDZY bramką kwoty a wywołaniem providera — "
        "przed bramką nie utrwala licznika, po wywołaniu nie zwalnia połączenia"
    )
