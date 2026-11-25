"""Stawka z faktur KSeF na liście kontraktów (0782): filtr i pole wiersza."""

from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract_rate_history_finding import ContractRateHistoryFinding
from app.services.contract_rate_history.service import FOR_HUMAN


def open_rate_history_contracts():
    """Podzapytanie: kontrakty z podpowiedzią stawki z faktur do decyzji."""

    return select(ContractRateHistoryFinding.contract_id).where(
        ContractRateHistoryFinding.status.in_(FOR_HUMAN)
    )


async def attach_rate_history_changes(db: AsyncSession, items: Sequence[Any]) -> None:
    """Wpisz w wiersze listy pierwszy krok podpowiedzi (przed redakcją kwot)."""

    ids = [item.id for item in items if getattr(item, "id", None) is not None]
    if not ids:
        return
    rows = (
        await db.scalars(
            select(ContractRateHistoryFinding).where(
                ContractRateHistoryFinding.contract_id.in_(ids),
                ContractRateHistoryFinding.status.in_(FOR_HUMAN),
            )
        )
    ).all()
    by_contract: dict[int, dict[str, Any]] = {}
    for row in rows:
        steps = [s for s in row.steps or [] if not s.get("baseline")]
        if not steps:
            continue
        first = min(steps, key=lambda s: s["from"])
        by_contract[row.contract_id] = {
            "from": first["from"],
            "leg": first["leg"],
            "rate": float(first["rate"]),
            "category": row.category,
            "count": len(steps),
        }
    for item in items:
        change = by_contract.get(getattr(item, "id", None))
        if change is not None:
            item.rate_history_change = change
