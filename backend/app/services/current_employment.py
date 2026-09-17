"""„Kandydat obecnie pracuje u klienta X" wyprowadzone z umów (17.09.2026).

Do tej zmiany ten sygnał dopuszczalności brał się WYŁĄCZNIE z ręcznego wiersza
``candidate_conflicts`` typu ``current_employment``, choć kontrakty wiedzą
dokładnie, kto u kogo pracuje. Ręczne wiersze zostają (pracodawcy spoza naszych
umów); ten moduł dokłada to, co wynika z umów.

Reguła „umowa trwa" godzi dwie istniejące, rozjechane definicje:
``candidates._derive_employment`` (sam status) i
``contractor_identity.is_current_contract`` (sama data startu). Status
rozstrzyga KONIEC (umowa B2B jest bezterminowa, dopóki ktoś jej nie zakończy —
``end_date`` świadomie nie jest czytane), data startu rozstrzyga, czy umowa już
się zaczęła. ``_derive_employment`` jest celowo nietknięte — to inny ekran.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract import Contract, ContractStatus

LIVE_CONTRACT_STATUSES: tuple[ContractStatus, ...] = (
    ContractStatus.active,
    ContractStatus.ending,
)


def is_live_contract(contract: Any, today: date) -> bool:
    if getattr(contract, "status", None) not in LIVE_CONTRACT_STATUSES:
        return False
    start = getattr(contract, "start_date", None)
    return start is None or start <= today


async def current_employment_client_ids(
    db: AsyncSession,
    candidate_ids: Iterable[int],
    *,
    client_id: Optional[int] = None,
    today: date,
) -> dict[int, set[int]]:
    """``{candidate_id: {client_id, ...}}`` — każdy przekazany id jest w wyniku,
    także bez umów (pusty zbiór), żeby „brak wpisu" nie mylił się
    z „nie sprawdzono". Jedno zapytanie ``IN (...)``."""
    ids = sorted({int(cid) for cid in candidate_ids if cid is not None})
    out: dict[int, set[int]] = {cid: set() for cid in ids}
    if not ids:
        return out
    stmt = select(Contract.candidate_id, Contract.client_id).where(
        Contract.candidate_id.in_(ids),
        Contract.client_id.isnot(None),
        Contract.status.in_(LIVE_CONTRACT_STATUSES),
        or_(Contract.start_date.is_(None), Contract.start_date <= today),
    )
    if client_id is not None:
        stmt = stmt.where(Contract.client_id == client_id)
    for cand_id, cl_id in (await db.execute(stmt)).all():
        out.setdefault(cand_id, set()).add(cl_id)
    return out
