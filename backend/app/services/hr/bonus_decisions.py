"""Ikona premii w górnym pasku: co czeka na decyzję Płac.

Trzy grupy (decyzje Artura 30.10.2026): premie z podpisanych umów bez uwag, Liga
i wyścigi, pozycje do sprawdzenia. Wyścig miesięczny zostaje voucherem: potwierdzenie
to tylko ślad, kto go przekazał, bez przelewu. Etapy premii dla osoby i dzwonek
„można naliczyć” też są tutaj.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_now
from app.models.app_setting import AppSetting
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.competition_winner import CompetitionType, CompetitionWinner
from app.models.contract import Contract, ContractStatus
from app.models.hr_payroll import HrBonus
from app.models.hr_profile import EmployeeProfile
from app.models.notification import NotificationType
from app.models.user import User
from app.services.contract_rates import RATE_SCHEDULE_LOADS
from app.services.hr import audit, placement_bonuses
from app.services.hr.bonus_flags import stage_facts
from app.services.hr.bonus_rules import automation_floor_for, load_rules
from app.services.hr.employment_terms import terms
from app.services.hr.league_bonuses import TYPE_LABELS
from app.services.hr.notify import notify_each
from app.services.hr.payroll_access import PayrollViewer
from app.services.hr.payroll_errors import PayrollForbidden, PayrollNotFound

VOUCHER_SETTING = "hr_voucher_confirmations"
VOUCHER_TYPES = (
    CompetitionType.monthly_recommendations.value,
    CompetitionType.monthly_placements.value,
)
MISSING_RATES_LIMIT = 300
PLACEMENT_OPTIONS_DAYS = 200


def group_decisions(
    items: Iterable[dict[str, Any]], *, viewer_id: int
) -> dict[str, list[dict[str, Any]]]:
    """Propozycje na grupy paska; własnej premii nikt nie zatwierdza, więc jej nie ma."""

    groups: dict[str, list[dict[str, Any]]] = {"signed": [], "league": [], "check": []}
    for item in items:
        if item["recipient_user_id"] == viewer_id:
            continue
        if item.get("flags"):
            groups["check"].append(item)
        elif item["source"] == "league":
            groups["league"].append(item)
        else:
            groups["signed"].append(item)
    return groups


async def contracts_missing_rates(
    db: AsyncSession, *, today: date
) -> list[dict[str, Any]]:
    """Kontrakty z oknem automatu, którym nie da się policzyć marży.

    To nie są wiersze premii (kwota musi być dodatnia): premia powstanie sama po
    uzupełnieniu stawki.
    """

    rules = await load_rules(db)
    floor = automation_floor_for(rules, today)
    contracts = list(
        await db.scalars(
            select(Contract)
            .options(*RATE_SCHEDULE_LOADS)
            .where(
                Contract.start_date >= floor,
                Contract.status.in_(placement_bonuses.STARTED_STATUSES),
                Contract.returned_from_contract_id.is_(None),
            )
            .order_by(Contract.start_date, Contract.id)
            .limit(MISSING_RATES_LIMIT)
        )
    )
    missing: list[Contract] = []
    for contract in contracts:
        margin = await placement_bonuses.contract_margin(
            db, contract, contract.start_date
        )
        if margin.per_hour is None:
            missing.append(contract)
    if not missing:
        return []
    context = await placement_bonuses.load_context(db, missing)
    ids = {person for c in missing for person in context.people(c)[:2] if person}
    names = dict(
        (
            await db.execute(select(User.id, User.name).where(User.id.in_(ids or {0})))
        ).all()
    )
    result = []
    for contract in missing:
        dl_id, recruiter_id, _source = context.people(contract)
        candidate, client = context.names(contract)
        result.append(
            {
                "contract_id": contract.id,
                "candidate": candidate,
                "client": client,
                "start_date": contract.start_date.isoformat(),
                "recruiter_name": names.get(recruiter_id),
                "dl_name": names.get(dl_id),
            }
        )
    return result


async def placement_options(db: AsyncSession, *, today: date) -> list[dict[str, Any]]:
    contracts = list(
        await db.scalars(
            select(Contract)
            .where(
                Contract.start_date >= today - timedelta(days=PLACEMENT_OPTIONS_DAYS),
                Contract.status != ContractStatus.void,
            )
            .order_by(Contract.start_date.desc(), Contract.id.desc())
            .limit(MISSING_RATES_LIMIT)
        )
    )
    context = await placement_bonuses.load_context(db, contracts)
    return [
        {
            "contract_id": contract.id,
            "label": " · ".join(context.names(contract)),
            "start_date": contract.start_date.isoformat(),
        }
        for contract in contracts
    ]


async def _confirmations(db: AsyncSession, *, lock: bool = False) -> dict[str, Any]:
    query = select(AppSetting).where(AppSetting.key == VOUCHER_SETTING)
    if lock:
        query = query.with_for_update()
    row = await db.scalar(query)
    return dict(row.value) if row is not None and isinstance(row.value, dict) else {}


async def pending_vouchers(db: AsyncSession) -> list[dict[str, Any]]:
    """Zwycięzcy wyścigów miesięcznych bez potwierdzenia, od startu automatu."""

    rules = await load_rules(db)
    if rules.automation_since is None:
        return []
    since = rules.automation_since.strftime("%Y-%m")
    confirmed = await _confirmations(db)
    rows = await db.execute(
        select(CompetitionWinner, User.name)
        .join(User, User.id == CompetitionWinner.user_id)
        .where(
            CompetitionWinner.competition_type.in_(VOUCHER_TYPES),
            CompetitionWinner.period >= since,
        )
        .order_by(CompetitionWinner.period, CompetitionWinner.rank)
    )
    return [
        {
            "id": winner.id,
            "label": TYPE_LABELS.get(winner.competition_type, winner.competition_type),
            "period": winner.period,
            "rank": winner.rank,
            "name": name,
        }
        for winner, name in rows.all()
        if str(winner.id) not in confirmed
    ]


async def confirm_voucher(
    db: AsyncSession, viewer: PayrollViewer, winner_id: int
) -> dict[str, Any]:
    winner = await db.get(CompetitionWinner, winner_id)
    if winner is None or winner.competition_type not in VOUCHER_TYPES:
        raise PayrollNotFound("Nie ma takiego vouchera.")
    if winner.user_id == viewer.user_id:
        raise PayrollForbidden("Własnego vouchera nie potwierdzasz.")
    confirmed = await _confirmations(db, lock=True)
    confirmed[str(winner_id)] = {
        "by": viewer.user_id,
        "at": local_now().isoformat(),
    }
    row = await db.get(AppSetting, VOUCHER_SETTING)
    if row is None:
        db.add(AppSetting(key=VOUCHER_SETTING, value=confirmed))
    else:
        row.value = confirmed
    audit.record(
        db,
        actor_user_id=viewer.user_id,
        subject_user_id=winner.user_id,
        entity_type="competition_voucher",
        entity_id=winner.id,
        action="voucher_confirmed",
        sensitivity="payroll",
        details={"type": winner.competition_type, "period": winner.period},
    )
    await db.flush()
    return {"id": winner_id, "confirmed": True}


async def stages_for(
    db: AsyncSession, contract_ids: Iterable[int], *, today: date
) -> dict[int, dict[str, Any]]:
    """Etapy premii per kontrakt: podpis obu stron, kontrakt, zamówienie, start."""

    ids = sorted(set(contract_ids))
    if not ids:
        return {}
    signed = set(
        await db.scalars(
            select(B2BGeneratedContract.contract_id).where(
                B2BGeneratedContract.contract_id.in_(ids),
                B2BGeneratedContract.signature_status == "signed_both",
            )
        )
    )
    return {
        contract.id: stage_facts(contract, signed=contract.id in signed, today=today)
        for contract in await db.scalars(select(Contract).where(Contract.id.in_(ids)))
    }


async def notify_ready(db: AsyncSession, *, today: date) -> int:
    """Dzwonek „można naliczyć”: raz, po terminie, przy zamówieniu, bez kwoty."""

    rows = await db.execute(
        select(HrBonus, EmployeeProfile.employment_type)
        .join(Contract, Contract.id == HrBonus.contract_id)
        .outerjoin(
            EmployeeProfile, EmployeeProfile.user_id == HrBonus.recipient_user_id
        )
        .where(
            HrBonus.source == placement_bonuses.SOURCE,
            HrBonus.status == "proposed",
            HrBonus.eligible_on <= today,
            Contract.client_order_start_date.is_not(None),
            func.coalesce(
                HrBonus.rule_snapshot["ready_notified"].as_boolean(), False
            ).is_(False),
        )
        .with_for_update(of=HrBonus, skip_locked=True)
    )
    sent = 0
    for bonus, form in rows.all():
        bonus.rule_snapshot = {**(bonus.rule_snapshot or {}), "ready_notified": True}
        await notify_each(
            db,
            [bonus.recipient_user_id],
            title=terms(form)["bonus_ready_title"],
            message=(bonus.description or "Placement")
            + ". Decyzja jest teraz po stronie Płac.",
            ntype=NotificationType.hr_bonus_assigned,
            link="/my-time?tab=bonuses",
            related_entity_type="hr_bonus",
            related_entity_id=bonus.id,
        )
        sent += 1
    await db.flush()
    return sent


__all__ = [
    "confirm_voucher",
    "contracts_missing_rates",
    "group_decisions",
    "notify_ready",
    "pending_vouchers",
    "placement_options",
    "stages_for",
]
