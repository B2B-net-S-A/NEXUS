"""NIP nabywcy → klient NEXUSA (``clients.nip``) i rodzina klienta po scaleniu.

Klucz to polski NIP (10 cyfr) albo identyfikator obcy z prefiksem kraju
(„FI12345678”, „NO123456785”): klient zagraniczny ma go w tym samym polu,
a faktura niesie go jako ``KodUE`` + ``NrVatUE`` albo ``KodKraju`` + ``NrID``.

Numer prowadzi do klienta KANONICZNEGO: scalenie duplikatu nie przepisuje
danych, więc NIP bywa na scalonym wierszu (``merged_into_client_id``). Ten sam
NIP u dwóch różnych klientów kanonicznych to niejednoznaczność — faktura
czeka na Finanse, nie trafia do klienta wybranego kolejnością wierszy.
Klient usunięty z profilu (``deleted_at``) nie przyjmuje faktur.

Zamówienia i faktury klienta czytamy razem z jego scalonymi duplikatami
(``family``): dane po scaleniu bywają jeszcze na wierszu duplikatu.

Klient może mieć dodatkowe numery (``client_buyer_numbers``, 0781): spółki grupy
— oddział, spółka leasingowa, fundusz — fakturują się pod własnym numerem,
a ``clients.nip`` jest jeden (decyzja Artura z 25.11.2026). Rejestr czyta je
tak samo jak ``clients.nip``, więc ten sam numer u innego klienta to nadal
niejednoznaczność. Dopisanie przy innym numerze klienta (``differs``) idzie
tylko jawnie: ``extra=True`` w ``add_buyer_number``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.client_buyer_number import ClientBuyerNumber
from app.services.client_identity import client_display_name
from app.services.order_client_identity import REGISTRY_KEY, normalize_buyer_number

#: Bezpiecznik łańcucha scaleń (API nie pozwala scalić do scalonego).
_MERGE_CHAIN_LIMIT = 5

BuyerNumberState = Literal["add", "same", "differs", "taken", "none"]


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

    extras = (
        await db.execute(select(ClientBuyerNumber.client_id, ClientBuyerNumber.number))
    ).all()
    targets: dict[str, set[int]] = {}
    numbers = [(cid, raw) for cid, raw, _m, _d in rows] + list(extras)
    for client_id, raw_nip in numbers:
        nip = normalize_buyer_number(raw_nip or "")
        if not REGISTRY_KEY.fullmatch(nip):
            continue
        target = canonical(int(client_id))
        if target is None or target in deleted:
            continue
        targets.setdefault(nip, set()).add(target)
    return NipRegistry(
        by_nip={nip: next(iter(ids)) for nip, ids in targets.items() if len(ids) == 1},
        ambiguous=frozenset(nip for nip, ids in targets.items() if len(ids) > 1),
    )


async def canonical_clients(db: AsyncSession) -> dict[int, int]:
    """Klient → klient kanoniczny po scaleniach (jak ``nip_registry``), bez usuniętych."""

    rows = (
        await db.execute(
            select(Client.id, Client.merged_into_client_id, Client.deleted_at)
        )
    ).all()
    pointer = {int(cid): (int(m) if m is not None else None) for cid, m, _d in rows}
    deleted = {int(cid) for cid, _m, removed in rows if removed is not None}
    found: dict[int, int] = {}
    for client_id in pointer:
        current = client_id
        for _ in range(_MERGE_CHAIN_LIMIT):
            target = pointer.get(current)
            if target is None:
                break
            current = target
        else:
            continue
        if current in pointer and current not in deleted:
            found[client_id] = current
    return found


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


@dataclass(frozen=True)
class BuyerNumber:
    """Czy numer nabywcy z faktury można dopisać do klienta.

    ``add`` — klient nie ma numeru, a tego numeru nie ma nikt inny; ``same`` —
    klient ma już ten numer; ``differs`` — ma inny (nie nadpisujemy); ``taken`` —
    numer ma inny klient (dopisanie zrobiłoby niejednoznaczność, a faktury
    przestałyby się wiązać u obu); ``none`` — brak numeru albo klienta.
    """

    state: BuyerNumberState
    number: Optional[str] = None
    client_id: Optional[int] = None
    existing: Optional[str] = None
    owner_id: Optional[int] = None
    #: ``add`` przy kliencie z innym numerem: numer trafia do ``client_buyer_numbers``.
    extra: bool = False


async def _canonical(db: AsyncSession, client_id: int) -> Optional[Client]:
    current = await db.get(Client, client_id)
    for _ in range(_MERGE_CHAIN_LIMIT):
        if current is None or current.merged_into_client_id is None:
            break
        current = await db.get(Client, current.merged_into_client_id)
    if current is None or current.merged_into_client_id is not None:
        return None
    return None if current.deleted_at is not None else current


async def check_buyer_number(
    db: AsyncSession,
    client_id: Optional[int],
    number: Optional[str],
    *,
    extra: bool = False,
) -> BuyerNumber:
    """Stan numeru względem klienta kanonicznego i jego scalonych duplikatów.

    ``extra=True``: klient z innym numerem dostaje ``add`` z ``extra`` zamiast
    ``differs`` (dodatkowy numer spółki grupy); ``taken`` obowiązuje tak samo.
    """

    key = normalize_buyer_number(number or "")
    client = await _canonical(db, client_id) if client_id is not None else None
    if client is None or not REGISTRY_KEY.fullmatch(key):
        return BuyerNumber("none", number=key or None)
    members = await family(db, [client.id])
    existing = [
        raw.strip()
        for raw in await db.scalars(select(Client.nip).where(Client.id.in_(members)))
        if raw and raw.strip()
    ]
    added = list(
        await db.scalars(
            select(ClientBuyerNumber.number).where(
                ClientBuyerNumber.client_id.in_(members)
            )
        )
    )
    if any(normalize_buyer_number(raw) == key for raw in existing + added):
        return BuyerNumber("same", number=key, client_id=client.id)
    if existing and not extra:
        return BuyerNumber(
            "differs", number=key, client_id=client.id, existing=existing[0]
        )
    registry = await nip_registry(db)
    if key in registry.ambiguous or key in registry.by_nip:
        return BuyerNumber(
            "taken",
            number=key,
            client_id=client.id,
            owner_id=registry.by_nip.get(key),
        )
    return BuyerNumber(
        "add",
        number=key,
        client_id=client.id,
        existing=existing[0] if existing else None,
        extra=bool(existing),
    )


async def add_buyer_number(
    db: AsyncSession,
    client_id: Optional[int],
    number: Optional[str],
    *,
    extra: bool = False,
    source: str = "manual",
    actor_id: Optional[int] = None,
) -> BuyerNumber:
    """Dopisuje numer tylko w stanie ``add``; inny stan wraca bez zapisu.

    Klient bez numeru dostaje go w ``clients.nip``; klient z innym numerem —
    tylko przy ``extra=True`` — jako wiersz ``client_buyer_numbers``.
    """

    current = await _canonical(db, client_id) if client_id is not None else None
    if current is None:
        return BuyerNumber("none", number=number)
    # Blokada wiersza: dwa przypisania naraz nie nadpiszą sobie numeru.
    client = await db.scalar(
        select(Client)
        .where(Client.id == current.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    check = await check_buyer_number(db, client.id, number, extra=extra)
    if check.state == "add" and check.extra:
        db.add(
            ClientBuyerNumber(
                client_id=client.id,
                number=check.number,
                source=source,
                added_by=actor_id,
            )
        )
        await db.flush()
    elif check.state == "add":
        client.nip = check.number
        await db.flush()
    return check


async def extra_numbers(db: AsyncSession, client_id: int) -> list[ClientBuyerNumber]:
    """Dodatkowe numery klienta i jego scalonych duplikatów, najstarszy pierwszy."""

    members = await family(db, [client_id])
    return list(
        await db.scalars(
            select(ClientBuyerNumber)
            .where(ClientBuyerNumber.client_id.in_(members))
            .order_by(ClientBuyerNumber.created_at, ClientBuyerNumber.id)
        )
    )


async def remove_extra_number(
    db: AsyncSession, client_id: int, number_id: int
) -> Optional[ClientBuyerNumber]:
    """Usuwa dodatkowy numer klienta; ``None`` — nie ma go u tego klienta."""

    row = await db.get(ClientBuyerNumber, number_id, with_for_update=True)
    if row is None or row.client_id not in await family(db, [client_id]):
        return None
    await db.delete(row)
    await db.flush()
    return row


def is_registry_key(number: Optional[str]) -> bool:
    """Czy numer z faktury nadaje się do zapisania u klienta (patrz ``REGISTRY_KEY``)."""

    return bool(number) and REGISTRY_KEY.fullmatch(number or "") is not None


async def number_taken_by(
    db: AsyncSession, client_id: Optional[int], number: str
) -> Optional[str]:
    """Kto INNY ma ten numer: nazwa klienta albo opis, ``None`` gdy nikt.

    Ten sam numer u dwóch klientów zatrzymuje faktury obu (``ambiguous_buyer``),
    więc formularz klienta odmawia tak samo jak „Przypisz i dopisz NIP”.
    """

    key = normalize_buyer_number(number)
    registry = await nip_registry(db)
    if key in registry.ambiguous:
        return "kilku innych klientów"
    owner = registry.by_nip.get(key)
    if owner is None:
        return None
    if client_id is not None and owner in await family(db, [client_id]):
        return None
    return (await names(db, [owner])).get(owner)


async def names(db: AsyncSession, client_ids: Iterable[int]) -> dict[int, str]:
    ids = sorted({int(cid) for cid in client_ids})
    if not ids:
        return {}
    rows = await db.execute(select(Client).where(Client.id.in_(ids)))
    return {client.id: client_display_name(client) for client in rows.scalars()}


__all__ = [
    "BuyerNumber",
    "NipRegistry",
    "add_buyer_number",
    "canonical_clients",
    "check_buyer_number",
    "extra_numbers",
    "family",
    "is_registry_key",
    "names",
    "nip_registry",
    "number_taken_by",
    "remove_extra_number",
]
