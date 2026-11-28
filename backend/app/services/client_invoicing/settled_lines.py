"""Pozycje „do faktury” z przyjętego rozliczenia zamiast stawki zamówienia × 168 h.

Decyzja Artura z 27.11.2026 po pomiarze IV–X: „Wystaw za miesiąc” liczyło
zamówienia okresowe ze stałej liczby godzin z zamówienia (domyślnie 168 h),
więc za październik (22 dni robocze) zgadzało się z fakturą Finansów tylko
przy 93 z 624 faktur (PKO, Alior, Bank Pocztowy, Orlen, ERSTE, CA, Cardif,
Nordea). Poprawną kwotę liczy już „Do faktury dla klienta” w Rozliczeniach
(``client_settlements.client_invoice.invoice_month``): MD z przyjętego RCP
albo godziny zatwierdzone w T4T, nadgodziny, MD wdrożeniowe, dodatki,
estymacja i podział na zamówienia. Tu bierzemy stamtąd pozycje osoby dla
linii okresowej.

* Wiersz z pozycjami (stan inny niż „czeka”) — pozycje zastępują linię
  zamówienia (``source = "settlement"``).
* Osoba jest w rozliczeniach klienta, ale bez przyjętego RCP albo z godzinami
  niezatwierdzonymi w T4T — linia zostaje policzona z zamówienia (podgląd),
  z powodem w ``awaiting``; szkic faktury jej nie wystawi (``issue._row_block``).
* Klient bez żadnego rozliczenia w NEXUSIE za ten miesiąc
  (``client_settlements``: klient spoza rozliczeń, miesiąc sprzed rozliczeń
  w NEXUSIE) albo osoba spoza jego rozliczeń — linia z zamówienia jak dotąd.
  Bez tego warunku każda osoba z kontraktem u takiego klienta czekałaby na
  RCP, którego nie będzie (CI 27.11.2026). Zestaw reguł klienta tego nie
  rozstrzyga: trzyma też same reguły faktury (``cl.*``).
* Dokument klienta z godzinami (decyzja Artura z 28.11.2026): przy
  ``cl.after_signed_document`` wiersz z KEŚU bez podpisu klienta
  (``awaiting_signature``) i wiersz z KCP bez akceptacji klienta mailem
  (``cl.client_acceptance``, ``awaiting_client``) czeka tak samo jak bez RCP.
  Ten sam ``awaiting_signature`` przy wstrzymaniu na protokół albo arkusze
  miesiąca (``signature_hold`` widoku) nie czeka tutaj: podpis każdej osoby
  sprawdza ``issue._signature_block``, który przy KEŚU arkusza nie szuka.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: Wiersz rozliczenia, z którego nie wystawiamy faktury, i powód dla Finansów.
AWAITING = {
    "waiting": "czeka na przyjęte rozliczenie (RCP)",
    "awaiting_t4t": "czeka na godziny zatwierdzone w T4T",
    "awaiting_signature": "czeka na podpisane KEŚU",
    "awaiting_client": "czeka na akceptację KCP klienta",
}
#: Stan wiersza przy wstrzymaniu klienta na protokół albo arkusze miesiąca.
_DOCUMENT_HOLD = "awaiting_signature"
_UNITS = {
    "md": "md",
    "godz.": "hours",
    "godz": "hours",
    "h": "hours",
    "dni": "days",
    "mies.": "month",
}


@dataclass(frozen=True)
class SettledPosition:
    name: str
    basis: str
    quantity: Decimal
    unit_price: Optional[Decimal]
    net: Decimal
    currency: str
    kind: str


@dataclass(frozen=True)
class Settled:
    """Stan osoby w „Do faktury dla klienta” za miesiąc."""

    state: str
    positions: tuple[SettledPosition, ...]
    #: Klient czeka na protokół albo arkusze miesiąca, nie na KEŚU tej osoby.
    document_hold: bool = False

    @property
    def awaiting(self) -> Optional[str]:
        if self.document_hold and self.state == _DOCUMENT_HOLD and self.positions:
            return None
        if self.state in AWAITING:
            return AWAITING[self.state]
        if not self.positions:
            return AWAITING["waiting"]
        return None


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def position_from(item: dict[str, Any]) -> Optional[SettledPosition]:
    quantity = _decimal(item.get("quantity"))
    net = _decimal(item.get("net"))
    if quantity is None or net is None:
        return None
    unit = str(item.get("unit") or "").strip().lower()
    return SettledPosition(
        name=str(item.get("name") or ""),
        basis=_UNITS.get(unit, "md"),
        quantity=quantity,
        unit_price=_decimal(item.get("unit_price")),
        net=net,
        currency=str(item.get("currency") or "PLN").upper(),
        kind=str(item.get("kind") or "base"),
    )


def settled_from_rows(
    rows: Iterable[dict[str, Any]], *, document_hold: bool = False
) -> dict[tuple[int, Optional[int]], Settled]:
    """Klucz (kontrakt, linia zamówienia wiersza albo ``None``) → stan i pozycje.

    ``document_hold`` — widok klienta ma ``signature_hold`` (protokół, arkusze)."""

    out: dict[tuple[int, Optional[int]], Settled] = {}
    for row in rows:
        contract_id = row.get("contract_id")
        if contract_id is None:
            continue
        items = tuple(
            p
            for p in (position_from(i) for i in row.get("positions") or [])
            if p is not None
        )
        out[(int(contract_id), row.get("order_id"))] = Settled(
            state=str(row.get("state") or "waiting"),
            positions=items,
            document_hold=document_hold,
        )
    return out


def find(
    settled: dict[tuple[int, Optional[int]], Settled],
    contract_id: Optional[int],
    order_id: Optional[int],
) -> Optional[Settled]:
    """Wiersz linii zamówienia, a bez niego jedyny wiersz kontraktu."""

    if contract_id is None:
        return None
    exact = settled.get((contract_id, order_id))
    if exact is not None:
        return exact
    loose = [s for (c, o), s in settled.items() if c == contract_id and o is None]
    return loose[0] if len(loose) == 1 else None


async def for_clients(
    db: AsyncSession, client_ids: Iterable[int], period: str
) -> dict[tuple[int, Optional[int]], Settled]:
    """„Do faktury dla klienta” wszystkich wskazanych klientów za miesiąc."""

    from app.models.client_settlement import ClientSettlement
    from app.services.client_settlements import client_invoice

    wanted = sorted(set(client_ids))
    if not wanted:
        return {}
    settling = set(
        (
            await db.scalars(
                select(ClientSettlement.client_id)
                .where(
                    ClientSettlement.client_id.in_(wanted),
                    ClientSettlement.period_month == period,
                )
                .distinct()
            )
        ).all()
    )
    out: dict[tuple[int, Optional[int]], Settled] = {}
    for client_id in wanted:
        if client_id not in settling:
            continue
        try:
            # Savepoint: błąd SQL w rozliczeniach jednego klienta nie może
            # przerwać transakcji, w której liczymy resztę „Do faktury”.
            async with db.begin_nested():
                view = await client_invoice.invoice_month(
                    db, client_id, period, amounts=True
                )
        except Exception:
            # Błąd rozliczeń jednego klienta nie może zatrzymać „Do faktury”
            # pozostałych: jego linie zostają z zamówienia, przyczyna w logu.
            logger.exception(
                "do faktury: rozliczenie klienta %s za %s niedostępne",
                client_id,
                period,
            )
            continue
        out.update(
            settled_from_rows(
                view.get("rows") or [],
                document_hold=view.get("signature_hold") is not None,
            )
        )
    return out


async def with_kesu(
    db: AsyncSession, contract_ids: Iterable[int], period: str
) -> set[int]:
    """Kontrakty z KEŚU w przyjętym rozliczeniu miesiąca (plan albo faktyczne).

    Ich dokumentem klienta jest KEŚU (stan w ``AWAITING``), nie arkusz ani
    protokół z ``cl.client_document`` — tak jak w „Do faktury dla klienta”,
    gdzie KEŚU zdejmuje wstrzymanie na arkusze (``client_invoice.invoice_month``)."""

    from app.models.client_settlement import ClientSettlement
    from app.services.client_settlements import service

    ids = {int(i) for i in contract_ids if i is not None}
    if not ids:
        return set()
    found = await db.scalars(
        select(ClientSettlement).where(
            ClientSettlement.contract_id.in_(ids),
            ClientSettlement.period_month == period,
            ClientSettlement.status == "accepted",
        )
    )
    return {s.contract_id for s in found.all() if service.kesu_state(s) is not None}
