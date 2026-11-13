"""Odczyt faktury FA(2)/FA(3) z KSeF w zakresie potrzebnym do e-faktury Peppol.

``services/hr/ksef/fa.py`` czyta to, czego potrzebują Rozliczenia (kwoty,
okres, pozycje w skrócie). E-faktura potrzebuje więcej: adresów stron, VAT UE
nabywcy, rabatu pozycji (``P_10``), stawek VAT, kwot VAT w PLN przy walucie
(``P_14_*W``), rachunków, ``DodatkowyOpis`` i danych faktury korygowanej.

Ten sam bezpieczny parser co ``fa`` (bez DTD i encji, bez sieci, limit
rozmiaru): najpierw ``fa.parse_invoice`` sprawdza plik i podstawowe pola.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from lxml import etree

from app.services.hr.ksef import fa

_CENT = Decimal("0.01")


class UnsupportedInvoice(ValueError):
    """Faktura poprawna, ale bez danych, z których zbudujemy e-fakturę."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

VAT_PLN_FIELDS = ("P_14_1W", "P_14_2W", "P_14_3W", "P_14_4W")
#: Pola VAT per stawka w FA(3) (kwoty w walucie faktury).
VAT_RATE_FIELDS = ("P_14_1", "P_14_2", "P_14_3", "P_14_4", "P_14_5")


@dataclass(frozen=True)
class FaParty:
    name: Optional[str]
    nip: Optional[str]
    #: Kod kraju i numer VAT UE nabywcy bez polskiego NIP-u (``KodUE``, ``NrVatUE``).
    eu_country: Optional[str]
    eu_vat: Optional[str]
    country: Optional[str]
    line1: Optional[str]
    line2: Optional[str]

    @property
    def vat_id(self) -> Optional[str]:
        """Numer VAT z prefiksem kraju („PL5711707392”, „FI28583949”)."""

        if self.eu_country and self.eu_vat:
            number = self.eu_vat.replace(" ", "").upper()
            country = self.eu_country.upper()
            return number if number.startswith(country) else f"{country}{number}"
        if self.nip:
            return f"PL{self.nip}"
        return None


@dataclass(frozen=True)
class FaLine:
    number: Optional[str]
    uu_id: Optional[str]
    name: str
    unit: Optional[str]
    quantity: Optional[Decimal]
    #: Cena jednostkowa netto przed rabatem (``P_9A``).
    unit_price: Optional[Decimal]
    #: Kwota rabatu pozycji (``P_10``), gdy nie jest wliczona w cenę.
    discount: Optional[Decimal]
    net: Decimal
    vat_rate: Optional[str]
    before: bool = False


@dataclass(frozen=True)
class FaAccount:
    number: str
    swift: Optional[str]


@dataclass(frozen=True)
class FaCorrected:
    invoice_number: Optional[str]
    ksef_number: Optional[str]
    issue_date: Optional[date]


@dataclass(frozen=True)
class FaDocument:
    number: str
    issue_date: date
    sale_date: Optional[date]
    period_from: Optional[date]
    period_to: Optional[date]
    currency: str
    kind: str
    seller: FaParty
    buyer: FaParty
    lines: tuple[FaLine, ...]
    net_total: Optional[Decimal]
    vat_total: Decimal
    vat_total_pln: Optional[Decimal]
    #: VAT z faktury per pole (``P_14_1`` → kwota); w korekcie to różnice.
    vat_by_field: dict[str, Decimal]
    gross_total: Decimal
    due_date: Optional[date]
    accounts: tuple[FaAccount, ...] = ()
    notes: tuple[str, ...] = ()
    order_refs: tuple[str, ...] = ()
    corrected: tuple[FaCorrected, ...] = ()
    correction_reason: Optional[str] = None
    reverse_charge: bool = False


def _text(node: Any, *path: str, limit: int = 1024) -> Optional[str]:
    current = node
    for name in path:
        if current is None:
            return None
        current = current.find(f"{{*}}{name}")
    if current is None or current.text is None:
        return None
    value = " ".join(current.text.split())
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
        value = Decimal(raw.replace(",", ".").replace(" ", ""))
    except InvalidOperation:
        raise fa.InvoiceParseError("bad_amount") from None
    if not value.is_finite():
        raise fa.InvoiceParseError("bad_amount")
    return value


def _money(raw: Optional[str]) -> Optional[Decimal]:
    value = _decimal(raw)
    return None if value is None else value.quantize(_CENT)


