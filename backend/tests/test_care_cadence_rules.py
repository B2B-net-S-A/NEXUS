"""Rytm kontaktu z konsultantem (etap 3, O7–O9, 17.10.2026) — reguły bez bazy.

Poziomy: co 2 tygodnie, co miesiąc, co kwartał, tylko kamienie, wstrzymany.
Bez zmian: pierwsze 90 dni co 2 tygodnie, potem co miesiąc. Zmiana z datą
„do kiedy” po tej dacie oddaje poprzedni rytm. Kamienie (dzień 7 po starcie
i 30 dni przed końcem) zostają przy każdym rytmie. Daty stałe, zmyślone.
"""

from __future__ import annotations

from datetime import date

from app.services.care.cadence_rules import (
    CadencePeriod,
    level_on,
    suggested_level,
    transitions,
)
from app.services.care.plan import conversations_between, planned_slots

START = date(2023, 3, 1)


def _due(slots, *, since: date | None = None) -> list[tuple[str, date]]:
    return [
        (slot.kind, slot.due_on)
        for slot in slots
        if since is None or slot.due_on >= since
    ]


def test_level_follows_program_default_and_the_latest_period() -> None:
    program = level_on(START, [], date(2023, 3, 20))
    assert (program.level, program.source) == ("biweekly", "program")
    # Program trwa 90 dni: ostatni dzień to dzień 89 od startu.
    assert program.until_on == date(2023, 5, 29)
    later = level_on(START, [], date(2023, 5, 30))
    assert (later.level, later.source, later.until_on) == ("monthly", "default", None)

    quarter = CadencePeriod(id=1, level="quarterly", starts_on=date(2025, 2, 12))
    burst = CadencePeriod(
        id=2,
        level="biweekly",
        starts_on=date(2026, 10, 15),
        until_on=date(2026, 12, 31),
    )
    assert level_on(START, [quarter, burst], date(2026, 11, 1)).level == "biweekly"
    assert level_on(START, [quarter, burst], date(2026, 11, 1)).period is burst
    # Po dacie „do kiedy” wraca poprzedni rytm, a nie domyślny.
    back = level_on(START, [quarter, burst], date(2027, 1, 1))
    assert (back.level, back.source, back.period) == ("quarterly", "period", quarter)


def test_later_change_on_the_same_day_wins() -> None:
    first = CadencePeriod(id=5, level="paused", starts_on=date(2026, 10, 1))
    second = CadencePeriod(id=6, level="monthly", starts_on=date(2026, 10, 1))
    assert level_on(START, [second, first], date(2026, 10, 2)).level == "monthly"


def test_temporary_biweekly_returns_to_monthly_after_the_date() -> None:
    """Makieta M2: słaba opinia 15.10 → co 2 tygodnie do 31.12, potem co miesiąc."""

    periods = [
        CadencePeriod(id=1, level="quarterly", starts_on=date(2025, 2, 12)),
        CadencePeriod(id=2, level="monthly", starts_on=date(2026, 7, 3)),
        CadencePeriod(
            id=3,
            level="biweekly",
            starts_on=date(2026, 10, 15),
            until_on=date(2026, 12, 31),
        ),
    ]
    today = date(2026, 10, 15)
    slots = planned_slots(START, date(2027, 1, 31), today, periods=periods)
    assert _due(slots, since=today) == [
        ("cadence", date(2026, 10, 29)),
        ("cadence", date(2026, 11, 12)),
        ("cadence", date(2026, 11, 26)),
        ("cadence", date(2026, 12, 10)),
        ("cadence", date(2026, 12, 24)),
        # Kamień zostaje zawsze; co miesiąc od 01.01 wypada dopiero po końcu.
        ("pre_end", date(2027, 1, 1)),
    ]


def test_paused_keeps_only_milestones() -> None:
    start = date(2026, 1, 1)
    pause = CadencePeriod(id=1, level="paused", starts_on=date(2026, 10, 1))
    slots = planned_slots(start, date(2027, 1, 31), date(2026, 10, 1), periods=[pause])
    # 01.09 to jeszcze miesięczny rytm sprzed wstrzymania (okno wstecz 30 dni).
    assert _due(slots) == [
        ("cadence", date(2026, 9, 1)),
        ("pre_end", date(2027, 1, 1)),
    ]
    milestones = planned_slots(
        start,
        date(2027, 1, 31),
        date(2026, 10, 1),
        periods=[CadencePeriod(id=2, level="milestones", starts_on=date(2026, 10, 1))],
    )
    assert _due(milestones, since=date(2026, 10, 1)) == [("pre_end", date(2027, 1, 1))]


