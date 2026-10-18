"""Faktura sprzedażowa z KSeF: parser FA(2)/FA(3) z etapu 4 + pola potrzebne do zamówień.

Kwoty, numer, daty, korekta, pozycje i okres czyta ``services/hr/ksef/fa.py``
(ten sam bezpieczny parser: bez DTD i encji, bez sieci, limit rozmiaru).
Tu dochodzi to, czego faktura od osoby nie potrzebowała:

* nabywca — ``Podmiot2/DaneIdentyfikacyjne/NIP`` (polski NIP) i ``Nazwa``,
* termin płatności — najwcześniejszy ``Platnosc/TerminPlatnosci/Termin``,
* „Zapłacono” w samej fakturze — ``Platnosc/Zaplacono`` = 1 z ``DataZaplaty``,
* teksty, w których szukamy numeru zamówienia klienta:
  ``WarunkiTransakcji/Zamowienia/NrZamowienia``, ``Umowy/NrUmowy`` i wartości
  ``DodatkowyOpis`` (nazwy pozycji są w ``items``),
* okres usługi — z faktury (``OkresFa``, ``P_6``, wspólny miesiąc ``P_6A``),
  a bez nich miesiąc daty wystawienia: brak ``P_6`` w FA oznacza, że data
  sprzedaży jest równa dacie wystawienia (``period_source='issue_date'``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from lxml import etree

from app.services.hr.ksef import fa

MAX_REFS = 20
REF_MAX_LENGTH = 300


@dataclass(frozen=True)
class SalesInvoice:
    base: fa.ParsedInvoice
    buyer_name: Optional[str]
    due_date: Optional[date]
    paid_on: Optional[date]
    period: Optional[tuple[int, int]]
    period_source: Optional[str]
    order_refs: list[str] = field(default_factory=list)


def _texts(nodes: Any) -> list[str]:
    out = []
    for node in nodes:
        if node is None or node.text is None:
            continue
        value = " ".join(node.text.split())[:REF_MAX_LENGTH]
        if value:
            out.append(value)
    return out


def _date(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw.strip()[:10])
    except ValueError:
        return None


def parse_sales_invoice(xml: bytes) -> SalesInvoice:
    """Odczyt faktury sprzedażowej; błędy formatu jak w ``fa`` (``InvoiceParseError``)."""

    base = fa.parse_invoice(xml)
    # ``fa.parse_invoice`` już sprawdził rozmiar, DTD i poprawność XML-a.
    root = etree.fromstring(xml, fa._parser())  # noqa: SLF001 — ten sam bezpieczny parser
    invoice = root.find("{*}Fa")
    buyer = root.find("{*}Podmiot2/{*}DaneIdentyfikacyjne")
    buyer_name = None
    if buyer is not None:
        names = _texts(buyer.iterfind("{*}Nazwa"))
        buyer_name = names[0][:255] if names else None

    due_dates = [
        day
        for day in (
            _date(node.text)
            for node in invoice.iterfind("{*}Platnosc/{*}TerminPlatnosci/{*}Termin")
        )
        if day is not None
    ]
    paid_on = None
    paid = invoice.find("{*}Platnosc/{*}Zaplacono")
    if paid is not None and (paid.text or "").strip() == "1":
        paid_on = _date(invoice.findtext("{*}Platnosc/{*}DataZaplaty"))

    refs: list[str] = []
    for path in (
        "{*}WarunkiTransakcji/{*}Zamowienia/{*}NrZamowienia",
        "{*}WarunkiTransakcji/{*}Umowy/{*}NrUmowy",
        "{*}DodatkowyOpis/{*}Wartosc",
    ):
        refs.extend(_texts(invoice.iterfind(path)))
    refs = list(dict.fromkeys(refs))[:MAX_REFS]

    period = base.period
    period_source: Optional[str] = "invoice" if period is not None else None
    if (
        period is None
        and fa.PERIOD_YEARS[0] <= base.issue_date.year <= fa.PERIOD_YEARS[1]
    ):
        period = (base.issue_date.year, base.issue_date.month)
        period_source = "issue_date"
    return SalesInvoice(
        base=base,
        buyer_name=buyer_name,
        due_date=min(due_dates) if due_dates else None,
        paid_on=paid_on,
        period=period,
        period_source=period_source,
        order_refs=refs,
    )


__all__ = ["SalesInvoice", "parse_sales_invoice"]
