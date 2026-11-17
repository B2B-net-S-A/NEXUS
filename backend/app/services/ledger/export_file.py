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
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Optional, Protocol

from openpyxl import Workbook
from openpyxl.styles import Font

from app.core.export_safety import safe_cell, safe_row


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
    #: Rachunek odbiorcy przelewu (zakup), 26 cyfr NRB.
    payment_account: Optional[str] = None


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


#: Tylko typy z próbek (17.11.2026): FVS, WDT (usługa dla kontrahenta z UE)
#: i FKZ. FVZ, FKS i reszta czekają na próbkę — ``schemat`` i ``Rodzaj``
#: tych typów to pola, których NEXUS nie zna; dopisanie typu = wiersz tu.
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
}

#: Nazwy krajów w pliku (``khKrajNazwa``); w próbkach tylko Polska i Finlandia.
_COUNTRY_NAMES: dict[str, str] = {
    "PL": "Polska", "AT": "Austria", "BE": "Belgia", "BG": "Bułgaria",
    "HR": "Chorwacja", "CY": "Cypr", "CZ": "Czechy", "DK": "Dania",
    "EE": "Estonia", "FI": "Finlandia", "FR": "Francja", "DE": "Niemcy",
    "EL": "Grecja", "GR": "Grecja", "HU": "Węgry", "IE": "Irlandia",
    "IT": "Włochy", "LV": "Łotwa", "LT": "Litwa", "LU": "Luksemburg",
    "MT": "Malta", "NL": "Holandia", "PT": "Portugalia", "RO": "Rumunia",
    "SK": "Słowacja", "SI": "Słowenia", "ES": "Hiszpania", "SE": "Szwecja",
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


def _document(lines: list[ExportLine]) -> list[str]:
    """Blok ``Dokument{…}`` jednej faktury — kolejność pól jak w próbkach."""

    head = lines[0]
    invoice = head.invoice
    if invoice is None:
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
    to_pay = Decimal(0) if kind.correction else abs(invoice.gross)
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