def test_same_level_change_does_not_shift_the_dates() -> None:
    """„Co miesiąc” ustawione przy domyślnym „co miesiąc” zostawia terminy."""

    start = date(2024, 1, 15)
    today = date(2026, 10, 16)
    plain = planned_slots(start, None, today)
    pinned = planned_slots(
        start,
        None,
        today,
        periods=[CadencePeriod(id=1, level="monthly", starts_on=date(2026, 10, 1))],
    )
    assert _due(pinned) == _due(plain)


def test_regular_talk_next_to_a_milestone_is_dropped() -> None:
    """Rozmowa z rytmu na 6 dni przed kamieniem albo po nim to ta sama rozmowa."""

    start = date(2026, 1, 1)
    # Co miesiąc od dnia 90 (01.04): …, 01.09, 01.10, 01.11; koniec 05.12 → kamień 05.11.
    slots = planned_slots(start, date(2026, 12, 5), date(2026, 10, 1))
    due = _due(slots, since=date(2026, 10, 1))
    assert ("pre_end", date(2026, 11, 5)) in due
    assert ("cadence", date(2026, 11, 1)) not in due
    assert ("cadence", date(2026, 10, 1)) in due
    assert ("cadence", date(2026, 12, 1)) in due


def test_conversations_in_a_month_come_from_the_rhythm() -> None:
    start = date(2026, 9, 1)
    first, last = date(2026, 10, 1), date(2026, 10, 31)
    # Program co 2 tygodnie: 13.10 i 27.10.
    assert conversations_between(start, None, [], first, last) == 2
    quarterly = [CadencePeriod(id=1, level="quarterly", starts_on=date(2026, 9, 20))]
    assert conversations_between(start, None, quarterly, first, last) == 0
    # Kamień też jest rozmową (koniec 15.11 → 16.10).
    assert conversations_between(start, date(2026, 11, 15), quarterly, first, last) == 1


def test_history_lists_start_program_end_changes_and_return() -> None:
    periods = [
        CadencePeriod(id=1, level="quarterly", starts_on=date(2025, 2, 12)),
        CadencePeriod(id=2, level="monthly", starts_on=date(2026, 7, 3)),
        CadencePeriod(
            id=3,
            level="biweekly",
            starts_on=date(2026, 10, 15),
            until_on=date(2026, 12, 31),
        ),
    ]
    steps = transitions(START, periods)
    assert [(s.on, s.kind, s.level) for s in steps] == [
        (date(2023, 3, 1), "start", "biweekly"),
        (date(2023, 5, 30), "program_end", "monthly"),
        (date(2025, 2, 12), "change", "quarterly"),
        (date(2026, 7, 3), "change", "monthly"),
        (date(2026, 10, 15), "change", "biweekly"),
        (date(2027, 1, 1), "return", "monthly"),
    ]
    assert steps[4].period is periods[2]


def test_return_is_not_listed_when_a_later_change_covers_it() -> None:
    periods = [
        CadencePeriod(
            id=1,
            level="paused",
            starts_on=date(2026, 9, 1),
            until_on=date(2026, 11, 15),
        ),
        CadencePeriod(id=2, level="quarterly", starts_on=date(2026, 10, 1)),
    ]
    kinds = [(s.kind, s.level) for s in transitions(START, periods)]
    assert ("return", "quarterly") not in kinds
    assert kinds[-1] == ("change", "quarterly")


def test_signals_only_suggest_a_more_frequent_rhythm() -> None:
    assert suggested_level("monthly", {"weak_feedback"}) == "biweekly"
    assert suggested_level("quarterly", {"order_end"}) == "biweekly"
    assert suggested_level("biweekly", {"wants_change"}) is None
    # Zaległa rozmowa to telefon, nie zmiana rytmu.
    assert suggested_level("monthly", {"overdue"}) is None
    # Wstrzymany zostaje wstrzymany — decyduje opiekun, podpowiedź tylko przy rozmowach.
    assert suggested_level("paused", {"weak_feedback"}) is None
