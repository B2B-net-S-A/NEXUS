"""Premie: ręczne, decyzje o propozycjach automatów, zmiany i anulowanie.

Kto (``payroll_access.PayrollViewer``):

* **Płace** — przyznają, zmieniają, zatwierdzają i anulują każdą premię
  (poza własną),
* **przełożony** — proponuje premię ręczną swojemu człowiekowi (od 19.10.2026
  to propozycja: ``proposed`` bez ``assigned_by``, bez dzwonka osobie;
  zatwierdzają ją tylko Płace, nigdy autor — decyzja Artura), zatwierdza albo
  odrzuca propozycje automatów dla swoich ludzi, zmienia i anuluje (wycofuje)
  tylko premie, które sam zaproponował.

Reguły: okres ręcznej premii — ostatnie 12 miesięcy i bieżący (Compass,
``BONUS_PERIOD_MAX_MONTHS_BACK``); propozycji placementu nie da się
zatwierdzić przed terminem (start + 21 dni roboczych); nic w zamkniętym
miesiącu (409). Anulowanie jest miękkie — wiersz zostaje ze statusem.

Dzwonek ``hr_bonus_assigned`` (przyznanie, zmiana i anulowanie przyznanej)
nie niesie kwoty; kwota zostaje w ``hr_audit_events`` z ``sensitivity='payroll'``.

**Premia „wypłacona” (R11, etap 4).** Przy włączonym module rozliczeń premia
jest wypłacona dopiero, gdy opłacone jest rozliczenie miesiąca, w którym ją
przyznano (ta sama osoba, okres i waluta — ``paid_flags``), a nie przy
zamknięciu miesiąca. Przy wyłączonym module zostaje stara reguła (miesiąc
zamknięty w płacach) — ``paid_flags`` zwraca wtedy ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_now
from app.models.contract import Contract
from app.models.hr_payroll import HrBonus, PayrollPeriod
from app.models.hr_settlement import PayrollSettlement
from app.models.hr_profile import EmployeeProfile
from app.models.notification import NotificationType
from app.models.user import User
from app.services.hr import audit, payroll_periods
from app.services.hr import modules as hr_modules
from app.services.hr.employment_terms import bonus_message, terms
from app.services.hr.notify import notify_each
from app.services.hr.settlements_rules import settled_in_nexus
from app.services.hr.payroll_access import PayrollViewer
from app.services.hr.payroll_errors import (
    PayrollConflict,
    PayrollError,
    PayrollForbidden,
    PayrollNotFound,
)
from app.services.hr.payroll_periods import (
    add_months,
    assert_open,
    label,
    validate_period,
)
from app.services.hr_payroll_schema import (
    AUTOMATED_SOURCES,
    BONUS_CATEGORIES,
    CURRENCIES,
    DESCRIPTION_MAX_LENGTH,
)

BONUS_PERIOD_MAX_MONTHS_BACK = 12
BONUS_MIN = Decimal("0.01")
BONUS_MAX = Decimal("1000000")
#: Powody anulowania nadawane przez automaty (automat może je cofnąć).
AUTO_CANCEL_REASONS: frozenset[str] = frozenset(
    {"contract_ended", "contract_void", "rule_no_longer_applies"}
)

CATEGORY_LABELS: dict[str, str] = {
    "sales": "Sprzedaż",
    "delivery_lead": "Delivery Lead",
    "recruiter": "Rekruter",
    "custom": "Inna",
    "league": "Liga",
}


@dataclass(frozen=True)
class BonusInput:
    recipient_user_id: int
    amount: Decimal
    currency: str
    category: str
    period_year: int
    period_month: int
    description: Optional[str]
    contract_id: Optional[int] = None


def clean_amount(amount: Decimal) -> Decimal:
    """Kwota premii zaokrąglona HALF_UP (jak raport płac), zakres na wyniku.

    Zakres sprawdzany po zaokrągleniu: 0,004 zaokrągla się do 0,00 i bez tego
    przechodziło do bazy, gdzie CHECK kwoty dawał 500 (audyt A2, 19.10.2026).
    Wstępne sprawdzenie chroni ``quantize`` przed liczbą spoza precyzji.
    """

    if not amount.is_finite() or amount <= 0 or amount > BONUS_MAX:
        raise PayrollError("Kwota premii: od 0,01 do 1 000 000.")
    value = amount.quantize(BONUS_MIN, rounding=ROUND_HALF_UP)
    if value < BONUS_MIN:
        raise PayrollError("Kwota premii: od 0,01 do 1 000 000.")
    return value


def clean_currency(currency: str) -> str:
    code = (currency or "").strip().upper()
    if code not in CURRENCIES:
        raise PayrollError("Waluta premii: PLN, EUR albo USD.")
    return code


def clean_category(category: str) -> str:
    if category not in BONUS_CATEGORIES:
        raise PayrollError("Nieznana kategoria premii.")
    return category


def clean_description(text: Optional[str]) -> Optional[str]:
    value = (text or "").strip()
    if len(value) > DESCRIPTION_MAX_LENGTH:
        raise PayrollError(f"Opis premii: najwyżej {DESCRIPTION_MAX_LENGTH} znaków.")
    return value or None


def validate_manual_period(year: int, month: int, today: date) -> None:
    validate_period(year, month)
    earliest = add_months(today.year, today.month, -BONUS_PERIOD_MAX_MONTHS_BACK)
    current = (today.year, today.month)
    if not earliest <= (year, month) <= current:
        raise PayrollError(f"Okres premii: od {label(*earliest)} do {label(*current)}.")


def is_automated(bonus: HrBonus) -> bool:
    return bonus.source in AUTOMATED_SOURCES


def bonus_payload(
    bonus: HrBonus,
    names: dict[int, str],
    *,
    with_snapshot: bool,
    today: Optional[date] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": bonus.id,
        "recipient_user_id": bonus.recipient_user_id,
        "recipient_name": names.get(bonus.recipient_user_id),
        "proposed_by": bonus.proposed_by,
        "proposed_by_name": names.get(bonus.proposed_by) if bonus.proposed_by else None,
        "amount": str(bonus.amount),
        "currency": bonus.currency,
        "category": bonus.category,
        "category_label": CATEGORY_LABELS.get(bonus.category, bonus.category),
        "period_year": bonus.period_year,
        "period_month": bonus.period_month,
        "status": bonus.status,
        "source": bonus.source,
        "contract_id": bonus.contract_id,
        "eligible_on": bonus.eligible_on.isoformat() if bonus.eligible_on else None,
        "description": bonus.description,
        "assigned_by": bonus.assigned_by,
        "assigned_at": bonus.assigned_at.isoformat() if bonus.assigned_at else None,
        "cancelled_at": bonus.cancelled_at.isoformat() if bonus.cancelled_at else None,
        "cancel_reason": bonus.cancel_reason,
        "edited": bool((bonus.rule_snapshot or {}).get("edited_amount")),
        "edited_recipient": bool((bonus.rule_snapshot or {}).get("edited_recipient")),
    }
    if today is not None and bonus.eligible_on is not None:
        payload["eligible"] = bonus.eligible_on <= today
    if with_snapshot:
        payload["rule_snapshot"] = bonus.rule_snapshot or {}
    return payload


async def names_for(db: AsyncSession, bonuses: list[HrBonus]) -> dict[int, str]:
    ids = {b.recipient_user_id for b in bonuses} | {
        b.proposed_by for b in bonuses if b.proposed_by
    }
    if not ids:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(ids)))
    return {int(uid): str(name) for uid, name in rows.all()}


async def _notify(db: AsyncSession, bonus: HrBonus, *, event: str) -> None:
    """Dzwonek osobie: ``event`` = new / changed / cancelled, słowa z jej formy."""

    # Przy B2B i zleceniu „wynagrodzenie dodatkowe”, nie „premia” (21.10.2026).
    form = await db.scalar(
        select(EmployeeProfile.employment_type).where(
            EmployeeProfile.user_id == bonus.recipient_user_id
        )
    )
    # Dzwonek nie cofa decyzji o premii (``notify_each`` łapie awarię).
    await notify_each(
        db,
        [bonus.recipient_user_id],
        title=terms(form)[f"bonus_{event}_title"],
        message=bonus_message(
            form,
            label(bonus.period_year, bonus.period_month),
            cancelled=event == "cancelled",
        ),
        ntype=NotificationType.hr_bonus_assigned,
        link="/my-time?tab=bonuses",
        related_entity_type="hr_bonus",
        related_entity_id=bonus.id,
        log_tag="payroll",
        # Zmiana i anulowanie tego samego dnia co przyznanie to nowy dzwonek,
        # nie duplikat do połknięcia przez dzienny dedup (audyt 22.10, F15).
        fresh=True,
    )


def _audit(
    db: AsyncSession,
    bonus: HrBonus,
    *,
    actor_id: Optional[int],
    action: str,
    **extra: Any,
) -> None:
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=bonus.recipient_user_id,
        entity_type="hr_bonus",
        entity_id=bonus.id,
        action=action,
        sensitivity="payroll",
        details={
            "amount": str(bonus.amount),
            "currency": bonus.currency,
            "category": bonus.category,
            "period": f"{bonus.period_year}-{bonus.period_month:02d}",
            "source": bonus.source,
            "status": bonus.status,
            **extra,
        },
    )


async def _locked_bonus(db: AsyncSession, bonus_id: int) -> HrBonus:
    bonus = await db.scalar(
        select(HrBonus)
        .where(HrBonus.id == bonus_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if bonus is None:
        raise PayrollNotFound("Nie ma takiej premii.")
    return bonus


def _require_scope(viewer: PayrollViewer, bonus: HrBonus) -> None:
    """Premia spoza zakresu = 404 (nie zdradzamy, że istnieje)."""

    if not viewer.sees_person(bonus.recipient_user_id):
        raise PayrollNotFound("Nie ma takiej premii.")


MANUAL_PROPOSAL_OWN = (
    "Własnej propozycji premii nie zatwierdzasz — zatwierdzą ją Płace."
)
MANUAL_PROPOSAL_PAYROLL_ONLY = "Premię ręczną od przełożonego zatwierdzają Płace."


def approval_refusal(viewer: PayrollViewer, bonus: HrBonus) -> Optional[str]:
    """Kto nie zatwierdza tej premii — zdanie odmowy albo ``None``.

    Propozycję ręczną (od przełożonego) zatwierdzają tylko Płace i nigdy jej
    autor (decyzja Artura 19.10.2026), bo inaczej przełożony przyznawałby
    premię sam sobie do akceptu. Propozycje automatów — Płace albo przełożony.
    """

    if bonus.recipient_user_id == viewer.user_id:
        return "Premii dla siebie nie zatwierdzasz."
    if not viewer.manages_bonuses_of(bonus.recipient_user_id):
        return "Propozycje zatwierdzają Płace albo przełożony tej osoby."
    if bonus.source == "manual":
        if bonus.proposed_by == viewer.user_id:
            return MANUAL_PROPOSAL_OWN
        if not viewer.payroll:
            return MANUAL_PROPOSAL_PAYROLL_ONLY
    return None


def can_approve(viewer: PayrollViewer, bonus: HrBonus) -> bool:
    """Przycisk „Zatwierdź” na liście — tylko propozycja, którą widz może zatwierdzić."""

    return bonus.status == "proposed" and approval_refusal(viewer, bonus) is None


async def _assert_contract_exists(db: AsyncSession, contract_id: Optional[int]) -> None:
    if contract_id is None:
        return
    found = await db.scalar(select(Contract.id).where(Contract.id == contract_id))
    if found is None:
        raise PayrollNotFound("Nie ma takiego kontraktu.")


async def _change_recipient(
    db: AsyncSession,
    viewer: PayrollViewer,
    bonus: HrBonus,
    recipient_id: int,
    reason: Optional[str],
) -> Optional[int]:
    """Zmiana odbiorcy (tylko Płace, z powodem). Zwraca poprzedniego odbiorcę."""

    if recipient_id == bonus.recipient_user_id:
        return None
    if not viewer.payroll:
        raise PayrollForbidden("Osobę w premii zmieniają Płace.")
    if recipient_id == viewer.user_id:
        raise PayrollForbidden("Premii nie przyznajesz sobie.")
    text = (reason or "").strip()
    if not text:
        raise PayrollError("Podaj powód zmiany osoby.")
    person = await db.scalar(
        select(User.is_active)
        .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
        .where(User.id == recipient_id)
    )
    if person is None:
        raise PayrollNotFound("Ta osoba nie ma kartoteki pracownika.")
    if not person:
        raise PayrollError("Ta osoba nie ma już aktywnego konta.")
    previous = bonus.recipient_user_id
    snapshot = bonus.rule_snapshot or {}
    bonus.rule_snapshot = {
        **snapshot,
        "edited_recipient": True,
        "automat_recipient_user_id": snapshot.get(
            "automat_recipient_user_id", previous
        ),
        "recipient_change_reason": clean_description(text),
    }
    bonus.recipient_user_id = recipient_id
    return previous


async def create_manual(
    db: AsyncSession, viewer: PayrollViewer, data: BonusInput, *, today: date
) -> HrBonus:
    """Premia ręczna: Płace przyznają od razu, przełożony tylko proponuje."""

    if data.recipient_user_id == viewer.user_id:
        raise PayrollForbidden("Premii nie przyznajesz sobie.")
    if not viewer.manages_bonuses_of(data.recipient_user_id):
        raise PayrollForbidden(
            "Premię ręczną przyznają Płace albo przełożony swojemu człowiekowi."
        )
    profile = await db.scalar(
        select(EmployeeProfile.id).where(
            EmployeeProfile.user_id == data.recipient_user_id
        )
    )
    if profile is None:
        raise PayrollNotFound("Ta osoba nie ma kartoteki pracownika.")
    validate_manual_period(data.period_year, data.period_month, today)
    await assert_open(db, data.period_year, data.period_month)
    await _assert_contract_exists(db, data.contract_id)
    assign = viewer.payroll
    bonus = HrBonus(
        recipient_user_id=data.recipient_user_id,
        proposed_by=viewer.user_id,
        amount=clean_amount(data.amount),
        currency=clean_currency(data.currency),
        category=clean_category(data.category),
        period_year=data.period_year,
        period_month=data.period_month,
        status="assigned" if assign else "proposed",
        source="manual",
        contract_id=data.contract_id,
        description=clean_description(data.description),
        assigned_by=viewer.user_id if assign else None,
        assigned_at=local_now() if assign else None,
    )
    db.add(bonus)
    await db.flush()
    if not assign:
        # Dzwonek osobie dopiero przy zatwierdzeniu Płac (``approve_bonus``).
        _audit(db, bonus, actor_id=viewer.user_id, action="bonus_proposed")
        return bonus
    _audit(db, bonus, actor_id=viewer.user_id, action="bonus_assigned")
    await _notify(
        db,
        bonus,
        event="new",
    )
    return bonus


async def update_bonus(
    db: AsyncSession,
    viewer: PayrollViewer,
    bonus_id: int,
    changes: dict[str, Any],
    *,
    today: date,
) -> HrBonus:
    bonus = await _locked_bonus(db, bonus_id)
    _require_scope(viewer, bonus)
    if bonus.recipient_user_id == viewer.user_id:
        raise PayrollForbidden("Własnej premii nie zmieniasz.")
    if not viewer.payroll and bonus.proposed_by != viewer.user_id:
        raise PayrollForbidden("Przełożony zmienia tylko premie, które sam przyznał.")
    if bonus.status == "cancelled":
        raise PayrollConflict("Ta premia jest anulowana.")
    # Od 19.10.2026 premia przełożonego to propozycja dla Płac: po zatwierdzeniu
    # kwotę, okres i walutę zmieniają już tylko Płace — inaczej przełożony
    # podniósłby zatwierdzoną kwotę bez ponownej decyzji (audyt 21.10.2026).
    if not viewer.payroll and bonus.status != "proposed":
        raise PayrollForbidden("Przyznaną premię zmieniają Płace.")
    await assert_open(db, bonus.period_year, bonus.period_month)

    before = {
        "amount": str(bonus.amount),
        "currency": bonus.currency,
        "period": f"{bonus.period_year}-{bonus.period_month:02d}",
        "recipient_user_id": bonus.recipient_user_id,
    }
    previous_recipient: Optional[int] = None
    if "recipient_user_id" in changes:
        previous_recipient = await _change_recipient(
            db,
            viewer,
            bonus,
            changes["recipient_user_id"],
            changes.get("change_reason"),
        )
    if "contract_id" in changes and changes["contract_id"] != bonus.contract_id:
        if is_automated(bonus):
            raise PayrollError("Premia automatu należy do swojego kontraktu.")
        if not viewer.payroll:
            raise PayrollForbidden("Placement w premii zmieniają Płace.")
        await _assert_contract_exists(db, changes["contract_id"])
        bonus.contract_id = changes["contract_id"]
    year = changes.get("period_year", bonus.period_year)
    month = changes.get("period_month", bonus.period_month)
    if (year, month) != (bonus.period_year, bonus.period_month):
        validate_period(year, month)
        if not viewer.payroll:
            validate_manual_period(year, month, today)
        await assert_open(db, year, month)
        bonus.period_year, bonus.period_month = year, month
        if is_automated(bonus):
            bonus.rule_snapshot = {**(bonus.rule_snapshot or {}), "edited_period": True}
    if "amount" in changes:
        amount = clean_amount(changes["amount"])
        if amount != bonus.amount and is_automated(bonus):
            bonus.rule_snapshot = {**(bonus.rule_snapshot or {}), "edited_amount": True}
        bonus.amount = amount
    if "currency" in changes:
        bonus.currency = clean_currency(changes["currency"])
    if "category" in changes:
        bonus.category = clean_category(changes["category"])
    if "description" in changes:
        bonus.description = clean_description(changes["description"])
    await db.flush()
    _audit(db, bonus, actor_id=viewer.user_id, action="bonus_changed", before=before)
    if bonus.status == "assigned" and previous_recipient is not None:
        # Dzwonki bez kwoty: poprzednia osoba traci premię, nowa ją dostaje.
        current = bonus.recipient_user_id
        bonus.recipient_user_id = previous_recipient
        await _notify(db, bonus, event="cancelled")
        bonus.recipient_user_id = current
        await _notify(db, bonus, event="new")
        return bonus
    if bonus.status == "assigned":
        await _notify(
            db,
            bonus,
            event="changed",
        )
    return bonus


async def approve_bonus(
    db: AsyncSession, viewer: PayrollViewer, bonus_id: int, *, today: date
) -> HrBonus:
    bonus = await _locked_bonus(db, bonus_id)
    _require_scope(viewer, bonus)
    refusal = approval_refusal(viewer, bonus)
    if refusal is not None:
        raise PayrollForbidden(refusal)
    if bonus.status == "cancelled" and bonus.cancel_reason in AUTO_CANCEL_REASONS:
        raise PayrollConflict(
            "Propozycja nieaktualna — kontrakt skończył się przed terminem premii "
            "albo zmieniły się jej warunki."
        )
    if bonus.status != "proposed":
        raise PayrollConflict("Ta premia nie czeka na zatwierdzenie.")
    # Płace mogą zatwierdzić wcześniej (decyzja Artura 30.10.2026): wypłata i tak
    # wypada w miesiącu premii, a brak zamówienia wychodzi przy jego zamknięciu.
    if (
        not viewer.payroll
        and bonus.eligible_on is not None
        and bonus.eligible_on > today
    ):
        raise PayrollConflict(
            f"Premia liczy się do {bonus.eligible_on:%d.%m.%Y} — "
            "zatwierdzisz ją od tego dnia."
        )
    await assert_open(db, bonus.period_year, bonus.period_month)
    bonus.status = "assigned"
    bonus.assigned_by = viewer.user_id
    bonus.assigned_at = local_now()
    await db.flush()
    _audit(db, bonus, actor_id=viewer.user_id, action="bonus_approved")
    await _notify(
        db,
        bonus,
        event="new",
    )
    return bonus


async def cancel_bonus(
    db: AsyncSession, viewer: PayrollViewer, bonus_id: int, *, note: Optional[str]
) -> HrBonus:
    bonus = await _locked_bonus(db, bonus_id)
    _require_scope(viewer, bonus)
    if bonus.recipient_user_id == viewer.user_id:
        raise PayrollForbidden("Własnej premii nie anulujesz.")
    own = bonus.proposed_by == viewer.user_id
    proposal_for_report = (
        bonus.status == "proposed"
        and is_automated(bonus)
        and viewer.manages_bonuses_of(bonus.recipient_user_id)
    )
    if not (viewer.payroll or own or proposal_for_report):
        raise PayrollForbidden(
            "Przełożony anuluje tylko premie, które sam przyznał, "
            "i propozycje automatów dla swoich ludzi."
        )
    if bonus.status == "cancelled":
        raise PayrollConflict("Ta premia jest już anulowana.")
    await assert_open(db, bonus.period_year, bonus.period_month)
    was_assigned = bonus.status == "assigned"
    bonus.status = "cancelled"
    bonus.cancelled_by = viewer.user_id
    bonus.cancelled_at = local_now()
    bonus.cancel_reason = "manual"
    bonus.cancel_note = clean_description(note)
    await db.flush()
    _audit(db, bonus, actor_id=viewer.user_id, action="bonus_cancelled")
    if was_assigned:
        await _notify(
            db,
            bonus,
            event="cancelled",
        )
    return bonus


async def paid_flags(
    db: AsyncSession, bonuses: list[HrBonus]
) -> Optional[dict[int, bool]]:
    """Premia wypłacona = rozliczenie jej miesiąca opłacone (R11) — i przyznana
    przed zapłatą (premia dopisana po ponownym otwarciu w opłaconej kwocie nie była).

    ``None`` — moduł rozliczeń wyłączony: wołający zostaje przy starej regule
    („miesiąc zamknięty w płacach = rozliczona”).
    """

    modules = await hr_modules.load_modules(db)
    if not modules.get(hr_modules.HrModule.settlements):
        return None
    # Miesiąc sprzed rozliczeń w NEXUSIE: stara reguła (miesiąc zamknięty).
    from app.services.hr.settlements import load_settlements_since  # cykl importów

    since = await load_settlements_since(db)
    archive = {
        bonus.id
        for bonus in bonuses
        if not settled_in_nexus(bonus.period_year, bonus.period_month, since)
    }
    closed = (
        await payroll_periods.closed_months(
            db,
            sorted(
                {
                    (bonus.period_year, bonus.period_month)
                    for bonus in bonuses
                    if bonus.id in archive
                }
            ),
        )
        if archive
        else set()
    )
    assigned = [bonus for bonus in bonuses if bonus.status == "assigned"]
    if not assigned:
        return {bonus.id: False for bonus in bonuses}
    rows = await db.execute(
        select(
            PayrollSettlement.user_id,
            PayrollSettlement.currency,
            PayrollPeriod.year,
            PayrollPeriod.month,
            PayrollSettlement.paid_at,
        )
        .join(PayrollPeriod, PayrollPeriod.id == PayrollSettlement.period_id)
        .where(
            PayrollSettlement.status == "paid",
            PayrollSettlement.user_id.in_(
                sorted({bonus.recipient_user_id for bonus in assigned})
            ),
        )
    )
    paid = {
        (int(user_id), str(currency), int(year), int(month)): paid_at
        for user_id, currency, year, month, paid_at in rows.all()
    }

    def covered(bonus: HrBonus) -> bool:
        # Premia przyznana po zapłacie (miesiąc otwarty ponownie) nie była
        # w opłaconej kwocie — nie jest wypłacona (audyt 19.10.2026).
        key = (
            bonus.recipient_user_id,
            bonus.currency,
            bonus.period_year,
            bonus.period_month,
        )
        if key not in paid:
            return False
        paid_at = paid[key]
        return (
            paid_at is None or bonus.assigned_at is None or bonus.assigned_at <= paid_at
        )

    return {
        bonus.id: bonus.status == "assigned"
        and (
            (bonus.period_year, bonus.period_month) in closed
            if bonus.id in archive
            else covered(bonus)
        )
        for bonus in bonuses
    }


async def list_bonuses(
    db: AsyncSession,
    viewer: PayrollViewer,
    *,
    year: Optional[int] = None,
    month: Optional[int] = None,
    status: Optional[str] = None,
    user_id: Optional[int] = None,
    limit: int = 500,
) -> list[HrBonus]:
    query = select(HrBonus)
    if year is not None:
        query = query.where(HrBonus.period_year == year)
    if month is not None:
        query = query.where(HrBonus.period_month == month)
    if status is not None:
        query = query.where(HrBonus.status == status)
    if user_id is not None:
        query = query.where(HrBonus.recipient_user_id == user_id)
    if not viewer.payroll:
        visible = sorted({viewer.user_id, *viewer.report_ids})
        query = query.where(HrBonus.recipient_user_id.in_(visible))
    query = query.order_by(
        HrBonus.period_year.desc(), HrBonus.period_month.desc(), HrBonus.id.desc()
    ).limit(limit)
    return list(await db.scalars(query))


__all__ = [
    "AUTO_CANCEL_REASONS",
    "BonusInput",
    "CATEGORY_LABELS",
    "MANUAL_PROPOSAL_OWN",
    "MANUAL_PROPOSAL_PAYROLL_ONLY",
    "approval_refusal",
    "approve_bonus",
    "bonus_payload",
    "can_approve",
    "cancel_bonus",
    "create_manual",
    "list_bonuses",
    "names_for",
    "paid_flags",
    "update_bonus",
    "validate_manual_period",
]
