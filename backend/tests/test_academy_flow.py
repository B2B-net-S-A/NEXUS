"""Akademia — przejścia między etapami (czysta funkcja)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.services.academy_flow import (
    TASK_FAILED_REASON,
    AcademyActionError,
    ActionInput,
    apply_action,
    next_cohort,
)

NOW = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 24)


def _apply(status: str, action: ActionInput, **extra) -> dict:
    return apply_action(
        status=status,
        call_attempts=extra.get("call_attempts", 0),
        contract_sent_at=extra.get("contract_sent_at"),
        action=action,
        now=NOW,
        today=TODAY,
        task_due_days=5,
        user_id=7,
    )


def test_next_cohort_is_first_day_of_next_month():
    assert next_cohort(date(2026, 9, 24)) == date(2026, 10, 1)
    assert next_cohort(date(2026, 9, 1)) == date(2026, 10, 1)
    assert next_cohort(date(2026, 12, 31)) == date(2027, 1, 1)


def test_happy_path_from_call_list_to_signed():
    assert _apply("new", ActionInput("call"))["status"] == "to_call"
    scheduled = _apply("to_call", ActionInput("schedule", session_id=3))
    assert scheduled["status"] == "scheduled" and scheduled["session_id"] == 3
    task = _apply("scheduled", ActionInput("give_task"))
    assert task["status"] == "task_given"
    assert task["attended"] is True
    assert task["task_due"] == date(2026, 9, 29)
    assert _apply("task_given", ActionInput("task_passed"))["status"] == "task_passed"
    sent = _apply("task_passed", ActionInput("contract_sent"))
    assert sent["status"] == "contract_sent" and sent["contract_sent_at"] == NOW
    signed = _apply("contract_sent", ActionInput("signed"), contract_sent_at=NOW)
    assert signed["status"] == "signed"
    assert signed["cohort_month"] == date(2026, 10, 1)
    assert "contract_sent_at" not in signed


def test_signing_without_sent_step_stamps_contract_sent():
    signed = _apply("task_passed", ActionInput("signed", cohort_month=date(2026, 11, 17)))
    assert signed["contract_sent_at"] == NOW
    # Edycja to zawsze pierwszy dzień miesiąca.
    assert signed["cohort_month"] == date(2026, 11, 1)


def test_no_answer_counts_attempts_without_moving():
    changes = _apply("to_call", ActionInput("no_answer"), call_attempts=2)
    assert changes["call_attempts"] == 3
    assert "status" not in changes


def test_reject_requires_reason_and_remembers_stage():
    with pytest.raises(AcademyActionError) as err:
        _apply("to_call", ActionInput("reject", reason="   "))
    assert err.value.code == "reason_required"
    changes = _apply("to_call", ActionInput("reject", reason="Nie pasuje umowa zlecenie"))
    assert changes["status"] == "rejected"
    assert changes["closed_stage"] == "to_call"
    assert changes["closed_reason"] == "Nie pasuje umowa zlecenie"
    assert changes["closed_by"] == 7


def test_failed_task_is_a_rejection_with_reason():
    changes = _apply("task_given", ActionInput("task_failed", reason="brak rozmowy"))
    assert changes["status"] == "rejected"
    assert changes["task_result"] == "failed"
    assert changes["closed_reason"] == f"{TASK_FAILED_REASON}: brak rozmowy"
    bare = _apply("task_given", ActionInput("task_failed"))
    assert bare["closed_reason"] == TASK_FAILED_REASON


@pytest.mark.parametrize(
    "status,action",
    [
        ("new", "schedule"),
        ("to_call", "give_task"),
        ("scheduled", "signed"),
        ("rejected", "call"),
        ("signed", "reject"),
        ("withdrew", "no_answer"),
    ],
)
def test_actions_from_the_wrong_stage_are_refused(status, action):
    with pytest.raises(AcademyActionError) as err:
        _apply(status, ActionInput(action, session_id=1, reason="x"))
    assert err.value.code == "wrong_stage"
    assert err.value.status_code == 409


def test_schedule_needs_a_session():
    with pytest.raises(AcademyActionError) as err:
        _apply("to_call", ActionInput("schedule"))
    assert err.value.code == "session_required"


def test_task_due_cannot_be_in_the_past():
    with pytest.raises(AcademyActionError):
        _apply("scheduled", ActionInput("give_task", task_due=date(2026, 9, 1)))


def test_restore_brings_excluded_person_back_to_calls():
    changes = _apply("rejected", ActionInput("restore"))
    assert changes["status"] == "to_call"
    assert changes["closed_reason"] is None
    assert changes["session_id"] is None


def test_unknown_action_is_422():
    with pytest.raises(AcademyActionError) as err:
        _apply("new", ActionInput("teleport"))
    assert err.value.status_code == 422


# ── runda 8 audytu (26.09.2026) ────────────────────────────────────────────


def test_signed_person_can_withdraw_before_the_edition():
    """R8-N2-7 (decyzja Artura 26.09.2026): „W akademii” ma wyjście."""
    changes = _apply("signed", ActionInput("withdraw", reason="Zrezygnował sam"))
    assert changes["status"] == "withdrew"
    assert changes["closed_stage"] == "signed"
    # Wykluczenie po podpisie dalej nie wchodzi w grę.
    with pytest.raises(AcademyActionError):
        _apply("signed", ActionInput("reject", reason="x"))


def test_restore_starts_over_without_old_reapplication_and_contract():
    """R8-N2-8: „aplikował ponownie” sprzed przywrócenia nie wraca przy
    kolejnym wykluczeniu; umowa i edycja dotyczą poprzedniego podejścia."""
    changes = _apply("withdrew", ActionInput("restore"))
    for key in ("reapplied_at", "contract_sent_at", "signed_at", "cohort_month"):
        assert key in changes and changes[key] is None


@pytest.mark.parametrize("action", ["reject", "withdraw"])
def test_leaving_before_the_meeting_frees_the_session(action):
    """R8-N2-9: wykluczony albo zrezygnowany nie wisi na liście terminu."""
    changes = _apply("scheduled", ActionInput(action, reason="Nie pasuje"))
    assert changes["session_id"] is None
    # Kto był na spotkaniu, zostaje przy terminie (historia).
    later = _apply("task_passed", ActionInput(action, reason="Nie pasuje"))
    assert "session_id" not in later
