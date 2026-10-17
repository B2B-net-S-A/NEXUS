"""Odczyt faktury FA(2)/FA(3) z KSeF — tylko pola potrzebne Rozliczeniom.

Schemat ``http://crd.gov.pl/wzor/2025/06/25/13775/`` (FA(3)) i poprzedni FA(2);
elementy czytamy po nazwie lokalnej, więc oba warianty idą tą samą drogą.

Co bierzemy:

* sprzedawca — ``Podmiot1/DaneIdentyfikacyjne/NIP`` i ``Nazwa``; nabywca —
  ``Podmiot2/DaneIdentyfikacyjne/NIP`` (sprawdzamy, że to spółka),
* ``Fa/P_2`` numer, ``P_1`` data wystawienia, ``KodWaluty``, ``RodzajFaktury``
  (``KOR``/``KOR_ZAL``/``KOR_ROZ`` = korekta z ``DaneFaKorygowanej``),
* kwoty: netto = suma ``P_13_*``, VAT = suma ``P_14_1``–``P_14_5`` (w walucie
  faktury), brutto = ``P_15``; w korekcie to RÓŻNICE (mogą być ujemne),
* okres: ``OkresFa/P_6_Do``, potem ``P_6``, potem wspólny miesiąc ``P_6A``
  pozycji; bez żadnej z tych dat okres zostaje pusty (dopasowanie decyduje
  wtedy po osobie), bo data wystawienia z początku następnego miesiąca
  wskazałaby zły miesiąc,
* pozycje ``FaWiersz`` w kształcie czytanym przez widok rozbieżności:
  ``name, quantity, unit, unit_price, net, vat_rate`` (kwoty jako napisy
  dziesiętne z kropką); wiersz „stan przed korektą” ma ``before_correction``.

XML z zewnątrz: bez DTD i encji (odrzucamy ``<!DOCTYPE``), bez sieci, limit
rozmiaru (KSeF przyjmuje do 3 MB z załącznikiem) i liczby pozycji.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from lxml import etree

from app.services.hr_settlement_schema import AMOUNT_MAX, CURRENCIES

MAX_XML_BYTES = 5 * 1024 * 1024
MAX_ITEMS = 500
SUPPORTED_VARIANTS = ("2", "3")
CORRECTION_TYPES = frozenset({"KOR", "KOR_ZAL", "KOR_ROZ"})
NET_FIELDS = (
    "P_13_1",
    "P_13_2",
    "P_13_3",
    "P_13_4",
    "P_13_5",
    "P_13_6",
    "P_13_6_1",
    "P_13_6_2",
    "P_13_6_3",
    "P_13_7",
    "P_13_8",
    "P_13_9",
    "P_13_10",
    "P_13_11",
)
VAT_FIELDS = ("P_14_1", "P_14_2", "P_14_3", "P_14_4", "P_14_5")
_LIMIT = Decimal(AMOUNT_MAX)
_CENT = Decimal("0.01")
_NIP_RE = re.compile(r"^\d{10}$")
#: Lata miesiąca rozliczenia, które przyjmuje ``ck_payroll_invoices_period``.
PERIOD_YEARS = (2020, 2100)

PARSE_ERRORS = {
    "too_large": "plik faktury jest za duży",
    "doctype": "plik faktury ma niedozwoloną deklarację DTD",
    "malformed": "plik faktury nie jest poprawnym XML-em",
    "not_invoice": "plik nie jest fakturą FA",
    "unsupported_form": "nieobsługiwany wariant faktury (oczekiwany FA(2) albo FA(3))",
    "missing_seller": "brak NIP-u sprzedawcy",
    "missing_number": "brak numeru faktury",
    "missing_issue_date": "brak daty wystawienia",
    "bad_amount": "kwota w fakturze ma zły format",
    "unsupported_currency": "waluta faktury spoza PLN, EUR i USD",
    "missing_amounts": "brak kwoty należności (P_15)",
    "too_many_items": "faktura ma więcej niż 500 pozycji",
}


class InvoiceParseError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(PARSE_ERRORS.get(code, code))


@dataclass(frozen=True)
class ParsedInvoice:
    form: str
    seller_nip: str
    seller_name: Optional[str]
    buyer_nip: Optional[str]
    invoice_number: str
    invoice_type: str
    kind: str
    corrected_ksef_number: Optional[str]
    corrected_invoice_number: Optional[str]
    issue_date: date
    sale_date: Optional[date]
    period: Optional[tuple[int, int]]
    currency: str
    #: ``None`` = faktura bez sum ``P_13_*`` (np. uproszczona) — kwota z metadanych.
    net_amount: Optional[Decimal]
    vat_amount: Decimal
    gross_amount: Decimal
    items: list[dict[str, Any]] = field(default_factory=list)


def _parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
        remove_comments=True,
        remove_pis=True,
    )


def _child(parent: Any, *path: str) -> Any:
    node = parent
    for name in path:
        if node is None:
            return None
        node = node.find(f"{{*}}{name}")
    return node


def _text(parent: Any, *path: str, limit: int = 512) -> Optional[str]:
    node = _child(parent, *path)
    if node is None or node.text is None:
        return None
    value = " ".join(node.text.split())
    return value[:limit] or None


def _date(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _decimal(raw: Optional[str]) -> Optional[Decimal]:
    if raw is None:
        return None
    try:
        value = Decimal(raw.replace(",", "."))
    except InvalidOperation:
        raise InvoiceParseError("bad_amount") from None
    if not value.is_finite() or abs(value) > _LIMIT:
        raise InvoiceParseError("bad_amount")
    return value


def _money(raw: Optional[str]) -> Optional[Decimal]:
    value = _decimal(raw)
    return None if value is None else value.quantize(_CENT)


def _plain(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else format(value, "f")


def _items(fa: Any) -> list[dict[str, Any]]:
    rows = list(fa.iterfind("{*}FaWiersz"))
    if len(rows) > MAX_ITEMS:
        raise InvoiceParseError("too_many_items")
    items = []
    for row in rows:
        item: dict[str, Any] = {
            "name": _text(row, "P_7") or "",
            "quantity": _plain(_decimal(_text(row, "P_8B"))),
            "unit": _text(row, "P_8A", limit=32),
            "unit_price": _plain(_decimal(_text(row, "P_9A"))),
            "net": _plain(_money(_text(row, "P_11"))),
            "vat_rate": _text(row, "P_12", limit=8),
        }
        if _text(row, "StanPrzed") == "1":
            item["before_correction"] = True
        items.append(item)
    return items


def _row_dates(fa: Any) -> list[date]:
    days = []
    for row in fa.iterfind("{*}FaWiersz"):
        if _text(row, "StanPrzed") == "1":
            continue
        day = _date(_text(row, "P_6A"))
        if day is not None:
            days.append(day)
    return days


def _sale(fa: Any) -> tuple[Optional[date], Optional[tuple[int, int]]]:
    """Data sprzedaży i miesiąc rozliczenia (bez zgadywania z daty wystawienia)."""

    sale, period = _sale_and_period(fa)
    if period is not None and not PERIOD_YEARS[0] <= period[0] <= PERIOD_YEARS[1]:
        # Miesiąc spoza zakresu Płac (CHECK bazy) — faktura bez okresu, do przypisania.
        period = None
    return sale, period


def _sale_and_period(fa: Any) -> tuple[Optional[date], Optional[tuple[int, int]]]:
    period_end = _date(_text(fa, "OkresFa", "P_6_Do"))
    if period_end is not None:
        return period_end, (period_end.year, period_end.month)
    sale = _date(_text(fa, "P_6"))
    if sale is not None:
        return sale, (sale.year, sale.month)
    days = _row_dates(fa)
    months = {(day.year, day.month) for day in days}
    if len(months) == 1:
        return max(days), months.pop()
    return None, None


def _sum(fa: Any, fields: tuple[str, ...]) -> Optional[Decimal]:
    values = [_money(_text(fa, name)) for name in fields]
    present = [value for value in values if value is not None]
    return sum(present, Decimal("0")) if present else None


def parse_invoice(xml: bytes) -> ParsedInvoice:
    if len(xml) > MAX_XML_BYTES:
        raise InvoiceParseError("too_large")
    lowered = xml.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise InvoiceParseError("doctype")
    try:
        root = etree.fromstring(xml, _parser())
    except etree.XMLSyntaxError:
        raise InvoiceParseError("malformed") from None
    if etree.QName(root).localname != "Faktura":
        raise InvoiceParseError("not_invoice")
    variant = _text(root, "Naglowek", "WariantFormularza")
    if (
        _text(root, "Naglowek", "KodFormularza") != "FA"
        or variant not in SUPPORTED_VARIANTS
    ):
        raise InvoiceParseError("unsupported_form")
    fa = _child(root, "Fa")
    if fa is None:
        raise InvoiceParseError("not_invoice")

    seller_nip = _text(root, "Podmiot1", "DaneIdentyfikacyjne", "NIP")
    if not seller_nip or not _NIP_RE.match(seller_nip):
        raise InvoiceParseError("missing_seller")
    number = _text(fa, "P_2", limit=256)
    if not number:
        raise InvoiceParseError("missing_number")
    issue_date = _date(_text(fa, "P_1"))
    if issue_date is None:
        raise InvoiceParseError("missing_issue_date")
    currency = (_text(fa, "KodWaluty", limit=3) or "PLN").upper()
    if currency not in CURRENCIES:
        raise InvoiceParseError("unsupported_currency")
    gross = _money(_text(fa, "P_15"))
    if gross is None:
        raise InvoiceParseError("missing_amounts")

    invoice_type = (_text(fa, "RodzajFaktury", limit=16) or "VAT").upper()
    corrected = _child(fa, "DaneFaKorygowanej")
    items = _items(fa)
    net = _sum(fa, NET_FIELDS)
    vat = _sum(fa, VAT_FIELDS)
    sale_date, period = _sale(fa)
    return ParsedInvoice(
        form=f"FA({variant})",
        seller_nip=seller_nip,
        seller_name=_text(root, "Podmiot1", "DaneIdentyfikacyjne", "Nazwa", limit=255),
        buyer_nip=_text(root, "Podmiot2", "DaneIdentyfikacyjne", "NIP", limit=10),
        invoice_number=number,
        invoice_type=invoice_type,
        kind="correction" if invoice_type in CORRECTION_TYPES else "original",
        corrected_ksef_number=_text(corrected, "NrKSeFFaKorygowanej", limit=64),
        corrected_invoice_number=_text(corrected, "NrFaKorygowanej", limit=256),
        issue_date=issue_date,
        sale_date=sale_date,
        period=period,
        currency=currency,
        net_amount=net,
        vat_amount=vat if vat is not None else Decimal("0.00"),
        gross_amount=gross,
        items=items,
    )
