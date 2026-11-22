"""Plik paczki księgi do Symfonii FK (K3b) — czyste funkcje renderujące.

Trzy formaty: dwa neutralne (XLSX i CSV z wierszem na pozycję dekretu, jak
w E2) i „Symfonia FK — import dokumentów (szablon 4)” — tekst w układzie
pliku z eBI24 (próbki od Finansów z 17.11.2026). Dopisanie formatu = nowa
klasa i wpis w ``FORMATS``. Tekst z danych idzie w neutralnych przez
``safe_row`` / ``safe_cell`` (komórka od ``= + - @`` nie stanie się formułą
w arkuszu), w szablonie 4 przez ``_text`` (bez końców wierszy i znaków,
których nie ma w Windows-1250).
"""

from __future__ import annotations

import csv
import io
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Optional, Protocol

from openpyxl import Workbook
from openpyxl.styles import Font

from app.core.export_safety import safe_cell, safe_row


@dataclass(frozen=True)
class ExportRegister:
    """Pozycja rejestru VAT z opisu faktury (kwoty dodatnie, znak z faktury)."""

    name: str
    rate: str
    net: Decimal
    vat: Decimal
    gross: Decimal
    net_cur: Optional[Decimal] = None
    vat_cur: Optional[Decimal] = None
    gross_cur: Optional[Decimal] = None
    #: Rejestr VAT należnego (import usług, WNT) — ``Naliczony =0``.
    output: bool = False
    eu: bool = False
    service: bool = False


