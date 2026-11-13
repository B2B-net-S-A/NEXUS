"""Budowa XML-a faktury FA(3) z faktury wystawianej w NEXUSIE (E4).

Schemat ``http://crd.gov.pl/wzor/2025/06/25/13775/`` (FA(3), ``1-0E``),
kolejność elementów jak w schemacie MF. Odczyt tego samego pliku robi
``services/hr/ksef/fa.py`` — testy sprawdzają „round-trip” (zbuduj → przeczytaj).

Co budujemy:

* ``Naglowek`` — ``FA (3)``, ``1-0E``, wariant 3, czas wytworzenia, ``SystemInfo``,
* ``Podmiot1`` — sprzedawca z ustawień (NIP, nazwa, adres),
* ``Podmiot2`` — nabywca: polski NIP, VAT UE (``KodUE`` + ``NrVatUE``), numer
  spoza UE (``KodKraju`` + ``NrID``) albo ``BrakID``; adres; ``JST`` i ``GV`` = 2,
* ``Fa`` — waluta, ``P_1`` data wystawienia, ``P_2`` numer, ``P_6`` albo
  ``OkresFa``, sumy ``P_13_x``/``P_14_x`` per stawka (``P_14_xW`` w złotych
  przy walucie obcej), ``P_15``, ``Adnotacje`` (odwrotne obciążenie przy
  ``np II``, zwolnienie z podstawą przy ``zw``), ``RodzajFaktury``
  (``VAT``/``KOR``/``ZAL``), dane faktury korygowanej, ``FaWiersz`` (korekta:
  wiersze „przed” z ``StanPrzed``), ``Platnosc`` (termin, przelew, rachunek),
  ``WarunkiTransakcji`` (numer zamówienia klienta), dla zaliczkowej
  ``Zamowienie`` z wierszami zamówienia.

Kwoty: wartość pozycji = ilość × cena netto, zaokrąglona do grosza; VAT liczony
od sumy wartości netto w stawce (art. 106e ust. 1 pkt 14). W korekcie sumy to
różnice „po − przed” w każdej stawce. Kurs waluty: ``KursWaluty`` w pozycji
i ``P_14_xW`` = VAT × kurs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Optional

from lxml import etree

NAMESPACE = "http://crd.gov.pl/wzor/2025/06/25/13775/"
SYSTEM_CODE = "FA (3)"
SCHEMA_VERSION = "1-0E"
FORM_VARIANT = "3"
SYSTEM_INFO = "NEXUS"
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
#: Przelew (``FormaPlatnosci`` = 6).
PAYMENT_TRANSFER = "6"
MAX_LINES = 500
NAME_MAX = 512
#: Kody krajów UE w ``KodUE`` (Grecja to ``EL``, Irlandia Płn. ``XI``).
EU_CODES = frozenset(
    {
        "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR",
        "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PT", "RO", "SE",
        "SI", "SK", "XI",
    }
)  # fmt: skip


@dataclass(frozen=True)
class VatRate:
    code: str
    label: str
    percent: Decimal
    net_field: str
    vat_field: Optional[str] = None
    vat_pln_field: Optional[str] = None


#: Stawki ``P_12`` FA(3) i pola sum. Kolejność = kolejność pól w schemacie.
VAT_RATES: dict[str, VatRate] = {
    rate.code: rate
    for rate in (
        VatRate("23", "23%", Decimal("23"), "P_13_1", "P_14_1", "P_14_1W"),
        VatRate("8", "8%", Decimal("8"), "P_13_2", "P_14_2", "P_14_2W"),
        VatRate("5", "5%", Decimal("5"), "P_13_3", "P_14_3", "P_14_3W"),
        VatRate("0 KR", "0% (kraj)", ZERO, "P_13_6_1"),
        VatRate("0 EX", "0% eksport", ZERO, "P_13_6_3"),
        VatRate("zw", "zw.", ZERO, "P_13_7"),
        VatRate("np I", "np. (poza krajem)", ZERO, "P_13_8"),
        VatRate("np II", "np. — usługi w UE, odwrotne obciążenie", ZERO, "P_13_9"),
    )
}
REVERSE_CHARGE_RATES = frozenset({"np II"})


class InvoiceBuildError(ValueError):
    """Szkic nie nadaje się do wysłania — komunikat dla Finansów."""


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def decimal_or_none(raw: Any) -> Optional[Decimal]:
    if raw is None or raw == "":
        return None
    try:
        value = Decimal(str(raw).replace(",", ".").replace(" ", ""))
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def plain(value: Decimal) -> str:
    """Liczba bez zbędnych zer i bez notacji wykładniczej (``21.000`` → ``21``)."""

    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return format(normalized.quantize(Decimal("1")), "f")
    return format(normalized, "f")


def line_net(line: dict[str, Any]) -> Optional[Decimal]:
    quantity = decimal_or_none(line.get("quantity"))
    price = decimal_or_none(line.get("unit_price"))
    if quantity is None or price is None:
        return None
    return money(quantity * price)


@dataclass(frozen=True)
class RateTotal:
    rate: VatRate
    net: Decimal
    vat: Decimal


@dataclass(frozen=True)
class Totals:
    rates: tuple[RateTotal, ...]
    net: Decimal
    vat: Decimal
    gross: Decimal


def _by_rate(lines: list[dict[str, Any]]) -> dict[str, Decimal]:
    sums: dict[str, Decimal] = {}
    for line in lines:
        net = line_net(line)
        code = str(line.get("vat_rate") or "")
        if net is None or code not in VAT_RATES:
            raise InvoiceBuildError(
                f"Pozycja „{(line.get('name') or '')[:60]}” nie ma ilości, ceny albo stawki VAT."
            )
        sums[code] = sums.get(code, ZERO) + net
    return sums


def _vat(code: str, net: Decimal) -> Decimal:
    return money(net * VAT_RATES[code].percent / Decimal("100"))


def totals(
    lines: list[dict[str, Any]], lines_before: Optional[list[dict[str, Any]]] = None
) -> Totals:
    """Sumy per stawka; z ``lines_before`` — różnice korekty (po − przed)."""

    after = _by_rate(lines)
    before = _by_rate(lines_before) if lines_before else {}
    out: list[RateTotal] = []
    for code, rate in VAT_RATES.items():
        if code not in after and code not in before:
            continue
        net = after.get(code, ZERO) - before.get(code, ZERO)
        vat = _vat(code, after.get(code, ZERO)) - _vat(code, before.get(code, ZERO))
        out.append(RateTotal(rate, money(net), money(vat)))
    net_total = money(sum((r.net for r in out), ZERO))
    vat_total = money(sum((r.vat for r in out), ZERO))
    return Totals(tuple(out), net_total, vat_total, money(net_total + vat_total))


# ── Nabywca ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BuyerId:
    """Identyfikator nabywcy w ``Podmiot2/DaneIdentyfikacyjne``."""

    kind: str  # nip | eu | other | none
    nip: Optional[str] = None
    country: Optional[str] = None
    number: Optional[str] = None


def buyer_id(raw: Optional[str]) -> BuyerId:
    """Z numeru w postaci ``clients.nip`` (``1111111111``, ``FI12345678``)."""

    value = "".join(ch for ch in str(raw or "").upper() if ch.isalnum())
    if not value:
        return BuyerId("none")
    if value.startswith("PL") and value[2:].isdigit() and len(value) == 12:
        value = value[2:]
    if value.isdigit() and len(value) == 10:
        return BuyerId("nip", nip=value)
    prefix = value[:2]
    if prefix.isalpha() and len(value) > 2:
        code = "EL" if prefix == "GR" else prefix
        if code in EU_CODES:
            return BuyerId("eu", country=code, number=value[2:])
        return BuyerId("other", country=prefix, number=value[2:])
    return BuyerId("other", number=value)


# ── Dokument ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Party:
    name: str
    address_l1: str
    address_l2: Optional[str] = None
    country: str = "PL"


@dataclass(frozen=True)
class BankAccount:
    number: str
    bank: Optional[str] = None
    swift: Optional[str] = None


@dataclass(frozen=True)
class CorrectedInvoice:
    number: str
    issue_date: date
    ksef_number: Optional[str]
    reason: Optional[str]


@dataclass(frozen=True)
class InvoiceDocument:
    invoice_type: str  # VAT | KOR | ZAL
    number: str
    issue_date: date
    currency: str
    seller_nip: str
    seller: Party
    buyer: Party
    buyer_ident: BuyerId
    lines: list[dict[str, Any]]
    lines_before: list[dict[str, Any]] = field(default_factory=list)
    sale_date: Optional[date] = None
    period_from: Optional[date] = None
    period_to: Optional[date] = None
    issue_place: Optional[str] = None
    fx_rate: Optional[Decimal] = None
    due_date: Optional[date] = None
    account: Optional[BankAccount] = None
    client_order_number: Optional[str] = None
    notes: Optional[str] = None
    exemption_basis: Optional[str] = None
    corrected: Optional[CorrectedInvoice] = None
    created_at: Optional[datetime] = None


def _sub(parent: etree._Element, name: str, value: Any = None) -> etree._Element:
    node = etree.SubElement(parent, f"{{{NAMESPACE}}}{name}")
    if value is not None:
        node.text = value if isinstance(value, str) else str(value)
    return node


def _amount(value: Decimal) -> str:
    return format(money(value), "f")


def _clean(text: Optional[str], limit: int = NAME_MAX) -> Optional[str]:
    if text is None:
        return None
    value = " ".join(str(text).split())[:limit]
    return value or None


def validate(doc: InvoiceDocument) -> None:
    if doc.invoice_type not in ("VAT", "KOR", "ZAL"):
        raise InvoiceBuildError("Nieobsługiwany rodzaj faktury.")
    if not doc.number:
        raise InvoiceBuildError("Faktura nie ma numeru.")
    if not doc.seller_nip or not doc.seller.name or not doc.seller.address_l1:
        raise InvoiceBuildError(
            "Uzupełnij dane sprzedawcy (nazwa, NIP, adres) w ustawieniach wystawiania."
        )
    if not doc.buyer.name or not doc.buyer.address_l1:
        raise InvoiceBuildError("Uzupełnij nazwę i adres nabywcy.")
    if not doc.lines:
        raise InvoiceBuildError("Faktura nie ma pozycji.")
    if len(doc.lines) + len(doc.lines_before) > MAX_LINES:
        raise InvoiceBuildError("Faktura ma więcej niż 500 pozycji.")
    if doc.currency != "PLN" and (doc.fx_rate is None or doc.fx_rate <= 0):
        raise InvoiceBuildError(
            "Brak kursu NBP waluty z dnia roboczego przed datą dostawy."
        )
    codes = {str(line.get("vat_rate")) for line in [*doc.lines, *doc.lines_before]}
    if "zw" in codes and not _clean(doc.exemption_basis, 256):
        raise InvoiceBuildError(
            "Pozycja zwolniona wymaga podstawy zwolnienia w ustawieniach wystawiania."
        )
    if doc.invoice_type == "KOR" and doc.corrected is None:
        raise InvoiceBuildError("Korekta musi wskazywać fakturę korygowaną.")
    totals(doc.lines, doc.lines_before)


def _podmiot1(root: etree._Element, doc: InvoiceDocument) -> None:
    node = _sub(root, "Podmiot1")
    ident = _sub(node, "DaneIdentyfikacyjne")
    _sub(ident, "NIP", doc.seller_nip)
    _sub(ident, "Nazwa", _clean(doc.seller.name))
    _address(node, doc.seller)


def _address(parent: etree._Element, party: Party) -> None:
    address = _sub(parent, "Adres")
    _sub(address, "KodKraju", (party.country or "PL").upper()[:2])
    _sub(address, "AdresL1", _clean(party.address_l1))
    if _clean(party.address_l2):
        _sub(address, "AdresL2", _clean(party.address_l2))


def _podmiot2(root: etree._Element, doc: InvoiceDocument) -> None:
    node = _sub(root, "Podmiot2")
    ident = _sub(node, "DaneIdentyfikacyjne")
    buyer = doc.buyer_ident
    if buyer.kind == "nip":
        _sub(ident, "NIP", buyer.nip)
    elif buyer.kind == "eu":
        _sub(ident, "KodUE", buyer.country)
        _sub(ident, "NrVatUE", buyer.number)
    elif buyer.kind == "other" and buyer.number:
        if buyer.country:
            _sub(ident, "KodKraju", buyer.country)
        _sub(ident, "NrID", buyer.number)
    else:
        _sub(ident, "BrakID", "1")
    _sub(ident, "Nazwa", _clean(doc.buyer.name))
    _address(node, doc.buyer)
    _sub(node, "JST", "2")
    _sub(node, "GV", "2")


def _line(
    parent: etree._Element,
    index: int,
    line: dict[str, Any],
    doc: InvoiceDocument,
    *,
    before: bool = False,
) -> None:
    row = _sub(parent, "FaWiersz")
    _sub(row, "NrWierszaFa", index)
    _sub(row, "P_7", _clean(line.get("name")) or "Usługa")
    if line.get("unit"):
        _sub(row, "P_8A", _clean(line.get("unit"), 32))
    _sub(row, "P_8B", plain(decimal_or_none(line.get("quantity")) or ZERO))
    _sub(row, "P_9A", plain(decimal_or_none(line.get("unit_price")) or ZERO))
    _sub(row, "P_11", _amount(line_net(line) or ZERO))
    _sub(row, "P_12", str(line.get("vat_rate")))
    if doc.currency != "PLN" and doc.fx_rate is not None:
        _sub(row, "KursWaluty", plain(doc.fx_rate))
    if before:
        _sub(row, "StanPrzed", "1")


def _sums(fa: etree._Element, doc: InvoiceDocument, result: Totals) -> None:
    for item in result.rates:
        rate = item.rate
        _sub(fa, rate.net_field, _amount(item.net))
        if rate.vat_field:
            _sub(fa, rate.vat_field, _amount(item.vat))
            if doc.currency != "PLN" and rate.vat_pln_field and doc.fx_rate:
                _sub(fa, rate.vat_pln_field, _amount(item.vat * doc.fx_rate))
    _sub(fa, "P_15", _amount(result.gross))


def _adnotacje(fa: etree._Element, doc: InvoiceDocument) -> None:
    codes = {str(line.get("vat_rate")) for line in doc.lines}
    node = _sub(fa, "Adnotacje")
    _sub(node, "P_16", "2")
    _sub(node, "P_17", "2")
    _sub(node, "P_18", "1" if codes & REVERSE_CHARGE_RATES else "2")
    _sub(node, "P_18A", "2")
    exemption = _sub(node, "Zwolnienie")
    if "zw" in codes:
        _sub(exemption, "P_19", "1")
        _sub(exemption, "P_19A", _clean(doc.exemption_basis, 256))
    else:
        _sub(exemption, "P_19N", "1")
    transport = _sub(node, "NoweSrodkiTransportu")
    _sub(transport, "P_22N", "1")
    _sub(node, "P_23", "2")
    margin = _sub(node, "PMarzy")
    _sub(margin, "P_PMarzyN", "1")


def _correction(fa: etree._Element, doc: InvoiceDocument) -> None:
    corrected = doc.corrected
    assert corrected is not None
    if _clean(corrected.reason, 256):
        _sub(fa, "PrzyczynaKorekty", _clean(corrected.reason, 256))
    data = _sub(fa, "DaneFaKorygowanej")
    _sub(data, "DataWystFaKorygowanej", corrected.issue_date.isoformat())
    _sub(data, "NrFaKorygowanej", corrected.number)
    if corrected.ksef_number:
        _sub(data, "NrKSeF", "1")
        _sub(data, "NrKSeFFaKorygowanej", corrected.ksef_number)
    else:
        _sub(data, "NrKSeFN", "1")


def _payment(fa: etree._Element, doc: InvoiceDocument) -> None:
    if doc.due_date is None and doc.account is None:
        return
    node = _sub(fa, "Platnosc")
    if doc.due_date is not None:
        term = _sub(node, "TerminPlatnosci")
        _sub(term, "Termin", doc.due_date.isoformat())
    _sub(node, "FormaPlatnosci", PAYMENT_TRANSFER)
    if doc.account is not None and doc.account.number:
        account = _sub(node, "RachunekBankowy")
        _sub(account, "NrRB", "".join(doc.account.number.split()))
        if _clean(doc.account.swift, 11):
            _sub(account, "SWIFT", _clean(doc.account.swift, 11))
        if _clean(doc.account.bank, 256):
            _sub(account, "NazwaBanku", _clean(doc.account.bank, 256))


def _order(fa: etree._Element, doc: InvoiceDocument, result: Totals) -> None:
    """Zaliczkowa: zamówienie, na poczet którego wpłynęła zaliczka (pełna wartość)."""

    node = _sub(fa, "Zamowienie")
    _sub(node, "WartoscZamowienia", _amount(result.gross))
    for index, line in enumerate(doc.lines, start=1):
        row = _sub(node, "ZamowienieWiersz")
        net = line_net(line) or ZERO
        code = str(line.get("vat_rate"))
        _sub(row, "NrWierszaZam", index)
        _sub(row, "P_7Z", _clean(line.get("name")) or "Usługa")
        if line.get("unit"):
            _sub(row, "P_8AZ", _clean(line.get("unit"), 32))
        _sub(row, "P_8BZ", plain(decimal_or_none(line.get("quantity")) or ZERO))
        _sub(row, "P_9AZ", plain(decimal_or_none(line.get("unit_price")) or ZERO))
        _sub(row, "P_11NettoZ", _amount(net))
        if VAT_RATES[code].vat_field:
            _sub(row, "P_11VatZ", _amount(_vat(code, net)))
        _sub(row, "P_12Z", code)


def build_xml(doc: InvoiceDocument) -> bytes:
    """XML FA(3) w UTF-8; ``InvoiceBuildError``, gdy szkic jest niekompletny."""

    validate(doc)
    result = totals(doc.lines, doc.lines_before)
    root = etree.Element(f"{{{NAMESPACE}}}Faktura", nsmap={None: NAMESPACE})
    header = _sub(root, "Naglowek")
    code = _sub(header, "KodFormularza", "FA")
    code.set("kodSystemowy", SYSTEM_CODE)
    code.set("wersjaSchemy", SCHEMA_VERSION)
    _sub(header, "WariantFormularza", FORM_VARIANT)
    created = (doc.created_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    _sub(header, "DataWytworzeniaFa", created.strftime("%Y-%m-%dT%H:%M:%SZ"))
    _sub(header, "SystemInfo", SYSTEM_INFO)
    _podmiot1(root, doc)
    _podmiot2(root, doc)

    fa = _sub(root, "Fa")
    _sub(fa, "KodWaluty", doc.currency)
    _sub(fa, "P_1", doc.issue_date.isoformat())
    if _clean(doc.issue_place, 256):
        _sub(fa, "P_1M", _clean(doc.issue_place, 256))
    _sub(fa, "P_2", doc.number)
    if doc.invoice_type != "ZAL" and doc.period_from and doc.period_to:
        period = _sub(fa, "OkresFa")
        _sub(period, "P_6_Od", doc.period_from.isoformat())
        _sub(period, "P_6_Do", doc.period_to.isoformat())
    elif doc.sale_date and doc.sale_date != doc.issue_date:
        _sub(fa, "P_6", doc.sale_date.isoformat())
    _sums(fa, doc, result)
    if doc.invoice_type == "ZAL" and doc.currency != "PLN" and doc.fx_rate:
        _sub(fa, "KursWalutyZ", plain(doc.fx_rate))
    _adnotacje(fa, doc)
    _sub(fa, "RodzajFaktury", doc.invoice_type)
    if doc.invoice_type == "KOR":
        _correction(fa, doc)
    if _clean(doc.notes, 256):
        extra = _sub(fa, "DodatkowyOpis")
        _sub(extra, "Klucz", "Uwagi")
        _sub(extra, "Wartosc", _clean(doc.notes, 256))
    if doc.invoice_type != "ZAL":
        index = 0
        for line in doc.lines_before:
            index += 1
            _line(fa, index, line, doc, before=True)
        for line in doc.lines:
            index += 1
            _line(fa, index, line, doc)
    _payment(fa, doc)
    if _clean(doc.client_order_number, 256):
        terms = _sub(fa, "WarunkiTransakcji")
        orders = _sub(terms, "Zamowienia")
        _sub(orders, "NrZamowienia", _clean(doc.client_order_number, 256))
    if doc.invoice_type == "ZAL":
        _order(fa, doc, result)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


__all__ = [
    "EU_CODES",
    "VAT_RATES",
    "BankAccount",
    "BuyerId",
    "CorrectedInvoice",
    "InvoiceBuildError",
    "InvoiceDocument",
    "Party",
    "Totals",
    "build_xml",
    "buyer_id",
    "line_net",
    "money",
    "totals",
]
