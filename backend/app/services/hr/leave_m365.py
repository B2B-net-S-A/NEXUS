"""Jakie operacje Microsoft 365 wynikają ze zmiany wniosku — czysta funkcja.

* akceptacja / wpis za pracownika / L4 (wniosek zatwierdzony, jeszcze trwa
  albo się zacznie): autoodpowiedź (tylko gdy wniosek ma co najmniej jeden
  pełny dzień), wydarzenie „Poza biurem” w kalendarzu, reguła przekierowania
  poczty do zastępcy — WYŁĄCZNIE ze zgodą osoby (``forward_mail_consent``),
* anulowanie zatwierdzonego: zdjęcie autoodpowiedzi, usunięcie wydarzenia,
  zamknięcie reguły (gdy była zgoda).

Treść nie zdradza rodzaju nieobecności (D6): tytuł wydarzenia jest stały,
wydarzenie prywatne, autoodpowiedź bez typu. Urlop, który już minął, nie
dostaje niczego (jak wpis za pracownika w Compassie).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal, Optional

Event = Literal["approved", "cancelled", "forward_on", "forward_off"]

#: Tytuł wydarzenia w kalendarzu — zawsze ten sam, bez rodzaju nieobecności.
CALENDAR_SUBJECT = "Poza biurem"


@dataclass(frozen=True)
class LeaveSnapshot:
    id: str
    user_id: int
    start: date
    end: date
    half_day: Optional[str]
    total_days: Decimal
    substitute_user_id: Optional[int]
    forward_mail_consent: bool
    oof_internal_message: Optional[str]
    oof_external_message: Optional[str]
    return_on: date


@dataclass(frozen=True)
class PlannedOperation:
    kind: str
    dedupe_key: str
    payload: dict[str, Any]


def forward_rule_name(leave_id: str) -> str:
    return f"NEXUS · zastępstwo · {leave_id}"


def plan_operations(
    event: Event, leave: LeaveSnapshot, *, today: date, revision: int = 0
) -> list[PlannedOperation]:
    """Operacje do kolejki; ``revision`` rozróżnia kolejne zmiany zgody."""

    base = f"leave:{leave.id}"
    window = {"start": leave.start.isoformat(), "end": leave.end.isoformat()}
    if event == "approved":
        if leave.end < today:
            return []
        ops: list[PlannedOperation] = []
        if leave.total_days >= Decimal("1"):
            ops.append(
                PlannedOperation(
                    kind="set_oof",
                    dedupe_key=f"{base}:set_oof",
                    payload={
                        **window,
                        "return_on": leave.return_on.isoformat(),
                        "timezone": "Europe/Warsaw",
                        "substitute_user_id": leave.substitute_user_id,
                        "internal_message": leave.oof_internal_message,
                        "external_message": leave.oof_external_message,
                    },
                )
            )
        ops.append(
            PlannedOperation(
                kind="calendar_event_upsert",
                dedupe_key=f"{base}:calendar_event_upsert",
                payload={
                    **window,
                    "half_day": leave.half_day,
                    "subject": CALENDAR_SUBJECT,
                    "show_as": "oof",
                    "sensitivity": "private",
                    "transaction_id": f"nexus-leave-{leave.id}",
                },
            )
        )
        if leave.forward_mail_consent and leave.substitute_user_id is not None:
            ops.append(_forward(base, leave, "forward_rule_open", revision, window))
        return ops
    if event == "cancelled":
        ops = [
            PlannedOperation(
                kind="clear_oof",
                dedupe_key=f"{base}:clear_oof",
                payload={**window},
            ),
            PlannedOperation(
                kind="calendar_event_delete",
                dedupe_key=f"{base}:calendar_event_delete",
                payload={"transaction_id": f"nexus-leave-{leave.id}"},
            ),
        ]
        if leave.forward_mail_consent:
            ops.append(_forward(base, leave, "forward_rule_close", revision, window))
        return ops
    if leave.end < today:
        return []
    if event == "forward_on":
        if not leave.forward_mail_consent or leave.substitute_user_id is None:
            return []
        return [_forward(base, leave, "forward_rule_open", revision, window)]
    return [_forward(base, leave, "forward_rule_close", revision, window)]


def _forward(
    base: str,
    leave: LeaveSnapshot,
    kind: str,
    revision: int,
    window: dict[str, str],
) -> PlannedOperation:
    suffix = f":r{revision}" if revision else ""
    return PlannedOperation(
        kind=kind,
        dedupe_key=f"{base}:{kind}{suffix}",
        payload={
            **window,
            "substitute_user_id": leave.substitute_user_id,
            "rule_name": forward_rule_name(leave.id),
        },
    )
