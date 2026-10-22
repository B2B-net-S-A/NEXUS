"""Tablica opieki, popyt, karta konsultanta — czyste reguły (bez bazy).

Klucze kart i kolumna z zapisanego stanu, grupowanie sygnałów popytu (ten
sam klient, dział i role w 30 dniach), widoczność rozstrzygniętego popytu,
adres ``/jobs/new``, pytania z mapy klienta w oknie rozmowy i miesiąc końca
projektu. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from app.services.care import board_state
from app.services.care.board import decision_column
from app.services.care.card import gap_questions
from app.services.care.conversation_save import (
    CASE_AREA_DENIED,
    CASE_ASSIGNEE_DENIED,
    MAX_CASES_PER_DAY,
    CaseRequest,
    case_request_problem,
    month_end,
    over_daily_limit,
    parse_gap_key,
    reports_to_note,
)
from app.services.care.portfolio import hiring_signal
from app.services.care.demand import (
    Signal,
    clean_roles,
    group_signals,
    jobs_new_url,
    notify_link,
    signal_hiring,
    visible,
)

TODAY = date(2026, 10, 22)


def _state(**overrides) -> board_state.BoardState:
    base = {
        "key": "contact:plan:1",
        "kind": "contact",
        "column": "in_progress",
        "scheduled_at": None,
        "retry_on": None,
        "outcome": None,
        "job_id": None,
        "note": None,
        "updated_by": None,
        "updated_at": None,
    }
    base.update(overrides)
    return board_state.BoardState(**base)


def test_card_keys_parse_and_reject_garbage() -> None:
    assert board_state.parse_key("contact:plan:12").ids == (12,)
    assert board_state.parse_key("contact:plan:12").kind == "contact"
    assert board_state.parse_key("contact:followup:7").variant == "contact_followup"
    assert board_state.parse_key("feedback:3").kind == "feedback"
    assert board_state.parse_key("decision:9").kind == "decision"
    demand = board_state.parse_key("demand:5:44")
    assert demand.kind == "demand" and demand.ids == (5, 44)
    # Stary kształt z działem (sprzed 22.10.2026) już nie jest kluczem.
    for raw in ("", "demand:5:0:44", "contact:plan:x", "case:1", "feedback:3:1"):
        assert board_state.parse_key(raw) is None
    assert board_state.demand_key(5, 44) == "demand:5:44"


def test_demand_key_does_not_depend_on_area() -> None:
    """Zmiana działu menedżera nie gubi stanu karty popytu (klucz bez działu)."""

    before = _signal(3, 2, area_id=7)
    after = _signal(3, 2, area_id=8)
    assert before.key == after.key == "demand:1:3"
    assert notify_link(before.key, 7) == "/care?card=demand:1:3&area=7"
    assert notify_link(before.key, None) == "/care?card=demand:1:3&area=0"


def test_column_without_row_is_new_and_waiting_returns_on_retry_day() -> None:
    assert board_state.column_for(None, TODAY) == "new"
    assert board_state.column_for(_state(), TODAY) == "in_progress"
    waiting = _state(column="waiting", retry_on=TODAY + timedelta(days=1))
    assert board_state.column_for(waiting, TODAY) == "waiting"
    due = _state(column="waiting", retry_on=TODAY)
    assert board_state.column_for(due, TODAY) == "new"


def test_board_note_is_trimmed_to_one_line() -> None:
    assert board_state.clean_note("  oddzwoni\n jutro  ") == "oddzwoni jutro"
    assert board_state.clean_note("   ") is None
    assert len(board_state.clean_note("x" * 900)) == 500


def _signal(conv_id: int, days_ago: int, **overrides) -> Signal:
    base = {
        "conversation_id": conv_id,
        "contract_id": 100 + conv_id,
        "client_id": 1,
        "client_name": "Firma Przykładowa",
        "candidate_name": "Anna Przykładowa",
        "on": TODAY - timedelta(days=days_ago),
        "area_id": 7,
        "area_name": "Płatności",
        "roles": ("Java Developer",),
        "source": "widzial",
        "note": None,
    }
    base.update(overrides)
    return Signal(**base)


def test_same_client_area_and_roles_within_30_days_is_one_card() -> None:
    groups = group_signals(
        [
            _signal(1, 40),
            _signal(2, 10),
            _signal(3, 2, roles=("java developer",)),
            _signal(4, 5, area_id=8),
            _signal(5, 1, roles=("Tester",)),
        ]
    )
    heads = [group.head.conversation_id for group in groups]
    # Najnowszy otwiera grupę; 40 dni od najnowszego (2 dni temu) to już osobna karta.
    assert heads == [5, 3, 4, 1]
    first = next(g for g in groups if g.head.conversation_id == 3)
    assert [s.conversation_id for s in first.signals] == [3, 2]
    assert first.keys == ["demand:1:3", "demand:1:2"]


def test_resolved_demand_hides_and_not_now_comes_back_on_retry_day() -> None:
    assert visible(None, TODAY)
    assert visible(_state(kind="demand", column="waiting", retry_on=TODAY), TODAY)
    assert not visible(_state(kind="demand", outcome="confirmed"), TODAY)
    assert not visible(_state(kind="demand", outcome="stale"), TODAY)
    later = _state(
        kind="demand",
        column="waiting",
        outcome="not_now",
        retry_on=TODAY + timedelta(days=30),
    )
    assert not visible(later, TODAY)
    assert visible(later, TODAY + timedelta(days=30))


def test_jobs_new_url_reads_only_given_fields() -> None:
    assert (
        jobs_new_url(
            client_id=12,
            hm_contact_id=345,
            skill_ids=[1, 2, 2],
            title="Java  Developer",
        )
        == "/jobs/new?client=12&hm=345&skills=1,2&title=Java%20Developer"
    )
    assert (
        jobs_new_url(client_id=12, hm_contact_id=None, skill_ids=[], title=None)
        == "/jobs/new?client=12"
    )


_GAPS = [
    {
        "kind": "area_no_source",
        "area": {"id": 7, "name": "Płatności"},
        "last_seen": date(2025, 1, 10),
    },
    {"kind": "area_no_source", "area": {"id": 8, "name": "Karty"}, "last_seen": None},
    {
        "kind": "manager_unplaced",
        "contact": {"id": 33, "name": "Ewa Przykładowa"},
        "position": "Kierownik zespołu",
        "area": {"id": 7, "name": "Płatności"},
        "consultants": 2,
    },
    {
        "kind": "single_source",
        "skill_id": 501,
        "name": "Kafka",
        "source": "jobs",
        "refs": 1,
        "last_seen": TODAY,
        "areas": ["Płatności"],
    },
    {
        "kind": "single_source",
        "skill_id": 502,
        "name": "Go",
        "source": "notes",
        "refs": 1,
        "last_seen": TODAY,
        "areas": ["Karty"],
    },
]


def test_gap_questions_only_for_consultant_area_and_manager() -> None:
    questions = gap_questions(
        _GAPS, area={"id": 7, "name": "Płatności"}, manager_contact_id=33
    )
    assert [q["key"] for q in questions] == [
        "reports_to:33",
        "area:7",
        "single:501",
    ]
    assert questions[0]["kind"] == "reports_to"
    assert questions[0]["contact_id"] == 33
    assert questions[1]["detail"].endswith("10.01.2025")
    assert questions[2]["area_id"] == 7
    # Bez działu i menedżera — nic do dopytania.
    assert gap_questions(_GAPS, area=None, manager_contact_id=None) == []
    # Cache mapy trzyma daty jako tekst ISO.
    cached = [{**_GAPS[0], "last_seen": "2025-01-10"}]
    assert gap_questions(
        cached, area={"id": 7, "name": "Płatności"}, manager_contact_id=None
    )[0]["detail"].endswith("10.01.2025")
    assert (
        len(
            gap_questions(
                _GAPS,
                area={"id": 7, "name": "Płatności"},
                manager_contact_id=33,
                limit=2,
            )
        )
        == 2
    )


def test_month_end_and_gap_keys() -> None:
    assert month_end("2027-02") == date(2027, 2, 28)
    assert month_end("2028-02") == date(2028, 2, 29)
    with pytest.raises(HTTPException):
        month_end("2027")
    assert parse_gap_key("reports_to:33") == ("reports_to", 33)
    assert parse_gap_key("single:501") == ("single", 501)
    for raw in ("area:", "who:1", "area:x"):
        with pytest.raises(HTTPException):
            parse_gap_key(raw)


# ── Sprawy z okna rozmowy (audyt bezpieczeństwa 22.10.2026) ──────────────────


def test_case_from_conversation_without_handler_only_unassigned_or_self() -> None:
    plain = CaseRequest(title="Nowy laptop", area="administration")
    mine = CaseRequest(title="Nowy laptop", area="administration", assignee_user_id=7)
    other = CaseRequest(title="Nowy laptop", area="administration", assignee_user_id=8)
    assert case_request_problem(plain, actor_id=7, handler=False) is None
    assert case_request_problem(mine, actor_id=7, handler=False) is None
    assert (
        case_request_problem(other, actor_id=7, handler=False) == CASE_ASSIGNEE_DENIED
    )
    assert case_request_problem(other, actor_id=7, handler=True) is None


def test_negotiation_case_from_conversation_only_for_handler() -> None:
    talk = CaseRequest(title="Nowa stawka", area="negotiation")
    assert case_request_problem(talk, actor_id=7, handler=False) == CASE_AREA_DENIED
    assert case_request_problem(talk, actor_id=7, handler=True) is None


def test_daily_case_limit() -> None:
    assert not over_daily_limit(0, 5)
    assert not over_daily_limit(MAX_CASES_PER_DAY - 5, 5)
    assert over_daily_limit(MAX_CASES_PER_DAY - 4, 5)
    assert over_daily_limit(MAX_CASES_PER_DAY, 1)


def test_hiring_signal_only_in_demand_scope() -> None:
    """Sygnał popytu w „Klientach” widzi DL klienta i admin, nie każdy czytelnik."""

    hiring = {1, 2}
    assert hiring_signal(1, hiring, None)  # admin
    assert hiring_signal(1, hiring, frozenset({1}))  # DL klienta
    assert not hiring_signal(2, hiring, frozenset({1}))  # DL innego klienta
    assert not hiring_signal(1, hiring, frozenset())  # TCM, HoR, Finanse
    assert not hiring_signal(3, hiring, None)


def test_decision_waiting_returns_to_new_after_retry_day_also_in_progress() -> None:
    waiting = _state(
        key="decision:3", kind="decision", column="waiting", retry_on=TODAY
    )
    later = _state(
        key="decision:3",
        kind="decision",
        column="waiting",
        retry_on=TODAY + timedelta(days=2),
    )
    assert decision_column("in_progress", waiting, TODAY) == "new"
    assert decision_column("open", waiting, TODAY) == "new"
    assert decision_column("in_progress", later, TODAY) == "waiting"
    assert decision_column("in_progress", None, TODAY) == "in_progress"
    assert decision_column("open", None, TODAY) == "new"


def test_reports_to_note_is_kept_as_client_note() -> None:
    """Notatka przy „Komu podlega …?” nie ginie — także bez wybranej osoby."""

    text = reports_to_note(TODAY, "Ewa Przykładowa", "  podlega pod  dyrektora IT ")
    assert text == (
        "Z rozmowy z konsultantem 22.10.2026 (komu podlega Ewa Przykładowa): "
        "podlega pod dyrektora IT"
    )
    assert reports_to_note(TODAY, "Ewa Przykładowa", "   ") is None
    assert reports_to_note(TODAY, "Ewa Przykładowa", None) is None


def test_demand_roles_and_source_fall_back_to_the_conversation() -> None:
    """„Klient zatrudnia” bez karty: role i źródło z rozmowy (nie giną)."""

    assert signal_hiring(None, None, ["Java Developer", " QA "], "slyszal") == (
        ("Java Developer", "QA"),
        "slyszal",
    )
    # Karta z rozmowy wygrywa, gdy ma role i źródło.
    assert signal_hiring(["Tester"], "widzial", ["Java"], "plotka") == (
        ("Tester",),
        "widzial",
    )
    # Karta bez ról — role z rozmowy.
    assert signal_hiring([], None, ["Java"], "plotka") == (("Java",), "plotka")
    assert signal_hiring(None, None, None, None) == ((), None)
    assert clean_roles(["java", "Java", "", "  "]) == ["java"]