def _party(root: Any, tag: str) -> FaParty:
    node = root.find(f"{{*}}{tag}")
    ident = node.find("{*}DaneIdentyfikacyjne") if node is not None else None
    address = node.find("{*}Adres") if node is not None else None
    return FaParty(
        name=_text(ident, "Nazwa", limit=512),
        nip=_text(ident, "NIP", limit=10),
        eu_country=_text(ident, "KodUE", limit=4),
        eu_vat=_text(ident, "NrVatUE", limit=32),
        country=_text(address, "KodKraju", limit=2),
        line1=_text(address, "AdresL1", limit=512),
        line2=_text(address, "AdresL2", limit=512),
    )


def _lines(invoice: Any) -> tuple[FaLine, ...]:
    out = []
    for row in invoice.iterfind("{*}FaWiersz"):
        net = _money(_text(row, "P_11"))
        if net is None:
            # Bez P_11 (faktura liczona od brutto, P_11A) netto pozycji nie ma
            # w pliku, a zgadywanie dałoby e-fakturę inną niż w KSeF.
            raise UnsupportedInvoice("gross_lines")
        out.append(
            FaLine(
                number=_text(row, "NrWierszaFa", limit=32),
                uu_id=_text(row, "UU_ID", limit=64),
                name=_text(row, "P_7", limit=1024) or "",
                unit=_text(row, "P_8A", limit=32),
                quantity=_decimal(_text(row, "P_8B")),
                unit_price=_decimal(_text(row, "P_9A")),
                discount=_money(_text(row, "P_10")),
                net=net,
                vat_rate=_text(row, "P_12", limit=8),
                before=_text(row, "StanPrzed") == "1",
            )
        )
    return tuple(out)


def _sum(invoice: Any, fields: tuple[str, ...]) -> Optional[Decimal]:
    values = [_money(_text(invoice, name)) for name in fields]
    present = [value for value in values if value is not None]
    return sum(present, Decimal("0")) if present else None


def read(xml: bytes) -> FaDocument:
    """Faktura z KSeF → ``FaDocument``; zły plik = ``fa.InvoiceParseError``,
    pozycje bez netto = ``UnsupportedInvoice('gross_lines')``."""

    base = fa.parse_invoice(xml)
    root = etree.fromstring(xml, fa._parser())  # noqa: SLF001 — ten sam bezpieczny parser
    invoice = root.find("{*}Fa")
    due_dates = [
        day
        for day in (
            _date(node.text)
            for node in invoice.iterfind("{*}Platnosc/{*}TerminPlatnosci/{*}Termin")
        )
        if day is not None
    ]
    accounts = []
    for node in invoice.iterfind("{*}Platnosc/{*}RachunekBankowy"):
        number = _text(node, "NrRB", limit=64)
        if number:
            accounts.append(FaAccount(number=number, swift=_text(node, "SWIFT", limit=16)))
    notes = []
    for node in invoice.iterfind("{*}DodatkowyOpis"):
        value = _text(node, "Wartosc", limit=512)
        if value:
            notes.append(value)
    refs = [
        value
        for value in (
            " ".join((node.text or "").split())[:256]
            for node in invoice.iterfind(
                "{*}WarunkiTransakcji/{*}Zamowienia/{*}NrZamowienia"
            )
        )
        if value
    ]
    corrected = tuple(
        FaCorrected(
            invoice_number=_text(node, "NrFaKorygowanej", limit=256),
            ksef_number=_text(node, "NrKSeFFaKorygowanej", limit=64),
            issue_date=_date(_text(node, "DataWystFaKorygowanej")),
        )
        for node in invoice.iterfind("{*}DaneFaKorygowanej")
    )
    return FaDocument(
        number=base.invoice_number,
        issue_date=base.issue_date,
        sale_date=_date(_text(invoice, "P_6")),
        period_from=_date(_text(invoice, "OkresFa", "P_6_Od")),
        period_to=_date(_text(invoice, "OkresFa", "P_6_Do")),
        currency=base.currency,
        kind=base.kind,
        seller=_party(root, "Podmiot1"),
        buyer=_party(root, "Podmiot2"),
        lines=_lines(invoice),
        net_total=base.net_amount,
        vat_total=base.vat_amount,
        vat_total_pln=_sum(invoice, VAT_PLN_FIELDS),
        vat_by_field={
            name: amount
            for name in VAT_RATE_FIELDS
            if (amount := _money(_text(invoice, name))) is not None
        },
        gross_total=base.gross_amount,
        due_date=min(due_dates) if due_dates else None,
        accounts=tuple(accounts),
        notes=tuple(dict.fromkeys(notes)),
        order_refs=tuple(dict.fromkeys(refs)),
        corrected=corrected,
        correction_reason=base.correction_reason,
        reverse_charge=_text(invoice, "Adnotacje", "P_18") == "1",
    )
