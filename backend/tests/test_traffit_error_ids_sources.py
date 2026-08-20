"""Źródła faz `cortex` i `candidates_cv_fields` muszą wypuścić ID padłych wierszy.

Adapter w ``app/tasks/traffit_sync.py`` zamienia ``stats["error_ids"]`` na błędy
PRZYPISANE do wiersza (``PhaseProgress.add_error``), a dopiero przypisany błąd
może trafić do kwarantanny. Dopóki oba źródła liczyły wyłącznie anonimowe
``errors``, każdy błąd tych faz był dla ``_blocking_errors`` nieprzypisany:
jeden trwale wywracający się kandydat mroził GLOBALNY znacznik ``__daily__``
bezterminowo, okno delty rosło z każdą nocą, a ``checks.traffit`` stał na
``degraded`` — czyli sygnał przestawał cokolwiek znaczyć.

Testy są jednostkowe (bez Postgresa): interesuje nas kontrakt statystyk, a nie
zapisy, które ta ścieżka wykonuje po drodze.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.services.cortex.extractor_traffit as cortex_extractor
import app.services.cv_field_backfill as cv_fields


# ── Wspólne atrapy ───────────────────────────────────────────────────────────


class _Nested:
    """Atrapa ``db.begin_nested()`` — savepoint per wiersz."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False  # wyjątek leci dalej, tak jak przy prawdziwym savepoincie


class _CortexDb:
    def __init__(self, rows: list[tuple[int, str]]) -> None:
        self._rows = rows

    async def execute(self, *a, **k):
        rows = self._rows
        return SimpleNamespace(all=lambda: rows)

    async def commit(self):
        return None

    def begin_nested(self):
        return _Nested()


class _CvFieldsDb:
    """Zwraca kandydatów RAZ, potem pustą stronę (keyset pagination)."""

    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._pages = [rows, []]

    async def execute(self, *a, **k):
        page = self._pages.pop(0) if self._pages else []
        scalars = SimpleNamespace(all=lambda: page)
        return SimpleNamespace(scalars=lambda: scalars)

    async def commit(self):
        return None

    def begin_nested(self):
        return _Nested()


def _candidate(cid: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=cid,
        skills=None,
        city=None,
        years_it_experience=None,
        email="x@example.com",  # niepuste → ścieżka kolizji e-maila nie rusza DB
        raw_cv_text="x" * 500,
    )


class _NoopQuota:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.fixture
def cv_fields_env(monkeypatch):
    """Wszystko poza samym zapisem wiersza — zapis ma paść."""
    monkeypatch.setattr(cv_fields, "SLEEP_BETWEEN_CALLS_S", 0)
    monkeypatch.setattr(cv_fields, "ai_feature", lambda *a, **k: _NoopQuota())

    async def _parse(*a, **k):
        return {"city": "Warszawa"}

    monkeypatch.setattr(cv_fields, "parse_cv_with_claude", _parse)

    def _explode(*a, **k):
        raise RuntimeError("apply boom")

    monkeypatch.setattr(cv_fields, "_apply_cv_enrichment", _explode)


# ── cortex ───────────────────────────────────────────────────────────────────


async def test_cortex_failing_row_lands_in_error_ids(monkeypatch):
    async def _taxonomy(db):
        return {}

    def _explode(*a, **k):
        raise RuntimeError("normalize boom")

    monkeypatch.setattr(cortex_extractor, "load_taxonomy", _taxonomy)
    monkeypatch.setattr(cortex_extractor, "normalize_and_upsert", _explode)

    stats = await cortex_extractor.run_traffit_backfill(
        _CortexDb([(41, "Python"), (42, "Go")])
    )
    assert stats["errors"] == 2
    assert stats["error_ids"] == [41, 42]


async def test_cortex_error_ids_are_capped(monkeypatch):
    """500+ padających wierszy to awaria systemowa, nie zatruty wiersz.

    Cap chroni JSONB (``cortex_extraction_runs.stats`` i
    ``traffit_sync_state.stats``) przed 49 tysiącami identyfikatorów po
    nieudanym pełnym reconcile, a nadmiar ZOSTAJE nieprzypisany — czyli dalej
    mrozi watermark, co przy awarii systemowej jest bezpieczną odpowiedzią.
    """

    async def _taxonomy(db):
        return {}

    def _explode(*a, **k):
        raise RuntimeError("normalize boom")

    monkeypatch.setattr(cortex_extractor, "load_taxonomy", _taxonomy)
    monkeypatch.setattr(cortex_extractor, "normalize_and_upsert", _explode)

    rows = [(i, "Python") for i in range(600)]
    stats = await cortex_extractor.run_traffit_backfill(_CortexDb(rows))
    assert stats["errors"] == 600
    assert len(stats["error_ids"]) == cortex_extractor._MAX_ERROR_IDS == 500


# ── candidates_cv_fields ─────────────────────────────────────────────────────


async def test_cv_fields_failing_row_lands_in_error_ids(cv_fields_env):
    stats = await cv_fields.backfill_cv_fields(_CvFieldsDb([_candidate(7)]))
    assert stats["errors"] == 1
    assert stats["error_ids"] == [7]


async def test_cv_fields_error_ids_are_capped(cv_fields_env):
    rows = [_candidate(i) for i in range(600)]
    stats = await cv_fields.backfill_cv_fields(_CvFieldsDb(rows))
    assert stats["errors"] == 600
    assert len(stats["error_ids"]) == cv_fields._MAX_ERROR_IDS == 500


async def test_cv_fields_error_ids_use_the_shared_progress_dict(cv_fields_env):
    """``progress`` bywa obiektem wywołującego — `setdefault`, nie przypisanie.

    Admin endpoint podaje własny słownik i czyta z niego postęp na żywo;
    nadpisanie klucza zgubiłoby to, co wywołujący już tam miał.
    """
    shared: dict = {"errors": 0}
    stats = await cv_fields.backfill_cv_fields(
        _CvFieldsDb([_candidate(11)]), progress=shared
    )
    assert stats is shared
    assert shared["error_ids"] == [11]
