"""NIP nabywcy → klient NEXUSA (``clients.nip``) i rodzina klienta po scaleniu.

Numer prowadzi do klienta KANONICZNEGO: scalenie duplikatu nie przepisuje
danych, więc NIP bywa na scalonym wierszu (``merged_into_client_id``). Ten sam
NIP u dwóch różnych klientów kanonicznych to niejednoznaczność — faktura
czeka na Finanse, nie trafia do klienta wybranego kolejnością wierszy.
Klient usunięty z profilu (``deleted_at``) nie przyjmuje faktur.

Zamówienia i faktury klienta czytamy razem z jego scalonymi duplikatami
(``family``): dane po scaleniu bywają jeszcze na wierszu duplikatu.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.services.client_identity import client_display_name
from app.services.order_client_identity import normalize_registry_id

#: Bezpiecznik łańcucha scaleń (API nie pozwala scalić do scalonego).
_MERGE_CHAIN_LIMIT = 5


@dataclass(frozen=True)
class NipRegistry:
    by_nip: dict[str, int] = field(default_factory=dict)
    ambiguous: frozenset[str] = frozenset()

    def resolve(self, nip: Optional[str]) -> tuple[Optional[int], Optional[str]]:
        """(klient, powód braku): ``unknown_buyer`` / ``ambiguous_buyer``."""

        if not nip:
            return None, "unknown_buyer"
        if nip in self.ambiguous:
            return None, "ambiguous_buyer"
        client_id = self.by_nip.get(nip)
        return (client_id, None) if client_id is not None else (None, "unknown_buyer")


async def nip_registry(db: AsyncSession) -> NipRegistry:
    rows = (
        await db.execute(
            select(
                Client.id,
                Client.nip,
                Client.merged_into_client_id,
                Client.deleted_at,
            )
        )
    ).all()
    pointer = {int(cid): (int(m) if m is not None else None) for cid, _n, m, _d in rows}
    deleted = {int(cid) for cid, _n, _m, removed in rows if removed is not None}

    def canonical(client_id: int) -> Optional[int]:
        current = client_id
        for _ in range(_MERGE_CHAIN_LIMIT):
            target = pointer.get(current)
            if target is None:
                return current if current in pointer else None
            current = target
        return None

    targets: dict[str, set[int]] = {}
    for client_id, raw_nip, _merged, _deleted in rows:
        nip = normalize_registry_id(raw_nip or "")
        if len(nip) != 10 or not nip.isdigit():
            continue
        target = canonical(int(client_id))
        if target is None or target in deleted:
            continue
        targets.setdefault(nip, set()).add(target)
    return NipRegistry(
        by_nip={nip: next(iter(ids)) for nip, ids in targets.items() if len(ids) == 1},
        ambiguous=frozenset(nip for nip, ids in targets.items() if len(ids) > 1),
    )


async def family(db: AsyncSession, client_ids: Iterable[int]) -> set[int]:
    """Klienci i ich scalone duplikaty (w obie strony, jeden poziom)."""

    ids = {int(cid) for cid in client_ids}
    if not ids:
        return set()
    rows = (
        await db.execute(
            select(Client.id, Client.merged_into_client_id).where(
                or_(Client.id.in_(ids), Client.merged_into_client_id.in_(ids))
            )
        )
    ).all()
    found = set(ids)
    for client_id, merged_into in rows:
        found.add(int(client_id))
        if merged_into is not None:
            found.add(int(merged_into))
    return found


async def names(db: AsyncSession, client_ids: Iterable[int]) -> dict[int, str]:
    ids = sorted({int(cid) for cid in client_ids})
    if not ids:
        return {}
    rows = await db.execute(select(Client).where(Client.id.in_(ids)))
    return {client.id: client_display_name(client) for client in rows.scalars()}


__all__ = ["NipRegistry", "family", "names", "nip_registry"]
