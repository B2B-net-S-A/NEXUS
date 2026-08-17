"""Faza ``candidates_cv_fields`` w nocnym syncu — kontrakty.

Domyka lukę świeżości po Fali 3: nowe/zmienione CV dostają pola strukturalne
w tę samą noc, w którą przyszły. Kontrakty, które muszą przeżyć:
- delta-only: full-scan (files_since=None) jest świadomym no-op z notatką;
- selekcja = kandydaci dotknięci w biegu ∩ scope filter (tekst + puste pola);
- ``backfill_cv_fields(candidate_ids=[])`` nie dotyka bazy i nie płaci.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services.cv_field_backfill import backfill_cv_fields
from app.tasks import traffit_sync as ts


def test_phase_registered_in_plan_and_names():
    assert "candidates_cv_fields" in ts.PHASE_NAMES
    importer = SimpleNamespace(
        import_users=None,
        import_clients=None,
        import_contacts=None,
        import_workflows=None,
        import_candidates=lambda **k: None,
        import_jobs=lambda **k: None,
        import_talents=None,
        import_candidates_cv=lambda **k: None,
        import_candidate_files=lambda **k: None,
        enrich_missing_names=lambda **k: None,
        import_pipelines=lambda **k: None,
        import_candidate_activities=lambda **k: None,
        import_candidate_sources=lambda **k: None,
    )
    names = [name for name, _ in ts._phase_plan(importer, None, None)]
    assert "candidates_cv_fields" in names
    # Po enrich_names (imiona najpierw — ten sam parser), przed pipelines.
    assert (
        names.index("candidates_enrich_names")
        < names.index("candidates_cv_fields")
        < names.index("pipelines")
    )


@pytest.mark.asyncio
async def test_full_mode_is_deliberate_noop():
    result = await ts._cv_fields_phase(None)
    out = result.as_dict()
    assert out["processed"] == 0
    assert "note" in out and "delta-only" in out["note"]
    assert result.errors == 0


@pytest.mark.asyncio
async def test_backfill_with_empty_ids_touches_nothing():
    class ExplodingDb:
        def __getattr__(self, name):  # każda interakcja z DB = porażka testu
            raise AssertionError(f"backfill dotknął DB przez .{name}")

    stats = await backfill_cv_fields(ExplodingDb(), candidate_ids=[])
    assert stats["processed"] == 0 and stats["stopped_reason"] is None


@pytest.mark.asyncio
async def test_delta_phase_scopes_by_touched_ids(monkeypatch):
    captured: dict = {}

    async def fake_backfill(db, *, candidate_ids=None, limit=None, **kw):
        captured["ids"] = candidate_ids
        captured["limit"] = limit
        return {"processed": len(candidate_ids or []), "updated": 0, "errors": 0}

    class FakeResult:
        def scalars(self):
            return self

        def all(self):
            return [11, 22]

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, *a, **k):
            return FakeResult()

    import app.services.cv_field_backfill as backfill_mod

    monkeypatch.setattr(backfill_mod, "backfill_cv_fields", fake_backfill)
    monkeypatch.setattr(ts, "AsyncSessionLocal", lambda: FakeSession())
    monkeypatch.setattr(ts.settings, "TRAFFIT_SYNC_CV_FIELDS_LIMIT", 7, raising=False)

    result = await ts._cv_fields_phase(datetime.now(timezone.utc))
    assert captured["ids"] == [11, 22]
    assert captured["limit"] == 7
    assert result.as_dict()["processed"] == 2
