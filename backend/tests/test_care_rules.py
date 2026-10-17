"""Opieka nad konsultantami — reguły bez bazy (plan kontaktów, nazwy, notatki).

Plan liczony od startu kontraktu (etap 3, O7, 17.10.2026): kamienie — dzień 7
od startu i 30 dni przed końcem zamówienia/umowy — oraz rozmowy według rytmu:
domyślnie co 2 tygodnie przez pierwsze 90 dni, potem co miesiąc. Daty są
stałe (bez „dziś” przy imporcie).
"""

from __future__ import annotations

from datetime import date, timedelta

from app.models.contract_care import CareConversation, CarePlanItem
from app.services.care.plan import (
    FOLLOW_UP_LABEL,
    LOOKBACK_DAYS,
    PlannedSlot,
    add_months,
    end_of_cooperation,
    next_contact,
    planned_slots,
)
from app.services.care.skills import SkillDictionary, display_name, name_key
from app.services.care.tech_map import note_pattern, skills_in_note
from app.services.contract_care_schema import (
    CARD_STATUSES,
    HIRING_SOURCES,
    REDEPLOY_REASONS,
    REDEPLOY_STATUSES,
)


def _kinds(slots: list[PlannedSlot]) -> list[tuple[str, date]]:
    return [(slot.kind, slot.due_on) for slot in slots]


def test_plan_starts_with_day_7_then_biweekly_for_90_days_then_monthly() -> None:
    start = date(2026, 9, 1)
    slots = planned_slots(start, None, date(2026, 9, 1), lookahead_days=200)
    assert _kinds(slots) == [
        ("day_7", date(2026, 9, 8)),
        ("cadence", date(2026, 9, 15)),
        ("cadence", date(2026, 9, 29)),
        ("cadence", date(2026, 10, 13)),
        ("cadence", date(2026, 10, 27)),
        ("cadence", date(2026, 11, 10)),
        ("cadence", date(2026, 11, 24)),
        # Dzień 90 (30.11) kończy program; co miesiąc liczy się od niego.
        ("cadence", date(2026, 12, 30)),
        ("cadence", date(2027, 1, 30)),
        ("cadence", date(2027, 2, 28)),
    ]
    # ``seq`` rozmowy z rytmu = dzień terminu (jeden punkt na dzień).
    assert [s.seq for s in slots if s.kind == "cadence"][0] == date(
        2026, 9, 15
    ).toordinal()


def test_plan_adds_pre_end_and_stops_after_the_end() -> None:
    start = date(2026, 9, 1)
    end = date(2026, 12, 31)
    slots = planned_slots(start, end, date(2026, 9, 1), lookahead_days=400)
    assert ("pre_end", date(2026, 12, 1)) in _kinds(slots)
    assert all(slot.due_on <= end for slot in slots)
    assert not [slot for slot in slots if slot.kind == "quarterly"]
    pre_end = next(slot for slot in slots if slot.kind == "pre_end")
    # Przedłużenie = nowy punkt (seq to dzień końca), stary znika w ensure_plan.
    assert pre_end.seq == end.toordinal()


def test_plan_does_not_backfill_history_before_the_window() -> None:
    """Stary kontrakt przy włączeniu modułu nie dostaje stosu zaległości."""

    slots = planned_slots(date(2024, 1, 15), None, date(2026, 10, 16))
    assert all(slot.due_on >= date(2026, 9, 16) for slot in slots)
    # Co miesiąc od dnia 90 (14.04.2024).
    assert _kinds(slots) == [
        ("cadence", date(2026, 10, 14)),
        ("cadence", date(2026, 11, 14)),
        ("cadence", date(2026, 12, 14)),
        ("cadence", date(2027, 1, 14)),
    ]


def test_plan_skips_pre_end_shorter_than_cooperation() -> None:
    slots = planned_slots(date(2026, 10, 1), date(2026, 10, 20), date(2026, 10, 1))
    assert _kinds(slots) == [
        ("day_7", date(2026, 10, 8)),
        ("cadence", date(2026, 10, 15)),
    ]


def test_add_months_clamps_to_month_end() -> None:
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)
    assert add_months(date(2027, 12, 15), 2) == date(2028, 2, 15)


def test_end_of_cooperation_takes_the_nearest_known_end() -> None:
    assert end_of_cooperation(None, None) is None
    assert end_of_cooperation(date(2027, 1, 31), None) == date(2027, 1, 31)
    assert end_of_cooperation(date(2027, 6, 30), date(2027, 3, 31)) == date(2027, 3, 31)


