"""Należności po terminie: VAT w PLN faktur walutowych, eskalacja monitu, stan na dzień.

Przegląd skrzynek Finansów z 23.11.2026: nikt nie monitował klientów o zapłatę
(dwie faktury w EUR wyszły 1,5 i 2,5 miesiąca po terminie dopiero na pytanie
klienta), klient z fakturami w EUR płacił netto w EUR, a VAT w PLN nie dopłacał,
a główna księgowa co miesiąc ok. 20. dnia ręcznie składała listę przeterminowanych
należności. Reguła: ``docs/claude/zamowienia/monity-i-naleznosci-po-terminie.md``.

* **VAT w PLN nieopłacony** (``vat_gap``) — faktura w walucie obcej, wpłaty
  w walucie faktury pokryły co najmniej netto, a do zapłaty zostało (to już tylko
  VAT). Taki VAT klient płaci w PLN na rachunek PLN, więc dowód „po terminie” idzie
  z wyciągów rachunku PLN (``Proof.verdict(currency="PLN")``), a kwota w PLN to
  VAT × kurs faktury (kurs z wystawienia w NEXUSIE, inaczej średni NBP z dnia
  roboczego przed dniem sprzedaży — jak w Księdze, ``ledger/sources.invoice_rate``).
* **Eskalacja** (``escalation``) — 7, 14 i 30 dni po terminie.
* **Stan na dzień** (``as_of``) — łańcuch bez faktur wystawionych i wpłat
  zaksięgowanych po tym dniu (lista na zamknięcie miesiąca).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_issued_invoice import ClientIssuedInvoice
from app.models.fx_rate import FxRate
from app.services.client_invoicing.billing import money
from app.services.client_invoicing.ledger import ZERO, Chain
from app.services.finance_ledger import posting

#: (od ilu dni po terminie, poziom) — od najwyższego.
LEVELS: tuple[tuple[int, str], ...] = ((30, "final"), (14, "second"), (7, "first"))
LEVEL_LABELS: dict[str, str] = {
    "first": "Przypomnienie o płatności",
    "second": "Ponowne wezwanie do zapłaty",
    "final": "Ostateczne wezwanie do zapłaty",
}
#: Monit wcześniej niż 7. dnia po terminie nie jest proponowany.
FIRST_DAY = LEVELS[-1][0]


def escalation(days: int) -> Optional[str]:
    """Poziom monitu dla liczby dni po terminie (``None`` = jeszcze za wcześnie)."""

    for threshold, level in LEVELS:
        if days >= threshold:
            return level
    return None


def vat_gap(chain: Chain) -> Optional[Decimal]:
    """Nieopłacony VAT faktury walutowej (w walucie faktury) albo ``None``.

    Wpłaty w walucie faktury pokryły co najmniej netto całego łańcucha (z korektami),
    a coś zostało do zapłaty — to nie może być nic innego niż VAT. Wpłata mniejsza
    niż netto to zwykła częściowa zapłata (reszta to i netto, i VAT).
    """

    head = chain.head
    if head.currency == "PLN" or head.paid_in_invoice_on is not None:
        return None
    vat = money(chain.gross - chain.net)
    if vat <= ZERO or chain.net <= ZERO:
        return None
    if chain.paid < chain.net or chain.to_pay <= ZERO:
        return None
    return chain.to_pay


@dataclass(frozen=True)
class Rate:
    rate: Decimal
    day: date
    #: ``issued`` — kurs z faktury wystawionej w NEXUSIE; ``nbp`` — średni NBP.
    source: str


def to_pln(amount: Decimal, rate: Optional[Rate]) -> Optional[Decimal]:
    if rate is None:
        return None
    return (Decimal(amount) * rate.rate).quantize(Decimal("0.01"), ROUND_HALF_UP)


def rate_day(chain: Chain) -> date:
    head = chain.head
    return posting.rate_day(head.sale_date or head.issue_date)


async def rates(db: AsyncSession, chains: Iterable[Chain]) -> dict[int, Rate]:
    """Kurs faktury pierwotnej łańcucha (id pierwotnej → kurs); bez kursu — brak klucza."""

    foreign = [chain for chain in chains if chain.head.currency != "PLN"]
    if not foreign:
        return {}
    out: dict[int, Rate] = {}
    for sales_id, rate, day in await db.execute(
        select(
            ClientIssuedInvoice.sales_invoice_id,
            ClientIssuedInvoice.fx_rate,
            ClientIssuedInvoice.fx_date,
        ).where(
            ClientIssuedInvoice.sales_invoice_id.in_([c.head.id for c in foreign]),
            ClientIssuedInvoice.fx_rate.is_not(None),
            ClientIssuedInvoice.fx_date.is_not(None),
        )
    ):
        out[int(sales_id)] = Rate(Decimal(rate), day, "issued")
    wanted = {
        (chain.head.currency, rate_day(chain))
        for chain in foreign
        if chain.head.id not in out
    }
    if wanted:
        nbp = {
            (currency, day): Decimal(value)
            for currency, day, value in await db.execute(
                select(
                    FxRate.currency, FxRate.effective_date, FxRate.rate_to_pln
                ).where(
                    FxRate.source == "NBP",
                    FxRate.currency.in_({currency for currency, _ in wanted}),
                    FxRate.effective_date.in_({day for _, day in wanted}),
                )
            )
        }
        for chain in foreign:
            if chain.head.id in out:
                continue
            day = rate_day(chain)
            value = nbp.get((chain.head.currency, day))
            if value is not None:
                out[chain.head.id] = Rate(value, day, "nbp")
    return out


def as_of(chain: Chain, day: date) -> Optional[Chain]:
    """Łańcuch, jaki był na koniec ``day`` (``None`` — faktury jeszcze nie było).

    Bez korekt wystawionych i wpłat zaksięgowanych po tym dniu. „Zapłacono”
    w samej fakturze to zapłata przy wystawieniu, więc zostaje.
    """

    if chain.head.issue_date > day:
        return None
    return replace(
        chain,
        corrections=[c for c in chain.corrections if c.issue_date <= day],
        payments=[
            p for p in chain.payments if p.booked_on is None or p.booked_on <= day
        ],
    )


__all__ = [
    "FIRST_DAY",
    "LEVELS",
    "LEVEL_LABELS",
    "Rate",
    "as_of",
    "escalation",
    "rate_day",
    "rates",
    "to_pln",
    "vat_gap",
]
