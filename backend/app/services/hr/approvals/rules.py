"""Zasady zgód: do jakiej kwoty decyduje przełożony i kto zatwierdza resztę.

``app_settings['hr_approval_rules']``::

    {"final_approver_user_id": 12,
     "supervisor_limits": {"bonus": null, "subscription": null, "trip": 1500, …}}

* ``supervisor_limits[rodzaj]`` — kwota brutto w PLN, do której przełożony
  autora zatwierdza sam; ``null`` = nigdy (zawsze zatwierdzający). Brak
  wiersza albo nieczytelna wartość = ``DEFAULT_LIMITS`` (przykładowe progi
  z makiety; Artur ustawia je w Ustawieniach).
* ``final_approver_user_id`` — kto zatwierdza ponad próg (Artur). Puste albo
  konto nieaktywne = aktywni admini. Nigdy autor zgody ani osoba z premii.

Kwota do progu: subskrypcja co miesiąc liczy się ×12 (koszt roczny), netto
×1,23; kwota w innej walucie niż PLN zawsze idzie do zatwierdzającego.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.user import User
from app.services.hr import recipients
from app.services.hr_approvals_schema import KINDS, RULES_SETTING

#: Przykładowe progi z makiety (20.10.2026) — premia i nowa subskrypcja zawsze
#: u zatwierdzającego.
DEFAULT_LIMITS: dict[str, Optional[int]] = {
    "bonus": None,
    "subscription": None,
    "trip": 1500,
    "gift": 200,
    "training": 1000,
    "other": 500,
}
LIMIT_MAX = 1_000_000
VAT_FACTOR = Decimal("1.23")


@dataclass(frozen=True)
class ApprovalRules:
    final_approver_user_id: Optional[int]
    supervisor_limits: Mapping[str, Optional[int]]

    def limit_for(self, kind: str) -> Optional[int]:
        return self.supervisor_limits.get(kind)

    def as_dict(self) -> dict[str, Any]:
        return {
            "final_approver_user_id": self.final_approver_user_id,
            "supervisor_limits": dict(self.supervisor_limits),
        }


def _clean_limit(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int) and 0 <= value <= LIMIT_MAX:
        return value
    raise ValueError("Próg: liczba całkowita od 0 do 1 000 000 albo „nigdy”.")


def normalize(raw: Any) -> ApprovalRules:
    """Zasady z wiersza ustawień; nieczytelne pola = domyślne."""

    source = raw if isinstance(raw, Mapping) else {}
    limits_raw = source.get("supervisor_limits")
    limits_raw = limits_raw if isinstance(limits_raw, Mapping) else {}
    limits: dict[str, Optional[int]] = {}
    for kind in KINDS:
        if kind in limits_raw:
            try:
                limits[kind] = _clean_limit(limits_raw[kind])
            except ValueError:
                limits[kind] = DEFAULT_LIMITS[kind]
        else:
            limits[kind] = DEFAULT_LIMITS[kind]
    approver = source.get("final_approver_user_id")
    if isinstance(approver, bool) or not isinstance(approver, int):
        approver = None
    return ApprovalRules(final_approver_user_id=approver, supervisor_limits=limits)


def parse_update(raw: Mapping[str, Any]) -> ApprovalRules:
    """Zasady z formularza Ustawień — błąd zamiast cichej zamiany na domyślne."""

    limits_raw = raw.get("supervisor_limits") or {}
    if not isinstance(limits_raw, Mapping):
        raise ValueError("Progi: słownik rodzaj → kwota.")
    unknown = sorted(set(limits_raw) - set(KINDS))
    if unknown:
        raise ValueError(f"Nieznany rodzaj zgody: {', '.join(unknown)}.")
    limits = {
        kind: _clean_limit(limits_raw[kind])
        if kind in limits_raw
        else DEFAULT_LIMITS[kind]
        for kind in KINDS
    }
    approver = raw.get("final_approver_user_id")
    if approver is not None and (
        isinstance(approver, bool) or not isinstance(approver, int)
    ):
        raise ValueError("Zatwierdzający: identyfikator konta albo puste.")
    return ApprovalRules(final_approver_user_id=approver, supervisor_limits=limits)


async def load_rules(db: AsyncSession) -> ApprovalRules:
    raw = await db.scalar(
        select(AppSetting.value).where(AppSetting.key == RULES_SETTING)
    )
    return normalize(raw)


async def save_rules(db: AsyncSession, rules: ApprovalRules, *, actor: User) -> None:
    statement = insert(AppSetting).values(
        key=RULES_SETTING, value=rules.as_dict(), updated_by=actor.id
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": statement.excluded.value, "updated_by": actor.id},
        )
    )


async def final_approver_ids(db: AsyncSession, rules: ApprovalRules) -> list[int]:
    """Zatwierdzający z Ustawień, gdy ma aktywne konto; inaczej aktywni admini."""

    if rules.final_approver_user_id is not None:
        user = await db.get(User, rules.final_approver_user_id)
        if user is not None and user.is_active:
            return [user.id]
    return await recipients.admin_ids(db)


def comparable_amount(
    amount: Decimal, *, currency: str, amount_basis: str, recurrence: str
) -> Optional[Decimal]:
    """Kwota brutto w PLN do porównania z progiem; ``None`` = inna waluta."""

    if currency != "PLN":
        return None
    value = amount * VAT_FACTOR if amount_basis == "net" else amount
    if recurrence == "monthly":
        value *= 12
    return value


def within_supervisor_limit(
    rules: ApprovalRules,
    kind: str,
    amount: Decimal,
    *,
    currency: str,
    amount_basis: str,
    recurrence: str,
) -> bool:
    limit = rules.limit_for(kind)
    if limit is None:
        return False
    value = comparable_amount(
        amount, currency=currency, amount_basis=amount_basis, recurrence=recurrence
    )
    return value is not None and value <= limit


__all__ = [
    "DEFAULT_LIMITS",
    "ApprovalRules",
    "comparable_amount",
    "final_approver_ids",
    "load_rules",
    "normalize",
    "parse_update",
    "save_rules",
    "within_supervisor_limit",
]
