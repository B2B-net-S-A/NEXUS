"""Faktura FA(3) z KSeF → UBL 2.1 Peppol BIS Billing 3 (Invoice albo CreditNote).

Czysta funkcja: wejście to ``FaDocument`` (``fa_reader``) i adresy Peppol,
wyjście to bajty XML-a i rodzaj dokumentu. Nic nie wychodzi do sieci, nic nie
trafia do bazy; walidację reguł robi ``validation``.

Mapowanie (plan Nordei N2, prototyp z faktury z 11.2026):

* cena przed rabatem z umowy ramowej (``P_9A``) to ``cac:Price/cac:AllowanceCharge/
  cbc:BaseAmount``, rabat na jednostkę to ``Amount``, a ``PriceAmount`` = cena po
  rabacie = netto pozycji ÷ ilość. Gdy ta cena nie wychodzi dokładnie (więcej niż
  4 miejsca po przecinku), rabat idzie jako ``AllowanceCharge`` pozycji,
* stawki: „np II” (usługa dla firmy z UE, art. 100 ust. 1 pkt 4) i „oo” to
  odwrotne obciążenie — kategoria ``AE``, 0%, ``VATEX-EU-AE``; liczbowa stawka
  (23, 8, 5…) to ``S``; „np I” (poza UE) to ``O`` z ``VATEX-EU-O`` (bez numerów
  VAT stron, reguła BR-O-02). Zwolnienia i 0% nie występują na fakturach do
  Nordei — konwerter je odrzuca, zamiast zgadywać kod zwolnienia,
* NIDS z opisu pozycji („NIDS:1000007126”) → ``cbc:AccountingCost`` pozycji,
  osoba kontaktowa po stronie klienta („Contact: …”) → ``cbc:BuyerReference``,
* waluta z faktury; przy walucie innej niż PLN i stawce ``S`` VAT w PLN
  (``P_14_*W``) idzie jako drugi ``TaxTotal`` z ``TaxCurrencyCode`` PLN,
* PDF faktury (opcjonalnie) w ``AdditionalDocumentReference``,
* korekta: różnica pozycji „po” i „przed” (``StanPrzed``); suma ujemna to
  ``CreditNote`` (381), dodatnia to ``Invoice`` (380), obie z ``BillingReference``
  do faktury korygowanej. Korekta bez zmiany kwot (np. data sprzedaży) nie ma
  czego przenieść do e-faktury — ``NothingToSend``.

Kolejność elementów jest zgodna ze schematem UBL 2.1 (odbiorca sprawdza XSD).
Sumy kontrolne: suma pozycji musi być równa netto z faktury (``P_13_*``), a VAT
(z ``P_14_x``) i brutto — dokładnie kwotom z KSeF. Różnica = ``ConversionError``, bo e-faktura różna od
faktury w KSeF to dokument, którego nie wolno wysłać.
"""

from __future__ import annotations

import base64
import re
from collections import OrderedDict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from lxml import etree

from app.services.peppol.fa_reader import FaDocument, FaLine, FaParty

NS_INVOICE = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
NS_CREDIT_NOTE = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
NS_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
NS_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
CUSTOMIZATION_ID = (
    "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"
)
PROFILE_ID = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
#: Identyfikatory typu dokumentu w sieci Peppol (dostawca wysyła z nimi plik).
DOCTYPE_IDS = {
    "invoice": (f"{NS_INVOICE}::Invoice##{CUSTOMIZATION_ID}::2.1"),
    "credit_note": (f"{NS_CREDIT_NOTE}::CreditNote##{CUSTOMIZATION_ID}::2.1"),
}

_CENT = Decimal("0.01")
_PRICE = Decimal("0.0001")
_ZERO = Decimal("0")
_NIDS_RE = re.compile(r"NIDS\s*:\s*([0-9][0-9-]*[0-9])", re.IGNORECASE)
_CONTACT_RE = re.compile(r"Contact\s*:?\s*([^,;]+)", re.IGNORECASE)
_POSTAL_CITY_RE = re.compile(r"^([0-9]{2}-?[0-9]{3}|[0-9]{4,6})\s*,?\s+(.+)$")
_LINE_WITH_POSTAL_RE = re.compile(r"^(.*?)[,\s]+([0-9]{2}-[0-9]{3})\s+(.+)$")
_PEPPOL_ID_RE = re.compile(r"^([0-9]{4}):([A-Za-z0-9.\-_:]{1,50})$")