def _dictionary() -> SkillDictionary:
    return SkillDictionary(
        by_key={"java": 1, "spring boot": 2, "c#": 3, "go": 4, "golang": 4, "kafka": 5},
        names={1: "java", 2: "spring boot", 3: "c#", 4: "go", 5: "kafka"},
        categories={
            1: "language",
            2: "framework",
            3: "language",
            4: "language",
            5: "messaging",
        },
    )


def _plan_item(item_id: int, kind: str, due_on: date, status: str = "open"):
    return CarePlanItem(
        id=item_id, contract_id=1, kind=kind, seq=0, due_on=due_on, status=status
    )


def _talk(follow_up_on: date | None) -> CareConversation:
    return CareConversation(
        contract_id=1,
        occurred_on=date(2026, 9, 1),
        channel="phone",
        follow_up_on=follow_up_on,
    )


def test_next_contact_is_the_earliest_open_item_or_follow_up() -> None:
    today = date(2026, 10, 15)
    items = [
        _plan_item(3, "day_90", date(2026, 11, 20)),
        _plan_item(2, "day_30", date(2026, 10, 10)),
        _plan_item(1, "day_7", date(2026, 9, 1), status="done"),
    ]
    assert next_contact([], None, today) is None
    first = next_contact(items, None, today)
    assert (first.kind, first.due_on, first.plan_item_id, first.label) == (
        "day_30",
        date(2026, 10, 10),
        2,
        "Dzień 30",
    )
    assert first.payload(today) == {
        "due_on": date(2026, 10, 10),
        "label": "Dzień 30",
        "plan_item_id": 2,
        "overdue": True,
    }
    earlier = next_contact(items, _talk(date(2026, 10, 9)), today)
    assert (earlier.kind, earlier.label, earlier.plan_item_id) == (
        "follow_up",
        FOLLOW_UP_LABEL,
        None,
    )
    # Remis: punkt planu (rozmowa go zamknie).
    tie = next_contact(items, _talk(date(2026, 10, 10)), today)
    assert tie.plan_item_id == 2


def test_next_contact_drops_follow_up_older_than_lookback() -> None:
    today = date(2026, 10, 15)
    edge = today - timedelta(days=LOOKBACK_DAYS)
    assert next_contact([], _talk(edge), today).due_on == edge
    # Rozmowy z importu niosą terminy sprzed lat — taki nie jest „następnym”.
    stale = _talk(edge - timedelta(days=1))
    assert next_contact([], stale, today) is None
    later = _plan_item(5, "quarterly", today + timedelta(days=40))
    assert next_contact([later], stale, today).plan_item_id == 5
    assert next_contact([later], stale, today).payload(today)["overdue"] is False


def test_note_scan_finds_dictionary_names_and_aliases() -> None:
    dictionary = _dictionary()
    pattern = note_pattern(dictionary)
    text = "Zespół płatności: Java 17, Spring Boot, trochę C#. Kolejki na Kafka; nowy moduł w Golang."
    assert skills_in_note(text, dictionary, pattern) == {1, 2, 3, 4, 5}


def test_note_scan_ignores_short_words_inside_polish_text() -> None:
    """„go” w zdaniu („zrobić go”) to zaimek, nie technologia."""

    dictionary = _dictionary()
    pattern = note_pattern(dictionary)
    assert (
        skills_in_note("Trzeba go wdrożyć w JavaScript", dictionary, pattern) == set()
    )


def test_name_key_and_display_name() -> None:
    assert name_key("  Spring   Boot ") == "spring boot"
    assert (
        display_name("spring boot", ["Spring Boot", "spring boot", "Spring Boot"])
        == "Spring Boot"
    )
    assert display_name("java", []) == "Java"
    assert display_name("c#", []) == "C#"


def test_schema_vocabularies_match_the_api_literals() -> None:
    """Literal-e w ``app/api/contract_care.py`` muszą zgadzać się z CHECK-ami."""

    from typing import get_args

    from app.api import contract_care as api

    def strings(annotation) -> set[str]:
        values: set[str] = set()
        for arg in get_args(annotation):
            if isinstance(arg, str):
                values.add(arg)
            else:
                values |= strings(arg)
        return values

    def literal(model, field: str) -> set[str]:
        return strings(model.model_fields[field].annotation)

    assert literal(api.TechCardBody, "status") == set(CARD_STATUSES)
    assert literal(api.TechCardBody, "hiring_source") == set(HIRING_SOURCES)
    assert literal(api.RedeployCreateBody, "reason") == set(REDEPLOY_REASONS)
    assert literal(api.RedeployPatchBody, "status") == set(REDEPLOY_STATUSES)
