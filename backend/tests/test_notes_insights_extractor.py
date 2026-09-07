"""Polityka zapisu skonsolidowanej ekstrakcji notatek (repo-izacja ad-hoców).

Kontrakty, które MUSZĄ przeżyć każdą przyszłą zmianę:
- FILL_EMPTY dla kolumn; jedyny overwrite = stawka wpisana wcześniej przez nas.
- `_manual_override_skills` blokuje dopisywanie skilli.
- Wiersze z importu 08.2026 (bez `_input_hash`) są świeże, dopóki nie pojawi
  się nowsza notatka — inaczej pierwsze włączenie pętli przemieliłoby ~14k
  kandydatów bez żadnej zmiany danych.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.services.notes_insights_extractor import (
    apply_insights,
    legacy_row_is_fresh,
    notes_fingerprint,
)


def _cand(**kw):
    defaults = dict(
        skills=None,
        years_it_experience=None,
        expected_rate_hourly=None,
        expected_rate_currency=None,
        notice_period=None,
        notice_period_unit=None,
        availability_date=None,
        availability_status="unknown",
        cv_extracted_data=None,
        max_onsite_days_per_week=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _apply(cand, parsed, fp="fp-1"):
    # flag_modified wymaga instrumentacji ORM — SimpleNamespace jej nie ma,
    # więc podmieniamy na no-op przez monkeypatching modułu w teście wywołań.
    import app.services.notes_insights_extractor as mod

    original = mod.flag_modified
    mod.flag_modified = lambda *a, **k: None
    try:
        return apply_insights(cand, parsed, fingerprint=fp)
    finally:
        mod.flag_modified = original


def test_fill_empty_columns_and_insights_merge():
    cand = _cand()
    stats = _apply(
        cand,
        {
            "expected_rate": {"value": 150, "currency": "PLN", "period": "h"},
            "availability": {"notice_period": "1 miesiąc"},
            "years_confirmed": 7,
            "skills_evidenced": [{"name": "SQL", "evidence": "screening"}],
        },
    )
    assert cand.expected_rate_hourly == Decimal("150")
    assert cand.expected_rate_currency == "PLN"
    assert cand.notice_period == 1 and cand.notice_period_unit == "months"
    assert cand.years_it_experience == 7
    assert [s["name"] for s in cand.skills] == ["SQL"]
    ins = cand.cv_extracted_data["_notes_insights"]
    assert ins["_input_hash"] == "fp-1"
    assert ins["_rate_from_notes"] is True
    assert stats["changed"] == 1 and stats["rate_written"] == 1


def test_human_rate_is_never_overwritten():
    cand = _cand(expected_rate_hourly=Decimal("120"))
    stats = _apply(
        cand,
        {"expected_rate": {"value": 180, "currency": "PLN", "period": "h"}},
    )
    assert cand.expected_rate_hourly == Decimal("120"), "ludzki wpis nietykalny"
    assert stats["rate_written"] == 0 and stats["rate_updated"] == 0


def test_our_own_rate_updates_from_newer_note():
    cand = _cand(
        expected_rate_hourly=Decimal("120"),
        cv_extracted_data={
            "_notes_insights": {
                "_rate_from_notes": True,
                "expected_rate": {"value": 120, "period": "h"},
            }
        },
    )
    stats = _apply(
        cand,
        {"expected_rate": {"value": 140, "currency": "PLN", "period": "h"}},
    )
    assert cand.expected_rate_hourly == Decimal("140")
    assert stats["rate_updated"] == 1


def test_rate_equal_to_prior_extraction_counts_as_ours_without_marker():
    # Import 08.2026 nie stemplował _rate_from_notes — równość kolumny
    # z poprzednią ekstrakcją identyfikuje nasz wpis.
    cand = _cand(
        expected_rate_hourly=Decimal("95"),
        cv_extracted_data={
            "_notes_insights": {"expected_rate": {"value": 95, "period": "h"}}
        },
    )
    _apply(cand, {"expected_rate": {"value": 110, "period": "h"}})
    assert cand.expected_rate_hourly == Decimal("110")


def test_manual_skills_lock_respected():
    cand = _cand(
        skills=[{"name": "Java", "level": None}],
        cv_extracted_data={"_manual_override_skills": True},
    )
    stats = _apply(cand, {"skills_evidenced": [{"name": "Python", "evidence": "x"}]})
    assert [s["name"] for s in cand.skills] == ["Java"]
    assert stats["locked_skills"] == 1 and stats["skills_added"] == 0


def test_skills_append_dedup_case_insensitive():
    cand = _cand(skills=[{"name": "python", "level": None}])
    stats = _apply(
        cand,
        {
            "skills_evidenced": [
                {"name": "Python", "evidence": "dup"},
                {"name": "Terraform", "evidence": "ok"},
            ]
        },
    )
    names = [s["name"] for s in cand.skills]
    assert names == ["python", "Terraform"]
    assert stats["skills_added"] == 1


def test_asap_sets_status_and_iso_fills_date():
    cand = _cand()
    _apply(
        cand,
        {"availability": {"raw": "od zaraz", "available_from": "2026-09-01"}},
    )
    assert cand.availability_date == date(2026, 9, 1)
    status = getattr(cand.availability_status, "value", cand.availability_status)
    assert status == "actively_looking"


def test_onsite_days_fill_empty_from_explicit_value():
    cand = _cand()
    stats = _apply(cand, {"preferences": {"max_onsite_days_per_week": 2}})
    assert cand.max_onsite_days_per_week == 2
    assert stats["onsite_days_filled"] == 1
    assert cand.cv_extracted_data["_notes_insights"]["_onsite_days_from_notes"] is True


def test_onsite_days_zero_derived_from_remote_only():
    # "tylko zdalnie" bez jawnej liczby dni = 0 — ten sam wniosek co S4
    # w migracji 0278 dla wierszy zaznaczonych remote_only wcześniej.
    cand = _cand()
    stats = _apply(cand, {"preferences": {"remote_only": True}})
    assert cand.max_onsite_days_per_week == 0
    assert stats["onsite_days_filled"] == 1

    # remote_only=False/None nie zgaduje 0 — brak sygnału zostaje brakiem.
    cand2 = _cand()
    stats2 = _apply(cand2, {"preferences": {"remote_only": False}})
    assert cand2.max_onsite_days_per_week is None
    assert stats2["onsite_days_filled"] == 0


def test_onsite_days_human_value_never_overwritten():
    # Bez "aktualizacji własnego wpisu" jak przy stawce — liczba wprost
    # nazwana przez kandydata (albo wpisana ręcznie w modalu) jest nietykalna,
    # niezależnie od tego, co mówi świeższa notatka.
    cand = _cand(max_onsite_days_per_week=3)
    stats = _apply(cand, {"preferences": {"max_onsite_days_per_week": 5}})
    assert cand.max_onsite_days_per_week == 3, "ludzki wpis nietykalny"
    assert stats["onsite_days_filled"] == 0


def test_onsite_days_out_of_range_and_bool_ignored():
    cand = _cand()
    _apply(cand, {"preferences": {"max_onsite_days_per_week": 8}})
    assert cand.max_onsite_days_per_week is None

    cand2 = _cand()
    _apply(cand2, {"preferences": {"max_onsite_days_per_week": -1}})
    assert cand2.max_onsite_days_per_week is None

    # bool jest podtypem int w Pythonie — musi być jawnie wykluczony, inaczej
    # "max_onsite_days_per_week": true z JSON-a zapisałoby się jako 1.
    cand3 = _cand()
    _apply(cand3, {"preferences": {"max_onsite_days_per_week": True}})
    assert cand3.max_onsite_days_per_week is None

    # Brzeg zakresu (0) przechodzi.
    cand4 = _cand()
    stats4 = _apply(cand4, {"preferences": {"max_onsite_days_per_week": 0}})
    assert cand4.max_onsite_days_per_week == 0
    assert stats4["onsite_days_filled"] == 1


def test_prompt_mentions_onsite_days_and_version_bumped():
    from app.services.notes_insights_extractor import PROMPT, PROMPT_VERSION

    assert "max_onsite_days_per_week" in PROMPT
    assert PROMPT_VERSION == "v4-onsite-days"


def test_rate_guards_reject_md_and_absurd_values():
    cand = _cand()
    _apply(cand, {"expected_rate": {"value": 1200, "period": "md"}})
    assert cand.expected_rate_hourly is None, "stawka dzienna nie wchodzi do PLN/h"
    _apply(cand, {"expected_rate": {"value": 5000, "period": "h"}})
    assert cand.expected_rate_hourly is None, "wartość absurdalna odrzucona"


def test_fingerprint_changes_with_notes_and_is_order_insensitive():
    rows_a = [(1, "2026-08-01T10:00:00", date(2026, 8, 1), "x")]
    rows_b = [(1, "2026-08-02T10:00:00", date(2026, 8, 1), "x")]
    assert notes_fingerprint(rows_a) != notes_fingerprint(rows_b)
    two = [
        (1, "2026-08-01", date(2026, 8, 1), "x"),
        (2, "2026-08-02", date(2026, 8, 2), "y"),
    ]
    assert notes_fingerprint(two) == notes_fingerprint(list(reversed(two)))


def test_legacy_rows_fresh_until_newer_note_appears():
    legacy = {"_v2_extracted_at": "2026-08-14T19:00:00+00:00"}
    older = datetime(2026, 8, 10, tzinfo=timezone.utc)
    newer = datetime(2026, 8, 16, tzinfo=timezone.utc)
    assert legacy_row_is_fresh(legacy, older) is True
    assert legacy_row_is_fresh(legacy, newer) is False
    assert legacy_row_is_fresh(legacy, None) is True
    assert legacy_row_is_fresh(None, older) is False
    assert legacy_row_is_fresh({"_v2_extracted_at": "zepsute"}, older) is False


def test_is_due_daily_schedule(monkeypatch):
    from app.core.config import settings
    from app.tasks.notes_insights_sync import _is_due

    monkeypatch.setattr(settings, "NOTES_INSIGHTS_SYNC_HOUR_UTC", 4)
    now = datetime(2026, 8, 17, 5, 0, tzinfo=timezone.utc)
    assert _is_due(None, now) is True, "pierwszy bieg od razu"
    yesterday = datetime(2026, 8, 16, 5, 0, tzinfo=timezone.utc)
    assert _is_due(yesterday, now) is True, "wczorajszy znacznik + po godzinie okna"
    before_window = datetime(2026, 8, 17, 3, 0, tzinfo=timezone.utc)
    assert _is_due(yesterday, before_window) is False, "przed godziną okna"
    today_already = datetime(2026, 8, 17, 4, 30, tzinfo=timezone.utc)
    assert _is_due(today_already, now) is False, "dzisiejszy bieg już był"


def test_run_stats_include_onsite_days_filled():
    """`onsite_days_filled` musi być zainicjalizowany w `stats` ORAZ wymieniony
    w krotce agregującej `row_stats` do `stats` w `run_notes_insights_sync` —
    brak jednego z dwóch miejsc jest ciszej niż się wydaje: `stats[key] += ...`
    bez initu wywala `KeyError` (crash pierwszego kandydata z tym statem),
    a init bez wpisu w krotce agregującej daje statystykę zamrożoną na 0 na
    zawsze — bez crasha, więc bez szans, że ktoś to zauważy."""
    import inspect

    from app.tasks.notes_insights_sync import run_notes_insights_sync

    source = inspect.getsource(run_notes_insights_sync)
    assert source.count("onsite_days_filled") == 2


def test_malformed_rate_strings_never_raise():
    # Haiku potrafi zwrócić "150-200" — goły float() rzucałby i kandydat
    # wracał do selekcji każdego dnia (pętla-trucizna).
    cand = _cand()
    stats = _apply(cand, {"expected_rate": {"value": "150-200", "period": "h"}})
    assert cand.expected_rate_hourly is None and stats["changed"] == 0

    # Numeryczny string przechodzi (import 08.2026 zapisywał verbatim).
    cand2 = _cand()
    _apply(cand2, {"expected_rate": {"value": "150", "period": "h"}})
    assert cand2.expected_rate_hourly == Decimal("150.0")

    # Zepsuty prior nie wywraca ścieżki "czy to nasz wpis".
    cand3 = _cand(
        expected_rate_hourly=Decimal("120"),
        cv_extracted_data={
            "_notes_insights": {"expected_rate": {"value": "brak danych"}}
        },
    )
    stats3 = _apply(cand3, {"expected_rate": {"value": 140, "period": "h"}})
    assert cand3.expected_rate_hourly == Decimal("120"), "nieznany autor → nietykalne"
    assert stats3["rate_updated"] == 0


def test_stamp_no_content_freshens_candidate_without_ai():
    from datetime import timedelta

    from app.services.notes_insights_extractor import stamp_no_content

    import app.services.notes_insights_extractor as mod

    cand = _cand()
    original = mod.flag_modified
    mod.flag_modified = lambda *a, **k: None
    try:
        stamp_no_content(cand, fingerprint="fp-x")
    finally:
        mod.flag_modified = original
    ins = cand.cv_extracted_data["_notes_insights"]
    assert ins["_input_hash"] == "fp-x" and ins["_no_content"] is True
    # Stempel wystarcza selekcji: znacznik świeższy niż ostatnia notatka.
    just_before = datetime.now(timezone.utc) - timedelta(seconds=5)
    assert legacy_row_is_fresh(ins, just_before) is True

    # Istniejące fakty przeżywają stempel (aktualizują się tylko meta-klucze).
    cand2 = _cand(
        cv_extracted_data={"_notes_insights": {"expected_rate": {"value": 100}}}
    )
    mod.flag_modified = lambda *a, **k: None
    try:
        stamp_no_content(cand2, fingerprint="fp-y")
    finally:
        mod.flag_modified = original
    ins2 = cand2.cv_extracted_data["_notes_insights"]
    assert ins2["expected_rate"] == {"value": 100}
    assert ins2["_input_hash"] == "fp-y"


def test_truncated_json_is_repaired():
    from app.services.notes_insights_extractor import _close_open_json
    import json as _json

    cut = '{"skills_evidenced": [{"name": "SQL", "evidence": "praca z SQ'
    repaired = _json.loads(_close_open_json(cut))
    assert repaired["skills_evidenced"][0]["name"] == "SQL"

    ok = '{"a": [1, 2], "b": "x"}'
    assert _json.loads(_close_open_json(ok)) == {"a": [1, 2], "b": "x"}


def test_truncation_repair_uses_full_tail_not_last_brace():
    # Ucięta odpowiedź z wcześniejszym wewnętrznym '}' — cięcie na rfind('}')
    # gubiło pole "c" ZANIM naprawa je zobaczyła.
    from app.services.notes_insights_extractor import _close_open_json
    import json as _json

    raw = '{"a": {"b": 1}, "c": [{"name": "SQL", "evidence": "praca z SQ'
    repaired = _json.loads(_close_open_json(raw))
    assert repaired["a"] == {"b": 1}
    assert repaired["c"][0]["name"] == "SQL", "pole za wewnętrznym '}' przeżywa"
