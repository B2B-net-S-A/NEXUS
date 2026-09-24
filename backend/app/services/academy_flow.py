"""Akademia — przejścia między etapami naboru (czysta funkcja, bez bazy).

Etapy: ``new`` (z ogłoszeń, sortuje Luna) → ``to_call`` → ``scheduled``
(termin w biurze) → ``task_given`` → ``task_passed`` → ``contract_sent`` →
``signed`` (edycja od 1. dnia miesiąca). Wyjścia: ``rejected`` (decyzja
człowieka, pamiętana NA ZAWSZE — decyzja Artura 24.09.2026) i ``withdrew``
(osoba zrezygnowała sama; może wrócić przy kolejnym zgłoszeniu).

``apply_action`` zwraca słownik zmian do zapisania — handler zapisuje go na
wierszu pod blokadą. Limit miejsc w terminie sprawdza warstwa bazy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional

from app.models.academy import ACADEMY_ACTIVE_STATUSES

ACTIONS = (
    "call",
    "no_answer",
    "schedule",
    "absent",
    "give_task",
    "task_passed",
    "task_failed",
    "contract_sent",
    "signed",
    "reject",
    "withdraw",
    "restore",
    "note",
    "move_cohort",
)

# Skąd wolno wykonać akcję. `None` = z każdego etapu.
_ALLOWED_FROM: dict[str, Optional[tuple[str, ...]]] = {
    "call": ("new",),
    "no_answer": ("to_call",),
    "schedule": ("to_call", "scheduled"),
    "absent": ("scheduled",),
    "give_task": ("scheduled",),
    "task_passed": ("task_given",),
    "task_failed": ("task_given",),
    "contract_sent": ("task_passed",),
    "signed": ("task_passed", "contract_sent"),
    "reject": ACADEMY_ACTIVE_STATUSES,
    "withdraw": ACADEMY_ACTIVE_STATUSES,
    "restore": ("rejected", "withdrew"),
    "note": None,
    "move_cohort": ("signed",),
}

STATUS_LABELS = {
    "new": "Z ogłoszeń",
    "to_call": "Do telefonu",
    "scheduled": "Umówiony w biurze",
    "task_given": "Zadanie wydane",
    "task_passed": "Zaliczył zadanie",
    "contract_sent": "Umowa wysłana",
    "signed": "W akademii",
    "rejected": "Wykluczony",
    "withdrew": "Zrezygnował",
}

TASK_FAILED_REASON = "Nie zaliczył zadania"
REASON_MAX = 500
NOTE_MAX = 2000


class AcademyActionError(ValueError):
    """Akcja niedozwolona albo niepełna — handler zamienia na 409/422."""

    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ActionInput:
    action: str
    reason: Optional[str] = None
    session_id: Optional[int] = None
    task_due: Optional[date] = None
    cohort_month: Optional[date] = None
    note: Optional[str] = None


def next_cohort(today: date) -> date:
    """Edycja startuje 1. dnia miesiąca — podpis dziś = start od następnego."""
    if today.month == 12:
        return date(today.year + 1, 1, 1)
    return date(today.year, today.month + 1, 1)


def _clean(text: Optional[str], limit: int) -> Optional[str]:
    if text is None:
        return None
    value = " ".join(str(text).split())
    return value[:limit] or None


def apply_action(
    *,
    status: str,
    call_attempts: int,
    contract_sent_at: Optional[datetime],
    action: ActionInput,
    now: datetime,
    today: date,
    task_due_days: int,
    user_id: Optional[int],
) -> dict[str, Any]:
    """Zmiany dla akcji albo ``AcademyActionError``."""
    name = action.action
    if name not in _ALLOWED_FROM:
        raise AcademyActionError("unknown_action", "Nieznana akcja.", status_code=422)
    allowed = _ALLOWED_FROM[name]
    if allowed is not None and status not in allowed:
        raise AcademyActionError(
            "wrong_stage",
            f"Tej akcji nie da się wykonać na etapie „{STATUS_LABELS.get(status, status)}”. "
            "Odśwież listę — ktoś mógł już przesunąć tę osobę.",
        )

    changes: dict[str, Any] = {"updated_by": user_id}

    if name == "call":
        changes["status"] = "to_call"
    elif name == "no_answer":
        changes["call_attempts"] = call_attempts + 1
        changes["last_call_at"] = now
    elif name == "schedule":
        if action.session_id is None:
            raise AcademyActionError(
                "session_required", "Wybierz termin spotkania.", status_code=422
            )
        changes.update(
            status="scheduled",
            session_id=action.session_id,
            attended=None,
            last_call_at=now,
        )
    elif name == "absent":
        changes["attended"] = False
    elif name == "give_task":
        due = action.task_due or (today + timedelta(days=task_due_days))
        if due < today:
            raise AcademyActionError(
                "task_due_past",
                "Termin oddania zadania nie może być w przeszłości.",
                status_code=422,
            )
        changes.update(
            status="task_given", attended=True, task_due=due, task_result=None
        )
    elif name == "task_passed":
        changes.update(status="task_passed", task_result="passed")
    elif name == "task_failed":
        reason = _clean(action.reason, REASON_MAX)
        changes.update(
            status="rejected",
            task_result="failed",
            closed_stage=status,
            closed_reason=(
                f"{TASK_FAILED_REASON}: {reason}"[:REASON_MAX]
                if reason
                else TASK_FAILED_REASON
            ),
            closed_at=now,
            closed_by=user_id,
        )
    elif name == "contract_sent":
        changes.update(status="contract_sent", contract_sent_at=now)
    elif name == "signed":
        changes.update(
            status="signed",
            signed_at=now,
            cohort_month=_first_of_month(action.cohort_month) or next_cohort(today),
        )
        if contract_sent_at is None:
            changes["contract_sent_at"] = now
    elif name == "reject":
        reason = _clean(action.reason, REASON_MAX)
        if not reason:
            raise AcademyActionError(
                "reason_required",
                "Podaj powód — zostanie zapamiętany na stałe.",
                status_code=422,
            )
        changes.update(
            status="rejected",
            closed_stage=status,
            closed_reason=reason,
            closed_at=now,
            closed_by=user_id,
        )
    elif name == "withdraw":
        changes.update(
            status="withdrew",
            closed_stage=status,
            closed_reason=_clean(action.reason, REASON_MAX),
            closed_at=now,
            closed_by=user_id,
        )
    elif name == "restore":
        changes.update(
            status="to_call",
            closed_stage=None,
            closed_reason=None,
            closed_at=None,
            closed_by=None,
            session_id=None,
            attended=None,
            task_due=None,
            task_result=None,
        )
    elif name == "note":
        changes["note"] = _clean(action.note, NOTE_MAX)
    elif name == "move_cohort":
        cohort = _first_of_month(action.cohort_month)
        if cohort is None:
            raise AcademyActionError(
                "cohort_required", "Wybierz edycję.", status_code=422
            )
        changes["cohort_month"] = cohort
    return changes


def _first_of_month(value: Optional[date]) -> Optional[date]:
    return date(value.year, value.month, 1) if value else None
