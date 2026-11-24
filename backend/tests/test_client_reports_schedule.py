"""Katalog raportów klienta: okresy, terminy, stany, kalendarz, zatwierdzanie.

Czyste funkcje, bez bazy. Przykłady z inwentarza umów 15.11.2026 bez nazw:
„do 5. dnia następnego miesiąca”, „5 dni roboczych po okresie”, „rocznie
do 21 stycznia”, „na koniec każdego kwartału”, rok umowy od 27.02.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.services.client_reports import catalog, schedule, suggest


def test_monthly_period_and_day_of_month_due():
    period = schedule.period_containing("monthly", date(2026, 10, 17))
    assert (period.key, period.start, period.end) == (
        "2026-10",
        date(2026, 10, 1),
        date(2026, 10, 31),
    )
    assert period.label == "październik 2026"
    assert schedule.due_date({"type": "day_of_month", "day": 5}, period) == date(
        2026, 11, 5
    )


def test_day_of_month_clamps_to_short_month():
    period = schedule.period_containing("monthly", date(2027, 1, 10))
    assert schedule.due_date({"type": "day_of_month", "day": 31}, period) == date(
        2027, 2, 28
    )


def test_business_days_skip_weekend_and_polish_holiday():
    # Październik 2026 kończy się w sobotę, 1.11 to niedziela (Wszystkich
    # Świętych), więc 5 dni roboczych = 2–6.11.
    period = schedule.period_containing("monthly", date(2026, 10, 1))
    assert schedule.due_date(
        {"type": "business_days_after", "days": 5}, period
    ) == date(2026, 11, 6)
    # Tydzień 14–20.12 (pon–nd): 2 dni robocze po nim = 21 i 22.12.
    week = schedule.period_containing("weekly", date(2026, 12, 14))
    assert week.end == date(2026, 12, 20)
    assert schedule.due_date({"type": "business_days_after", "days": 2}, week) == date(
        2026, 12, 22
    )


def test_fixed_date_lands_after_period_end():
    year = schedule.period_containing("annual", date(2026, 6, 1))
    assert schedule.due_date({"type": "fixed", "month": 1, "day": 21}, year) == date(
        2027, 1, 21
    )


def test_quarter_and_end_of_period():
    quarter = schedule.period_containing("quarterly", date(2026, 8, 15))
    assert (quarter.key, quarter.label) == ("2026-Q3", "III kwartał 2026")
    assert schedule.due_date({"type": "end_of_period"}, quarter) == date(2026, 9, 30)


def test_contract_year_from_anchor_and_key_roundtrip():
    rule = {"type": "business_days_after", "days": 10, "anchor": "02-27"}
    period = schedule.period_containing("contract_year", date(2026, 11, 15), rule)
    assert (period.start, period.end) == (date(2026, 2, 27), date(2027, 2, 26))
    assert schedule.period_from_key("contract_year", period.key, rule) == period
    with pytest.raises(schedule.ScheduleError):
        schedule.period_from_key("contract_year", "2026-03-01", rule)


def test_contract_year_without_anchor_refuses():
    with pytest.raises(schedule.ScheduleError):
        schedule.period_containing("contract_year", date(2026, 1, 1), {"type": "none"})


@pytest.mark.parametrize(
    "rhythm,key",
    [
        ("monthly", "2026-13"),
        ("quarterly", "2026-Q5"),
        ("weekly", "2026-W00"),
        ("annual", "1999"),
        ("monthly", "2026-Q1"),
    ],
)
def test_bad_period_keys(rhythm, key):
    with pytest.raises(schedule.ScheduleError):
        schedule.period_from_key(rhythm, key)


def test_event_rhythm_has_no_periods():
    assert schedule.recent_periods("on_request", date(2026, 11, 15), 3) == []
    with pytest.raises(schedule.ScheduleError):
        schedule.period_containing("event", date(2026, 11, 15))


@pytest.mark.parametrize(
    "rule",
    [
        {"type": "day_of_month", "day": 0},
        {"type": "days_after", "days": 500},
        {"type": "fixed", "month": 2, "day": 30},
        {"type": "x"},
        {"type": "none", "anchor": "2-27"},
    ],
)
def test_validate_due_rule_refuses(rule):
    with pytest.raises(schedule.ScheduleError):
        schedule.validate_due_rule(rule)


def test_validate_due_rule_drops_unknown_fields():
    assert schedule.validate_due_rule({"type": "day_of_month", "day": 5, "x": 1}) == {
        "type": "day_of_month",
        "day": 5,
    }


@pytest.mark.parametrize(
    "due,sent,today,state",
    [
        (date(2026, 11, 5), True, date(2026, 11, 15), "sent"),
        (None, False, date(2026, 11, 15), "no_date"),
        (date(2026, 11, 5), False, date(2026, 11, 15), "overdue"),
        (date(2026, 11, 15), False, date(2026, 11, 15), "today"),
        (date(2026, 12, 5), False, date(2026, 11, 15), "todo"),
    ],
)
def test_report_state(due, sent, today, state):
    assert schedule.report_state(due, sent, today) == state


# ------------------------------------------------------------- zatwierdzanie


def _user(role="delivery_lead", roles=None):
    return SimpleNamespace(
        id=7, role=SimpleNamespace(value=role), roles=roles or [role]
    )


def test_dl_confirms_only_own_client_and_never_compliance(monkeypatch):
    monkeypatch.setattr(catalog, "is_delivery_lead_governed", lambda user: True)
    dl = _user()
    assert catalog.can_confirm(dl, "management", 12, frozenset({12}))
    assert not catalog.can_confirm(dl, "management", 11, frozenset({12}))
    assert not catalog.can_confirm(dl, "compliance", 12, frozenset({12}))


def test_admin_confirms_everything_and_finance_nothing(monkeypatch):
    monkeypatch.setattr(catalog, "is_delivery_lead_governed", lambda user: False)
    assert catalog.can_confirm(_user("admin"), "compliance", 12, None)
    assert not catalog.can_confirm(_user("finance"), "management", 12, None)


# ------------------------------------------------------------------ kalendarz


def _definition(**kwargs):
    base = dict(
        id=1,
        client_id=12,
        rhythm="monthly",
        due_rule={"type": "day_of_month", "day": 5},
        valid_from=None,
        valid_to=None,
        preparer="dl",
        preparer_user_id=None,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_calendar_month_has_due_item_and_carries_overdue():
    definition = _definition()
    month, later = catalog.calendar_entries(
        definition, date(2026, 12, 1), date(2026, 12, 31), date(2026, 12, 10), {}
    )
    keys = [(e.period.key, e.state, e.carried) for e in month]
    # Za listopad termin 05.12 minął; październik (05.11) przeniesiony jako zaległy.
    assert ("2026-11", "overdue", False) in keys
    assert ("2026-10", "overdue", True) in keys
    assert later == []


def test_calendar_sent_period_is_not_carried():
    definition = _definition()
    sent = {"2026-10": object()}
    month, _ = catalog.calendar_entries(
        definition, date(2026, 12, 1), date(2026, 12, 31), date(2026, 12, 10), sent
    )
    assert all(e.period.key != "2026-10" for e in month)


def test_calendar_past_month_does_not_carry():
    definition = _definition()
    month, _ = catalog.calendar_entries(
        definition, date(2026, 10, 1), date(2026, 10, 31), date(2026, 12, 10), {}
    )
    assert [e.period.key for e in month] == ["2026-09"]


def test_calendar_quarterly_shows_in_upcoming():
    definition = _definition(rhythm="quarterly", due_rule={"type": "end_of_period"})
    month, later = catalog.calendar_entries(
        definition, date(2026, 11, 1), date(2026, 11, 30), date(2026, 11, 15), {}
    )
    # III kwartał (termin 30.09) niewysłany — zaległość niesiona do bieżącego miesiąca.
    assert [(e.period.key, e.carried) for e in month] == [("2026-Q3", True)]
    assert [e.period.key for e in later] == ["2026-Q4", "2027-Q1"]


def test_calendar_undated_rule_gives_one_item():
    definition = _definition(due_rule={"type": "none"})
    month, later = catalog.calendar_entries(
        definition, date(2026, 11, 1), date(2026, 11, 30), date(2026, 11, 15), {}
    )
    assert [(e.period.key, e.state) for e in month] == [("2026-11", "no_date")]
    assert later == []


def test_new_definition_has_no_overdue_from_before_it_existed():
    from datetime import datetime, timezone

    definition = _definition(created_at=datetime(2026, 11, 15, 9, tzinfo=timezone.utc))
    info = catalog.next_due(definition, {}, date(2026, 11, 15))
    assert (info["period_key"], info["state"]) == ("2026-11", "todo")
    month, _ = catalog.calendar_entries(
        definition, date(2026, 11, 1), date(2026, 11, 30), date(2026, 11, 15), {}
    )
    assert month == []


def test_calendar_respects_valid_from():
    definition = _definition(valid_from=date(2026, 11, 1))
    month, _ = catalog.calendar_entries(
        definition, date(2026, 11, 1), date(2026, 11, 30), date(2026, 11, 15), {}
    )
    assert month == []


def test_next_due_prefers_open_overdue():
    definition = _definition(valid_from=date(2026, 10, 1))
    info = catalog.next_due(definition, {}, date(2026, 11, 15))
    assert (info["period_key"], info["state"]) == ("2026-10", "overdue")
    info = catalog.next_due(definition, {"2026-10": object()}, date(2026, 11, 15))
    assert (info["period_key"], info["state"], info["due"]) == (
        "2026-11",
        "todo",
        "2026-12-05",
    )


# --------------------------------------------------------- propozycje z umów


def test_parse_proposals_keeps_valid_and_drops_invented_fragments(monkeypatch):
    monkeypatch.setattr(suggest, "all_generators", lambda: ())
    raw = """Oto lista:
    [
      {"name": "Zestawienie zaangażowania", "family": "management", "rhythm": "monthly",
       "due_rule": {"type": "day_of_month", "day": 5}, "recipient": "przedstawiciel klienta",
       "preparer": "dl", "generator_key": "headcount_month", "chunk_id": 10, "source_ref": "§ 7"},
      {"name": "Zestawienie  zaangażowania!", "family": "management", "rhythm": "monthly", "chunk_id": 10},
      {"name": "Raport z kosmosu", "family": "management", "rhythm": "monthly", "chunk_id": 999},
      {"name": "Zły termin", "family": "compliance", "rhythm": "annual", "due_rule": {"type": "fixed", "month": 13}, "chunk_id": 11},
      {"name": "Zła rodzina", "family": "x", "rhythm": "monthly", "chunk_id": 11}
    ]"""
    out = suggest.parse_proposals(raw, {10, 11})
    assert [item["name"] for item in out] == ["Zestawienie zaangażowania", "Zły termin"]
    assert out[0]["generator_key"] is None  # nieznany generator odpada
    assert out[0]["due_rule"] == {"type": "day_of_month", "day": 5}
    assert out[1]["due_rule"] == {"type": "none"}


def test_parse_proposals_survives_garbage():
    assert suggest.parse_proposals("nie wiem", {1}) == []
    assert suggest.parse_proposals("[{]", {1}) == []


def test_known_name_by_containment():
    known = {suggest.normalize_name("Zestawienie zaangażowania")}
    assert suggest.is_known("Zestawienie zaangażowania (liczba osób w miesiącu)", known)
    assert suggest.is_known("zestawienie  ZAANGAŻOWANIA", known)
    assert not suggest.is_known(
        "Raport", {suggest.normalize_name("Raport miesięczny rekrutacji")}
    )


def _payload_definition(**kwargs):
    from datetime import datetime, timezone

    base = dict(
        id=9,
        client_id=12,
        name="Rabat od obrotu",
        family="management",
        generator_key="annual_spend",
        params={
            "tiers": [{"up_to": 1000.0, "rate": 1.5}],
            "currency": "EUR",
            "marginal": True,
        },
        rhythm="annual",
        due_rule={"type": "fixed", "month": 1, "day": 31},
        recipient=None,
        channel=None,
        file_format=None,
        preparer="finance",
        preparer_user_id=None,
        source_kind="contract",
        source_contract_id=None,
        source_chunk_id=None,
        source_ref=None,
        status="active",
        valid_from=None,
        valid_to=None,
        notes=None,
        confirmed_at=datetime(2026, 11, 15, tzinfo=timezone.utc),
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_amount_params_hidden_without_amounts_view():
    definition = _payload_definition()
    common = dict(preparer="Finanse", next_info={}, last_sent=None, confirmable=False)
    hidden = catalog.definition_payload(definition, can_view_amounts=False, **common)
    assert "tiers" not in hidden["params"]
    assert hidden["params"] == {"currency": "EUR", "marginal": True}
    shown = catalog.definition_payload(definition, can_view_amounts=True, **common)
    assert shown["params"]["tiers"] == [{"up_to": 1000.0, "rate": 1.5}]


def test_next_due_ignores_periods_after_valid_to():
    definition = _definition(valid_from=date(2026, 1, 1), valid_to=date(2026, 8, 31))
    sent = {f"2026-{m:02d}": object() for m in range(1, 9)}
    info = catalog.next_due(definition, sent, date(2026, 11, 15))
    assert info["state"] != "overdue"


def test_tracking_start_uses_company_calendar_not_utc():
    from datetime import datetime, timezone

    # 23:30 UTC 30.11 to już 1.12 w Warszawie — listopad nie jest do pilnowania.
    definition = _definition(
        rhythm="monthly",
        due_rule={"type": "end_of_period"},
        created_at=datetime(2026, 11, 30, 23, 30, tzinfo=timezone.utc),
    )
    assert catalog.tracking_start(definition) == date(2026, 12, 1)
    info = catalog.next_due(definition, {}, date(2026, 12, 1))
    assert info["state"] != "overdue"
