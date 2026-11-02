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

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract import Contract
from app.models.hr_payroll import HrBonus
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User
from app.services.hr.bonus_rules import BonusRules, load_rules, money, rule_amount
from app.services.hr.placement_bonuses import ends_before_deadline

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


def _pln(value: Decimal) -> str:
    return f"{value:.2f}".replace(".", ",") + " zł"


def _role(bonus: HrBonus) -> str:
    return (bonus.source_key or "").rsplit(":", 1)[-1]


def amount_flag(bonus: HrBonus) -> Optional[dict[str, str]]:
    """Kwota z arkusza inna niż reguła. Podwójna z października jest celowa (30.10)."""

    snapshot = bonus.rule_snapshot or {}
    if not snapshot.get("settlement_import") or snapshot.get(
        "amount_edited_after_import"
    ):
        return None
    expected = rule_amount(snapshot, _role(bonus))
    if expected is None or bonus.amount in (expected, money(expected * 2)):
        return None
    note = snapshot.get("settlement_note")
    return {
        "code": "amount_rule",
        "label": f"Kwota inna niż reguła: {_pln(expected)}",
        "detail": f"Z arkusza: {_pln(bonus.amount)}. Z reguły: {_pln(expected)}."
        + (f" Uwaga z arkusza: {note}" if note else ""),
        "rule_amount": str(expected),
    }


def scope_flag(
    bonus: HrBonus, contract: Contract, rules: BonusRules
) -> Optional[dict[str, str]]:
    """Dodatkowa premia u klienta spoza listy reguły (np. z arkusza)."""

    if _role(bonus) != "dl_extra":
        return None
    mine = [r for r in rules.extra_dl if r.recipient_user_id == bonus.recipient_user_id]
    if not mine or any(rule.covers(contract.client_id) for rule in mine):
        return None
    return {
        "code": "extra_scope",
        "label": "Poza zakresem reguły",
        "detail": "Reguła dodatkowej premii DL nie obejmuje tego klienta. Sprawdź, czy premia się należy.",
    }


async def _double_dl(db: AsyncSession, contract_ids: list[int]) -> set[tuple[int, int]]:
    """(kontrakt, osoba) z premią DL i dodatkową premią DL naraz."""

    rows = await db.execute(
        select(HrBonus.contract_id, HrBonus.recipient_user_id).where(
            HrBonus.contract_id.in_(contract_ids),
            HrBonus.status != "cancelled",
            or_(
                HrBonus.source_key.like("contract:%:dl"),
                HrBonus.source_key.like("contract:%:dl_extra"),
            ),
        )
    )
    seen: dict[tuple[int, int], int] = {}
    for pair in map(tuple, rows.all()):
        seen[pair] = seen.get(pair, 0) + 1
    return {pair for pair, count in seen.items() if count > 1}


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
    double_dl = await _double_dl(db, contract_ids) if contract_ids else set()
    rules = await load_rules(db)
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
            for flag in (
                margin_flag(bonus),
                amount_flag(bonus),
                scope_flag(bonus, contract, rules),
            ):
                if flag:
                    flags.append(flag)
            if (contract.id, bonus.recipient_user_id) in double_dl:
                flags.append(
                    {
                        "code": "second_bonus",
                        "label": "Druga premia tej osoby za ten placement",
                        "detail": "Ta osoba ma premię DL i dodatkową premię DL za ten sam placement. Zostaw jedną.",
                    }
                )
            if (
                snapshot.get("settlement_import")
                and bonus.status == "proposed"
                and bonus.eligible_on is not None
                and ends_before_deadline(contract, bonus.eligible_on)
            ):
                flags.append(
                    {
                        "code": "contract_ended",
                        "label": "Kontrakt zakończony przed terminem",
                        "detail": "Premia jest z arkusza, więc automat jej nie anuluje. Sprawdź, czy się należy.",
                    }
                )
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
    active = str(getattr(contract.status, "value", contract.status)) in (
        "active",
        "ending",
        "ended",
    )
    return {
        # Kontrakt spoza Generatora nie ma znacznika podpisu, a działa: etap minął.
        "signed": signed or active,
        "contract_active": active,
        "order": contract.client_order_start_date is not None,
        "started": start is not None and start <= today,
        "start_date": start.isoformat() if start else None,
    }


__all__ = [
    "SUSPICIOUS_MARGIN_PER_HOUR",
    "amount_flag",
    "bonus_flags",
    "margin_flag",
    "scope_flag",
    "stage_facts",
]
