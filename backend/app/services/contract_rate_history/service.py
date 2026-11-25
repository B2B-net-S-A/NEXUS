"""Historia stawek z faktur KSeF: podpowiedzi, wpis, odrzucenie i cofnięcie (0781).

* ``run`` — przebieg pętli: reguła dla wszystkich kontraktów z fakturami,
  podpowiedzi w ``contract_rate_history_findings`` (``refresh``), potem wpis
  automatyczny podpowiedzi ``automatic`` (flaga ``CONTRACT_RATE_HISTORY_AUTO_APPLY``).
* ``apply`` — kroki do harmonogramu stawki klienta / kosztowej, bez aneksu
  (decyzja Artura 25.11.2026: faktury za te miesiące są już wystawione, aneksu
  nie ma na papierze). ``user=None`` = automat: tylko podpowiedź bez powodów
  „do sprawdzenia”, czyli taka, która nie zmienia dzisiejszej stawki.
  Człowiek może wpisać też krok zmieniający dzisiejszą stawkę kosztową
  (stawka kontraktu i koszt trwających zamówień idą za nią); dzisiejszą stawkę
  klienta prowadzi zamówienie, więc taki krok odsyłamy do aneksu.
* ``undo_auto`` — „Cofnij” wpisu automatycznego przez ``UNDO_DAYS`` dni:
  usuwa jego kroki; podpowiedź wraca na kartę i automat już jej nie rusza.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional, Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.activity import Activity
from app.models.contract import Contract
from app.models.contract_candidate_rate import ContractCandidateRate
from app.models.contract_client_rate import ContractClientRate
from app.models.contract_rate_history_finding import ContractRateHistoryFinding
from app.models.user import User
from app.services.contract_rate_history import collect, infer

logger = logging.getLogger(__name__)

UNDO_DAYS = 7
FIRST_MONTH = "2026-01"
OPEN, AUTO, APPLIED, DISMISSED, UNDONE, RESOLVED = (
    "open",
    "auto_applied",
    "applied",
    "dismissed",
    "undone",
    "resolved",
)
#: Stan, w którym podpowiedź jest na karcie do decyzji człowieka.
FOR_HUMAN = (OPEN, UNDONE)
MAX_EVIDENCE_IN_NOTE = 3


class RateHistoryError(Exception):
    """Odmowa z komunikatem dla człowieka (trasa zamienia ją na 409)."""


def months_window(today: date) -> tuple[str, str]:
    """Od stycznia 2026 (KSeF w NEXUSIE) do ostatniego pełnego miesiąca."""

    return FIRST_MONTH, collect.shift(collect.month_key(today), -1)


def step_dict(step: infer.ProposedStep) -> dict[str, Any]:
    return {
        "leg": step.leg,
        "from": step.effective_from.isoformat(),
        "rate": str(step.rate),
        "nexus_rate": str(step.nexus_rate) if step.nexus_rate is not None else None,
        "months": list(step.months),
        "evidence": list(step.evidence),
        "reasons": list(step.reasons),
        "impact": str(step.impact),
        "baseline": step.baseline,
    }


def signature(steps: Sequence[dict[str, Any]]) -> str:
    key = [(s["leg"], s["from"], s["rate"]) for s in steps]
    return hashlib.sha256(json.dumps(key).encode()).hexdigest()


async def compute(
    db: AsyncSession, today: date, contract_ids: Optional[set[int]] = None
) -> dict[int, infer.ContractResult]:
    first, last = months_window(today)
    inputs = await collect.load_inputs(
        db, first_month=first, last_month=last, contract_ids=contract_ids
    )
    return {i.contract_id: infer.infer(i, today) for i in inputs}


async def refresh(
    db: AsyncSession, results: dict[int, infer.ContractResult], *, full: bool = True
) -> list[ContractRateHistoryFinding]:
    """Zapisz podpowiedzi przebiegu (bez commita); zwraca wiersze z krokami.

    Ta sama propozycja (``signature``) zostaje w swoim stanie: odrzucona nie
    wraca, cofnięta czeka na człowieka. Nowa propozycja otwiera wiersz od nowa.
    Kontrakt, w którym różnica zniknęła (człowiek wpisał krok, nowsza faktura),
    przechodzi z „do decyzji” na ``resolved``.
    """

    stmt = select(ContractRateHistoryFinding)
    if not full:
        stmt = stmt.where(ContractRateHistoryFinding.contract_id.in_(results))
    rows = {r.contract_id: r for r in (await db.scalars(stmt)).all()}
    touched: list[ContractRateHistoryFinding] = []
    for contract_id, result in results.items():
        row = rows.get(contract_id)
        if not result.steps:
            if row is not None and row.status in FOR_HUMAN:
                row.status = RESOLVED
            continue
        steps = [step_dict(s) for s in result.steps]
        sig = signature(steps)
        if row is None:
            row = ContractRateHistoryFinding(contract_id=contract_id, status=OPEN)
            db.add(row)
        elif row.signature != sig:
            row.status = OPEN
            row.created_steps = None
            row.decided_by = None
            row.decided_at = None
        elif row.status == RESOLVED:
            row.status = OPEN
        row.category = result.category
        row.automatic = result.automatic
        row.steps = steps
        row.signature = sig
        touched.append(row)
    # Kontrakty bez obserwacji w tym przebiegu (np. zakończone przed oknem).
    for contract_id, row in rows.items():
        if contract_id not in results and row.status in FOR_HUMAN:
            row.status = RESOLVED
    await db.flush()
    return touched


async def _load_contract(db: AsyncSession, contract_id: int, *, lock: bool) -> Contract:
    stmt = (
        select(Contract)
        .where(Contract.id == contract_id)
        .options(
            selectinload(Contract.client_rate_schedule),
            selectinload(Contract.candidate_rate_schedule),
        )
    )
    if lock:
        stmt = stmt.with_for_update()
    contract = (await db.scalars(stmt)).one_or_none()
    if contract is None:
        raise RateHistoryError("Kontrakt nie istnieje.")
    return contract


def _note(step: infer.ProposedStep) -> str:
    if step.baseline:
        return infer.BASELINE_NOTE
    numbers = ", ".join(step.evidence[:MAX_EVIDENCE_IN_NOTE])
    more = len(step.evidence) - MAX_EVIDENCE_IN_NOTE
    suffix = f" i {more} innych" if more > 0 else ""
    return f"Z faktur KSeF: {numbers}{suffix}"[:500]


async def _write_steps(
    db: AsyncSession,
    contract: Contract,
    result: infer.ContractResult,
    *,
    user: Optional[User],
    today: date,
) -> list[dict[str, Any]]:
    created: list[tuple[str, Any]] = []
    for step in result.steps:
        if step.leg == infer.CLIENT:
            row: Any = ContractClientRate(
                contract_id=contract.id,
                rate=step.rate,
                effective_from=step.effective_from,
                note=_note(step),
                created_by=user.id if user else None,
            )
        else:
            row = ContractCandidateRate(
                contract_id=contract.id,
                rate=step.rate,
                effective_from=step.effective_from,
                note=_note(step),
                created_by=user.id if user else None,
            )
        db.add(row)
        created.append((step.leg, row))
    await db.flush()
    await db.refresh(contract, ["client_rate_schedule", "candidate_rate_schedule"])
    # Krok kosztowy zmieniający dzisiejszą stawkę (tylko decyzja człowieka):
    # kolumna kontraktu i koszt trwających zamówień idą za harmonogramem.
    new_cost = contract.effective_candidate_rate(today)
    if new_cost is not None and contract.rate_candidate != new_cost:
        from app.services.contract_order_sync import (  # noqa: PLC0415 — cykl importów
            resync_contract_safely,
        )

        contract.rate_candidate = new_cost
        await db.flush()
        await resync_contract_safely(db, contract)
    return [{"leg": leg, "id": row.id} for leg, row in created]


def _changes_today_client(result: infer.ContractResult) -> bool:
    return any(
        s.leg == infer.CLIENT and infer.REASON_TODAY in s.reasons for s in result.steps
    )


async def _apply_result(
    db: AsyncSession,
    contract: Contract,
    row: ContractRateHistoryFinding,
    result: infer.ContractResult,
    *,
    user: Optional[User],
    today: date,
) -> ContractRateHistoryFinding:
    created = await _write_steps(db, contract, result, user=user, today=today)
    row.status = AUTO if user is None else APPLIED
    row.created_steps = created
    row.steps = [step_dict(s) for s in result.steps]
    row.signature = signature(row.steps)
    row.category = result.category
    row.automatic = result.automatic
    row.decided_by = user.id if user else None
    row.decided_at = datetime.now(timezone.utc)
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract.id,
            action="rate_history_ksef_applied",
            user_id=user.id if user else None,
            details={
                "automatic": user is None,
                "steps": [
                    {"leg": s["leg"], "from": s["from"], "rate": s["rate"]}
                    for s in row.steps
                ],
            },
        )
    )
    await db.flush()
    return row


async def apply(
    db: AsyncSession, contract_id: int, *, user: Optional[User], today: date
) -> ContractRateHistoryFinding:
    """Wpisz kroki z faktur (bez commita). Różnicę liczymy od nowa po blokadzie."""

    contract = await _load_contract(db, contract_id, lock=True)
    row = await db.scalar(
        select(ContractRateHistoryFinding).where(
            ContractRateHistoryFinding.contract_id == contract_id
        )
    )
    if row is None or row.status not in FOR_HUMAN:
        raise RateHistoryError("Ta podpowiedź jest już rozstrzygnięta.")
    result = (await compute(db, today, {contract_id})).get(contract_id)
    if result is None or not result.steps:
        row.status = RESOLVED
        await db.flush()
        raise RateHistoryError("Stawka w kontrakcie zgadza się już z fakturami.")
    if user is None and (not result.automatic or row.status != OPEN):
        raise RateHistoryError("Ta różnica wymaga decyzji człowieka.")
    if _changes_today_client(result):
        raise RateHistoryError(
            "Dzisiejszą stawkę klienta prowadzi zamówienie — zmień ją aneksem "
            "„Zmiana stawki” albo w zamówieniu; historię wpiszesz po tej zmianie."
        )
    return await _apply_result(db, contract, row, result, user=user, today=today)


async def dismiss(
    db: AsyncSession, contract_id: int, *, user: User
) -> ContractRateHistoryFinding:
    row = await db.scalar(
        select(ContractRateHistoryFinding).where(
            ContractRateHistoryFinding.contract_id == contract_id
        )
    )
    if row is None or row.status not in FOR_HUMAN:
        raise RateHistoryError("Ta podpowiedź jest już rozstrzygnięta.")
    row.status = DISMISSED
    row.decided_by = user.id
    row.decided_at = datetime.now(timezone.utc)
    await db.flush()
    return row


def undo_deadline(row: ContractRateHistoryFinding) -> Optional[datetime]:
    if row.status != AUTO or row.decided_at is None:
        return None
    return row.decided_at + timedelta(days=UNDO_DAYS)


async def undo_auto(
    db: AsyncSession, contract_id: int, *, user: User
) -> ContractRateHistoryFinding:
    await _load_contract(db, contract_id, lock=True)
    row = await db.scalar(
        select(ContractRateHistoryFinding).where(
            ContractRateHistoryFinding.contract_id == contract_id
        )
    )
    deadline = undo_deadline(row) if row is not None else None
    if row is None or deadline is None:
        raise RateHistoryError("Cofnąć można tylko wpis automatyczny NEXUSA.")
    if deadline < datetime.now(timezone.utc):
        raise RateHistoryError(
            f"„Cofnij” działało {UNDO_DAYS} dni — zmień stawkę ręcznie."
        )
    created = row.created_steps or []
    client_ids = [s["id"] for s in created if s["leg"] == infer.CLIENT]
    cost_ids = [s["id"] for s in created if s["leg"] == infer.COST]
    if client_ids:
        await db.execute(
            delete(ContractClientRate).where(
                ContractClientRate.id.in_(client_ids),
                ContractClientRate.contract_id == contract_id,
            )
        )
    if cost_ids:
        await db.execute(
            delete(ContractCandidateRate).where(
                ContractCandidateRate.id.in_(cost_ids),
                ContractCandidateRate.contract_id == contract_id,
            )
        )
    row.status = UNDONE
    row.decided_by = user.id
    row.decided_at = datetime.now(timezone.utc)
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract_id,
            action="rate_history_ksef_undone",
            user_id=user.id,
            details={"step_ids": created},
        )
    )
    await db.flush()
    return row


async def run(
    db: AsyncSession,
    today: date,
    *,
    auto_apply: bool,
    contract_ids: Optional[set[int]] = None,
) -> dict[str, int]:
    """Przebieg pętli: podpowiedzi i wpis automatyczny (commit per kontrakt).

    ``contract_ids`` zawęża przebieg (testy, ręczne przeliczenie jednego
    kontraktu) — wtedy wiersze innych kontraktów zostają nietknięte.
    """

    results = await compute(db, today, contract_ids)
    if contract_ids is not None:
        for missing in contract_ids - set(results):
            results[missing] = infer.ContractResult(missing, infer.OK)
    rows = await refresh(db, results, full=contract_ids is None)
    await db.commit()
    applied = 0
    if auto_apply:
        for row in rows:
            result = results[row.contract_id]
            if row.status != OPEN or not result.automatic:
                continue
            try:
                contract = await _load_contract(db, row.contract_id, lock=True)
                await _apply_result(db, contract, row, result, user=None, today=today)
                await db.commit()
                applied += 1
            except Exception:  # noqa: BLE001 — jeden kontrakt nie zatrzymuje reszty
                await db.rollback()
                logger.exception(
                    "rate history auto-apply failed for contract %s", row.contract_id
                )
    return {
        "contracts": len(results),
        "findings": len(rows),
        "auto_applied": applied,
    }


def view(row: ContractRateHistoryFinding, *, amounts: bool) -> dict[str, Any]:
    """Karta kontraktu; kwoty i skutek tylko pod bramką kwot kontraktu."""

    steps = []
    for s in row.steps or []:
        item = {
            "leg": s["leg"],
            "from": s["from"],
            "months": s.get("months") or [],
            "evidence": s.get("evidence") or [],
            "reasons": s.get("reasons") or [],
            "baseline": bool(s.get("baseline")),
        }
        if amounts:
            item["rate"] = float(Decimal(s["rate"]))
            item["nexus_rate"] = (
                float(Decimal(s["nexus_rate"])) if s.get("nexus_rate") else None
            )
            item["impact"] = float(Decimal(s.get("impact") or "0"))
        steps.append(item)
    reasons = list(
        dict.fromkeys(r for s in row.steps or [] for r in (s.get("reasons") or []))
    )
    deadline = undo_deadline(row)
    return {
        "id": row.id,
        "contract_id": row.contract_id,
        "category": row.category,
        "automatic": row.automatic,
        "status": row.status,
        "reasons": reasons,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "undo_until": deadline.isoformat() if deadline else None,
        "steps": steps,
    }
