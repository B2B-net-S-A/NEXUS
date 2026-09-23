"""Zapis stanu sprzed zakończenia kontraktu (0359).

Wołają to wszystkie ścieżki kończące kontrakt — przez
``apply_contract_order_offboarding``, jedyne miejsce, które zmienia zamówienia
przy zakończeniu. Stan kontraktu sprzed zakończenia podaje wołający
(``ContractStateBefore``), bo w chwili wywołania serwisu zamówień kontrakt ma
już zwykle nowy status i datę końca.

Reguły scalania (jeden OTWARTY wiersz na kontrakt):

* pierwszy zapis epizodu zakłada wiersz ze stanem „przed" kontraktu i każdego
  ruszanego zamówienia;
* kolejne zapisy (cron materializujący zakończenie z przyszłą datą, zmiana
  daty zakończenia, ponowienie) dopisują zamówienia, których jeszcze nie ma,
  i aktualizują WYŁĄCZNIE stan „po" — stan „przed" nigdy nie jest nadpisywany,
  bo to on jest celem cofnięcia;
* wskrzeszenie kontraktu inną drogą (``reopen_contract``: przedłużenie,
  zmiana statusu, aneks) zamyka wiersz jako ``superseded``
  (:func:`supersede_open_snapshot`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.contract import Contract
from app.models.contract_termination_snapshot import (
    SNAPSHOT_SOURCE_TERMINATION,
    SNAPSHOT_STATUS_OPEN,
    SNAPSHOT_STATUS_SUPERSEDED,
    ContractTerminationSnapshot,
)


def _value(raw: Any) -> Any:
    return getattr(raw, "value", raw)


def _iso(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value is not None else None


@dataclass(frozen=True)
class ContractStateBefore:
    """Pola kontraktu, które zakończenie zmienia — odczytane PRZED zmianą."""

    status: str
    end_date: Optional[date]
    terminated_at: Optional[date]
    termination_reason: Optional[str]
    termination_lessons: Optional[str]

    @classmethod
    def of(cls, contract: Contract) -> "ContractStateBefore":
        return cls(
            status=str(_value(contract.status)),
            end_date=contract.end_date,
            terminated_at=contract.terminated_at,
            termination_reason=(
                None
                if contract.termination_reason is None
                else str(_value(contract.termination_reason))
            ),
            termination_lessons=contract.termination_lessons,
        )

    def as_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "end_date": _iso(self.end_date),
            "terminated_at": _iso(self.terminated_at),
            "termination_reason": self.termination_reason,
            "termination_lessons": self.termination_lessons,
        }


@dataclass(frozen=True)
class OrderStateChange:
    """Jedno zamówienie ruszone przez zakończenie: stan przed i po."""

    order_id: int
    order_group_id: Optional[int]
    status_before: str
    end_date_before: Optional[date]
    group_status_before: Optional[str]
    status_after: str
    end_date_after: Optional[date]

    def as_json(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "order_group_id": self.order_group_id,
            "status_before": self.status_before,
            "end_date_before": _iso(self.end_date_before),
            "group_status_before": self.group_status_before,
            "status_after": self.status_after,
            "end_date_after": _iso(self.end_date_after),
        }


async def open_snapshot(
    db: AsyncSession, contract_id: int, *, lock: bool = False
) -> Optional[ContractTerminationSnapshot]:
    query = select(ContractTerminationSnapshot).where(
        ContractTerminationSnapshot.contract_id == contract_id,
        ContractTerminationSnapshot.status == SNAPSHOT_STATUS_OPEN,
    )
    if lock:
        query = query.with_for_update()
    return await db.scalar(query)


async def record_termination_snapshot(
    db: AsyncSession,
    *,
    contract_id: int,
    effective_date: date,
    contract_before: Optional[ContractStateBefore],
    changes: Iterable[OrderStateChange],
    actor_id: Optional[int],
) -> ContractTerminationSnapshot:
    """Załóż albo uzupełnij otwarty wiersz epizodu. Nie commituje."""

    changes = list(changes)
    snapshot = await open_snapshot(db, contract_id, lock=True)
    if snapshot is None:
        before = contract_before
        if before is None:
            # Ścieżka bez stanu od wołającego (cron domykający datę końca):
            # czytamy kontrakt teraz. Cron ustawia ``ended`` tuż przed
            # wywołaniem, ale datę końca zostawia — to ona jest faktem.
            contract = await db.get(Contract, contract_id)
            before = (
                ContractStateBefore.of(contract)
                if contract is not None
                else ContractStateBefore("active", None, None, None, None)
            )
        snapshot = ContractTerminationSnapshot(
            contract_id=contract_id,
            effective_date=effective_date,
            status=SNAPSHOT_STATUS_OPEN,
            source=SNAPSHOT_SOURCE_TERMINATION,
            contract_before=before.as_json(),
            orders=[change.as_json() for change in changes],
            created_by_user_id=actor_id,
        )
        db.add(snapshot)
        return snapshot

    entries: list[dict[str, Any]] = [dict(item) for item in (snapshot.orders or [])]
    by_order = {int(item["order_id"]): item for item in entries}
    for change in changes:
        existing = by_order.get(change.order_id)
        if existing is None:
            item = change.as_json()
            entries.append(item)
            by_order[change.order_id] = item
            continue
        existing["status_after"] = change.status_after
        existing["end_date_after"] = _iso(change.end_date_after)
    snapshot.orders = entries
    flag_modified(snapshot, "orders")
    snapshot.effective_date = effective_date
    return snapshot


async def supersede_open_snapshot(db: AsyncSession, contract_id: int) -> bool:
    """Kontrakt wrócił do życia inną drogą — stan „przed" jest nieaktualny."""

    snapshot = await open_snapshot(db, contract_id, lock=True)
    if snapshot is None:
        return False
    snapshot.status = SNAPSHOT_STATUS_SUPERSEDED
    snapshot.closed_at = datetime.now(timezone.utc)
    return True
