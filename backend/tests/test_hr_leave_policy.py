"""Reguły urlopów — czyste funkcje (``app/services/hr/leave_policy.py``).

Przypadki brzegowe i ścieżki odmowy: rodzaje dla B2B, pół dnia, limity
ustawowe, twardy limit umowy o pracę, podział B2B, kto decyduje, kto widzi
rodzaj nieobecności (D6), kto anuluje.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.hr.calendar import WorkCalendar
from app.services.hr.leave_m365 import LeaveSnapshot, plan_operations
from app.services.hr.leave_policy import (
    Actor,
    LeavePolicyError,
    PoolYear,
    CANCEL_REASON_MAX,
    allowed_types,
    approver_cancel_refusal,
    can_decide,
    can_see_type,
    own_cancel_refusal,
    plan_days,
    requested_days,
    team_cancel_refusal,
    validate_shape,
)

D = Decimal


def _days(start: date, end: date, half_day=None):
    return requested_days(WorkCalendar(), start, end, half_day)


def _shape(**overrides) -> None:
    values = {
        "leave_type": "vacation",
        "start": date(2026, 11, 2),
        "end": date(2026, 11, 6),
        "half_day": None,
        "employment_type": "uop",
        "for_self": True,
    }
    values.update(overrides)
    validate_shape(**values)


# ── Kształt wniosku ───────────────────────────────────────────────────────────


def test_contractors_may_only_take_vacation() -> None:
    assert allowed_types("b2b") == ("vacation",)
    assert allowed_types("zlecenie") == ("vacation",)
    assert "sick_leave" in allowed_types("uop")
    with pytest.raises(LeavePolicyError, match="wyłącznie o urlop"):
        _shape(leave_type="on_demand", employment_type="b2b")
    with pytest.raises(LeavePolicyError, match="Osobie na umowie zlecenie"):
        _shape(leave_type="sick_leave", employment_type="zlecenie", for_self=False)


def test_holiday_in_lieu_only_on_employment_contract() -> None:
    _shape(leave_type="holiday_in_lieu", employment_type="uop")
    with pytest.raises(LeavePolicyError):
        _shape(leave_type="holiday_in_lieu", employment_type="b2b")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"end": date(2026, 11, 1)}, "przed datą początku"),
        ({"half_day": "morning"}, "jednym dniu"),
        ({"leave_type": "holiday"}, "Nieznany rodzaj"),
        ({"end": date(2027, 12, 1)}, "najwyżej rok"),
    ],
)
def test_malformed_requests_are_refused(overrides, message) -> None:
    with pytest.raises(LeavePolicyError, match=message):
        _shape(**overrides)


def test_half_day_counts_as_half_only_on_single_day() -> None:
    assert _days(date(2026, 11, 4), date(2026, 11, 4), "afternoon") == [
        (date(2026, 11, 4), D("0.5"))
    ]
    # Pół dnia w sobotę nie daje żadnego dnia roboczego.
    assert _days(date(2026, 11, 7), date(2026, 11, 7), "morning") == []


def test_request_without_working_days_is_refused() -> None:
    with pytest.raises(LeavePolicyError, match="nie ma dni roboczych"):
        plan_days(leave_type="vacation", employment_type="uop", days=[], pools={})


# ── Pula ──────────────────────────────────────────────────────────────────────


def test_employment_contract_with_pool_has_hard_limit() -> None:
    days = _days(date(2026, 11, 2), date(2026, 11, 6))
    pools = {2026: PoolYear(2026, D("26"), booked_paid_days=D("23"))}
    with pytest.raises(LeavePolicyError, match="urlop bezpłatny"):
        plan_days(leave_type="vacation", employment_type="uop", days=days, pools=pools)


def test_employment_contract_without_pool_is_unlimited_and_paid() -> None:
    days = _days(date(2026, 11, 2), date(2026, 11, 6))
    plan = plan_days(leave_type="vacation", employment_type="uop", days=days, pools={})
    assert plan.total == D("5")
    assert plan.paid == D("5")
    assert plan.unpaid == D("0")


def test_contractor_without_pool_takes_everything_unpaid() -> None:
    days = _days(date(2026, 11, 2), date(2026, 11, 4))
    plan = plan_days(leave_type="vacation", employment_type="b2b", days=days, pools={})
    assert plan.paid == D("0")
    assert plan.unpaid == D("3")
    assert all(not day.paid for day in plan.days)


def test_contractor_half_day_is_atomic() -> None:
    days = _days(date(2026, 11, 4), date(2026, 11, 4), "morning")
    tight = {2026: PoolYear(2026, D("10"), booked_paid_days=D("9.5"))}
    plan = plan_days(
        leave_type="vacation", employment_type="b2b", days=days, pools=tight
    )
    assert plan.paid == D("0.5")
    empty = {2026: PoolYear(2026, D("10"), booked_paid_days=D("10"))}
    plan = plan_days(
        leave_type="vacation", employment_type="b2b", days=days, pools=empty
    )
    assert plan.paid == D("0") and plan.unpaid == D("0.5")


def test_contractor_full_day_is_not_split_by_half_day_left() -> None:
    days = _days(date(2026, 11, 2), date(2026, 11, 3))
    pools = {2026: PoolYear(2026, D("10"), booked_paid_days=D("8.5"))}
    plan = plan_days(
        leave_type="vacation", employment_type="b2b", days=days, pools=pools
    )
    assert [d.paid for d in plan.days] == [True, False]
    assert plan.years[0].remaining_after == D("0.5")


def test_non_pool_types_do_not_touch_the_pool() -> None:
    days = _days(date(2026, 11, 2), date(2026, 11, 6))
    pools = {2026: PoolYear(2026, D("2"))}
    plan = plan_days(
        leave_type="sick_leave", employment_type="uop", days=days, pools=pools
    )
    assert plan.paid == D("0") and plan.unpaid == D("0")
    assert plan.years[0].remaining_after == D("2")


# ── Limity ustawowe (Compass ich nie pilnował) ───────────────────────────────


def test_on_demand_is_limited_to_four_days_a_year() -> None:
    days = _days(date(2026, 11, 2), date(2026, 11, 3))
    used = {2026: PoolYear(2026, None, on_demand_days=D("3"))}
    with pytest.raises(LeavePolicyError, match="zostało 1"):
        plan_days(leave_type="on_demand", employment_type="uop", days=days, pools=used)
    ok = {2026: PoolYear(2026, None, on_demand_days=D("2"))}
    assert plan_days(
        leave_type="on_demand", employment_type="uop", days=days, pools=ok
    ).total == D("2")


def test_childcare_art_188_is_limited_to_two_days_a_year() -> None:
    days = _days(date(2026, 11, 2), date(2026, 11, 4))
    with pytest.raises(LeavePolicyError, match="art. 188"):
        plan_days(leave_type="childcare", employment_type="uop", days=days, pools={})
    half = _days(date(2026, 11, 2), date(2026, 11, 2), "morning")
    used = {2026: PoolYear(2026, None, childcare_days=D("1.5"))}
    assert plan_days(
        leave_type="childcare", employment_type="uop", days=half, pools=used
    ).total == D("0.5")


# ── Kto decyduje, kto widzi, kto anuluje ─────────────────────────────────────


def test_only_manager_hr_and_admin_decide_and_nobody_decides_own() -> None:
    manager = Actor(user_id=10)
    hr = Actor(user_id=20, is_people_admin=True)
    admin = Actor(user_id=30, is_admin=True)
    colleague = Actor(user_id=40)
    assert can_decide(manager, subject_user_id=1, subject_manager_id=10)
    assert can_decide(hr, subject_user_id=1, subject_manager_id=10)
    assert can_decide(admin, subject_user_id=1, subject_manager_id=None)
    assert not can_decide(colleague, subject_user_id=1, subject_manager_id=10)
    assert not can_decide(manager, subject_user_id=2, subject_manager_id=None)
    for actor in (manager, hr, admin):
        assert not can_decide(
            actor, subject_user_id=actor.user_id, subject_manager_id=None
        )


def test_type_of_absence_is_visible_only_inside_d6_circle() -> None:
    assert can_see_type(Actor(user_id=1), subject_user_id=1, subject_manager_id=10)
    assert can_see_type(Actor(user_id=10), subject_user_id=1, subject_manager_id=10)
    assert can_see_type(
        Actor(user_id=20, is_people_admin=True),
        subject_user_id=1,
        subject_manager_id=10,
    )
    assert not can_see_type(Actor(user_id=40), subject_user_id=1, subject_manager_id=10)


def test_own_cancel_rules() -> None:
    today = date(2026, 11, 2)
    assert (
        own_cancel_refusal(status="pending", start=date(2026, 11, 3), today=today)
        is None
    )
    assert (
        own_cancel_refusal(status="approved", start=date(2026, 11, 3), today=today)
        is None
    )
    assert own_cancel_refusal(status="approved", start=today, today=today) is not None
    assert own_cancel_refusal(status="rejected", start=date(2026, 12, 1), today=today)
    assert team_cancel_refusal(status="approved") is None
    assert team_cancel_refusal(status="cancelled") is not None


@pytest.mark.parametrize(
    "start, allowed",
    [
        (date(2026, 11, 3), True),  # przed pierwszym dniem
        (date(2026, 11, 2), False),  # pierwszy dzień
        (date(2026, 10, 1), False),  # dni już minęły
    ],
)
def test_own_pending_cancel_stops_on_the_first_day(start: date, allowed: bool) -> None:
    """Decyzja Artura 28.10.2026: osoba nie anuluje sama nieobecności, która
    trwa albo minęła — także niezatwierdzonego wniosku."""

    refusal = own_cancel_refusal(status="pending", start=start, today=date(2026, 11, 2))
    if allowed:
        assert refusal is None
    else:
        assert refusal is not None
        assert "przełożony albo Kadry" in refusal


def test_approver_cancel_needs_a_reason_once_the_term_started() -> None:
    today = date(2026, 11, 2)
    future = date(2026, 11, 3)
    # Przed pierwszym dniem powód jest opcjonalny.
    assert approver_cancel_refusal(start=future, today=today, reason=None) is None
    assert approver_cancel_refusal(start=future, today=today, reason="  ") is None
    assert approver_cancel_refusal(start=future, today=today, reason="ab") is not None
    # Od pierwszego dnia (także trwający i miniony) — wymagany, 3–500 znaków.
    for start in (today, date(2026, 10, 1)):
        missing = approver_cancel_refusal(start=start, today=today, reason=None)
        assert missing is not None and "powód" in missing.lower()
        assert approver_cancel_refusal(start=start, today=today, reason=" ab ")
        assert (
            approver_cancel_refusal(start=start, today=today, reason="Był w pracy")
            is None
        )
    too_long = "x" * (CANCEL_REASON_MAX + 1)
    assert approver_cancel_refusal(start=today, today=today, reason=too_long)
    assert (
        approver_cancel_refusal(
            start=today, today=today, reason="x" * CANCEL_REASON_MAX
        )
        is None
    )


# ── Microsoft 365: co trafia do kolejki ───────────────────────────────────────


def _snapshot(**overrides) -> LeaveSnapshot:
    values = {
        "id": "00000000-0000-0000-0000-000000000001",
        "user_id": 1,
        "start": date(2026, 11, 2),
        "end": date(2026, 11, 6),
        "half_day": None,
        "total_days": D("5"),
        "substitute_user_id": 2,
        "forward_mail_consent": False,
        "oof_internal_message": None,
        "oof_external_message": None,
        "return_on": date(2026, 11, 9),
    }
    values.update(overrides)
    return LeaveSnapshot(**values)


def test_approval_queues_oof_and_private_event_without_type() -> None:
    ops = plan_operations("approved", _snapshot(), today=date(2026, 10, 16))
    kinds = [op.kind for op in ops]
    assert kinds == ["set_oof", "calendar_event_upsert"]
    event = ops[1].payload
    assert event["subject"] == "Poza biurem"
    assert event["sensitivity"] == "private"
    assert all("leave_type" not in op.payload for op in ops)


def test_half_day_gets_event_with_hours_but_no_oof() -> None:
    snapshot = _snapshot(
        start=date(2026, 11, 4),
        end=date(2026, 11, 4),
        half_day="morning",
        total_days=D("0.5"),
    )
    ops = plan_operations("approved", snapshot, today=date(2026, 10, 16))
    assert [op.kind for op in ops] == ["calendar_event_upsert"]
    assert ops[0].payload["half_day"] == "morning"


def test_finished_leave_queues_nothing() -> None:
    assert plan_operations("approved", _snapshot(), today=date(2026, 11, 7)) == []


def test_cancel_clears_what_approval_set() -> None:
    ops = plan_operations(
        "cancelled",
        _snapshot(forward_mail_consent=True),
        today=date(2026, 10, 16),
        revision=2,
    )
    assert [op.kind for op in ops] == [
        "clear_oof",
        "calendar_event_delete",
        "forward_rule_close",
    ]
    assert ops[2].dedupe_key.endswith(":r2")
