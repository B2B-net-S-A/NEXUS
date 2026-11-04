"""Faza ``candidates_cv_fields`` w nocnym syncu — kontrakty.

Domyka lukę świeżości po Fali 3: nowe/zmienione CV dostają pola strukturalne
w tę samą noc, w którą przyszły. Kontrakty, które muszą przeżyć:
- pełny bieg nie dokłada własnego okna (no-op z notatką, gdy nic nie czeka),
  ale domyka okna, których delta nie skończyła w budżecie (runda 6 audytu);
- selekcja = okno `updated_at` biegu ∩ scope filter (tekst + puste pola);
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
    # Po enrich_names (imiona najpierw — ten sam parser). Od audytu 22.09 r2
    # (INTG-01) ruchy pipeline'u idą PRZED fazami wzbogacania CV.
    assert (
        names.index("pipelines")
        < names.index("candidates_enrich_names")
        < names.index("candidates_cv_fields")
    )


class _NoopSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _patch_cursor(monkeypatch, initial):
    """Kursor okien w pamięci zamiast w `traffit_sync_state`."""
    store = {"windows": [dict(w) for w in initial]}

    async def load(db):
        return [dict(w) for w in store["windows"]]

    async def save(db, windows):
        store["windows"] = [dict(w) for w in windows]

    monkeypatch.setattr(ts, "_load_cv_fields_windows", load)
    monkeypatch.setattr(ts, "_save_cv_fields_windows", save)
    monkeypatch.setattr(ts, "AsyncSessionLocal", lambda: _NoopSession())
    return store


@pytest.mark.asyncio
async def test_full_mode_without_pending_windows_is_deliberate_noop(monkeypatch):
    _patch_cursor(monkeypatch, [])
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


def _fake_backfill(calls, *, stop_at=None, reason="limit"):
    """Backfill, który „przetwarza" okno do `stop_at` (last_id) i staje."""

    async def fake(
        db,
        *,
        after_id=0,
        updated_since=None,
        updated_before=None,
        limit=None,
        progress=None,
        **kw,
    ):
        calls.append(
            {
                "after_id": after_id,
                "since": updated_since,
                "until": updated_before,
                "limit": limit,
            }
        )
        stats = progress if progress is not None else {}
        stats.setdefault("processed", 0)
        stats["stopped_reason"] = None
        if stop_at is not None and len(calls) == 1:
            stats["processed"] += limit
            stats["last_id"] = stop_at
            stats["stopped_reason"] = reason
            return stats
        stats["processed"] += 1
        stats["stopped_reason"] = "done"
        return stats

    return fake


@pytest.mark.asyncio
async def test_delta_window_cut_by_limit_is_carried_not_lost(monkeypatch):
    """Runda 6 audytu (T6-3): limit 200 po `id` rosnąco w oknie
    `updated_at >= files_since` po cichu gubił resztę okna — kolejna noc ma
    nowe `files_since`. Niedokończone okno musi czekać w kursorze i wznowić się
    OD wiersza, na którym bieg stanął."""
    import app.services.cv_field_backfill as backfill_mod

    store = _patch_cursor(monkeypatch, [])
    calls: list = []
    monkeypatch.setattr(
        backfill_mod, "backfill_cv_fields", _fake_backfill(calls, stop_at=500)
    )
    monkeypatch.setattr(ts.settings, "TRAFFIT_SYNC_CV_FIELDS_LIMIT", 7, raising=False)

    since = datetime(2026, 9, 25, 2, 0, tzinfo=timezone.utc)
    result = await ts._cv_fields_phase(since)

    assert calls[0]["since"] == since and calls[0]["after_id"] == 0
    assert calls[0]["limit"] == 7
    assert calls[0]["until"] is not None and calls[0]["until"] > since
    out = result.as_dict()
    assert out["stopped_reason"] == "limit"
    assert out["pending_windows"] == 1
    (window,) = store["windows"]
    assert window["since"] == since.isoformat()
    # last_id=500 nie został przetworzony (limit) — wznowienie od niego.
    assert window["after_id"] == 499


@pytest.mark.asyncio
async def test_next_delta_finishes_carried_window_before_its_own(monkeypatch):
    import app.services.cv_field_backfill as backfill_mod

    carried = {
        "since": "2026-09-24T02:00:00+00:00",
        "until": "2026-09-24T03:00:00+00:00",
        "after_id": 499,
    }
    store = _patch_cursor(monkeypatch, [carried])
    calls: list = []
    monkeypatch.setattr(backfill_mod, "backfill_cv_fields", _fake_backfill(calls))

    since = datetime(2026, 9, 25, 2, 0, tzinfo=timezone.utc)
    result = await ts._cv_fields_phase(since)

    assert [c["after_id"] for c in calls] == [499, 0]
    assert calls[0]["since"].isoformat() == carried["since"]
    assert calls[1]["since"] == since
    assert store["windows"] == []
    out = result.as_dict()
    assert out["carried_windows"] == 1 and out["pending_windows"] == 0


@pytest.mark.asyncio
async def test_full_run_drains_carried_windows(monkeypatch):
    """Pełny bieg nie dokłada własnego okna, ale nie może przerywać zaległości."""
    import app.services.cv_field_backfill as backfill_mod

    carried = {
        "since": "2026-09-24T02:00:00+00:00",
        "until": "2026-09-24T03:00:00+00:00",
        "after_id": 10,
    }
    store = _patch_cursor(monkeypatch, [carried])
    calls: list = []
    monkeypatch.setattr(backfill_mod, "backfill_cv_fields", _fake_backfill(calls))

    await ts._cv_fields_phase(None)

    assert len(calls) == 1 and calls[0]["after_id"] == 10
    assert store["windows"] == []


@pytest.mark.asyncio
async def test_quota_stop_keeps_later_windows_untouched(monkeypatch):
    import app.services.cv_field_backfill as backfill_mod

    carried = {
        "since": "2026-09-24T02:00:00+00:00",
        "until": "2026-09-24T03:00:00+00:00",
        "after_id": 0,
    }
    store = _patch_cursor(monkeypatch, [carried])
    calls: list = []
    monkeypatch.setattr(
        backfill_mod,
        "backfill_cv_fields",
        _fake_backfill(calls, stop_at=42, reason="quota: x"),
    )

    since = datetime(2026, 9, 25, 2, 0, tzinfo=timezone.utc)
    await ts._cv_fields_phase(since)

    assert len(calls) == 1  # własne okno nie ruszone
    # Runda 7 (R7-V2-5): okno czekające sięga w czasie do startu bieżącej fazy
    # i obejmuje wszystkie id powyżej swojego kursora (0), więc nowe okno nie
    # ma już czego dodać i nie jest zapisywane obok.
    assert [w["after_id"] for w in store["windows"]] == [41]
    assert store["windows"][0]["since"] == carried["since"]


def test_windows_payload_is_parsed_defensively():
    payload = {
        "delta": {
            "windows": [
                {
                    "since": "2026-09-24T02:00:00+00:00",
                    "until": "2026-09-24T03:00:00+00:00",
                    "after_id": "5",
                },
                {"since": "x", "until": None},
                "garbage",
            ]
        },
        "full": {"after_id": 3},
    }
    windows = ts._cv_fields_windows_from_payload(payload)
    assert windows == [
        {
            "since": "2026-09-24T02:00:00+00:00",
            "until": "2026-09-24T03:00:00+00:00",
            "after_id": 5,
        }
    ]
    assert ts._cv_fields_windows_from_payload(None) == []
