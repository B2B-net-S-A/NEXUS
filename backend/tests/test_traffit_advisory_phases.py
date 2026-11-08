"""Klasa wyjątku w statystykach błędów źródeł (`cv_field_backfill`, `cv_backfill`).

Importer Traffita, który czytał te statystyki, usunięto 08.11.2026; źródła
zostają i dalej zapisują klasę wyjątku w `error_types`.
"""

from __future__ import annotations

from types import SimpleNamespace

import app.services.cv_field_backfill as cv_fields
import tests.test_traffit_error_ids_sources as sources

# Atrapy padającego wiersza z pliku o ID błędów (razem z fixture'em).
cv_fields_env = sources.cv_fields_env


async def test_cv_fields_source_records_the_exception_class(cv_fields_env):
    stats = await cv_fields.backfill_cv_fields(
        sources._CvFieldsDb([sources._candidate(7)])
    )

    assert stats["error_types"] == {7: "RuntimeError"}


async def test_name_backfill_source_records_the_exception_class(monkeypatch):
    import app.services.cv_backfill as cv_backfill

    class _Quota:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Db:
        async def execute(self, *a, **k):
            return [SimpleNamespace(id=287387)]

        async def scalar(self, *a, **k):
            return SimpleNamespace(id=287387)

        async def rollback(self):
            return None

        async def commit(self):
            return None

    async def _broken(*a, **k):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "synthetic")

    monkeypatch.setattr(cv_backfill, "ai_feature", lambda *a, **k: _Quota())
    monkeypatch.setattr(cv_backfill, "backfill_candidate_from_stored_cv", _broken)

    stats = await cv_backfill.backfill_missing_names(_Db())

    assert stats["error_ids"] == [287387]
    assert stats["error_types"] == {287387: "UnicodeDecodeError"}