#: Jednostki z faktur (``P_8A``) → kody UN/ECE Rec 20.
_UNITS = {
    "godz.": "HUR",
    "godz": "HUR",
    "godzina": "HUR",
    "godziny": "HUR",
    "godzin": "HUR",
    "h": "HUR",
    "hour": "HUR",
    "hours": "HUR",
    "szt.": "H87",
    "szt": "H87",
    "dzień": "DAY",
    "dni": "DAY",
    "md": "DAY",
    "mies.": "MON",
    "miesiąc": "MON",
}
_STANDARD_RATES = {"23", "22", "8", "7", "5", "4", "3"}
#: Stawka → pole VAT w FA(3) (``P_14_1`` 23/22%, ``P_14_2`` 8/7%, ``P_14_3`` 5%,
#: ``P_14_4`` 4/3%).
_VAT_FIELD = {
    "23": "P_14_1",
    "22": "P_14_1",
    "8": "P_14_2",
    "7": "P_14_2",
    "5": "P_14_3",
    "4": "P_14_4",
    "3": "P_14_4",
}
_REVERSE_RATES = {"np ii", "np", "oo"}
_OUTSIDE_RATES = {"np i"}

ERRORS = {
    "no_lines": "Faktura nie ma pozycji do przeniesienia.",
    "unsupported_rate": "Stawka VAT {rate} nie jest obsługiwana w e-fakturze.",
    "mixed_outside": "Pozycje „np I” (poza UE) razem z innymi stawkami — taką fakturę trzeba wysłać ręcznie.",
    "net_mismatch": "Suma pozycji ({lines}) różni się od netto faktury ({net}).",
    "vat_mismatch": "VAT z pozycji ({lines}) różni się od VAT faktury ({vat}).",
    "gross_mismatch": "Brutto e-faktury ({ubl}) różni się od brutto faktury ({gross}).",
    "missing_buyer_vat": "Brak numeru VAT nabywcy, wymaganego przy odwrotnym obciążeniu.",
    "missing_seller_vat": "Brak NIP-u sprzedawcy.",
    "bad_peppol_id": "Adres Peppol {value} ma zły format (oczekiwany „schemat:numer”).",
    "missing_corrected": "Korekta bez numeru faktury korygowanej.",
    "missing_vat_pln": "Faktura w walucie ze stawką VAT bez kwoty VAT w PLN (P_14_W).",
}


class ConversionError(ValueError):
    def __init__(self, code: str, **params: object) -> None:
        self.code = code
        self.params = {key: str(value) for key, value in params.items()}
        super().__init__(ERRORS.get(code, code).format(**self.params))


class NothingToSend(ValueError):
    """Korekta bez zmiany kwot — nie ma czego przenieść do e-faktury."""


@dataclass(frozen=True)
class PeppolId:
    scheme: str
    value: str

    @classmethod
    def parse(cls, raw: str) -> "PeppolId":
        match = _PEPPOL_ID_RE.match((raw or "").strip())
        if not match:
            raise ConversionError("bad_peppol_id", value=raw or "—")
        return cls(match.group(1), match.group(2))

    def __str__(self) -> str:
        return f"{self.scheme}:{self.value}"


@dataclass(frozen=True)
class Attachment:
    filename: str
    content: bytes
    mime_code: str = "application/pdf"
    description: str = "Faktura PDF"


@dataclass(frozen=True)
class Receiver:
    """Nabywca w sieci Peppol: adres i (opcjonalnie) identyfikator rejestrowy."""

    endpoint: PeppolId
    legal_id: Optional[str] = None
    legal_id_scheme: Optional[str] = None


@dataclass(frozen=True)
class UblResult:
    xml: bytes
    document_type: str  # invoice | credit_note
    total: Decimal
    currency: str

    @property
    def doctype_id(self) -> str:
        return DOCTYPE_IDS[self.document_type]


