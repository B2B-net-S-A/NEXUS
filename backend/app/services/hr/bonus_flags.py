"""Oznaczenia „Do sprawdzenia” przy premiach z placementów (tylko Płace).

Wiersz z oznaczeniem nie wchodzi domyślnie do „Zatwierdź zaznaczone”, ale nic nie
blokuje: decyzję podejmują Płace (decyzje Artura 30.10.2026). Brak zamówienia
po terminie to pozycja do sprawdzenia, a nie odmowa, bo część kontraktów nie ma
w NEXUSIE daty zamówienia.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract import Contract
from app.models.hr_payroll import HrBonus
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User

#: Marża powyżej tej kwoty wygląda na stawkę za dzień wpisaną jako godzinową.
SUSPICIOUS_MARGIN_PER_HOUR = Decimal("100")
#: Etapy, po których widać, kto prowadził proces po weryfikacji.
LATER_STAGES = (
    PipelineStage.client_interview,
    PipelineStage.interview,
    PipelineStage.acceptance,
)
MD_HOURS = Decimal(8)


def _margin(bonus: HrBonus) -> Optional[Decimal]:
    raw = (bonus.rule_snapshot or {}).get("margin_per_hour")
    try:
        return Decimal(str(raw)) if raw is not None else None
    except InvalidOperation:
        return None


def margin_flag(bonus: HrBonus) -> Optional[dict[str, str]]:
    margin = _margin(bonus)
    if margin is None or margin <= SUSPICIOUS_MARGIN_PER_HOUR:
        return None
    return {
        "code": "high_margin",
        "label": "Sprawdź stawkę",
        "detail": (
            f"Marża {margin} zł/h wygląda na stawkę za dzień. Jeśli to MD, podziel "
            f"stawkę przez {MD_HOURS} h i popraw kontrakt."
        ),
    }


async def bonus_flags(
    db: AsyncSession, bonuses: Sequence[HrBonus], *, today: date
) -> dict[int, list[dict[str, str]]]:
    """Oznaczenia per premia; hurtem, kilka zapytań niezależnie od liczby premii."""

    if not bonuses:
        return {}
    recipients = sorted({b.recipient_user_id for b in bonuses})
    active = dict(
        (
            await db.execute(
                select(User.id, User.is_active).where(User.id.in_(recipients))
            )
        ).all()
    )
    contract_ids = sorted({b.contract_id for b in bonuses if b.contract_id})
    contracts = (
        {
            c.id: c
            for c in await db.scalars(
                select(Contract).where(Contract.id.in_(contract_ids))
            )
        }
        if contract_ids
        else {}
    )
    later_owner = await _later_owners(db, list(contracts.values()))
    twins = await _second_hires(db, list(contracts.values()))
    found: dict[int, list[dict[str, str]]] = {}
    for bonus in bonuses:
        flags: list[dict[str, str]] = []
        if not active.get(bonus.recipient_user_id, True):
            flags.append(
                {
                    "code": "inactive",
                    "label": "Konto nieaktywne",
                    "detail": "Ta osoba nie ma aktywnego konta. Usuń premię albo przepisz ją na inną osobę.",
                }
            )
        contract = contracts.get(bonus.contract_id) if bonus.contract_id else None
        snapshot = bonus.rule_snapshot or {}
        if contract is not None and bonus.source == "contract_placement":
            flag = margin_flag(bonus)
            if flag:
                flags.append(flag)
            if (
                bonus.eligible_on is not None
                and bonus.eligible_on <= today
                and contract.client_order_start_date is None
            ):
                flags.append(
                    {
                        "code": "no_order",
                        "label": "Brak zamówienia",
                        "detail": "Termin minął, a kontrakt nie ma daty zamówienia. Sprawdź, czy konsultant wystartował.",
                    }
                )
            owner = later_owner.get(contract.id)
            if (
                snapshot.get("role") == "recruiter"
                and not snapshot.get("edited_recipient")
                and owner is not None
                and owner[0] != bonus.recipient_user_id
            ):
                flags.append(
                    {
                        "code": "owner",
                        "label": "Sprawdź osobę",
                        "detail": f"Dalsze etapy prowadziła osoba: {owner[1]}.",
                    }
                )
            if contract.id in twins and snapshot.get("role") == "recruiter":
                flags.append(
                    {
                        "code": "twin",
                        "label": "Druga rekrutacja",
                        "detail": "Ta osoba jest zatrudniona też w innej rekrutacji tego klienta. Sprawdź, kto ją domknął.",
                    }
                )
            if contract.is_replacement:
                flags.append(
                    {
                        "code": "replacement",
                        "label": "Replacement",
                        "detail": "Zastępstwo: sprawdź gwarancję i osobę, której premia się należy.",
                    }
                )
            if contract.fte is not None and contract.fte < 1:
                flags.append(
                    {
                        "code": "part_time",
                        "label": f"{contract.fte} FTE",
                        "detail": "Niepełny etat: przepracowanie progu godzin trwa dłużej niż termin.",
                    }
                )
        if flags:
            found[bonus.id] = flags
    return found


async def _later_owners(
    db: AsyncSession, contracts: list[Contract]
) -> dict[int, tuple[int, str]]:
    """Kontrakt → ostatnia osoba, która prowadziła kandydata po weryfikacji."""

    pairs = {
        (c.candidate_id, c.job_id): c.id
        for c in contracts
        if c.candidate_id is not None and c.job_id is not None
    }
    if not pairs:
        return {}
    rows = await db.execute(
        select(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.moved_by,
            User.name,
        )
        .join(User, User.id == CandidateStage.moved_by)
        .where(
            CandidateStage.stage.in_(LATER_STAGES),
            CandidateStage.candidate_id.in_({p[0] for p in pairs}),
            CandidateStage.job_id.in_({p[1] for p in pairs}),
        )
        .order_by(CandidateStage.moved_at, CandidateStage.id)
    )
    found: dict[int, tuple[int, str]] = {}
    for candidate_id, job_id, moved_by, name in rows.all():
        contract_id = pairs.get((candidate_id, job_id))
        if contract_id is not None:
            found[contract_id] = (moved_by, name)
    return found


async def _second_hires(db: AsyncSession, contracts: list[Contract]) -> set[int]:
    """Kontrakty, których kandydat ma etap „Zatrudniony” w innej rekrutacji klienta."""

    wanted = [c for c in contracts if c.candidate_id is not None and c.job_id]
    if not wanted:
        return set()
    rows = await db.execute(
        select(CandidateStage.candidate_id, CandidateStage.job_id, Job.client_id)
        .join(Job, Job.id == CandidateStage.job_id)
        .where(
            CandidateStage.stage == PipelineStage.hired,
            CandidateStage.candidate_id.in_({c.candidate_id for c in wanted}),
        )
    )
    hires = rows.all()
    return {
        contract.id
        for contract in wanted
        if any(
            candidate == contract.candidate_id
            and job != contract.job_id
            and client == contract.client_id
            for candidate, job, client in hires
        )
    }


def stage_facts(contract: Contract, *, signed: bool, today: date) -> dict[str, Any]:
    """Etapy premii dla osoby: podpis, kontrakt, zamówienie, start (bez kwot)."""

    start = contract.start_date
    return {
        "signed": signed,
        "contract_active": str(getattr(contract.status, "value", contract.status))
        in ("active", "ending", "ended"),
        "order": contract.client_order_start_date is not None,
        "started": start is not None and start <= today,
        "start_date": start.isoformat() if start else None,
    }


__all__ = ["SUSPICIOUS_MARGIN_PER_HOUR", "bonus_flags", "margin_flag", "stage_facts"]
