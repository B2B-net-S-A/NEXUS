"""Kolejka back office'u: reguły bez bazy (eskalacja, kroki, karty, tytuły)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.core.scheduling import DEFAULT_TZ
from app.models.back_office import BoCard
from app.services.admin_cases import rules as case_rules
from app.services.back_office import board, escalation, steps, sync
from app.services.back_office.access import Viewer
from app.services.back_office.sources import AREA_LANE, CardSpec
from app.services.back_office_schema import TEAM_LANES
from app.services.hr.calendar import WorkCalendar

ZONE = ZoneInfo(DEFAULT_TZ)


def _card(**fields) -> BoCard:
    values = {
        "team": "care",
        "lane": "help",
        "source_kind": "case",
        "source_key": "case:1",
        "title": "Tytuł",
        "state": "new",
        "lane_locked": False,
        "meta": {},
        "created_at": datetime(2026, 11, 2, 10, 0, tzinfo=ZONE),
        "updated_at": datetime(2026, 11, 2, 10, 0, tzinfo=ZONE),
        "assignee_user_id": None,
        "escalated_at": None,
        "closed_at": None,
        "substituting": False,
    }
    return BoCard(**{**values, **fields})


def test_every_case_area_lands_in_a_lane_of_its_team() -> None:
    assert set(AREA_LANE) == set(case_rules.AREA_LABELS)
    for team, lane in AREA_LANE.values():
        assert lane in TEAM_LANES[team]


@pytest.mark.parametrize(
    ("created", "expected"),
    [
        # Poniedziałek → wtorek, ta sama godzina.
        (datetime(2026, 11, 2, 10, 0, tzinfo=ZONE), date(2026, 11, 3)),
        # Piątek → poniedziałek: weekend się nie liczy.
        (datetime(2026, 11, 6, 15, 0, tzinfo=ZONE), date(2026, 11, 9)),
        # Wtorek 10.11 → czwartek 12.11: 11 listopada to święto.
        (datetime(2026, 11, 10, 9, 0, tzinfo=ZONE), date(2026, 11, 12)),
    ],
)
def test_escalation_counts_one_working_day(created: datetime, expected: date) -> None:
    moment = escalation.escalation_moment(created, WorkCalendar())
    assert moment.date() == expected
    assert moment.hour == created.hour


def test_company_day_off_also_delays_escalation() -> None:
    calendar = WorkCalendar(company_days_off={date(2026, 11, 3): "Dzień firmy"})
    moment = escalation.escalation_moment(
        datetime(2026, 11, 2, 10, 0, tzinfo=ZONE), calendar
    )
    assert moment.date() == date(2026, 11, 4)


def test_only_unassigned_new_cards_without_acceptance_escalate() -> None:
    now = datetime(2026, 11, 3, 10, 0, tzinfo=ZONE)
    calendar = WorkCalendar()
    assert escalation.should_escalate(_card(), now=now, calendar=calendar)
    assert not escalation.should_escalate(
        _card(), now=now - timedelta(minutes=1), calendar=calendar
    )
    assert not escalation.should_escalate(
        _card(assignee_user_id=5), now=now, calendar=calendar
    )
    assert not escalation.should_escalate(
        _card(state="in_progress"), now=now, calendar=calendar
    )
    assert not escalation.should_escalate(
        _card(escalated_at=now), now=now, calendar=calendar
    )
    for kind in ("timesheet", "bonus", "changes"):
        assert not escalation.should_escalate(
            _card(source_kind=kind), now=now, calendar=calendar
        )
    assert not escalation.should_escalate(
        _card(lane="triage"), now=now, calendar=calendar
    )


def _facts(**fields) -> steps.ContractFacts:
    values = {
        "status": "active",
        "agreement_last_day": None,
        "signed": False,
        "active_orders": 1,
        "any_orders": 1,
        "open_decision": True,
    }
    return steps.ContractFacts(**{**values, **fields})


def _case(checklist=()) -> SimpleNamespace:
    return SimpleNamespace(checklist=list(checklist))


def _step(definition: tuple[steps.Step, ...], slug: str) -> steps.Step:
    return next(step for step in definition if step.slug == slug)


def test_exit_has_five_steps_across_four_teams() -> None:
    assert len(steps.EXIT_STEPS) == 5
    assert {step.team for step in steps.EXIT_STEPS} == set(TEAM_LANES)
    for step in (*steps.EXIT_STEPS, *steps.ENTRY_STEPS):
        assert step.lane in TEAM_LANES[step.team]


def test_steps_only_for_contract_cases() -> None:
    assert steps.steps_for_case("contract:7:end") == steps.EXIT_STEPS
    assert steps.steps_for_case("contract:7:start") == steps.ENTRY_STEPS
    assert steps.steps_for_case("compass:abc") == ()
    assert steps.steps_for_case("lifecycle:1:offboarding") == ()
    assert steps.steps_for_case(None) == ()


def test_contract_and_order_steps_count_from_source() -> None:
    end = _step(steps.EXIT_STEPS, "contract_end")
    order = _step(steps.EXIT_STEPS, "order_close")
    assert not steps.step_auto_done(end, _case(), _facts())
    assert steps.step_auto_done(end, _case(), _facts(status="ended"))
    assert steps.step_auto_done(
        end, _case(), _facts(agreement_last_day=date(2026, 12, 31))
    )
    assert not steps.step_auto_done(order, _case(), _facts())
    assert steps.step_auto_done(order, _case(), _facts(active_orders=0))
    # Kontrakt bez żadnego zamówienia nie „zamknął linii”: to krok do sprawdzenia.
    assert not steps.step_auto_done(
        order, _case(), _facts(active_orders=0, any_orders=0)
    )


def test_checklist_step_needs_every_matching_item() -> None:
    step = _step(steps.EXIT_STEPS, "equipment")
    items = [
        {"text": case_rules.END_EQUIPMENT_ITEM, "done": True},
        {"text": f"{case_rules.END_ACCESS_PREFIX}VPN", "done": False},
        {"text": case_rules.END_SETTLEMENT_ITEM, "done": True},
    ]
    assert not steps.step_auto_done(step, _case(items), _facts())
    items[1]["done"] = True
    assert steps.step_auto_done(step, _case(items), _facts())
    # Pusta checklista nie zalicza kroku sama.
    assert not steps.step_auto_done(step, _case(), _facts())


def test_decision_step_done_when_no_open_decision() -> None:
    step = _step(steps.EXIT_STEPS, "decision")
    assert not steps.step_auto_done(step, _case(), _facts())
    assert steps.step_auto_done(step, _case(), _facts(open_decision=False))


def _spec(**fields) -> CardSpec:
    values = {
        "source_kind": "gap",
        "source_key": "gap:1",
        "team": "orders",
        "lane": "gap",
        "title": "Przerwa",
    }
    return CardSpec(**{**values, **fields})


def test_source_comes_back_after_close_unless_dismissed() -> None:
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    closed = _card(state="done", closed_at=now)
    assert sync.apply_spec(closed, _spec(), now=now)
    assert closed.state == "new" and closed.closed_at is None

    dismissed = _card(state="done", closed_at=now, meta={"dismissed": True})
    sync.apply_spec(dismissed, _spec(), now=now)
    assert dismissed.state == "done" and dismissed.closed_at == now


def test_case_card_mirrors_case_but_other_cards_keep_own_person() -> None:
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    mirrored = _card(assignee_user_id=9, state="in_progress")
    sync.apply_spec(
        mirrored,
        _spec(mirrors_case=True, mirror_state="waiting", mirror_assignee=3),
        now=now,
    )
    assert mirrored.assignee_user_id == 3 and mirrored.state == "waiting"

    own = _card(assignee_user_id=9, state="in_progress", source_kind="gap")
    sync.apply_spec(own, _spec(), now=now)
    assert own.assignee_user_id == 9 and own.state == "in_progress"


def test_moved_card_stays_in_its_lane() -> None:
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    card = _card(team="care", lane="help", lane_locked=True)
    sync.apply_spec(card, _spec(team="orders", lane="gap"), now=now)
    assert (card.team, card.lane) == ("care", "help")


def _viewer(teams=(), lead=False, amounts=False) -> Viewer:
    return Viewer(user_id=1, teams=frozenset(teams), is_lead=lead, sees_amounts=amounts)


def _user(*, handler: bool = False):
    from app.models.user import UserRole

    return SimpleNamespace(
        id=1,
        has_role=lambda role: handler and role == UserRole.admin,
        section_permissions=None,
    )


def test_negotiation_title_hidden_from_other_teams(monkeypatch) -> None:
    from app.services.admin_cases import service as cases

    monkeypatch.setattr(cases, "is_handler", lambda user: False)
    card = _card(
        team="contracts",
        lane="annex",
        title="Nowa stawka od stycznia",
        meta={"area": "negotiation"},
    )
    user = _user()
    care = _viewer(teams=["care"])
    contracts = _viewer(teams=["contracts"])
    assert board.visible_title(card, viewer=care, user=user) == "Sprawa: Negocjacje"
    assert board.visible_title(card, viewer=contracts, user=user) == card.title


def test_amounts_only_for_payroll_and_no_actions_on_other_teams(monkeypatch) -> None:
    from app.services.admin_cases import service as cases

    monkeypatch.setattr(cases, "is_handler", lambda user: False)
    card = _card(
        id=4,
        team="finance",
        lane="bonus",
        source_kind="bonus",
        title="Premie 10.2026",
        meta={"year": 2026, "month": 10, "count": 3},
    )
    totals = {(2026, 10): [{"total": "100.00", "currency": "PLN"}]}
    user = _user()
    payroll = board.card_payload(
        card,
        viewer=_viewer(teams=["finance"], amounts=True),
        user=user,
        names={},
        totals=totals,
    )
    assert payroll["amounts"] == totals[(2026, 10)]
    assert payroll["actions"] == ["approve_all", "cancel_all"]
    substitute = board.card_payload(
        card, viewer=_viewer(teams=["care"]), user=user, names={}, totals=totals
    )
    assert substitute["amounts"] is None
    assert substitute["actions"] == []
    # Zespół Finansów bez Płac: karta bez kwot i bez akceptu zbiorczego.
    finance = board.card_payload(
        card, viewer=_viewer(teams=["finance"]), user=user, names={}, totals=totals
    )
    assert finance["amounts"] is None and finance["actions"] == []


def test_important_only_rhythm_keeps_milestones_and_moves_pre_end() -> None:
    from app.services.care import plan

    start = date(2026, 1, 5)
    end = date(2026, 12, 31)
    first, last = date(2026, 1, 1), date(2026, 12, 31)
    regular = plan.slots_between(start, end, (), first, last)
    important = plan.slots_between(start, end, (), first, last, important_only=True)
    assert {slot.kind for slot in regular} == {"day_7", "pre_end", "cadence"}
    assert {slot.kind for slot in important} == {"day_7", "pre_end"}
    pre_end = next(slot for slot in important if slot.kind == "pre_end")
    assert pre_end.due_on == end - timedelta(days=60)


def test_single_rule_routes_and_conflicting_rules_go_to_a_person() -> None:
    from app.services.back_office import triage

    route = triage.rule_routes("Faktura za październik", None)
    assert route == [triage.Route("finance", "invoice")]
    assert triage.decide(route, None, 0.0) == (route[0], route[0])

    many = triage.rule_routes("Aneks i faktura", "Proszę o aneks i korektę faktury")
    assert {r.team for r in many} == {"finance", "contracts"}
    target, guess = triage.decide(many, None, 0.0)
    assert target is None and guess is not None


def test_model_only_decides_when_sure_and_never_blocks() -> None:
    from app.services.back_office import triage

    sure = triage.Route("orders", "mail")
    assert triage.decide([], sure, 0.9) == (sure, sure)
    assert triage.decide([], sure, 0.5) == (None, sure)
    assert triage.decide([], None, 0.0) == (None, None)
    # Reguła i pewny model się różnią: decyduje człowiek.
    rule = triage.Route("finance", "invoice")
    assert triage.decide([rule], sure, 0.95) == (None, rule)


@pytest.mark.parametrize(
    "raw",
    [
        "nie json",
        '{"team": "care"}',
        '{"team": "care", "lane": "gap", "confidence": 1}',
        '{"team": "hakerzy", "lane": "help", "confidence": 1}',
        "[]",
    ],
)
def test_bad_model_answers_are_rejected(raw: str) -> None:
    from app.services.back_office import triage

    assert triage.parse_model_answer(raw) == (None, 0.0)


def test_good_model_answer_is_parsed() -> None:
    from app.services.back_office import triage

    route, confidence = triage.parse_model_answer(
        '{"team": "care", "lane": "help", "confidence": 0.9}'
    )
    assert route == triage.Route("care", "help") and confidence == 0.9
