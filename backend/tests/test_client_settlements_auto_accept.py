"""Automat „Przyjmuj RCP bez uwag automatycznie” bez bazy: reguła w katalogu
(domyślnie wyłączona), termin z N-tego dnia roboczego, okno porannego biegu."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.services.client_settlements import auto_accept, rules_catalog

WAW = ZoneInfo("Europe/Warsaw")


def test_regula_w_katalogu_domyslnie_wylaczona() -> None:
    rule = rules_catalog.RULES[auto_accept.RULE]
    assert rule.level == "off"
    assert rule.switch is True
    assert rule.params == {"workday": "3"}
    assert rules_catalog.effective(None)[auto_accept.RULE]["level"] == "off"
    # Klient z regułami zapisanymi przed tą zmianą też ma ją wyłączoną.
    stored = {"extra.multiplier": {"level": "warn", "params": {"pct": "120"}}}
    assert rules_catalog.effective(stored)[auto_accept.RULE]["level"] == "off"
    screen = [
        r
        for s in rules_catalog.as_screen(rules_catalog.effective(stored))
        for r in s["rules"]
        if r["key"] == auto_accept.RULE
    ]
    assert screen and screen[0]["switch"] is True


def test_wlaczona_tylko_przy_poziomie_innym_niz_off() -> None:
    rules = rules_catalog.effective({auto_accept.RULE: {"level": "off"}})
    assert auto_accept.enabled(rules) is False
    rules = rules_catalog.effective({auto_accept.RULE: {"level": "block"}})
    assert auto_accept.enabled(rules) is True


def test_dzien_roboczy_z_parametru_z_wartoscia_domyslna_i_przycieciem() -> None:
    def rules(value: str) -> dict:
        return rules_catalog.effective(
            {auto_accept.RULE: {"level": "block", "params": {"workday": value}}}
        )

    assert auto_accept.workday(rules("5")) == 5
    assert auto_accept.workday(rules("")) == auto_accept.DEFAULT_WORKDAY
    assert auto_accept.workday(rules("trzy")) == auto_accept.DEFAULT_WORKDAY
    assert auto_accept.workday(rules("0")) == 1
    assert auto_accept.workday(rules("99")) == auto_accept.MAX_WORKDAY


def test_termin_to_n_ty_dzien_roboczy_nastepnego_miesiaca() -> None:
    # 1.11.2026 to niedziela i święto: trzeci dzień roboczy to środa 4.11.
    assert auto_accept.due_from("2026-10", 3) == date(2026, 11, 4)
    assert auto_accept.due_from("2026-10", 1) == date(2026, 11, 2)
    # Styczeń 2027: 1.01 i 6.01 to święta, trzeci dzień roboczy to 7.01.
    assert auto_accept.due_from("2026-12", 3) == date(2027, 1, 7)


def test_biezacy_miesiac_przed_terminem_nie_zamkniety_tak() -> None:
    # Bieżący miesiąc kalendarzowy się nie skończył: nigdy.
    assert auto_accept.is_due("2026-11", date(2026, 11, 30), 1) is False
    # Rozliczany październik: od trzeciego dnia roboczego listopada.
    assert auto_accept.is_due("2026-10", date(2026, 11, 3), 3) is False
    assert auto_accept.is_due("2026-10", date(2026, 11, 4), 3) is True
    # Starszy, zamknięty miesiąc: od razu.
    assert auto_accept.is_due("2026-09", date(2026, 11, 2), 3) is True


def test_miesiace_do_przejrzenia_bez_biezacego() -> None:
    assert auto_accept.months_to_check(date(2026, 11, 23)) == [
        "2026-10",
        "2026-09",
        "2026-08",
    ]
    assert auto_accept.months_to_check(date(2027, 1, 7)) == [
        "2026-12",
        "2026-11",
        "2026-10",
    ]


def test_bieg_tylko_rano_w_dzien_roboczy() -> None:
    assert auto_accept.morning(datetime(2026, 11, 23, 7, 5, tzinfo=WAW)) is True
    assert auto_accept.morning(datetime(2026, 11, 23, 6, 59, tzinfo=WAW)) is False
    # Restart po wieczornym wdrożeniu nie przyjmuje wieczorem.
    assert auto_accept.morning(datetime(2026, 11, 23, 19, 0, tzinfo=WAW)) is False
    # Sobota i święto: nie.
    assert auto_accept.morning(datetime(2026, 11, 21, 8, 0, tzinfo=WAW)) is False
    assert auto_accept.morning(datetime(2026, 11, 11, 8, 0, tzinfo=WAW)) is False
