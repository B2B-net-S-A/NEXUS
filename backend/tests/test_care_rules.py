"""Opieka nad konsultantami — reguły bez bazy (plan kontaktów, nazwy, notatki).

Plan liczony od startu kontraktu: dzień 7, 30, 90, potem co kwartał oraz
30 dni przed końcem zamówienia/umowy. Daty są stałe (bez „dziś” przy imporcie).
"""

from __future__ import annotations

from datetime import date

from app.services.care.plan import (
    PlannedSlot,
    add_months,
    end_of_cooperation,
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


def test_plan_starts_with_days_7_30_90_then_quarters() -> None:
    start = date(2026, 9, 1)
    slots = planned_slots(start, None, date(2026, 9, 1), lookahead_days=400)
    assert _kinds(slots)[:6] == [
        ("day_7", date(2026, 9, 8)),
        ("day_30", date(2026, 10, 1)),
        ("day_90", date(2026, 11, 30)),
        ("quarterly", date(2027, 3, 1)),
        ("quarterly", date(2027, 6, 1)),
        ("quarterly", date(2027, 9, 1)),
    ]
    assert [slot.seq for slot in slots if slot.kind == "quarterly"] == [1, 2, 3]


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
    assert [(slot.kind, slot.due_on) for slot in slots] == [
        ("quarterly", date(2026, 10, 15)),
        ("quarterly", date(2027, 1, 15)),
    ]


def test_plan_skips_pre_end_shorter_than_cooperation() -> None:
    slots = planned_slots(date(2026, 10, 1), date(2026, 10, 20), date(2026, 10, 1))
    assert _kinds(slots) == [("day_7", date(2026, 10, 8))]


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
