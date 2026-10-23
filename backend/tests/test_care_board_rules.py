"""Tablica opieki, popyt, karta konsultanta — czyste reguły (bez bazy).

Klucze kart i kolumna z zapisanego stanu, grupowanie sygnałów popytu (ten
sam klient, dział i role w 30 dniach), widoczność rozstrzygniętego popytu,
adres ``/jobs/new``, pytania z mapy klienta w oknie rozmowy i miesiąc końca
projektu. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import pytest
from fastapi import HTTPException

from app.services.care import board_state
from app.services.care.board import (
    data_card_counts,
    decision_column,
    feedback_due_by_manager,
    order_end_contracts,
    pick_open_job,
    waiting_retry_on,
)
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
    conversation_of_link,
    jobs_new_url,
    notify_link,
    notify_title,
    role_key,
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


def test_jobs_new_url_carries_department_headcount_and_start() -> None:
    """R4: „otworzy /jobs/new z klientem, działem, HM i technologiami”."""

    assert (
        jobs_new_url(
            client_id=12,
            hm_contact_id=345,
            skill_ids=[1],
            title="Java Developer (Kafka)",
            area_name=" Płatności ",
            headcount=2,
            start_month="2027-01",
        )
        == "/jobs/new?client=12&hm=345&skills=1&title=Java%20Developer%20%28Kafka%29"
        "&dept=P%C5%82atno%C5%9Bci&headcount=2&start=2027-01"
    )
    assert (
        jobs_new_url(
            client_id=12,
            hm_contact_id=None,
            skill_ids=[],
            title=None,
            area_name="  ",
            headcount=None,
            start_month=None,
        )
        == "/jobs/new?client=12"
    )


def test_demand_bell_title_and_dedupe_keys() -> None:
    """R4: tytuł dzwonka i klucze, po których dzwonek liczy „tę samą pozycję”."""

    assert (
        notify_title("Bank Przykładowy", ["Java", "QA"])
        == "Popyt u klienta: Bank Przykładowy — Java, QA (z rozmowy z konsultantem)"
    )
    assert notify_title("Bank Przykładowy", []).startswith(
        "Popyt u klienta: Bank Przykładowy — nowe osoby"
    )
    assert len(notify_title("X" * 300, ["Java"])) == 255
    assert conversation_of_link("/care?card=demand:7:42&area=3") == 42
    assert conversation_of_link("/care?card=demand:7:42") == 42
    assert conversation_of_link("/care?card=feedback:5&area=0") is None
    assert conversation_of_link(None) is None
    assert role_key(["QA", " java ", "Java"]) == role_key(["java", "qa"])


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


# ── Domknięcie makiet 22.10.2026 (K3, R4, P1) ───────────────────────────────


def _contract(contract_id: int, end_in: Optional[int]):
    from app.services.care.access import CareContract

    end = TODAY + timedelta(days=end_in) if end_in is not None else None
    return CareContract(
        id=contract_id,
        client_id=1,
        client_name="Firma Przykładowa",
        candidate_id=contract_id,
        candidate_name=f"Osoba {contract_id}",
        job_id=None,
        job_title="QA",
        job_delivery_lead_id=None,
        status="active",
        start_date=TODAY - timedelta(days=200),
        contract_end_date=None,
        order_end_date=end,
        explicit_owner_id=None,
        client_default_owner_id=None,
    )


def test_decision_end_key_parses_as_decision() -> None:
    key = board_state.parse_key("decision:end:42")
    assert key is not None and key.variant == "decision_end"
    assert key.kind == "decision" and key.ids == (42,)
    assert board_state.parse_key("decision:end:x") is None
    # Karta danych nie ma stanu na tablicy.
    assert board_state.parse_key("data:5") is None


def test_order_end_within_60_days_without_entry_is_a_decision_card() -> None:
    contracts = [
        _contract(1, 20),  # pasuje
        _contract(2, 61),  # za daleko
        _contract(3, -1),  # już po końcu
        _contract(4, None),  # bezterminowo
        _contract(5, 60),  # brzeg: dzień 60 wchodzi
        _contract(6, 10),  # ma aktywny wpis
        _contract(7, 30),  # rozstrzygnięty na tę samą datę
        _contract(8, 0),  # brzeg: koniec dziś wchodzi
    ]
    picked = order_end_contracts(
        contracts,
        today=TODAY,
        active_ids={6},
        handled={(7, TODAY + timedelta(days=30)), (1, TODAY + timedelta(days=5))},
    )
    assert [c.id for c in picked] == [8, 1, 5]


def test_recently_resolved_decision_keeps_order_end_card_away() -> None:
    """Zamknięta „Decyzja” z innego powodu albo na inną datę („chce zmiany”,
    koniec projektu z rozmowy) nie wraca jako karta końca zamówienia."""

    contracts = [_contract(1, 20), _contract(2, 40)]
    picked = order_end_contracts(
        contracts,
        today=TODAY,
        active_ids=set(),
        handled=set(),
        resolved_ids=frozenset({2}),
    )
    assert [c.id for c in picked] == [1]


def test_open_job_prefers_role_match_then_newest() -> None:
    jobs = [(30, "Analityk danych"), (20, "Senior Java Developer"), (10, "QA")]
    assert pick_open_job(jobs, ["Java Developer"]) == {
        "id": 20,
        "title": "Senior Java Developer",
    }
    assert pick_open_job(jobs, ["Kierownik"]) == {"id": 30, "title": "Analityk danych"}
    assert pick_open_job(jobs, []) == {"id": 30, "title": "Analityk danych"}
    assert pick_open_job([], ["Java"]) is None


def test_data_card_only_when_something_to_fill() -> None:
    assert data_card_counts(None, None) is None
    assert data_card_counts({"certain": 0, "uncertain": 0}, 0) is None
    assert data_card_counts({"certain": 2, "uncertain": 1}, 3) == {
        "certain": 2,
        "uncertain": 1,
        "gaps": 3,
    }
    # Luki nieznane (mapa nie w cache) — liczą się same propozycje.
    assert data_card_counts({"certain": 0, "uncertain": 1}, None) == {
        "certain": 0,
        "uncertain": 1,
        "gaps": None,
    }


def test_waiting_retry_defaults() -> None:
    later = TODAY + timedelta(days=3)
    # Popyt „Nie teraz” bez daty wraca za 30 dni.
    assert waiting_retry_on("demand", "waiting", None, TODAY) == TODAY + timedelta(
        days=30
    )
    assert waiting_retry_on("demand", "waiting", later, TODAY) == later
    # Decyzja „Czeka na front office” bez daty zostaje bez daty.
    assert waiting_retry_on("decision", "waiting", None, TODAY) is None
    assert waiting_retry_on("contact", "waiting", None, TODAY) is None
    assert waiting_retry_on("demand", "in_progress", None, TODAY) is None


def test_decision_waiting_without_date_stays_waiting() -> None:
    state = _state(key="decision:3", kind="decision", column="waiting")
    assert decision_column("in_progress", state, TODAY) == "waiting"


def test_feedback_due_by_manager() -> None:
    requests = [
        {"contact_id": 5, "due_on": TODAY - timedelta(days=6)},
        {"contact_id": 9, "due_on": TODAY},
    ]
    assert feedback_due_by_manager(requests) == {
        5: TODAY - timedelta(days=6),
        9: TODAY,
    }


async def test_done_counts_resolved_demand_card_once(monkeypatch) -> None:
    """Audyt 22.10, F3: jedno rozstrzygnięcie karty popytu z dwoma źródłami
    zapisuje oba klucze z tym samym czasem — „Zrobione” liczy kartę raz."""

    from datetime import datetime, timezone

    from app.services.care import board as care_board

    now = datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc)

    def state(key: str, outcome: str, at: datetime) -> board_state.BoardState:
        return board_state.BoardState(
            key=key,
            kind="demand",
            column="done",
            scheduled_at=None,
            retry_on=None,
            outcome=outcome,
            job_id=None,
            note=None,
            updated_by=1,
            updated_at=at,
        )

    async def updated_between(_db, _first, _last, *, kind):
        assert kind == "demand"
        return [
            state("demand:7:100", "confirmed", now),
            state("demand:7:101", "confirmed", now),
            # Inna karta tego klienta, rozstrzygnięta osobno — liczy się osobno.
            state("demand:7:205", "stale", now + timedelta(hours=1)),
        ]

    monkeypatch.setattr(board_state, "updated_between", updated_between)
    done = await care_board._done(
        None,
        contract_ids=[],
        client_ids=None,
        include_feedback=False,
        include_demand=True,
        monday=date(2026, 10, 19),
        friday=date(2026, 10, 23),
        names_by_contract={},
    )
    assert done["this_week"] == 2
    assert sorted(row["key"] for row in done["recent"]) == [
        "demand:7:101",
        "demand:7:205",
    ]


async def test_demand_bell_keyed_by_signal_not_client(monkeypatch) -> None:
    """Audyt 22.10, F5 (decyzja Artura): dzwonek popytu ma encję sygnału
    (rozmowy), nie klienta — dobowy dedup ``emit`` (odbiorca + typ + encja)
    nie zjada drugiego, innego popytu u tego samego klienta tego samego dnia."""

    from datetime import datetime, timezone
    from types import SimpleNamespace

    from app.services.care import demand
    from app.services.care import structure_proposals
    from app.services.hr import notify as hr_notify

    sent: list[dict] = []

    async def client_leads(_db, client_ids):
        return {client_ids[0]: [11]}

    async def recent_recipients(_db, **_kwargs):
        return set()

    async def notify_each(_db, user_ids, **kwargs):
        sent.append({"users": list(user_ids), **kwargs})
        return len(user_ids)

    monkeypatch.setattr(structure_proposals, "client_leads", client_leads)
    monkeypatch.setattr(demand, "_recent_recipients", recent_recipients)
    monkeypatch.setattr(hr_notify, "notify_each", notify_each)

    contract = SimpleNamespace(client_id=7, client_name="Klient", candidate_name=None)
    now = datetime(2026, 10, 22, 10, 0, tzinfo=timezone.utc)
    for conversation_id, role in ((100, "Java"), (101, "QA")):
        await demand.notify_leads(
            None,
            conversation=SimpleNamespace(id=conversation_id),
            contract=contract,
            area=None,
            roles=[role],
            actor_id=None,
            now=now,
        )
    assert [(s["related_entity_type"], s["related_entity_id"]) for s in sent] == [
        ("care_demand", 100),
        ("care_demand", 101),
    ]


async def test_demand_recent_bells_read_old_client_and_new_signal_entity() -> None:
    """Audyt 22.10, F5: limit 30 dni czyta dzwonki z encją sygnału i stare
    (sprzed 22.10) z encją klienta — inaczej powtórzyłby dzwonki."""

    from datetime import datetime, timezone

    from sqlalchemy.dialects import postgresql

    from app.services.care import demand

    seen: list[str] = []

    class Result:
        def all(self):
            return []

    class Db:
        async def execute(self, statement):
            seen.append(
                str(
                    statement.compile(
                        dialect=postgresql.dialect(),
                        compile_kwargs={"literal_binds": True},
                    )
                )
            )
            return Result()

    found = await demand._recent_recipients(
        Db(),
        client_id=7,
        area_id=None,
        conversation_id=100,
        roles=frozenset({"java"}),
        now=datetime(2026, 10, 22, 10, 0, tzinfo=timezone.utc),
    )
    assert found == set()
    sql = seen[0]
    assert "'care_demand'" in sql
    assert "'client'" in sql
