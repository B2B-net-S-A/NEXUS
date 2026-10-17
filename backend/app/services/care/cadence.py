"""Rytm kontaktu z konsultantem (etap 3, O7–O9, 17.10.2026) — zapis, odczyt, sygnały.

* **Kto zmienia rytm** (O8): opiekun kontraktu, Delivery Lead klienta (jego
  portfel), head back office (``app_settings['hr_divisions']``) i admin.
  Bez akceptacji; zmianę widać w historii rytmu i na osi konsultanta.
* **Zmiana** to okres od dziś z powodem z listy, notatką (≤ 500 znaków —
  zostaje w okresie, do śladu HR idą same kody) i opcjonalną datą „do kiedy”.
  Zapis od razu przelicza plan kontraktu (``plan.ensure_plan``): przyszłe
  rozmowy starego rytmu znikają, kamienie zostają.
* **Sygnały** (O9) tylko podpowiadają: ostatnia opinia menedżera poniżej 3
  (widzą ją wyłącznie role z D11 — trasa przekazuje ``include_feedback``),
  koniec zamówienia za mniej niż 45 dni, „chce zmiany projektu” i „ryzyko
  odejścia” z rozmów („Do przepięcia”), zaległa rozmowa. Długiej
  nieobecności konsultanta NEXUS nie zna (konsultant nie ma kartoteki).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract_care import CareCadencePeriod
from app.models.user import User, UserRole
from app.services.access_scope import resolve_delivery_lead_assigned_client_ids
from app.services.care import access as care_access
from app.services.care import client_feedback, front_office
from app.services.care import plan as care_plan
from app.services.care.access import CareContract
from app.services.care.cadence_rules import (
    CadencePeriod,
    Effective,
    PeriodLike,
    add_months,
    level_on,
    suggested_level,
    transitions,
)
from app.services.care.week import client_managers
from app.services.hr import audit, structure

LEVEL_LABELS: dict[str, str] = {
    "biweekly": "co 2 tygodnie",
    "monthly": "co miesiąc",
    "quarterly": "co kwartał",
    "milestones": "tylko kamienie",
    "paused": "wstrzymany",
}
REASON_LABELS: dict[str, str] = {
    "new_at_client": "nowy u klienta",
    "weak_feedback": "słaba opinia menedżera",
    "order_end": "koniec zamówienia",
    "wants_change": "chce zmiany projektu",
    "stable": "stabilnie",
    "person_request": "prośba osoby",
    "long_absence": "długa nieobecność",
    "other": "inny powód",
    "imported": "z Compassa",
}

#: Opinia menedżera poniżej tej średniej to sygnał (O9).
WEAK_FEEDBACK_BELOW = 3.0
#: Koniec zamówienia bliżej niż tyle dni to sygnał (O9).
ORDER_END_SIGNAL_DAYS = 45
UPCOMING_COUNT = 5

CHANGE_DENIED = (
    "Rytm zmienia opiekun kontraktu, Delivery Lead klienta, head back office "
    "albo administrator."
)
ALREADY_SET = "Ten rytm już obowiązuje."
NOT_LIVE = "Rytm ustawia się przy trwającym kontrakcie."
NO_START = "Kontrakt nie ma daty startu — rytm liczy się od niej."
UNTIL_NOT_FUTURE = "Data „do kiedy” musi być późniejsza niż dziś."

#: Id okresu z podglądu — większe od każdego zapisanego, więc wygrywa remis dnia.
_PREVIEW_ID = 2**31 - 1


# ── Kto może zmienić rytm ───────────────────────────────────────────────────


@dataclass(frozen=True)
class Changer:
    user_id: int
    is_admin: bool
    is_head: bool
    dl_clients: frozenset[int]

    def can_change(self, contract: CareContract, owner_id: Optional[int]) -> bool:
        return (
            self.is_admin
            or self.is_head
            or (owner_id is not None and owner_id == self.user_id)
            or contract.client_id in self.dl_clients
        )


async def is_back_office_head(db: AsyncSession, user: User) -> bool:
    heads = await structure.load_division_heads(db)
    return heads.get("back_office") == user.id


async def changer(db: AsyncSession, user: User) -> Changer:
    dl_clients: frozenset[int] = frozenset()
    if user.has_role(UserRole.delivery_lead):
        dl_clients = await resolve_delivery_lead_assigned_client_ids(user, db) or (
            frozenset()
        )
    return Changer(
        user_id=user.id,
        is_admin=user.has_role(UserRole.admin),
        is_head=await is_back_office_head(db, user),
        dl_clients=dl_clients,
    )


# ── Odczyt ──────────────────────────────────────────────────────────────────


def _start(contract: CareContract) -> date:
    # Kontrakt bez startu nie ma planu; rytm liczy się wtedy jak po programie.
    return contract.start_date or date.min


def returns_to(
    start: date, periods: Sequence[PeriodLike], current: Effective
) -> Optional[str]:
    """Rytm po dacie „do kiedy” (albo po programie pierwszych 90 dni)."""

    if current.until_on is None:
        return None
    return level_on(start, periods, current.until_on + timedelta(days=1)).level


def current_payload(
    contract: CareContract,
    periods: Sequence[PeriodLike],
    today: date,
    names: Mapping[int, str],
) -> dict[str, Any]:
    start = _start(contract)
    current = level_on(start, periods, today)
    period = current.period
    author = getattr(period, "created_by", None)
    return {
        "level": current.level,
        "source": current.source,
        "starts_on": period.starts_on if period is not None else contract.start_date,
        "until_on": current.until_on,
        "returns_to": returns_to(start, periods, current),
        "reason": getattr(period, "reason", None),
        "note": getattr(period, "note", None),
        "author": person_ref(author, names),
    }


def person_ref(
    user_id: Optional[int], names: Mapping[int, str]
) -> Optional[dict[str, Any]]:
    if user_id is None:
        return None
    return {"id": user_id, "name": names.get(user_id, "")}


def history_payload(
    contract: CareContract,
    periods: Sequence[CareCadencePeriod],
    today: date,
    names: Mapping[int, str],
) -> list[dict[str, Any]]:
    steps = transitions(_start(contract), periods)
    if contract.start_date is None:
        steps = [step for step in steps if step.kind in ("change", "return")]
    out = []
    for step in steps:
        period = step.period if step.kind == "change" else None
        out.append(
            {
                "on": step.on,
                "kind": step.kind,
                "level": step.level,
                "reason": getattr(period, "reason", None),
                "note": getattr(period, "note", None),
                "until_on": getattr(period, "until_on", None),
                "author": person_ref(getattr(period, "created_by", None), names),
                "future": step.on > today,
            }
        )
    return out


def upcoming_payload(
    contract: CareContract,
    periods: Sequence[PeriodLike],
    today: date,
    *,
    limit: int = UPCOMING_COUNT,
) -> list[dict[str, Any]]:
    if contract.start_date is None:
        return []
    slots = care_plan.slots_between(
        contract.start_date,
        contract.end_date,
        periods,
        today,
        today + timedelta(days=care_plan.LOOKAHEAD_DAYS),
    )
    return [
        {
            "due_on": slot.due_on,
            "kind": slot.kind,
            "label": care_plan.KIND_LABELS.get(slot.kind, slot.kind),
        }
        for slot in slots[:limit]
    ]


def next_month(today: date) -> tuple[date, date]:
    first = add_months(today.replace(day=1), 1)
    return first, add_months(first, 1) - timedelta(days=1)


def this_month(today: date) -> tuple[date, date]:
    first = today.replace(day=1)
    return first, add_months(first, 1) - timedelta(days=1)


def month_count(
    contract: CareContract, periods: Sequence[PeriodLike], month: tuple[date, date]
) -> int:
    return care_plan.conversations_between(
        contract.start_date, contract.end_date, periods, month[0], month[1]
    )


async def signals_for(
    db: AsyncSession,
    contracts: Sequence[CareContract],
    *,
    today: date,
    overdue_days: Mapping[int, int],
    include_feedback: bool,
) -> dict[int, list[dict[str, Any]]]:
    """Sygnały przy konsultancie (podpowiedź, bez zmiany rytmu)."""

    ids = [contract.id for contract in contracts]
    out: dict[int, list[dict[str, Any]]] = {cid: [] for cid in ids}
    if not ids:
        return out
    feedback = (
        await client_feedback.last_by_contract(db, ids) if include_feedback else {}
    )
    redeploy = await front_office.active_redeploy(db, ids)
    for contract in contracts:
        signals = out[contract.id]
        last = feedback.get(contract.id)
        if (
            last is not None
            and last.average is not None
            and last.average < WEAK_FEEDBACK_BELOW
        ):
            signals.append(
                {"kind": "weak_feedback", "average": last.average, "on": last.held_on}
            )
        end = contract.end_date
        if end is not None and 0 <= (end - today).days < ORDER_END_SIGNAL_DAYS:
            signals.append({"kind": "order_end", "days": (end - today).days, "on": end})
        reasons = {item.reason for item in redeploy.get(contract.id, ())}
        for reason in ("wants_change", "attrition_risk"):
            if reason in reasons:
                signals.append({"kind": reason})
        late = overdue_days.get(contract.id)
        if late:
            signals.append({"kind": "overdue", "days": late})
    return out


def suggestion(level: str, signals: Iterable[Mapping[str, Any]]) -> Optional[str]:
    return suggested_level(level, {signal["kind"] for signal in signals})


async def _overdue_days(
    db: AsyncSession, contract: CareContract, today: date
) -> dict[int, int]:
    items = (await care_plan.open_items(db, [contract.id]))[contract.id]
    latest = (await care_plan.latest_conversations(db, [contract.id])).get(contract.id)
    upcoming = care_plan.next_contact(items, latest, today)
    if upcoming is None or upcoming.due_on >= today:
        return {}
    return {contract.id: (today - upcoming.due_on).days}


@dataclass(frozen=True)
class Proposal:
    level: str
    until_on: Optional[date]


async def _owner_month(
    db: AsyncSession,
    contract: CareContract,
    owner_id: int,
    proposed: Sequence[PeriodLike],
    today: date,
) -> dict[str, Any]:
    """Rozmowy opiekuna w następnym miesiącu: teraz i po zmianie tego kontraktu."""

    live = await care_access.live_contracts(db)
    owners = await care_access.effective_owners(db, live)
    mine = [c for c in live if owners[c.id].user_id == owner_id]
    periods = await care_plan.periods_by_contract(db, [c.id for c in mine])
    month = next_month(today)
    before = sum(month_count(c, periods.get(c.id, ()), month) for c in mine)
    own = month_count(contract, periods.get(contract.id, ()), month)
    names = await care_access.user_names(db, [owner_id])
    return {
        "owner": person_ref(owner_id, names),
        "month": month[0],
        "before": before,
        "after": before - own + month_count(contract, proposed, month),
    }


async def cadence_payload(
    db: AsyncSession,
    contract: CareContract,
    *,
    user: User,
    today: date,
    include_feedback: bool,
    proposal: Optional[Proposal] = None,
) -> dict[str, Any]:
    """Okno „Rytm kontaktu”: obecny rytm, historia, najbliższe rozmowy, podgląd."""

    if (
        proposal is not None
        and proposal.until_on is not None
        and proposal.until_on <= today
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, UNTIL_NOT_FUTURE)
    periods = (await care_plan.periods_by_contract(db, [contract.id])).get(
        contract.id, []
    )
    owner = (await care_access.effective_owners(db, [contract]))[contract.id].user_id
    names = await care_access.user_names(
        db, [owner, *(period.created_by for period in periods)]
    )
    current = current_payload(contract, periods, today, names)
    signals = (
        await signals_for(
            db,
            [contract],
            today=today,
            overdue_days=await _overdue_days(db, contract, today),
            include_feedback=include_feedback,
        )
    )[contract.id]
    preview = None
    if proposal is not None:
        proposed = [
            *periods,
            CadencePeriod(_PREVIEW_ID, proposal.level, today, proposal.until_on),
        ]
        effective = level_on(_start(contract), proposed, today)
        preview = {
            "level": proposal.level,
            "until_on": proposal.until_on,
            "returns_to": returns_to(_start(contract), proposed, effective)
            if proposal.until_on is not None
            else None,
            "upcoming": upcoming_payload(contract, proposed, today),
            "owner_month": (
                await _owner_month(db, contract, owner, proposed, today)
                if owner is not None and contract.start_date is not None
                else None
            ),
        }
    manager = (await client_managers(db, [contract])).get(contract.id)
    who = await changer(db, user)
    return {
        "contract_id": contract.id,
        "candidate_name": contract.candidate_name,
        "client_name": contract.client_name,
        "start_date": contract.start_date,
        "end_date": contract.end_date,
        "is_live": contract.is_live,
        "owner": person_ref(owner, names),
        "manager": manager,
        "current": current,
        "history": history_payload(contract, periods, today, names),
        "upcoming": upcoming_payload(contract, periods, today),
        "signals": signals,
        "suggested_level": suggestion(current["level"], signals),
        "preview": preview,
        "can_edit": contract.is_live and who.can_change(contract, owner),
    }


async def contract_cadence(
    db: AsyncSession, contract: CareContract, *, user: User, today: date
) -> dict[str, Any]:
    """Rytm w zakładce „Opieka” kontraktu (bez historii i podglądu)."""

    periods = (await care_plan.periods_by_contract(db, [contract.id])).get(
        contract.id, []
    )
    owner = (await care_access.effective_owners(db, [contract]))[contract.id].user_id
    names = await care_access.user_names(db, [p.created_by for p in periods])
    who = await changer(db, user)
    return {
        **current_payload(contract, periods, today, names),
        "can_edit": contract.is_live and who.can_change(contract, owner),
    }


# ── Zapis ───────────────────────────────────────────────────────────────────


async def set_cadence(
    db: AsyncSession,
    contract: CareContract,
    *,
    user: User,
    level: str,
    reason: str,
    note: Optional[str],
    until_on: Optional[date],
    today: date,
) -> CareCadencePeriod:
    """Nowy okres rytmu od dziś (bez commita) i przeliczony plan kontraktu."""

    owner = (await care_access.effective_owners(db, [contract]))[contract.id].user_id
    if not (await changer(db, user)).can_change(contract, owner):
        raise HTTPException(status.HTTP_403_FORBIDDEN, CHANGE_DENIED)
    if not contract.is_live:
        raise HTTPException(status.HTTP_409_CONFLICT, NOT_LIVE)
    if contract.start_date is None:
        raise HTTPException(status.HTTP_409_CONFLICT, NO_START)
    if until_on is not None and until_on <= today:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, UNTIL_NOT_FUTURE)
    periods = (await care_plan.periods_by_contract(db, [contract.id])).get(
        contract.id, []
    )
    current = level_on(contract.start_date, periods, today)
    if level == current.level and until_on is None and current.until_on is None:
        raise HTTPException(status.HTTP_409_CONFLICT, ALREADY_SET)
    period = CareCadencePeriod(
        contract_id=contract.id,
        level=level,
        starts_on=today,
        until_on=until_on,
        reason=reason,
        note=" ".join((note or "").split()) or None,
        created_by=user.id,
    )
    db.add(period)
    await db.flush()
    audit.record(
        db,
        actor_user_id=user.id,
        subject_user_id=None,
        entity_type="contract",
        entity_id=contract.id,
        action="care.cadence_set",
        details={
            "period_id": period.id,
            "level": level,
            "previous_level": current.level,
            "reason": reason,
            "until_on": until_on.isoformat() if until_on else None,
        },
    )
    await care_plan.ensure_plan(
        db,
        contract.id,
        start=contract.start_date,
        end=contract.end_date,
        today=today,
    )
    return period
