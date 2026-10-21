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
from app.services.care.card import gap_questions
from app.services.care.conversation_save import month_end, parse_gap_key
from app.services.care.demand import Signal, group_signals, jobs_new_url, visible

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
    demand = board_state.parse_key("demand:5:0:44")
    assert demand.kind == "demand" and demand.ids == (5, 0, 44)
    for raw in ("", "demand:5:44", "contact:plan:x", "case:1", "feedback:3:1"):
        assert board_state.parse_key(raw) is None
    assert board_state.demand_key(5, None, 44) == "demand:5:0:44"


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
    assert first.keys == ["demand:1:7:3", "demand:1:7:2"]


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