@dataclass(frozen=True)
class _Line:
    name: str
    quantity: Decimal
    unit_code: str
    net: Decimal
    price: Decimal
    price_base: Optional[Decimal]
    line_allowance: Decimal
    category: str
    percent: Decimal
    accounting_cost: Optional[str]


# ── Pomocnicze ───────────────────────────────────────────────────────────────


def _money(value: Decimal) -> str:
    return format(value.quantize(_CENT, rounding=ROUND_HALF_UP), "f")


def _number(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text if text not in {"-0", ""} else "0"


def _price(value: Decimal) -> str:
    """Cena: dwa miejsca, gdy wystarczą („175.50”), inaczej tyle, ile trzeba."""

    if value == value.quantize(_CENT):
        return _money(value)
    return _number(value)


def _unit(raw: Optional[str]) -> str:
    return _UNITS.get((raw or "").strip().lower(), "C62")


def _category(rate: Optional[str]) -> tuple[str, Decimal]:
    key = " ".join((rate or "").split()).lower()
    if key in _STANDARD_RATES:
        return "S", Decimal(key)
    if key in _REVERSE_RATES:
        return "AE", _ZERO
    if key in _OUTSIDE_RATES:
        return "O", _ZERO
    raise ConversionError("unsupported_rate", rate=rate or "(brak)")


def _nids(name: str) -> Optional[str]:
    match = _NIDS_RE.search(name)
    return match.group(1) if match else None


def _contact(lines: tuple[FaLine, ...]) -> Optional[str]:
    for line in lines:
        match = _CONTACT_RE.search(line.name)
        if match:
            value = " ".join(match.group(1).split()).strip(" .")
            # „Contact: Jan Kowalski Contractor …” — opis bywa bez przecinka.
            value = re.split(r"\s+Contractor\b", value, maxsplit=1)[0].strip()
            if value:
                return value[:200]
    return None


def _priced(
    quantity: Optional[Decimal],
    net: Decimal,
    gross_price: Optional[Decimal],
) -> tuple[Decimal, str, Decimal, Optional[Decimal], Decimal]:
    """(ilość, jednostka zastępcza, cena po rabacie, cena przed rabatem, rabat pozycji).

    Ilość × cena − rabat pozycji = netto (reguła PEPPOL-EN16931-R120), cena po
    rabacie = cena przed rabatem − rabat na jednostkę (R046). Cena nigdy nie jest
    ujemna (BR-27): znak pozycji niesie ilość."""

    sign = Decimal("-1") if net < 0 else Decimal("1")
    if quantity is None or quantity == 0:
        return sign, "C62", abs(net), None, _ZERO
    qty, amount = abs(quantity), abs(net)
    price = (amount / qty).quantize(_PRICE, rounding=ROUND_HALF_UP)
    if (qty * price).quantize(_CENT, rounding=ROUND_HALF_UP) == amount:
        base = gross_price if gross_price is not None and gross_price > price else None
        return sign * qty, "", price, base, _ZERO
    # Cena po rabacie nie wychodzi dokładnie — rabat jako AllowanceCharge pozycji.
    if gross_price is not None and gross_price >= 0:
        allowance = (qty * gross_price).quantize(_CENT, rounding=ROUND_HALF_UP) - amount
        if allowance >= 0:
            return sign * qty, "", gross_price, None, sign * allowance
    return sign, "C62", amount, None, _ZERO


def _build_line(source: FaLine, quantity: Optional[Decimal], net: Decimal) -> _Line:
    category, percent = _category(source.vat_rate)
    qty, unit_override, price, base, allowance = _priced(
        quantity, net, source.unit_price
    )
    return _Line(
        name=source.name or "Usługa",
        quantity=qty,
        unit_code=unit_override or _unit(source.unit),
        net=net,
        price=price,
        price_base=base,
        line_allowance=allowance,
        category=category,
        percent=percent,
        accounting_cost=_nids(source.name),
    )


def _pairs(
    lines: tuple[FaLine, ...],
) -> list[tuple[Optional[FaLine], Optional[FaLine]]]:
    """Pary (przed, po) w korekcie: po ``UU_ID``, potem po nazwie w kolejności."""

    before = [line for line in lines if line.before]
    after = [line for line in lines if not line.before]
    if not before:
        # Korekta różnicowa — pozycje to od razu różnice.
        return [(None, line) for line in after]
    pairs: list[tuple[Optional[FaLine], Optional[FaLine]]] = []
    free_before = list(before)
    for line in after:
        match = None
        if line.uu_id:
            match = next((b for b in free_before if b.uu_id == line.uu_id), None)
        if match is None:
            match = next((b for b in free_before if b.name == line.name), None)
        if match is None and line.number:
            match = next((b for b in free_before if b.number == line.number), None)
        if match is not None:
            free_before.remove(match)
        pairs.append((match, line))
    pairs.extend((b, None) for b in free_before)
    return pairs


def _correction_lines(doc: FaDocument) -> list[_Line]:
    out = []
    for before, after in _pairs(doc.lines):
        if before is None and after is not None:
            out.append(_build_line(after, after.quantity, after.net))
            continue
        if after is None and before is not None:
            quantity = -before.quantity if before.quantity is not None else None
            out.append(_build_line(before, quantity, -before.net))
            continue
        assert before is not None and after is not None
        net = after.net - before.net
        if net == 0:
            continue
        quantity = None
        if after.quantity is not None and before.quantity is not None:
            quantity = after.quantity - before.quantity
        out.append(_build_line(after, quantity or None, net))
    return out


def _lines(doc: FaDocument) -> list[_Line]:
    if doc.kind == "correction":
        return _correction_lines(doc)
    return [
        _build_line(line, line.quantity, line.net)
        for line in doc.lines
        if not line.before
    ]


def _split_address(
    party: FaParty,
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """(ulica, dodatkowa linia, kod pocztowy, miasto) z nieustrukturyzowanego adresu FA."""

    line1, line2 = party.line1, party.line2
    postal = city = None
    if line2:
        match = _POSTAL_CITY_RE.match(line2)
        if match:
            postal, city = match.group(1), match.group(2).strip(" ,")
            line2 = None
    if postal is None and line1:
        match = _LINE_WITH_POSTAL_RE.match(line1)
        if match:
            line1, postal, city = (
                match.group(1).strip(" ,"),
                match.group(2),
                match.group(3).strip(" ,"),
            )
    return line1, line2, postal, city


def _iban(raw: str, country: Optional[str]) -> str:
    compact = re.sub(r"[\s-]", "", raw).upper()
    if compact.isdigit() and len(compact) == 26:
        return f"PL{compact}"
    if compact[:2].isdigit() and country:
        return f"{country.upper()}{compact}"
    return compact


# ── Budowa XML-a ─────────────────────────────────────────────────────────────


class _Writer:
    def __init__(self, root_tag: str, root_ns: str) -> None:
        self.root = etree.Element(
            f"{{{root_ns}}}{root_tag}",
            nsmap={None: root_ns, "cac": NS_CAC, "cbc": NS_CBC},
        )

    @staticmethod
    def cbc(
        parent: etree._Element, tag: str, text: str, **attrs: str
    ) -> etree._Element:
        node = etree.SubElement(parent, f"{{{NS_CBC}}}{tag}", attrs)
        node.text = text
        return node

    @staticmethod
    def cac(parent: etree._Element, tag: str) -> etree._Element:
        return etree.SubElement(parent, f"{{{NS_CAC}}}{tag}")


def _amount(
    w: _Writer, parent: etree._Element, tag: str, value: Decimal, currency: str
) -> None:
    w.cbc(parent, tag, _money(value), currencyID=currency)


def _tax_category(
    w: _Writer,
    parent: etree._Element,
    tag: str,
    category: str,
    percent: Decimal,
    *,
    reason: bool,
) -> None:
    node = w.cac(parent, tag)
    w.cbc(node, "ID", category)
    if category != "O":
        w.cbc(node, "Percent", _number(percent))
    if reason and category == "AE":
        w.cbc(node, "TaxExemptionReasonCode", "VATEX-EU-AE")
        w.cbc(node, "TaxExemptionReason", "Reverse charge")
    elif reason and category == "O":
        w.cbc(node, "TaxExemptionReasonCode", "VATEX-EU-O")
        w.cbc(node, "TaxExemptionReason", "Not subject to VAT")
    scheme = w.cac(node, "TaxScheme")
    w.cbc(scheme, "ID", "VAT")


def _party(
    w: _Writer,
    parent: etree._Element,
    tag: str,
    party: FaParty,
    endpoint: PeppolId,
    *,
    with_vat: bool,
    legal_id: Optional[str] = None,
    legal_scheme: Optional[str] = None,
) -> None:
    holder = w.cac(parent, tag)
    node = w.cac(holder, "Party")
    w.cbc(node, "EndpointID", endpoint.value, schemeID=endpoint.scheme)
    street, extra, postal, city = _split_address(party)
    address = w.cac(node, "PostalAddress")
    if street:
        w.cbc(address, "StreetName", street)
    if extra:
        w.cbc(address, "AdditionalStreetName", extra)
    if city:
        w.cbc(address, "CityName", city)
    if postal:
        w.cbc(address, "PostalZone", postal)
    country = w.cac(address, "Country")
    w.cbc(country, "IdentificationCode", (party.country or "PL").upper())
    if with_vat and party.vat_id:
        tax = w.cac(node, "PartyTaxScheme")
        w.cbc(tax, "CompanyID", party.vat_id)
        scheme = w.cac(tax, "TaxScheme")
        w.cbc(scheme, "ID", "VAT")
    legal = w.cac(node, "PartyLegalEntity")
    w.cbc(legal, "RegistrationName", party.name or party.vat_id or "—")
    if legal_id:
        if legal_scheme:
            w.cbc(legal, "CompanyID", legal_id, schemeID=legal_scheme)
        else:
            w.cbc(legal, "CompanyID", legal_id)


def build(
    doc: FaDocument,
    *,
    sender: PeppolId,
    receiver: Receiver,
    attachment: Optional[Attachment] = None,
) -> UblResult:
    """``FaDocument`` → UBL; ``ConversionError`` albo ``NothingToSend``."""

    if not doc.seller.nip:
        raise ConversionError("missing_seller_vat")
    lines = _lines(doc)
    if not lines:
        if doc.kind == "correction":
            raise NothingToSend("Korekta nie zmienia kwot pozycji.")
        raise ConversionError("no_lines")
    categories = {line.category for line in lines}
    if "O" in categories and len(categories) > 1:
        raise ConversionError("mixed_outside")
    if "AE" in categories and not doc.buyer.vat_id:
        raise ConversionError("missing_buyer_vat")

    total_net = sum((line.net for line in lines), _ZERO)
    if doc.kind == "correction" and total_net == 0:
        raise NothingToSend("Korekta nie zmienia kwoty faktury.")
    if doc.net_total is not None and total_net != doc.net_total:
        raise ConversionError(
            "net_mismatch", lines=_money(total_net), net=_money(doc.net_total)
        )

    credit = total_net < 0
    sign = Decimal("-1") if credit else Decimal("1")
    currency = doc.currency

    # Rozbicie VAT: kategoria × stawka.
    breakdown: "OrderedDict[tuple[str, Decimal], Decimal]" = OrderedDict()
    for line in lines:
        key = (line.category, line.percent)
        breakdown[key] = breakdown.get(key, _ZERO) + line.net * sign
    # VAT per stawka bierzemy z faktury (``P_14_x``), nie liczymy od netto:
    # w korekcie KSeF ma różnicę VAT-ów zaokrąglonych osobno (100,02 → 100,04
    # przy 23% to VAT 0,01, a 23% od 0,02 = 0,00). Reguła BR-CO-17 dopuszcza
    # taką różnicę o grosz. Gdy kilka stawek trafia w jedno pole — liczymy.
    fields = [
        _VAT_FIELD.get(_number(key[1])) if key[0] == "S" else None for key in breakdown
    ]
    vat_by_key = {}
    for key, field in zip(breakdown, fields):
        if field and fields.count(field) == 1 and field in doc.vat_by_field:
            vat_by_key[key] = doc.vat_by_field[field] * sign
        else:
            vat_by_key[key] = (breakdown[key] * key[1] / 100).quantize(
                _CENT, rounding=ROUND_HALF_UP
            )
    vat_total = sum(vat_by_key.values(), _ZERO)
    net_total = total_net * sign
    gross = net_total + vat_total
    if gross != doc.gross_total * sign:
        raise ConversionError(
            "gross_mismatch", ubl=_money(gross), gross=_money(doc.gross_total * sign)
        )
    if vat_total != doc.vat_total * sign:
        raise ConversionError(
            "vat_mismatch", lines=_money(vat_total), vat=_money(doc.vat_total * sign)
        )
    tax_currency = None
    if currency != "PLN" and vat_total != 0:
        if doc.vat_total_pln is None:
            raise ConversionError("missing_vat_pln")
        tax_currency = "PLN"
    if doc.kind == "correction" and not any(c.invoice_number for c in doc.corrected):
        raise ConversionError("missing_corrected")

    document_type = "credit_note" if credit else "invoice"
    root_tag, root_ns = (
        ("CreditNote", NS_CREDIT_NOTE) if credit else ("Invoice", NS_INVOICE)
    )
    w = _Writer(root_tag, root_ns)
    r = w.root
    w.cbc(r, "CustomizationID", CUSTOMIZATION_ID)
    w.cbc(r, "ProfileID", PROFILE_ID)
    w.cbc(r, "ID", doc.number)
    w.cbc(r, "IssueDate", doc.issue_date.isoformat())
    if not credit and doc.due_date:
        w.cbc(r, "DueDate", doc.due_date.isoformat())
    w.cbc(
        r,
        "CreditNoteTypeCode" if credit else "InvoiceTypeCode",
        "381" if credit else "380",
    )
    notes = list(doc.notes)
    if "AE" in categories:
        notes.append("Reverse charge / Odwrotne obciążenie")
    if doc.kind == "correction":
        numbers = ", ".join(c.invoice_number for c in doc.corrected if c.invoice_number)
        notes.insert(0, f"Correction of invoice {numbers}")
        if doc.correction_reason:
            notes.insert(1, doc.correction_reason)
    if notes:
        w.cbc(r, "Note", " · ".join(dict.fromkeys(notes))[:1000])
    w.cbc(r, "DocumentCurrencyCode", currency)
    if tax_currency:
        w.cbc(r, "TaxCurrencyCode", tax_currency)
    buyer_reference = _contact(doc.lines) or (None if doc.order_refs else doc.number)
    if buyer_reference:
        w.cbc(r, "BuyerReference", buyer_reference)
    if doc.period_from and doc.period_to:
        period = w.cac(r, "InvoicePeriod")
        w.cbc(period, "StartDate", doc.period_from.isoformat())
        w.cbc(period, "EndDate", doc.period_to.isoformat())
    if doc.order_refs:
        order = w.cac(r, "OrderReference")
        w.cbc(order, "ID", doc.order_refs[0])
    for corrected in doc.corrected:
        if not corrected.invoice_number:
            continue
        billing = w.cac(r, "BillingReference")
        ref = w.cac(billing, "InvoiceDocumentReference")
        w.cbc(ref, "ID", corrected.invoice_number)
        if corrected.issue_date:
            w.cbc(ref, "IssueDate", corrected.issue_date.isoformat())
    if attachment is not None:
        extra = w.cac(r, "AdditionalDocumentReference")
        w.cbc(extra, "ID", doc.number)
        w.cbc(extra, "DocumentDescription", attachment.description)
        holder = w.cac(extra, "Attachment")
        w.cbc(
            holder,
            "EmbeddedDocumentBinaryObject",
            base64.b64encode(attachment.content).decode("ascii"),
            mimeCode=attachment.mime_code,
            filename=attachment.filename,
        )
    outside = categories == {"O"}
    _party(
        w,
        r,
        "AccountingSupplierParty",
        doc.seller,
        sender,
        with_vat=not outside,
        legal_id=doc.seller.nip,
    )
    _party(
        w,
        r,
        "AccountingCustomerParty",
        doc.buyer,
        receiver.endpoint,
        with_vat=not outside,
        legal_id=receiver.legal_id,
        legal_scheme=receiver.legal_id_scheme,
    )
    delivery_date = doc.sale_date or doc.period_to
    if delivery_date:
        delivery = w.cac(r, "Delivery")
        w.cbc(delivery, "ActualDeliveryDate", delivery_date.isoformat())
    for account in doc.accounts:
        means = w.cac(r, "PaymentMeans")
        w.cbc(means, "PaymentMeansCode", "30")
        w.cbc(means, "PaymentID", doc.number)
        payee = w.cac(means, "PayeeFinancialAccount")
        w.cbc(payee, "ID", _iban(account.number, doc.seller.country))
        if account.swift:
            branch = w.cac(payee, "FinancialInstitutionBranch")
            w.cbc(branch, "ID", account.swift)
    if not credit and not doc.due_date and gross > 0:
        # BR-CO-25: kwota do zapłaty wymaga terminu albo warunków płatności.
        terms = w.cac(r, "PaymentTerms")
        w.cbc(terms, "Note", "Payment according to the agreement")

    tax_total = w.cac(r, "TaxTotal")
    _amount(w, tax_total, "TaxAmount", vat_total, currency)
    for (category, percent), taxable in breakdown.items():
        subtotal = w.cac(tax_total, "TaxSubtotal")
        _amount(w, subtotal, "TaxableAmount", taxable, currency)
        _amount(w, subtotal, "TaxAmount", vat_by_key[(category, percent)], currency)
        _tax_category(w, subtotal, "TaxCategory", category, percent, reason=True)
    if tax_currency:
        pln_total = w.cac(r, "TaxTotal")
        _amount(
            w, pln_total, "TaxAmount", (doc.vat_total_pln or _ZERO) * sign, tax_currency
        )

    totals = w.cac(r, "LegalMonetaryTotal")
    _amount(w, totals, "LineExtensionAmount", net_total, currency)
    _amount(w, totals, "TaxExclusiveAmount", net_total, currency)
    _amount(w, totals, "TaxInclusiveAmount", gross, currency)
    _amount(w, totals, "PayableAmount", gross, currency)

    line_tag, qty_tag = (
        ("CreditNoteLine", "CreditedQuantity")
        if credit
        else ("InvoiceLine", "InvoicedQuantity")
    )
    for index, line in enumerate(lines, start=1):
        node = w.cac(r, line_tag)
        w.cbc(node, "ID", str(index))
        w.cbc(node, qty_tag, _number(line.quantity * sign), unitCode=line.unit_code)
        _amount(w, node, "LineExtensionAmount", line.net * sign, currency)
        if line.accounting_cost:
            w.cbc(node, "AccountingCost", line.accounting_cost)
        if line.line_allowance:
            allowance = w.cac(node, "AllowanceCharge")
            w.cbc(allowance, "ChargeIndicator", "false")
            w.cbc(allowance, "AllowanceChargeReason", "Discount")
            _amount(w, allowance, "Amount", line.line_allowance * sign, currency)
        item = w.cac(node, "Item")
        w.cbc(item, "Name", line.name)
        _tax_category(
            w, item, "ClassifiedTaxCategory", line.category, line.percent, reason=False
        )
        price = w.cac(node, "Price")
        w.cbc(price, "PriceAmount", _price(line.price), currencyID=currency)
        if line.price_base is not None:
            discount = w.cac(price, "AllowanceCharge")
            w.cbc(discount, "ChargeIndicator", "false")
            w.cbc(
                discount,
                "Amount",
                _price(line.price_base - line.price),
                currencyID=currency,
            )
            w.cbc(discount, "BaseAmount", _price(line.price_base), currencyID=currency)

    xml = etree.tostring(r, xml_declaration=True, encoding="UTF-8", pretty_print=True)
    return UblResult(
        xml=xml, document_type=document_type, total=gross, currency=currency
    )