@dataclass(frozen=True)
class ExportInvoice:
    """Dane faktury, których nie niesie dekret — dla szablonu 4 Symfonii.

    Wypełnia je ``exports.export_lines`` dla dokumentów ze źródeł „sprzedaż”
    i „koszty”; PK, RMK, listy płac i reszta mają ``None`` i szablon 4 ich nie
    przyjmuje (to import faktur).
    """

    #: Symbol dokumentu w Symfonii (``symbol FK``): FVS, WDT, FKZ, …
    symbol: str
    purchase: bool
    #: Numer faktury (sprzedaż: ``kod``, zakup: ``kod_obcy``).
    number: str
    issue_date: date
    #: Data sprzedaży / dostawy (zakup bez XML-a: data wystawienia).
    sale_date: date
    #: Data rejestru (``datarej``, ``datawpl``).
    register_date: date
    #: Okres w rejestrze VAT (``Rejestr.okres``).
    period_date: date
    due_date: date
    net: Decimal
    vat: Decimal
    gross: Decimal
    #: Stawka do rejestru VAT: ``"23"``, ``"8"``, ``"0"``, ``"-2"`` (nie podlega);
    #: ``None`` = stawka niestandardowa albo kilka stawek (szablon 4 odmówi).
    vat_rate: Optional[str]
    currency: str = "PLN"
    ksef_date: Optional[date] = None
    #: Korekta in minus: kwoty w rejestrze i zapisach idą ze znakiem minus.
    negative: bool = False
    #: Korekta: numer faktury korygowanej (zakup: NEXUS go nie zna).
    corrects_number: Optional[str] = None
    #: Konto rozrachunkowe z dekretu — pozycja dostaje znacznik rozliczeń.
    settlement_account: Optional[str] = None
    party_street: Optional[str] = None
    party_postal: Optional[str] = None
    party_city: Optional[str] = None
    party_country: Optional[str] = None
    #: Rachunek odbiorcy przelewu (zakup), jak na fakturze / w E3.
    payment_account: Optional[str] = None
    #: Rejestry VAT z opisu faktury (E2 wg księgowej); puste = jeden z kwot.
    registers: tuple[ExportRegister, ...] = ()
    #: Procedura JPK (``JPK_V7``): MK, BFK, …
    jpk_procedure: Optional[str] = None
    fx_rate: Optional[Decimal] = None
    fx_date: Optional[date] = None
    #: Numer tabeli NBP (``tabela``), np. ``211/A/NBP/2026``.
    fx_table: Optional[str] = None
    #: Rodzaj pozycji dekretu po numerze pozycji (``vat``, ``allocation``…).
    line_kinds: dict[int, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ExportLine:
    """Jedna pozycja dekretu w pliku paczki."""

    journal_no: int
    number: str
    doc_type: str
    doc_date: date
    op_date: date
    document_description: str
    line_no: int
    account: str
    debit: Optional[Decimal]
    credit: Optional[Decimal]
    description: str
    mpk: Optional[str]
    counterparty: Optional[str]
    tax_id: Optional[str]
    symfonia_id: Optional[str]
    currency: str
    amount_cur: Optional[Decimal]
    fx_rate: Optional[Decimal]
    fx_date: Optional[date]
    reverses: Optional[str]
    ksef_number: Optional[str]
    #: Dane faktury (tylko dokumenty ze źródeł sprzedaż / koszty).
    invoice: Optional[ExportInvoice] = None
    #: Dlaczego dokumentu ze źródła faktury nie da się opisać (``invoice`` puste).
    invoice_problem: Optional[str] = None


#: Kolumny formatu neutralnego (kolejność = kolejność w pliku).
COLUMNS: tuple[tuple[str, str], ...] = (
    ("journal_no", "Nr w dzienniku NEXUSA"),
    ("number", "Numer dokumentu"),
    ("doc_type", "Typ"),
    ("doc_date", "Data dokumentu"),
    ("op_date", "Data operacji"),
    ("document_description", "Opis dokumentu"),
    ("line_no", "Pozycja"),
    ("account", "Konto"),
    ("debit", "Wn"),
    ("credit", "Ma"),
    ("description", "Opis pozycji"),
    ("mpk", "MPK"),
    ("counterparty", "Kontrahent"),
    ("tax_id", "NIP / VAT UE"),
    ("symfonia_id", "ID Symfonii kontrahenta"),
    ("currency", "Waluta"),
    ("amount_cur", "Kwota w walucie"),
    ("fx_rate", "Kurs"),
    ("fx_date", "Data kursu"),
    ("reverses", "Storno dokumentu"),
    ("ksef_number", "Numer KSeF"),
)
_NUMBER_FORMATS: dict[str, str] = {
    "debit": "#,##0.00",
    "credit": "#,##0.00",
    "amount_cur": "#,##0.00",
    "fx_rate": "0.000000",
    "doc_date": "yyyy-mm-dd",
    "op_date": "yyyy-mm-dd",
    "fx_date": "yyyy-mm-dd",
}


def money(grosze: Optional[int]) -> Optional[Decimal]:
    """Grosze → złote z dwoma miejscami (``None`` zostaje ``None``)."""

    if grosze is None:
        return None
    return (Decimal(grosze) / 100).quantize(Decimal("0.01"))


class ExportFormat(Protocol):
    key: str
    label: str
    extension: str
    media_type: str

    def render(self, lines: list[ExportLine]) -> bytes: ...


def _values(line: ExportLine) -> list[Any]:
    return [getattr(line, name) for name, _ in COLUMNS]


class NeutralXlsx:
    key = "neutral_xlsx"
    label = "Arkusz XLSX (format neutralny)"
    extension = "xlsx"
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def render(self, lines: list[ExportLine]) -> bytes:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Dokumenty"
        sheet.append([label for _, label in COLUMNS])
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        formats = {
            index + 1: _NUMBER_FORMATS[name]
            for index, (name, _) in enumerate(COLUMNS)
            if name in _NUMBER_FORMATS
        }
        for line in lines:
            sheet.append(safe_row(_values(line)))
            row = sheet.max_row
            for column, number_format in formats.items():
                sheet.cell(row=row, column=column).number_format = number_format
        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()


def _csv_cell(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f").replace(".", ",")
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return ""
    return safe_cell(value)


class NeutralCsv:
    key = "neutral_csv"
    label = "CSV ze średnikiem (format neutralny)"
    extension = "csv"
    media_type = "text/csv; charset=utf-8"

    def render(self, lines: list[ExportLine]) -> bytes:
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
        writer.writerow([label for _, label in COLUMNS])
        for line in lines:
            writer.writerow([_csv_cell(value) for value in _values(line)])
        # BOM: polski Excel otwiera wtedy plik w UTF-8.
        return buffer.getvalue().encode("utf-8-sig")


# ── Symfonia FK: import dokumentów, szablon 4 ───────────────────────────────

CRLF = "\r\n"
SYMFONIA_ENCODING = "cp1250"


class SymfoniaFormatError(ValueError):
    """Dokument, którego szablon 4 nie obejmuje albo któremu brakuje danych."""


@dataclass(frozen=True)
class _SymfoniaType:
    """Typ dokumentu z próbki Symfonii (symbol FK → rejestr, schemat, nazwa)."""

    purchase: bool
    correction: bool
    #: Nazwa rejestru VAT tak, jak stoi w próbce (``rejestr_vat``, ``Skrot``).
    register: str
    #: ``schemat`` — kod schematu księgowania z próbki.
    schema: str
    #: ``nazwa`` — rodzaj dokumentu z próbki.
    title: str
    #: ``Rejestr.Rodzaj`` z próbki.
    register_kind: str
    #: ``def_dok.dUE`` / ``dUsl``: dokument UE, usługa (``mppFlags``, ``UE``, ``usluga``).
    eu_services: bool = False
    #: Układ zakupu z próbek z 18.11.2026 (FVZP samochód, IU import usług):
    #: rejestry i kwoty w walucie z opisu faktury, zapisy równoległe „5”.
    described: bool = False


#: Tylko typy z próbek: FVS, WDT (usługa dla kontrahenta z UE) i FKZ
#: (17.11.2026), FVZP i IU (18.11.2026). FVZ ma układ FVZP (ten sam rodzaj
#: dokumentu „Faktura zakupu”, inny symbol). FKS, WNT, DP, FZBO i reszta
#: czekają na próbkę; dopisanie typu = wiersz tu.
_SYMFONIA_TYPES: dict[str, _SymfoniaType] = {
    "FVS": _SymfoniaType(False, False, "Sprzedaż", "SP", "Faktura", "1"),
    "WDT": _SymfoniaType(
        False,
        False,
        "Świadczenie usług poza krajem",
        "SP",
        "Faktura",
        "1",
        eu_services=True,
    ),
    "FKZ": _SymfoniaType(
        True, True, "Korekta Zakupu", "ZK", "Faktura korygująca zakupu", "2000"
    ),
    "FVZ": _SymfoniaType(
        True, False, "Zakup", "ZK", "Faktura zakupu", "2000", described=True
    ),
    "FVZP": _SymfoniaType(
        True, False, "Zakup", "ZK", "Faktura zakupu", "2000", described=True
    ),
    "IU": _SymfoniaType(
        True,
        False,
        "Import usług VAT naliczony",
        "ZK",
        "Faktura zakupu",
        "2000",
        described=True,
    ),
}
#: Pozycje VAT w dokumencie w walucie mają ``pozycja =2`` (próbka IU).
_VAT_KINDS = ("vat", "vat_due")
#: Zapis równoległy „5” / 490 (``ZapisRownolegly =33`` w próbkach).
_PARALLEL_KINDS = ("allocation", "allocation_offset")
_PARALLEL_CODE = "33"

#: Nazwy krajów w pliku (``khKrajNazwa``); w próbkach tylko Polska i Finlandia.
_COUNTRY_NAMES: dict[str, str] = {
    "PL": "Polska", "AT": "Austria", "BE": "Belgia", "BG": "Bułgaria",
    "HR": "Chorwacja", "CY": "Cypr", "CZ": "Czechy", "DK": "Dania",
    "EE": "Estonia", "FI": "Finlandia", "FR": "Francja", "DE": "Niemcy",
    "EL": "Grecja", "GR": "Grecja", "HU": "Węgry", "IE": "Irlandia",
    "IT": "Włochy", "LV": "Łotwa", "LT": "Litwa", "LU": "Luksemburg",
    "MT": "Malta", "NL": "Holandia", "PT": "Portugalia", "RO": "Rumunia",
    "SK": "Słowacja", "SI": "Słowenia", "ES": "Hiszpania", "SE": "Szwecja",
    # Spoza UE (import usług): Indie z próbki IU z 18.11.2026, reszta z nazw
    # polskich MSZ — do potwierdzenia z kartoteką krajów Symfonii.
    "IN": "Indie", "US": "Stany Zjednoczone", "GB": "Wielka Brytania",
    "CH": "Szwajcaria", "NO": "Norwegia", "UA": "Ukraina", "CA": "Kanada",
    "IL": "Izrael", "SG": "Singapur", "AU": "Australia", "JP": "Japonia",
    "CN": "Chiny", "TR": "Turcja", "AE": "Zjednoczone Emiraty Arabskie",
    "IS": "Islandia",
}  # fmt: skip


def _text(value: Any) -> str:
    """Wartość pola: jedna linia, tylko znaki z Windows-1250.

    Znak spoza strony kodowej traci akcenty (``ä`` → ``a``), a gdy i to nie
    wystarczy — ``?``; zły znak nie przerywa całego pliku.
    """

    out: list[str] = []
    for char in " ".join(str(value if value is not None else "").split()):
        try:
            char.encode(SYMFONIA_ENCODING)
            out.append(char)
        except UnicodeEncodeError:
            ascii_char = (
                unicodedata.normalize("NFKD", char).encode("ascii", "ignore").decode()
            )
            out.append(ascii_char or "?")
    return "".join(out)


def _amount(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _day(value: Optional[date]) -> str:
    return value.isoformat() if value else ""


def _field(name: str, value: Any, depth: int = 1) -> str:
    return f"{chr(9) * depth}{name} ={_text(value)}"


def _nrb(account: Optional[str]) -> str:
    """Rachunek w grupach jak w próbce: ``61 1090 1014 0000 0712 1981 2874``."""

    digits = "".join(ch for ch in account or "" if ch.isdigit())
    if len(digits) != 26:
        return digits
    return " ".join([digits[:2], *(digits[i : i + 4] for i in range(2, 26, 4))])


def _country(invoice: ExportInvoice) -> tuple[str, str]:
    code = (invoice.party_country or "PL").upper()
    name = _COUNTRY_NAMES.get(code)
    if name is None:
        raise SymfoniaFormatError(f"kraj kontrahenta „{code}” — brak nazwy w pliku")
    return code, name


def _party_block(
    title: str, line: ExportLine, invoice: ExportInvoice, *, with_ident: bool
) -> list[str]:
    code, name = _country(invoice)
    fields = [
        ("khid", ""),
        *([("fk_ident", line.symfonia_id or "")] if with_ident else []),
        ("khnazwa", line.counterparty or ""),
        ("khulica", invoice.party_street or ""),
        ("khmiasto", invoice.party_city or ""),
        ("khkodpocz", invoice.party_postal or ""),
        ("khnip", line.tax_id or ""),
        ("khKrajKod", code),
        ("khKrajNazwa", name),
    ]
    return [f"\t{title}{{", *(_field(n, v, 2) for n, v in fields), "\t}"]


def _rate_text(value: Optional[Decimal]) -> str:
    if value is None:
        return "1.00"
    text_ = format(Decimal(value).normalize(), "f")
    return text_ if "." in text_ else f"{text_}.00"


def _described_registers(invoice: ExportInvoice) -> tuple[ExportRegister, ...]:
    if invoice.registers:
        return invoice.registers
    return (
        ExportRegister(
            name="",
            rate=invoice.vat_rate or "",
            net=abs(invoice.net),
            vat=abs(invoice.vat),
            gross=abs(invoice.gross),
        ),
    )


def _purchase_document(
    lines: list[ExportLine], invoice: ExportInvoice, kind: _SymfoniaType
) -> list[str]:
    """Faktura zakupu wg próbek z 18.11.2026 (FVZP samochód, IU import usług).

    Nagłówek ma kwoty ze znakiem minus (faktura) albo plus (korekta in minus),
    rejestr i zapisy odwrotnie; w walucie nagłówek idzie w walucie, a ``wkwota``
    to brutto w PLN. ``dozaplaty`` w obu próbkach to 0.00.
    """

    head = lines[0]
    foreign = invoice.currency != "PLN"
    if foreign and invoice.fx_rate is None:
        raise SymfoniaFormatError(f"faktura w {invoice.currency} bez kursu w dekrecie")
    if not invoice.registers and (foreign or invoice.symbol == "IU"):
        # Dekret sprzed opisu wg księgowej nie zna kwot rejestru w walucie.
        raise SymfoniaFormatError(
            f"faktura w {invoice.currency} bez rejestru VAT z opisu — przelicz "
            "dekret w Kosztach"
        )
    registers = _described_registers(invoice)
    inputs = [item for item in registers if not item.output] or list(registers)
    sign = Decimal(-1) if invoice.negative else Decimal(1)
    head_sign = -sign

    def total(name: str) -> Decimal:
        return sum((getattr(item, name) or Decimal(0) for item in inputs), Decimal(0))

    net_pln, vat_pln, gross_pln = total("net"), total("vat"), total("gross")
    if foreign:
        net_head, vat_head, gross_head = (
            total("net_cur"),
            total("vat_cur"),
            total("gross_cur"),
        )
    else:
        net_head, vat_head, gross_head = net_pln, vat_pln, gross_pln
    country, country_name = _country(invoice)
    out = ["Dokument{", _field("rodzaj_dok", "zakupu")]
    if head.ksef_number or kind.correction:
        out += [
            _field("KsefNumber", head.ksef_number or ""),
            _field("KSeFDate", _day(invoice.ksef_date or invoice.issue_date)),
        ]
    if kind.correction:
        # Próbka FKZ z 17.11.2026: faktura korygowana przed kwotami do zapłaty.
        parent = _text(invoice.corrects_number)
        out += [
            "\tDokument korygowany{",
            _field("kod", parent, 2),
            "\t}",
            "\tDokument nadrzędny{",
            _field("kod", parent, 2),
            "\t}",
            _field("opis", ""),
            _field("NazwaKor", parent),
            _field("DataKor", _day(invoice.issue_date)),
            _field("DataObcyKor", _day(invoice.issue_date)),
        ]
    # Próbki FVZP i IU: 0.00; korekta in minus 0.00, korekta in plus — dopłata.
    to_pay = (
        _amount(Decimal(0) if invoice.negative else gross_head)
        if kind.correction
        else "0.00"
    )
    out += [
        _field("dozaplaty", to_pay),
        _field("wdozaplaty", to_pay),
        _field("kod_obcy", invoice.number),
    ]
    if invoice.jpk_procedure:
        out += [_field("mppFlags", "0"), _field("JPK_V7", invoice.jpk_procedure)]
    out += [
        _field("symbol FK", invoice.symbol),
        _field("seria", f"s{invoice.symbol}"),
        _field("nazwa", kind.title),
        _field("data", _day(invoice.issue_date)),
        _field("datasp", _day(invoice.sale_date)),
        _field("dataWystawieniaObca", _day(invoice.issue_date)),
        _field("dataWystawienia", _day(invoice.issue_date)),
        _field("dataZakupu", _day(invoice.sale_date)),
        _field("dataSprzedazy", _day(invoice.sale_date)),
        _field("kodKH", ""),
        _field("khid", ""),
        _field("khnazwa", head.counterparty or ""),
        _field("khulica", invoice.party_street or ""),
        _field("khmiasto", invoice.party_city or ""),
        _field("khkodpocz", invoice.party_postal or ""),
        _field("khnip", head.tax_id or ""),
        _field("khKrajKod", country),
        _field("khKrajNazwa", country_name),
        _field("wplaty", "0.000000000000"),
        _field("rabat", "0.000000000000"),
        _field("plattypi", "131"),
        _field("forma_platnosci", "przelew"),
        _field("rejestr_platnosci", "BANK"),
        _field("plattermin", _day(invoice.due_date)),
        _field("netto", _amount(head_sign * net_head)),
        _field("vat", _amount(head_sign * vat_head)),
        _field("typ_dk", invoice.symbol),
        _field("wartoscsp", _amount(head_sign * net_head)),
        _field("waluta", invoice.currency if foreign else ""),
    ]
    if foreign:
        out.append(_field("tabela", invoice.fx_table or ""))
    out += [
        _field("kurs", _rate_text(invoice.fx_rate if foreign else None)),
        _field("schemat", kind.schema),
        _field("walnetto", _amount(head_sign * net_head)),
        _field("walbrutto", _amount(head_sign * gross_head)),
        _field("wartprzychod", "0.00"),
        _field("kursdoch", _rate_text(invoice.fx_rate if foreign else None)),
        _field("data_obcy", _day(invoice.issue_date)),
        _field("rejestr_vat", inputs[0].name or kind.register),
        _field("typ_rejestru_vat", "0"),
    ]
    out += _party_block("Dane sprzedawcy", head, invoice, with_ident=False)
    if foreign:
        out.append(_field("wkwota", _amount(gross_pln)))
    out += [
        _field("kwota", _amount(head_sign * gross_head)),
        _field("FK nazwa", invoice.number),
        _field("opis FK", head.document_description),
        _field("opis", head.document_description),
        _field("datarej", _day(invoice.register_date)),
        _field("datawpl", _day(invoice.register_date)),
    ]
    self_assessed = any(item.output for item in registers)
    for item in registers:
        name = item.name or kind.register
        out += ["\tRejestr{", _field("Skrot", name, 2)]
        if item.output:
            out.append(_field("Nazwa", name, 2))
        out += [
            _field("okres", _day(invoice.period_date), 2),
            _field("Rodzaj", kind.register_kind, 2),
            _field("stawka", item.rate or invoice.vat_rate, 2),
            _field("brutto", _amount(sign * item.gross), 2),
            _field("netto", _amount(sign * item.net), 2),
            _field("vat", _amount(sign * item.vat), 2),
            _field("ABC", "1", 2),
        ]
        if self_assessed:
            out += [
                _field("UE", "1" if item.eu else "0", 2),
                _field("Naliczony", "0" if item.output else "1", 2),
            ]
        if foreign:
            out += [
                _field("nettoWaluta", _amount(sign * (item.net_cur or Decimal(0))), 2),
                _field("vatWaluta", _amount(sign * (item.vat_cur or Decimal(0))), 2),
                _field(
                    "bruttoWaluta", _amount(sign * (item.gross_cur or Decimal(0))), 2
                ),
            ]
        if self_assessed and not item.output:
            out.append(_field("usluga", "1" if item.service else "0", 2))
        out.append("\t}")
    if foreign:
        for label in ("kurs VAT", "kurs CIT/PIT"):
            out += [
                "\tAtrybutWaluta{",
                _field("data", _day(invoice.fx_date), 2),
                _field("kurs", _rate_text(invoice.fx_rate), 2),
                _field("waluta", invoice.currency, 2),
                _field("dane", label, 2),
                "\t}",
            ]
    for line in lines:
        debit = line.debit is not None
        amount = line.debit if debit else line.credit
        if amount is None:
            raise SymfoniaFormatError(f"pozycja {line.line_no} bez kwoty")
        position_kind = invoice.line_kinds.get(line.line_no, "")
        parallel = position_kind in _PARALLEL_KINDS
        side_debit = debit != invoice.negative
        out += [
            "\tZapis{",
            _field("strona", "WN" if side_debit else "MA", 2),
            _field("konto", line.account, 2),
            _field("kwota", _amount(sign * amount), 2),
        ]
        if foreign and line.amount_cur is not None:
            out += [
                _field("wkwota", _amount(sign * line.amount_cur), 2),
                _field("kurs", _rate_text(line.fx_rate or invoice.fx_rate), 2),
                _field("tabela", invoice.fx_table or "", 2),
                _field("Waluta", line.currency, 2),
            ]
            group = "2" if position_kind in _VAT_KINDS else "1"
        else:
            group = "1" if parallel else "0"
        out.append(_field("pozycja", group, 2))
        if parallel:
            out.append(_field("ZapisRownolegly", _PARALLEL_CODE, 2))
        elif kind.correction and line.account == invoice.settlement_account:
            out.append(_field("IdDlaRozliczen", "1", 2))
        out.append("\t}")
    out += [
        "\tTransakcja{",
        _field("IdDlaRozliczen", "1" if kind.correction else "-1", 2),
        _field("termin", _day(invoice.due_date), 2),
    ]
    if invoice.payment_account:
        account = (
            _nrb(invoice.payment_account)
            if kind.correction
            else invoice.payment_account
        )
        out.append(_field("rachunek", account, 2))
    out += ["\t}", "}"]
    return out


def _document(lines: list[ExportLine]) -> list[str]:
    """Blok ``Dokument{…}`` jednej faktury — kolejność pól jak w próbkach."""

    head = lines[0]
    invoice = head.invoice
    if invoice is None:
        if head.reverses:
            raise SymfoniaFormatError(
                f"storno dokumentu {head.reverses} — szablon 4 nie ma storna, "
                "w Symfonii skoryguj albo usuń dokument ręcznie"
            )
        raise SymfoniaFormatError(
            head.invoice_problem or "to nie faktura — szablon 4 przyjmuje tylko faktury"
        )
    if invoice.vat_rate is None:
        raise SymfoniaFormatError(
            "stawka VAT inna niż 23, 8, 5, 0 albo kilka stawek na fakturze"
        )
    kind = _SYMFONIA_TYPES.get(invoice.symbol)
    if kind is None:
        raise SymfoniaFormatError(
            f"brak próbki Symfonii dla typu {invoice.symbol} "
            f"(obsługiwane: {', '.join(_SYMFONIA_TYPES)})"
        )
    if kind.described or (kind.purchase and invoice.registers):
        # Korekta z opisem faktury (rejestry, „5”, JPK) — ten sam układ zakupu,
        # z blokiem faktury korygowanej z próbki FKZ.
        return _purchase_document(lines, invoice, kind)
    if invoice.currency != "PLN":
        raise SymfoniaFormatError(
            f"faktura w {invoice.currency} — brak próbki waluty obcej"
        )
    sign = Decimal(-1) if invoice.negative else Decimal(1)
    gross = _amount(abs(invoice.gross))
    parent = _text(invoice.corrects_number)
    out = [
        "Dokument{",
        _field("rodzaj_dok", "zakupu" if kind.purchase else "sprzedaży"),
        _field("KsefNumber", head.ksef_number or ""),
        _field("KSeFDate", _day(invoice.ksef_date or invoice.issue_date)),
    ]
    if kind.correction:
        out += [
            "\tDokument korygowany{",
            _field("kod", parent, 2),
            "\t}",
            "\tDokument nadrzędny{",
            _field("kod", parent, 2),
            "\t}",
            _field("opis", ""),
            _field("NazwaKor", parent),
            _field("DataKor", _day(invoice.issue_date)),
            _field("DataObcyKor", _day(invoice.issue_date)),
        ]
    # Próbka: korekta in minus ma do zapłaty 0,00; korekta in plus — dopłatę.
    to_pay = Decimal(0) if invoice.negative else abs(invoice.gross)
    out += [
        _field("dozaplaty", _amount(to_pay)),
        _field("wdozaplaty", _amount(to_pay)),
        _field("kod_obcy" if kind.purchase else "kod", invoice.number),
    ]
    if kind.eu_services:
        out += [_field("mppFlags", "0"), _field("JPK_V7", "")]
    out += [
        _field("symbol FK", invoice.symbol),
        _field("seria", f"s{invoice.symbol}"),
        _field("nazwa", kind.title),
        _field("data", _day(invoice.issue_date)),
        _field("datasp", _day(invoice.sale_date)),
        _field("dataWystawieniaObca", _day(invoice.issue_date)),
        _field("dataWystawienia", _day(invoice.issue_date)),
        _field("dataZakupu", _day(invoice.sale_date)),
        _field("dataSprzedazy", _day(invoice.sale_date)),
    ]
    country, country_name = _country(invoice)
    if kind.eu_services and country == "PL":
        raise SymfoniaFormatError("usługa dla UE z kontrahentem z Polski")
    out += [
        _field("kodKH", ""),
        _field("khid", ""),
        _field("khnazwa", head.counterparty or ""),
        _field("khulica", invoice.party_street or ""),
        _field("khmiasto", invoice.party_city or ""),
        _field("khkodpocz", invoice.party_postal or ""),
        _field("khnip", head.tax_id or ""),
        _field("khKrajKod", country),
        _field("khKrajNazwa", country_name),
        _field("wplaty", "0.000000000000"),
        _field("rabat", "0.000000000000"),
        _field("plattypi", "131"),
        _field("forma_platnosci", "przelew"),
        _field("rejestr_platnosci", "BANK"),
        _field("plattermin", _day(invoice.due_date)),
        _field("netto", _amount(abs(invoice.net))),
        _field("vat", _amount(abs(invoice.vat))),
        _field("typ_dk", invoice.symbol),
    ]
    if kind.purchase:
        out.append(_field("wartoscsp", _amount(abs(invoice.net))))
    out += [
        _field("waluta", ""),
        _field("kurs", "1.00"),
        _field("schemat", kind.schema),
        _field("walnetto", _amount(abs(invoice.net))),
        _field("walbrutto", gross),
        _field("wartprzychod", "0.00" if kind.purchase else _amount(abs(invoice.net))),
        _field("kursdoch", "1.00"),
    ]
    if kind.purchase:
        out.append(_field("data_obcy", _day(invoice.issue_date)))
    out += [
        _field("rejestr_vat", kind.register),
        _field("typ_rejestru_vat", "0" if kind.purchase else "1"),
    ]
    out += _party_block(
        "Dane sprzedawcy" if kind.purchase else "Dane nabywcy",
        head,
        invoice,
        with_ident=not kind.purchase,
    )
    out += [
        _field("kwota", gross),
        _field("FK nazwa", invoice.number),
        _field("opis FK", head.document_description),
        _field("opis", head.document_description),
        _field("datarej", _day(invoice.register_date)),
        _field("datawpl", _day(invoice.register_date)),
        "\tRejestr{",
        _field("Skrot", kind.register, 2),
        _field("okres", _day(invoice.period_date), 2),
        _field("Rodzaj", kind.register_kind, 2),
        _field("stawka", invoice.vat_rate, 2),
        _field("brutto", _amount(sign * abs(invoice.gross)), 2),
        _field("netto", _amount(sign * abs(invoice.net)), 2),
        _field("vat", _amount(sign * abs(invoice.vat)), 2),
    ]
    if kind.purchase:
        out.append(_field("ABC", "1", 2))
    if kind.eu_services:
        out += [_field("UE", "1", 2), _field("usluga", "1", 2), _field("JPK_V7", "", 2)]
    out.append("\t}")
    for line in lines:
        debit = line.debit is not None
        amount = line.debit if debit else line.credit
        if amount is None:
            raise SymfoniaFormatError(f"pozycja {line.line_no} bez kwoty")
        # Korekta in minus: strona jak w fakturze pierwotnej, kwota ze znakiem
        # minus (w NEXUSIE strony są zamienione, a kwoty dodatnie).
        side_debit = debit != invoice.negative
        out += [
            "\tZapis{",
            _field("strona", "WN" if side_debit else "MA", 2),
            _field("konto", line.account, 2),
            _field("kwota", _amount(sign * amount), 2),
        ]
        # Pole ``pozycja`` i znacznik rozliczeń mają w próbkach tylko zakupy.
        if kind.purchase:
            out.append(_field("pozycja", "0", 2))
            if line.account == invoice.settlement_account:
                out.append(_field("IdDlaRozliczen", "1", 2))
        out.append("\t}")
    out += [
        "\tTransakcja{",
        _field("IdDlaRozliczen", "1" if kind.purchase else "-1", 2),
        _field("termin", _day(invoice.due_date), 2),
    ]
    if kind.purchase and invoice.payment_account:
        out.append(_field("rachunek", _nrb(invoice.payment_account), 2))
    out += ["\t}", "}"]
    return out


class SymfoniaFkDocuments:
    """Plik importu dokumentów Symfonii FK, szablon 4 (Windows-1250, CRLF).

    Układ jak w próbkach z eBI24: blok ``INFO{…}`` i po jednym ``Dokument{…}``
    na fakturę. Pola, których NEXUS nie zna (``kodKH`` / ``khid`` kontrahenta,
    który w Symfonii powstaje przez synchronizację z aplikacją eBI), zostają
    puste — lista w ``ksiega-nexusa-k3b-symfonia-szablon-4.md``.
    """

    key = "symfonia_fk_txt4"
    label = "Symfonia FK — import dokumentów (szablon 4)"
    extension = "txt"
    media_type = "text/plain; charset=windows-1250"

    def render(self, lines: list[ExportLine]) -> bytes:
        documents: dict[tuple[int, str], list[ExportLine]] = {}
        for line in lines:
            documents.setdefault((line.journal_no, line.number), []).append(line)
        out = [
            "INFO{",
            _field("Nazwa programu", "Sage Symfonia Finanse i Księgowość"),
            _field("Wersja szablonu", "4"),
            "}",
        ]
        problems: list[str] = []
        for group in documents.values():
            try:
                out += _document(group)
            except SymfoniaFormatError as exc:
                problems.append(f"{group[0].number} ({group[0].doc_type}): {exc}")
        if problems:
            shown = "; ".join(problems[:8])
            more = f" (i {len(problems) - 8} kolejnych)" if len(problems) > 8 else ""
            raise SymfoniaFormatError(
                f"Szablon 4 Symfonii nie przyjmie {len(problems)} dok.: {shown}{more}."
            )
        return (CRLF.join(out) + CRLF).encode(SYMFONIA_ENCODING)


FORMATS: dict[str, ExportFormat] = {
    item.key: item for item in (NeutralXlsx(), NeutralCsv(), SymfoniaFkDocuments())
}
DEFAULT_FORMAT = NeutralXlsx.key
