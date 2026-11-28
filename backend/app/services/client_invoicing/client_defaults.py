"""Adres nabywcy i termin płatności szkicu z historii klienta (28.11.2026).

Szkic z kartoteki klienta brał adres tylko z ``clients.address``, a ten miało
4 z 28 klientów z aktywnym kontraktem (produkcja 28.11.2026). Bez adresu XML
FA(3) nie powstaje („Uzupełnij nazwę i adres nabywcy”), więc NEXUS nie wysłałby
żadnej faktury tych klientów do KSeF. Termin płatności był 14 dni u wszystkich,
a na fakturach Finansów za X 19 z 27 klientów ma inny (21, 30, 35, 60).

Decyzja Artura 28.11.2026: gdy karta klienta i ustawienia wystawiania milczą,
szkic bierze te dane z tego, co Finanse już wystawiały temu klientowi:

* adres: kartoteka kontrahentów z eBI24 (``finance_counterparties``), a bez niej
  adres nabywcy z ostatniej faktury sprzedaży w KSeF pod NIP-em klienta (zostaje
  po wyłączeniu eBI24, także dla nowych klientów);
* termin: najczęstsza różnica „termin − data wystawienia” na fakturach klienta
  w KSeF z ostatnich 12 miesięcy (bez korekt); remis rozstrzyga nowsza faktura.

Tylko pod NIP-em klienta: Bosch ma też drugiego nabywcę (Robert Bosch GmbH),
którego adres i termin nie mogą trafić na fakturę spółki polskiej.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.finance_ledger import FinanceCounterparty

#: Okno historii terminów; starsze faktury mogą mieć dawne warunki umowy.
HISTORY_DAYS = 365
#: Termin spoza tego zakresu to błąd danych, nie warunek umowy.
MAX_TERM_DAYS = 120


@dataclass(frozen=True)
class ClientDefaults:
    address_l1: str = ""
    address_l2: str = ""
    country: str = ""
    payment_days: Optional[int] = None


def nip_key(number: Optional[str]) -> str:
    """NIP do porównania: same litery i cyfry, bez prefiksu PL."""

    value = "".join(ch for ch in str(number or "").upper() if ch.isalnum())
    return value[2:] if value.startswith("PL") and value[2:].isdigit() else value


def usual_term(pairs: list[tuple[date, date]]) -> Optional[int]:
    """Najczęstszy termin w dniach z par (wystawienie, termin); remis — nowszy."""

    counts: Counter[int] = Counter()
    latest: dict[int, date] = {}
    for issued, due in pairs:
        days = (due - issued).days
        if not 0 < days <= MAX_TERM_DAYS:
            continue
        counts[days] += 1
        latest[days] = max(latest.get(days, issued), issued)
    if not counts:
        return None
    return max(counts, key=lambda days: (counts[days], latest[days]))


async def for_client(
    db: AsyncSession, client: Client, *, today: date
) -> ClientDefaults:
    key = nip_key(client.nip)
    if not key:
        return ClientDefaults()
    address_l1 = address_l2 = country = ""
    party = await db.scalar(
        select(FinanceCounterparty)
        .where(FinanceCounterparty.id_value.in_((key, f"PL{key}")))
        .where(FinanceCounterparty.street.is_not(None))
        .order_by(FinanceCounterparty.id.desc())
        .limit(1)
    )
    if party is not None and (party.street or "").strip():
        address_l1 = party.street.strip()
        address_l2 = " ".join(p for p in (party.postal_code, party.city) if p)
        country = party.country or ""

    rows = (
        await db.execute(
            select(
                ClientSalesInvoice.buyer_nip,
                ClientSalesInvoice.buyer_foreign_id,
                ClientSalesInvoice.buyer_address_line1,
                ClientSalesInvoice.buyer_address_line2,
                ClientSalesInvoice.buyer_country,
                ClientSalesInvoice.issue_date,
                ClientSalesInvoice.due_date,
            )
            .where(
                ClientSalesInvoice.client_id == client.id,
                ClientSalesInvoice.invoice_kind == "original",
                ClientSalesInvoice.issue_date >= today - timedelta(days=HISTORY_DAYS),
            )
            .order_by(
                ClientSalesInvoice.issue_date.desc(), ClientSalesInvoice.id.desc()
            )
        )
    ).all()
    own = [row for row in rows if nip_key(row.buyer_nip or row.buyer_foreign_id) == key]
    if not address_l1:
        for invoice in own:
            if (invoice.buyer_address_line1 or "").strip():
                address_l1 = invoice.buyer_address_line1.strip()
                address_l2 = (invoice.buyer_address_line2 or "").strip()
                country = invoice.buyer_country or ""
                break
    term = usual_term(
        [
            (invoice.issue_date, invoice.due_date)
            for invoice in own
            if invoice.issue_date is not None and invoice.due_date is not None
        ]
    )
    return ClientDefaults(
        address_l1=address_l1[:255],
        address_l2=address_l2[:255],
        country=country.upper()[:2],
        payment_days=term,
    )
