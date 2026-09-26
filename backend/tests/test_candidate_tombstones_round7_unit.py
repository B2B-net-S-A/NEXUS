"""Runda 7 audytu — nagrobki usuniętych kandydatów i okna fazy cv_fields (bez bazy).

* R7-V2-2 — nagrobek maila (druga kartoteka Traffita tej samej osoby);
* R7-V2-3 — INSERT kandydata sam sprawdza nagrobek (usunięcie w trakcie fazy);
* R7-V2-4 — import Talent Radar czyta nagrobki;
* R7-V2-5 — okno fazy ``candidates_cv_fields`` nie gubi kandydata, któremu coś
  spoza syncu przesunęło ``updated_at``.

Testy z bazą: ``test_candidate_erasure_leftovers.py``.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

import app.tasks.traffit_sync as ts


@pytest.fixture
def hmac_key(monkeypatch):
    from app.services import candidate_audit

    monkeypatch.setattr(
        candidate_audit.settings, "CANDIDATE_IDENTITY_FINGERPRINT_KEY", "k" * 40
    )


# ── R7-V2-2: nagrobek maila ──────────────────────────────────────────────────


def test_email_tombstone_is_normalized_keyed_and_separate_from_id(hmac_key):
    from app.services.candidate_audit import (
        candidate_email_tombstone,
        candidate_source_tombstone,
    )

    first = candidate_email_tombstone("Jan.Kowalski@Example.com")
    assert first == candidate_email_tombstone("  jan.kowalski@example.com ")
    assert len(first) == 64 and "kowalski" not in first
    assert first != candidate_email_tombstone("jan.kowalski2@example.com")
    # Inna domena HMAC niż nagrobek identyfikatora.
    assert first != candidate_source_tombstone("email", "jan.kowalski@example.com")
    assert candidate_email_tombstone(None) is None
    assert candidate_email_tombstone("   ") is None


def test_email_tombstone_fails_closed_without_key(monkeypatch):
    from app.services import candidate_audit

    monkeypatch.setattr(
        candidate_audit.settings, "CANDIDATE_IDENTITY_FINGERPRINT_KEY", " "
    )
    with pytest.raises(RuntimeError):
        candidate_audit.candidate_email_tombstone("a@b.pl")


def test_importer_email_tombstone_source_matches_the_sql_guard():
    from app.services.candidate_audit import EMAIL_TOMBSTONE_SOURCE
    from app.services.traffit.importer import _CANDIDATE_TOMBSTONE_GUARD

    assert f"pc.external_source = '{EMAIL_TOMBSTONE_SOURCE}'" in (
        _CANDIDATE_TOMBSTONE_GUARD
    )


# ── R7-V2-3: INSERT sprawdza nagrobek w chwili zapisu ────────────────────────


def test_candidate_upsert_checks_tombstones_in_the_statement_itself():
    from app.services.traffit.importer import (
        _UPSERT_CANDIDATE,
        _UPSERT_CANDIDATE_NO_TOMBSTONES,
    )

    guarded = str(_UPSERT_CANDIDATE)
    assert "NOT EXISTS" in guarded and "purged_candidates" in guarded
    assert ":tombstone_source_hash" in guarded
    assert ":tombstone_email_hash" in guarded
    # R8-V2-4: numer z Traffita usunięty jako kandydat Talent Radar.
    assert "pc.external_source = 'tr_legacy'" in guarded
    assert ":tombstone_legacy_hash" in guarded
    # Nagrobek maila nie blokuje, gdy żyje kandydat z tym mailem (adopcja).
    assert "live.email = CAST(:email AS text)" in guarded
    # Baza sprzed 0388: tabeli nie wolno nawet wymienić w zapytaniu.
    bare = str(_UPSERT_CANDIDATE_NO_TOMBSTONES)
    assert "purged_candidates" not in bare
    assert "WHERE true" in bare


def test_every_parameter_of_the_insert_select_is_explicitly_typed():
    """W `INSERT ... SELECT` Postgres nie wyprowadza typu parametru z kolumny
    docelowej — goły `:created_by` przyszedłby jako `text` i nie wszedł do
    kolumny `integer`."""
    from app.services.traffit.importer import _UPSERT_CANDIDATE

    sql = str(_UPSERT_CANDIDATE)
    select_part = sql[sql.index("SELECT") : sql.index("ON CONFLICT")]
    bare = re.findall(r"(?<!CAST\()(?<![\w:]):(\w+)", select_part)
    assert not bare, f"parametry bez CAST w INSERT ... SELECT: {bare}"


# ── R7-V2-4: Talent Radar czyta nagrobki ─────────────────────────────────────


def _tr_importer():
    from app.services.talent_radar_importer import TalentRadarImporter

    return TalentRadarImporter("postgresql://x", target_db=None)


def test_talent_radar_skips_tombstoned_traffit_id_and_email(hmac_key):
    from app.services.candidate_audit import (
        candidate_email_tombstone,
        candidate_source_tombstone,
    )

    imp = _tr_importer()
    imp._tombstones = {
        "traffit": {candidate_source_tombstone("traffit", "48895")},
        "tr_legacy": set(),
        "email": {candidate_email_tombstone("gone@example.com")},
    }
    assert imp._is_tombstoned({"external_id": "48895", "email": None})
    assert imp._is_tombstoned({"external_id": "1", "email": "GONE@example.com"})
    assert not imp._is_tombstoned({"external_id": "1", "email": "live@example.com"})
    # Żywy właściciel identyfikatora nie jest usuniętą osobą.
    imp._ext_id_to_id = {"1": 7}
    assert not imp._is_tombstoned({"external_id": "1", "email": "gone@example.com"})
    # Żywy wiersz z tym mailem — osoba wróciła, CV łączy się z nią.
    imp._email_to_id = {"gone@example.com": 9}
    assert not imp._is_tombstoned({"external_id": "2", "email": "Gone@example.com"})


def test_talent_radar_without_tombstones_checks_nothing():
    imp = _tr_importer()
    assert not imp._is_tombstoned({"external_id": "1", "email": "a@b.pl"})


@pytest.mark.asyncio
async def test_talent_radar_upsert_does_not_touch_a_tombstoned_person(hmac_key):
    from app.services.candidate_audit import candidate_source_tombstone

    class CommitOnlyDb:
        async def commit(self):
            return None

        def __getattr__(self, name):
            raise AssertionError(f"import dotknął bazy przez .{name}")

    imp = _tr_importer()
    imp.target_db = CommitOnlyDb()
    imp._tombstones = {"tr_legacy": {candidate_source_tombstone("tr_legacy", "5")}}

    async def must_not_run(p):
        raise AssertionError("usunięta osoba doszła do dopasowania")

    imp._find_existing_id = must_not_run
    inserted, updated = await imp._upsert([{"external_id": "5", "email": None}])
    assert (inserted, updated) == (0, 0)
    assert imp.tombstoned == 1


# ── R7-V2-5: okna fazy cv_fields ─────────────────────────────────────────────


def test_id_caps_chain_to_the_smallest_earlier_cursor():
    windows = [
        {"after_id": 500},
        {"after_id": 100},
        {"after_id": 0},
        {"after_id": 600},
    ]
    # Okno z kursorem 0 obejmuje wszystko — ostatnie nie ma już czego dodać.
    assert ts._cv_fields_id_caps(windows) == [None, 500, 100, 0]
    # R8-V2-1: zapisana granica nie istnieje — liczy ją każdy bieg z kursorów.
    assert ts._cv_fields_id_caps(
        [{"after_id": 900}, {"after_id": 0, "until_id": 50}]
    ) == [
        None,
        900,
    ]
    assert ts._cv_fields_id_caps([{"after_id": 0, "until_id": 100}]) == [None]


class _NoopSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _patch_cursor(monkeypatch, initial):
    store = {"windows": [dict(w) for w in initial]}

    async def load(db):
        return [dict(w) for w in store["windows"]]

    async def save(db, windows):
        store["windows"] = [dict(w) for w in windows]

    monkeypatch.setattr(ts, "_load_cv_fields_windows", load)
    monkeypatch.setattr(ts, "_save_cv_fields_windows", save)
    monkeypatch.setattr(ts, "AsyncSessionLocal", lambda: _NoopSession())
    return store


def _fake_backfill(calls, *, stop_on_call=None, stop_at=None):
    async def fake(
        db,
        *,
        after_id=0,
        until_id=None,
        updated_since=None,
        updated_before=None,
        limit=None,
        progress=None,
        **kw,
    ):
        calls.append(
            {
                "after_id": after_id,
                "until_id": until_id,
                "since": updated_since,
                "until": updated_before,
            }
        )
        stats = progress if progress is not None else {}
        stats.setdefault("processed", 0)
        if stop_on_call is not None and len(calls) == stop_on_call:
            stats["last_id"] = stop_at
            stats["stopped_reason"] = "limit"
            return stats
        stats["stopped_reason"] = "done"
        return stats

    return fake


@pytest.mark.asyncio
async def test_carried_window_reaches_candidates_moved_after_its_old_end(monkeypatch):
    """Okno czekało z granicą `until` = start fazy, która je założyła. Kandydat
    z okna, któremu nocne `notes_insights` albo edycja przesunęły `updated_at`
    za tę granicę, wypadał ze wszystkich okien na stałe."""
    import app.services.cv_field_backfill as backfill_mod

    carried = {
        "since": "2026-09-24T02:00:00+00:00",
        "until": "2026-09-24T03:00:00+00:00",
        "after_id": 499,
    }
    _patch_cursor(monkeypatch, [carried])
    calls: list = []
    monkeypatch.setattr(backfill_mod, "backfill_cv_fields", _fake_backfill(calls))

    since = datetime(2026, 9, 25, 2, 0, tzinfo=timezone.utc)
    before = datetime.now(timezone.utc)
    await ts._cv_fields_phase(since)

    old_end = datetime.fromisoformat(carried["until"])
    assert calls[0]["until"] > old_end and calls[0]["until"] >= before
    # Nowe okno nie płaci drugi raz za id, które pokryło okno czekające.
    assert calls[1]["after_id"] == 0 and calls[1]["until_id"] == 499
    assert calls[0]["until_id"] is None


@pytest.mark.asyncio
async def test_window_fully_covered_by_an_earlier_one_is_dropped(monkeypatch):
    import app.services.cv_field_backfill as backfill_mod

    windows = [
        {
            "since": "2026-09-23T02:00:00+00:00",
            "until": "2026-09-23T03:00:00+00:00",
            "after_id": 10,
        },
        {
            "since": "2026-09-24T02:00:00+00:00",
            "until": "2026-09-24T03:00:00+00:00",
            "after_id": 700,
        },
    ]
    store = _patch_cursor(monkeypatch, windows)
    calls: list = []
    monkeypatch.setattr(backfill_mod, "backfill_cv_fields", _fake_backfill(calls))

    await ts._cv_fields_phase(None)

    assert [c["after_id"] for c in calls] == [10]
    assert store["windows"] == []


@pytest.mark.asyncio
async def test_stopped_later_window_does_not_persist_its_id_cap(monkeypatch):
    import app.services.cv_field_backfill as backfill_mod

    carried = {
        "since": "2026-09-24T02:00:00+00:00",
        "until": "2026-09-24T03:00:00+00:00",
        "after_id": 800,
    }
    store = _patch_cursor(monkeypatch, [carried])
    calls: list = []
    monkeypatch.setattr(
        backfill_mod,
        "backfill_cv_fields",
        _fake_backfill(calls, stop_on_call=2, stop_at=300),
    )

    since = datetime(2026, 9, 25, 2, 0, tzinfo=timezone.utc)
    await ts._cv_fields_phase(since)

    (window,) = store["windows"]
    assert window["since"] == since.isoformat()
    assert window["after_id"] == 299
    # R8-V2-1: okno, które zostanie pierwsze, nie może nieść granicy id.
    assert "until_id" not in window


@pytest.mark.asyncio
async def test_first_window_with_a_saved_id_cap_still_reaches_new_ids(monkeypatch):
    """R8-V2-1: okno zapisane przed rundą 8 z `until_id` zostało pierwsze po
    domknięciu starszego. Z zapisaną granicą obejmowało tylko id <= 100,
    a nowe okno (kursor 0 poprzedniego) odpadało jako „pokryte” — nowo
    zaimportowani kandydaci nie dostawali pól z CV nigdy."""
    import app.services.cv_field_backfill as backfill_mod

    carried = {
        "since": "2026-09-23T02:00:00+00:00",
        "until": "2026-09-23T03:00:00+00:00",
        "after_id": 0,
        "until_id": 100,
    }
    store = _patch_cursor(monkeypatch, [carried])
    calls: list = []
    monkeypatch.setattr(backfill_mod, "backfill_cv_fields", _fake_backfill(calls))

    await ts._cv_fields_phase(datetime(2026, 9, 26, 2, 0, tzinfo=timezone.utc))

    assert calls[0]["after_id"] == 0 and calls[0]["until_id"] is None
    assert store["windows"] == []


@pytest.mark.asyncio
async def test_middle_window_covers_ids_passed_by_an_earlier_window(monkeypatch):
    """R8-V2-1: wcześniejsze okno przesunęło kursor z 50 na 99. Wiersze 51..99
    zaktualizowane później nie należą już do niego, więc okno za nim musi
    sięgać do jego BIEŻĄCEGO kursora, nie do zapisanego 50."""
    import app.services.cv_field_backfill as backfill_mod

    windows = [
        {
            "since": "2026-09-23T02:00:00+00:00",
            "until": "2026-09-23T03:00:00+00:00",
            "after_id": 99,
        },
        {
            "since": "2026-09-24T02:00:00+00:00",
            "until": "2026-09-24T03:00:00+00:00",
            "after_id": 0,
            "until_id": 50,
        },
    ]
    _patch_cursor(monkeypatch, windows)
    calls: list = []
    monkeypatch.setattr(backfill_mod, "backfill_cv_fields", _fake_backfill(calls))

    await ts._cv_fields_phase(None)

    assert calls[0]["until_id"] is None
    assert calls[1]["after_id"] == 0 and calls[1]["until_id"] == 99


# ── R8-V2-4: import Traffita czyta nagrobek `tr_legacy` ──────────────────────


def test_traffit_import_tombstone_source_matches_talent_radar():
    from app.services.talent_radar_importer import SOURCE_VALUE
    from app.services.traffit.importer import TALENT_RADAR_TOMBSTONE_SOURCE

    assert TALENT_RADAR_TOMBSTONE_SOURCE == SOURCE_VALUE


class _TombstoneDb:
    """Atrapa bazy: zwraca nagrobki `purged_candidates` dla podanych źródeł."""

    def __init__(self, rows):
        self._rows = rows

    async def execute(self, statement, params=None):
        from unittest.mock import MagicMock

        result = MagicMock()
        sql = str(statement)
        if "to_regclass" in sql:
            result.fetchone.return_value = (True,)
        else:
            sources = set((params or {}).get("sources") or [])
            result.fetchall.return_value = [
                r for r in self._rows if r[0] in sources
            ]
        return result


@pytest.mark.asyncio
async def test_traffit_import_loads_talent_radar_id_tombstones(hmac_key):
    """R8-V2-4: kandydat usunięty jako `tr_legacy` (numer z Traffita) nie może
    wrócić nocnym importem Traffita, gdy rekord nie ma maila."""
    import app.services.traffit.importer as importer_mod
    from app.services.candidate_audit import candidate_source_tombstone

    legacy = candidate_source_tombstone("tr_legacy", "123")
    imp = importer_mod.TraffitImporter.__new__(importer_mod.TraffitImporter)
    imp.db = _TombstoneDb([("tr_legacy", legacy)])
    ids, emails = await imp._candidate_tombstones()
    assert legacy in ids
    assert emails == set()
