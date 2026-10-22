"""Karta konsultanta i okno rozmowy według makiet P2/P3/S3/S5 — czyste reguły.

Pytanie o grupę kategorii bez świeżego źródła („CI/CD i chmura — brak źródła
od 18 miesięcy”), postęp checklisty sprawy, tytuły osi (plan, rozmowa,
sprawy), opis sprawy z notatką z rozmowy, ślad potwierdzonych wierszy „Co
u klienta” i podtytuły checklisty końca współpracy. Bez bazy, dane fikcyjne.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException

from app.services.admin_cases import rules
from app.services.care.card import (
    CATEGORY_GROUPS,
    category_gaps,
    checklist_progress,
    gap_questions,
)
from app.services.care.conversation_save import (
    CASE_DESCRIPTION_PREFIX,
    CASE_NOTE_MAX,
    case_description,
    confirmed_rows,
    parse_gap_key,
)
from app.services.care.timeline import (
    MAIL_LINKED_DETAIL,
    case_event_text,
    conversation_title,
    plan_event_text,
)

TODAY = date(2026, 10, 22)


def _tech(name: str, category: str | None, last_seen: object) -> dict:
    return {
        "skill_id": hash(name) % 1000,
        "name": name,
        "category": category,
        "last_seen": last_seen,
    }


def test_category_gap_when_group_has_only_old_sources() -> None:
    techs = [
        _tech("Jenkins", "devops", date(2025, 4, 1)),
        _tech("Azure", "cloud", None),
        _tech("Java", "language", TODAY),
    ]
    [question] = category_gaps(techs, today=TODAY)
    assert question["key"] == "category:0"
    assert question["kind"] == "category_stale"
    assert question["subject"] == "CI/CD i chmura"
    assert question["detail"] == "brak źródła od 18 miesięcy. Czego używają?"


def test_category_gap_skips_fresh_and_unknown_groups() -> None:
    fresh = [
        _tech("Jenkins", "devops", date(2026, 9, 1)),
        _tech("Azure", "cloud", None),
    ]
    assert category_gaps(fresh, today=TODAY) == []
    # Grupy, z której mapa nie zna żadnej technologii, nie pytamy.
    assert category_gaps([_tech("Java", "language", None)], today=TODAY) == []
    # Cache mapy trzyma daty jako tekst ISO; bez daty = „brak źródła”.
    [cached] = category_gaps([_tech("Oracle", "database", "2024-01-15")], today=TODAY)
    assert cached["key"] == "category:1"
    assert cached["detail"].startswith("brak źródła od 33 miesięcy")
    [none] = category_gaps([_tech("Selenium", "qa", None)], today=TODAY)
    assert none["detail"] == "brak źródła. Czego używają?"


def test_category_gap_only_one_and_oldest_first() -> None:
    techs = [
        _tech("Oracle", "database", date(2024, 1, 1)),
        _tech("Jenkins", "devops", date(2025, 1, 1)),
    ]
    assert [q["key"] for q in category_gaps(techs, today=TODAY)] == ["category:1"]


def test_gap_questions_put_category_after_area_and_before_single() -> None:
    gaps = [
        {
            "kind": "area_no_source",
            "area": {"id": 7, "name": "Płatności"},
            "last_seen": None,
        },
        {
            "kind": "single_source",
            "skill_id": 501,
            "name": "Kafka",
            "areas": ["Płatności"],
        },
    ]
    questions = gap_questions(
        gaps,
        area={"id": 7, "name": "Płatności"},
        manager_contact_id=None,
        technologies=[_tech("Jenkins", "devops", None)],
        today=TODAY,
    )
    assert [q["key"] for q in questions] == ["area:7", "category:0", "single:501"]
    # Bez listy technologii — jak dotąd (stare wywołania).
    assert [
        q["key"]
        for q in gap_questions(
            gaps, area={"id": 7, "name": "Płatności"}, manager_contact_id=None
        )
    ] == ["area:7", "single:501"]


def test_category_gap_key_parses_only_known_groups() -> None:
    assert parse_gap_key("category:0") == ("category", 0)
    with pytest.raises(HTTPException):
        parse_gap_key(f"category:{len(CATEGORY_GROUPS)}")


def test_checklist_progress_ignores_broken_items() -> None:
    assert checklist_progress(None) == (0, 0)
    assert checklist_progress(
        [{"text": "a", "done": True}, {"text": "b", "done": False}, "x"]
    ) == (1, 2)


def test_conversation_title_follows_mockup() -> None:
    assert (
        conversation_title(
            plan_kind=None,
            channel="phone",
            satisfaction=4,
            signals=["wants_change"],
        )
        == "Rozmowa · telefon · 4/5 · chce zmiany projektu"
    )
    # Rozmowa, która zamknęła punkt planu, mówi który — bez formy.
    assert (
        conversation_title(
            plan_kind="day_7", channel="phone", satisfaction=5, signals=[]
        )
        == "Rozmowa · dzień 7 · 5/5"
    )
    assert (
        conversation_title(plan_kind=None, channel=None, satisfaction=None, signals=[])
        == "Rozmowa"
    )


def test_plan_event_text_counts_days() -> None:
    assert plan_event_text("pre_end", date(2026, 10, 24), TODAY) == (
        "Plan: kontakt przed końcem zamówienia",
        "za 2 dni",
    )
    assert plan_event_text("cadence", TODAY, TODAY)[1] == "dziś"
    assert plan_event_text("day_7", date(2026, 10, 23), TODAY) == (
        "Plan: rozmowa „dzień 7”",
        "jutro",
    )
    assert plan_event_text("cadence", date(2026, 10, 21), TODAY)[1] == "zaległy 1 dzień"
    assert plan_event_text("quarterly", date(2026, 10, 19), TODAY) == (
        "Plan: kontakt kwartalny",
        "zaległy 3 dni",
    )


def test_case_event_texts() -> None:
    common = {"from_mail": False, "mail_linked": False, "checklist": (0, 0)}
    assert case_event_text(
        "case_opened", "Negocjacje warunków", person="Natalia O.", **common
    ) == ("Sprawa otwarta: Negocjacje warunków", "Natalia O.")
    assert case_event_text(
        "case_opened",
        "Ubezpieczenie OC konsultanta",
        from_mail=True,
        mail_linked=True,
        person="Zofia R.",
        checklist=(0, 0),
    ) == ("Sprawa z maila: Ubezpieczenie OC konsultanta", MAIL_LINKED_DETAIL)
    assert case_event_text(
        "case_closed",
        "Wejście konsultanta",
        from_mail=False,
        mail_linked=False,
        person=None,
        checklist=(4, 4),
    ) == ("Sprawa zamknięta: Wejście konsultanta 4/4", None)
    # Tytuł zastępczy bez osoby — dopisku nie ma.
    assert case_event_text(
        "case_opened", "Sprawa: Negocjacje", person=None, **common
    ) == (
        "Sprawa otwarta: Sprawa: Negocjacje",
        None,
    )


def test_case_description_carries_note_and_link() -> None:
    text = case_description(date(2026, 10, 21), 42, "  Pyta o certyfikat Azure.\x00 ")
    assert text.startswith(CASE_DESCRIPTION_PREFIX)
    assert "21.10.2026: /care?contract=42" in text
    assert text.endswith("Notatka z rozmowy:\nPyta o certyfikat Azure.")
    assert case_description(date(2026, 10, 21), 42, None).endswith("/care?contract=42")
    long = case_description(date(2026, 10, 21), 42, "x" * (CASE_NOTE_MAX + 50))
    assert long.endswith("…")
    assert len(long.split("Notatka z rozmowy:\n", 1)[1]) == CASE_NOTE_MAX


def test_confirmed_rows_keep_window_order() -> None:
    assert confirmed_rows(
        {"technologies": "change", "area": "same", "manager": "same", "x": "same"}
    ) == (["area", "manager"], ["technologies"])
    assert confirmed_rows(None) == ([], [])


def test_end_of_cooperation_checklist_has_mockup_subtitles() -> None:
    texts = [
        item["text"]
        for item in rules.end_of_cooperation_checklist(equipment_ours=True, accesses=[])
    ]
    assert texts == [
        "Zwrot sprzętu i protokół — pozycja z ewidencji sprzętu",
        "Odebranie dostępów u klienta — lista z pakietu „Wejście u klienta”",
        "Ostatnia opinia menedżera — prośba o opinię przed końcem",
        "Decyzja: przekaż do front office albo „nie przepinamy”",
        "Rozliczenie ostatniego miesiąca — Finanse, bez kwot",
    ]
    assert all(len(text) <= rules.CHECKLIST_TEXT_MAX for text in texts)
