"""ZUS KEDU (K7a) — deklaracja miesiąca i zgłoszenia jako plik XML do e-Płatnika.

Płace liczą składki w NEXUSIE (``engine``), a plik KEDU przenosi wynik do
e-Płatnika bez przepisywania: ``render_month`` składa ZUS DRA z ZUS RCA
(i ZUS RSA, gdy są świadczenia albo przerwy), ``render_registrations`` —
zgłoszenia ZUS ZUA, ZUS ZZA i wyrejestrowania ZUS ZWUA. Funkcje są czyste:
bez bazy, sieci i zegara — daty przychodzą z wejścia.

Struktura: schemat KEDU 5.7 (``http://www.zus.pl/2026/KEDU_5_7``) ze
specyfikacji „EWD — Elektroniczna Wymiana Dokumentów” w wersji 2.27, ważnej
od 25.04.2026, opis pól z jej załącznika nr 1 („Zakres informacyjny dokumentów
ubezpieczeniowych ZUS”), wzorce z zestawu danych testowych ZUS (DRA_RCA.xml,
DRA_RCA_RSA.xml, ZUA.xml, ZZA.xml, ZWUA.xml), wszystko z BIP ZUS:
https://www.zus.pl/web/biuletyn-informacji-publicznej/inne/wymagania-dla-oprogramowania-interfejsowego/dokumenty-ubezpieczeniowe
Wynik przechodzi walidację tym XSD (``SCHEMA_VERIFIED``); import do e-Płatnika
jest do sprawdzenia przez Płace na pierwszym miesiącu — strona pomocy
e-Płatnika wymienia wersje KEDU tylko do 5.5.

Zasady:

* **Kwoty** przychodzą zaokrąglone do grosza na osobę (silnik). DRA to sumy
  z RCA plus Fundusz Pracy z Funduszem Solidarnościowym i FGŚP z listy; stóp
  tu nie liczymy. Kwota z więcej niż dwoma miejscami po przecinku to błąd.
* **Pola „nie wypełniać”** z załącznika nr 1 (statusy, identyfikatory ZUS,
  PFRON, zasiłki rodzinne) zostają puste; pola kwot DRA i RCA, które się
  wypełnia, wypisujemy w komplecie — zera też, jak Płatnik.
* **Nazwiska, imiona i nazwa skrócona** — wielkimi literami, jak w rejestrach
  ZUS. e-Płatnik porównuje dane z pliku ze swoimi i przy różnicy sam tworzy
  ZUS ZIPA albo ZUS ZIUA, więc nazwa skrócona musi być taka jak w ZUS.
* **Liczba ubezpieczonych** w DRA (III p1) = różne osoby z RCA i RSA.
* **Blok IX DRA** (do zapłaty) = IV p37 − V p5 + VI p7 + VII p3 — od 2018 r.
  jedna wpłata na rachunek składkowy; wynik ujemny trafia do „do zwrotu”.
* **Termin przesyłania** (DRA I p1): „3” = do 15. dnia — płatnik z osobowością
  prawną (kody od 2023 r.: 1 — 5. dzień, 3 — 15. dzień, 6 — 20. dzień).
* Błąd danych — ``KeduError`` z komunikatem po polsku. Komunikat nie zawiera
  numeru PESEL, NIP ani dokumentu osoby: wskazuje pozycję na liście wejścia.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from lxml import etree

from app.services.hr.payroll_errors import PayrollError
from app.services.hr.payroll_lists.pesel import checksum_ok as pesel_checksum_ok
from app.services.order_client_identity import nip_checksum_valid

NAMESPACE = "http://www.zus.pl/2026/KEDU_5_7"
SCHEMA_FILE = "kedu_5_7.xsd"
SCHEMA_VERSION = "5.7.0"
#: Wynik walidowany XSD-em KEDU 5.7 z BIP ZUS; import do e-Płatnika — niesprawdzony.
SCHEMA_VERIFIED = True
SCHEMA_SOURCE = (
    "ZUS, EWD — specyfikacja wejścia-wyjścia 2.27 (ważna od 25.04.2026): "
    "kedu_5_7.xsd, załącznik nr 1 i zestaw danych testowych z BIP ZUS"
)

#: Program w nagłówku KEDU (wymagany, żeby ZUS wiedział, skąd plik).
PROGRAM_PRODUCER = "NEXUS"
PROGRAM_SYMBOL = "NEXUS Płace"
PROGRAM_VERSION = "K7a"

ZERO = Decimal("0")
CENT = Decimal("0.01")
_ZERO = "0.00"
_XSI = "http://www.w3.org/2001/XMLSchema-instance"

#: Typ identyfikatora osoby (RCA/RSA III.A p3): PESEL, dowód osobisty, paszport.
ID_TYPES: dict[str, str] = {"P": "PESEL", "1": "dowód osobisty", "2": "paszport"}
REGISTRATION_KINDS: tuple[str, ...] = ("ZUA", "ZZA", "ZWUA")

_DOCUMENT_RE = re.compile(r"[A-Z0-9]{1,9}")
_NFZ_RE = re.compile(r"(0[1-9]|1[0-6])R")
_TERMINATION_RE = re.compile(r"\d{2}[RW]")


class KeduError(PayrollError):
    """Zła dana do pliku KEDU — komunikat po polsku, bez numerów osoby."""


@dataclass(frozen=True)
class KeduPayer:
    """Płatnik składek z osobowością prawną: NIP, REGON i nazwa skrócona z ZUS."""

    nip: str
    regon: str
    short_name: str
    #: DRA I p1 — „3” = do 15. dnia następnego miesiąca (osoba prawna).
    deadline_code: str = "3"


@dataclass(frozen=True)
class KeduPerson:
    """Osoba w raporcie albo zgłoszeniu: nazwisko, imię i identyfikator."""

    last_name: str
    first_name: str
    #: „P” = PESEL; bez PESEL-u „1” = dowód osobisty, „2” = paszport.
    id_type: str
    id_number: str


@dataclass(frozen=True)
class KeduInsured:
    """Jeden blok ZUS RCA: osoba × kod tytułu, kwoty zaokrąglone przez silnik.

    Kwoty to pola ``Result`` silnika (zsumowane, gdy osoba ma w miesiącu kilka
    pozycji z tym samym kodem tytułu).
    """

    person: KeduPerson
    #: 6 cyfr: kod tytułu (4) + prawo do emerytury/renty + niepełnosprawność,
    #: np. „011000” pracownik, „041100” zleceniobiorca.
    title_code: str
    pension_basis: Decimal = ZERO  # B p4 — emerytalne i rentowe
    sickness_basis: Decimal = ZERO  # B p5
    accident_basis: Decimal = ZERO  # B p6
    pension_employee: Decimal = ZERO  # B p7
    disability_employee: Decimal = ZERO  # B p8
    sickness_employee: Decimal = ZERO  # B p9
    pension_employer: Decimal = ZERO  # B p11
    disability_employer: Decimal = ZERO  # B p12
    accident_employer: Decimal = ZERO  # B p14
    health_basis: Decimal = ZERO  # C p1
    health: Decimal = ZERO  # C p4 — finansowana przez ubezpieczonego
    #: B p28 — wpłata PPK finansowana przez płatnika.
    ppk_employer: Decimal = ZERO
    #: B p3 — wymiar czasu pracy (licznik, mianownik); tylko pracownik.
    work_time: Optional[tuple[int, int]] = None
    #: B p2 — przekroczenie rocznej podstawy (30-krotności): „1” wg ubezpieczonego,
    #: „2” wg płatnika (silnik: notatka ``pension_limit``), „3” wg ZUS.
    annual_limit_code: Optional[str] = None


@dataclass(frozen=True)
class KeduBreak:
    """Jeden blok ZUS RSA: świadczenie albo przerwa w opłacaniu składek."""

    person: KeduPerson
    title_code: str
    #: Kod świadczenia/przerwy, 3 cyfry (np. 331 wynagrodzenie chorobowe,
    #: 313 zasiłek chorobowy, 111 urlop bezpłatny).
    code: str
    date_from: date
    date_to: date
    #: Liczba dni zasiłkowych albo wypłat (B p5).
    days: Optional[int] = None
    #: Kwota świadczenia/wynagrodzenia za czas choroby (B p6).
    amount: Optional[Decimal] = None


@dataclass(frozen=True)
class KeduMonth:
    """Miesiąc składkowy (= miesiąc wypłaty) jednego płatnika."""

    year: int
    month: int
    payer: KeduPayer
    insured: Sequence[KeduInsured]
    labour_fund: Decimal  # FP + FS (DRA VII p1)
    fgsp: Decimal  # DRA VII p2
    accident_rate: Decimal  # stopa wypadkowa w %, np. Decimal("1.67")
    created_on: date  # data wypełnienia dokumentów
    declaration_id: int = 1  # NN identyfikatora deklaracji: 01 = pierwsza za miesiąc
    breaks: Sequence[KeduBreak] = ()
    #: DRA V p1 — zasiłki z ubezpieczenia chorobowego wypłacone przez płatnika.
    sickness_benefits: Decimal = ZERO
    #: DRA V p3 — świadczenia z ubezpieczenia wypadkowego wypłacone przez płatnika.
    accident_benefits: Decimal = ZERO


@dataclass(frozen=True)
class KeduAddress:
    """Adres zameldowania na stałe miejsce pobytu (ZUA XI, ZZA VIII)."""

    postal_code: str  # 5 cyfr, „00-950” też przejdzie
    city: str
    municipality: str = ""  # gmina albo dzielnica
    street: str = ""
    house_number: str = ""
    flat_number: str = ""


@dataclass(frozen=True)
class KeduTermination:
    """ZWUA V — rozwiązanie albo wygaśnięcie stosunku pracy (pracownik)."""

    ended_on: date
    #: Kod trybu, np. „22R” porozumienie stron, „28R” upływ czasu, „48W” zgon.
    mode_code: str
    #: Kod podstawy prawnej, np. „402” (art. 30 § 1 pkt 1 KP).
    legal_basis_code: str
    #: Tekst podstawy — tylko przy kodzie „550”.
    legal_basis_text: Optional[str] = None
    #: 1 = z inicjatywy pracownika, 2 = pracodawcy; brak przy wygaśnięciu.
    initiator: Optional[int] = None


@dataclass(frozen=True)
class KeduRegistration:
    """Zgłoszenie (ZUA, ZZA) albo wyrejestrowanie (ZWUA) jednej osoby."""

    kind: str  # "ZUA" | "ZZA" | "ZWUA"
    person: KeduPerson
    birth_date: date
    title_code: str
    #: ZUA/ZZA: data powstania obowiązku ubezpieczeń; ZWUA: wyrejestrowanie od dnia.
    date_from: date
    #: ZUA/ZZA: kod oddziału NFZ, np. „07R” (mazowiecki).
    nfz_code: Optional[str] = None
    #: „K” albo „M” („F” z kartoteki NEXUSA = „K”).
    sex: Optional[str] = None
    citizenship: Optional[str] = None  # np. „POLSKIE”
    occupation_code: Optional[str] = None  # kod zawodu, 6 cyfr
    address: Optional[KeduAddress] = None
    #: ZUA VI — obowiązkowe ubezpieczenia (zleceniobiorca: bez chorobowego).
    pension: bool = True
    disability: bool = True
    sickness: bool = True
    accident: bool = True
    #: ZUA VIII — dobrowolne chorobowe zleceniobiorcy od ``date_from``.
    voluntary_sickness: bool = False
    #: ZWUA IV p3 — kod przyczyny: 100 ustanie tytułu, 500 zgon, 600 inna.
    reason_code: Optional[str] = None
    termination: Optional[KeduTermination] = None


# ── Walidacja ────────────────────────────────────────────────────────────────


def _digits(raw: str) -> str:
    return "".join(ch for ch in (raw or "") if not ch.isspace() and ch != "-")


def regon_checksum_valid(digits: str) -> bool:
    """REGON 9 albo 14 cyfr z cyfrą kontrolną (mod 11, wynik 10 = 0)."""

    if len(digits) == 9 and digits.isdigit():
        weights: tuple[int, ...] = (8, 9, 2, 3, 4, 5, 6, 7)
    elif len(digits) == 14 and digits.isdigit():
        if not regon_checksum_valid(digits[:9]):
            return False
        weights = (2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8)
    else:
        return False
    control = sum(int(d) * w for d, w in zip(digits, weights)) % 11
    return control % 10 == int(digits[-1])


def _payer(payer: KeduPayer) -> tuple[str, str, str]:
    nip = _digits(payer.nip)
    if not nip_checksum_valid(nip):
        raise KeduError("NIP płatnika: 10 cyfr z poprawną cyfrą kontrolną.")
    regon = _digits(payer.regon)
    if len(regon) == 14 and regon.endswith("00000"):
        regon = regon[:9]  # KRS zapisuje 9-cyfrowy REGON jako 14 cyfr z zerami
    if not regon_checksum_valid(regon):
        raise KeduError("REGON płatnika: 9 albo 14 cyfr z poprawną cyfrą kontrolną.")
    name = " ".join((payer.short_name or "").split()).upper()
    if not 1 <= len(name) <= 31:
        raise KeduError("Nazwa skrócona płatnika: od 1 do 31 znaków, taka jak w ZUS.")
    if not (len(payer.deadline_code) == 1 and payer.deadline_code.isdigit()):
        raise KeduError(
            "Termin przesyłania deklaracji: jedna cyfra (3 = do 15. dnia, osoba prawna)."
        )
    return nip, regon, name


def _where(doc: str, index: int) -> str:
    return f"{doc}, pozycja {index}"


def _name(raw: str, limit: int, label: str, where: str) -> str:
    value = " ".join((raw or "").split()).upper()
    if not value:
        raise KeduError(f"{where}: brak pola „{label}”.")
    if len(value) > limit:
        raise KeduError(
            f"{where}: {label} dłuższe niż {limit} znaków — skróć jak w ZUS."
        )
    return value


def _identity(person: KeduPerson, where: str) -> tuple[str, str, str, str]:
    """→ (nazwisko, imię, typ, numer) po walidacji; komunikat bez numeru."""

    last = _name(person.last_name, 31, "nazwisko", where)
    first = _name(person.first_name, 22, "imię", where)
    if person.id_type not in ID_TYPES:
        raise KeduError(
            f"{where}: typ identyfikatora to P (PESEL), 1 (dowód) albo 2 (paszport)."
        )
    number = _digits(person.id_number).upper()
    if person.id_type == "P":
        if len(number) != 11 or not number.isdigit():
            raise KeduError(f"{where}: PESEL to 11 cyfr.")
        if not pesel_checksum_ok(number):
            raise KeduError(
                f"{where}: PESEL ma złą cyfrę kontrolną — sprawdź kartotekę."
            )
    elif not _DOCUMENT_RE.fullmatch(number):
        raise KeduError(f"{where}: seria i numer dokumentu — do 9 liter i cyfr.")
    return last, first, person.id_type, number


def _title_code(raw: str, where: str) -> str:
    code = _digits(raw)
    if len(code) != 6 or not code.isdigit():
        raise KeduError(f"{where}: kod tytułu ubezpieczenia to 6 cyfr, np. 011000.")
    return code


def _amount(value: Decimal, integer_digits: int, where: str, label: str) -> str:
    """Kwota KEDU: nieujemna, grosze po kropce, nie dłuższa niż pole schematu."""

    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise KeduError(f"{where}: {label} — to nie jest kwota.") from None
    if not number.is_finite():
        raise KeduError(f"{where}: {label} — to nie jest kwota.")
    if number < 0:
        raise KeduError(f"{where}: {label} — kwota ujemna.")
    if number != number.quantize(CENT):
        raise KeduError(f"{where}: {label} — więcej niż dwa miejsca po przecinku.")
    text = f"{number.quantize(CENT):.2f}"
    if len(text) - 3 > integer_digits:
        raise KeduError(f"{where}: {label} — kwota za duża na pole KEDU.")
    return text


def _period(year: int, month: int) -> str:
    if not (1999 <= year <= 2100 and 1 <= month <= 12):
        raise KeduError("Okres rozliczeniowy: rok od 1999 i miesiąc 1–12.")
    return f"{year:04d}-{month:02d}"


def _accident_rate(rate: Decimal) -> str:
    text = _amount(rate, 2, "DRA", "stopa składki wypadkowej")
    if Decimal(text) == 0:
        raise KeduError("DRA: stopa składki wypadkowej — od 0,01 do 99,99 %.")
    return text


# ── Budowa XML ───────────────────────────────────────────────────────────────


def _el(
    parent: etree._Element, tag: str, text: Optional[str] = None, **attrs: str
) -> etree._Element:
    node = etree.SubElement(parent, f"{{{NAMESPACE}}}{tag}", attrs)
    if text is not None:
        node.text = text
    return node


def _fields(
    parent: etree._Element, values: Sequence[tuple[str, Optional[str]]]
) -> None:
    for tag, text in values:
        if text is not None:
            _el(parent, tag, text)


def _code_element(parent: etree._Element, tag: str, code: str) -> None:
    node = _el(parent, tag)
    _el(node, "p1", code[:4])
    _el(node, "p2", code[4])
    _el(node, "p3", code[5])


def _root(created_on: date) -> etree._Element:
    root = etree.Element(f"{{{NAMESPACE}}}KEDU", nsmap={None: NAMESPACE, "xsi": _XSI})
    root.set("wersja_schematu", "1")
    root.set(f"{{{_XSI}}}schemaLocation", f"{NAMESPACE} {SCHEMA_FILE}")
    header = _el(root, "naglowek.KEDU")
    program = _el(header, "program")
    _el(program, "producent", PROGRAM_PRODUCER)
    _el(program, "symbol", PROGRAM_SYMBOL)
    _el(program, "wersja", PROGRAM_VERSION)
    _el(header, "data_utworzenia_KEDU", created_on.isoformat())
    return root


def _payer_block(parent: etree._Element, tag: str, payer: tuple[str, str, str]) -> None:
    nip, regon, name = payer
    block = _el(parent, tag)
    _fields(block, [("p1", nip), ("p2", regon), ("p6", name)])


def _identifier(parent: etree._Element, tag: str, number: str, period: str) -> None:
    node = _el(parent, tag)
    _el(node, "p1", number)
    _el(node, "p2", period)


def _serialize(root: etree._Element) -> bytes:
    return etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", pretty_print=True
    )


def _sum(values: Sequence[Decimal]) -> Decimal:
    return sum(values, ZERO)


# ── Deklaracja miesiąca: DRA + RCA (+ RSA) ──────────────────────────────────


#: Kwoty bloku RCA III.B i III.C: (blok, pole, atrybut, cyfry przed kropką, etykieta).
#: Pozostałe pola kwot to zera; p19–p22 i p25 (PFRON, FK) oraz blok D — „nie wypełniać”.
_RCA_AMOUNTS: tuple[tuple[str, str, str, int, str], ...] = (
    ("B", "p4", "pension_basis", 6, "podstawa emerytalna i rentowe"),
    ("B", "p5", "sickness_basis", 6, "podstawa chorobowa"),
    ("B", "p6", "accident_basis", 6, "podstawa wypadkowa"),
    ("B", "p7", "pension_employee", 5, "emerytalna ubezpieczonego"),
    ("B", "p8", "disability_employee", 5, "rentowe ubezpieczonego"),
    ("B", "p9", "sickness_employee", 5, "chorobowa ubezpieczonego"),
    ("B", "p11", "pension_employer", 5, "emerytalna płatnika"),
    ("B", "p12", "disability_employer", 5, "rentowe płatnika"),
    ("B", "p14", "accident_employer", 5, "wypadkowa płatnika"),
    ("B", "p28", "ppk_employer", 5, "PPK płatnika"),
    ("C", "p1", "health_basis", 8, "podstawa zdrowotnej"),
    ("C", "p4", "health", 7, "składka zdrowotna"),
)
_RCA_ZEROS = {"B": (10, 13, 15, 16, 17, 18, 23, 24, 26, 27), "C": (2, 3, 5)}
#: B p29 — łączna kwota składek osoby (bez PPK).
_RCA_SOCIAL = (
    "pension_employee",
    "disability_employee",
    "sickness_employee",
    "pension_employer",
    "disability_employer",
    "accident_employer",
)


@dataclass(frozen=True)
class _Rca:
    identity: tuple[str, str, str, str]
    code: str
    item: KeduInsured
    amounts: dict[tuple[str, str], str]


def _rca_rows(insured: Sequence[KeduInsured]) -> list[_Rca]:
    rows: list[_Rca] = []
    for index, item in enumerate(insured, start=1):
        where = _where("RCA", index)
        identity = _identity(item.person, where)
        code = _title_code(item.title_code, where)
        if item.work_time is not None:
            numerator, denominator = item.work_time
            if not 1 <= numerator <= denominator <= 999:
                raise KeduError(
                    f"{where}: wymiar czasu pracy — licznik i mianownik 1–999."
                )
        if item.annual_limit_code not in (None, "1", "2", "3"):
            raise KeduError(
                f"{where}: informacja o przekroczeniu podstawy to 1, 2 albo 3."
            )
        amounts = {
            (block, tag): _amount(getattr(item, attr), digits, where, label)
            for block, tag, attr, digits, label in _RCA_AMOUNTS
        }
        for block, numbers in _RCA_ZEROS.items():
            amounts.update({(block, f"p{n}"): _ZERO for n in numbers})
        total = _sum([getattr(item, attr) for attr in _RCA_SOCIAL])
        amounts[("B", "p29")] = _amount(total, 6, where, "łączna kwota składek")
        rows.append(_Rca(identity, code, item, amounts))
    return rows


def _ordered(amounts: dict[tuple[str, str], str], block: str) -> list[tuple[str, str]]:
    fields = [(tag, text) for (name, tag), text in amounts.items() if name == block]
    return sorted(fields, key=lambda field: int(field[0][1:]))


def _rca_block(parent: etree._Element, block_id: int, row: _Rca) -> None:
    item = row.item
    last, first, id_type, number = row.identity
    block = _el(parent, "III", id_bloku=str(block_id))
    _fields(
        _el(block, "A"), [("p1", last), ("p2", first), ("p3", id_type), ("p4", number)]
    )
    b = _el(block, "B")
    _code_element(b, "p1", row.code)
    if item.annual_limit_code is not None:
        _el(b, "p2", item.annual_limit_code)
    if item.work_time is not None:
        time = _el(b, "p3")
        _el(time, "p1", f"{item.work_time[0]:03d}")
        _el(time, "p2", f"{item.work_time[1]:03d}")
    _fields(b, _ordered(row.amounts, "B"))
    _fields(_el(block, "C"), _ordered(row.amounts, "C"))


@dataclass(frozen=True)
class _Rsa:
    identity: tuple[str, str, str, str]
    code: str
    item: KeduBreak
    where: str


def _rsa_rows(breaks: Sequence[KeduBreak]) -> list[_Rsa]:
    rows: list[_Rsa] = []
    for index, item in enumerate(breaks, start=1):
        where = _where("RSA", index)
        identity = _identity(item.person, where)
        code = _title_code(item.title_code, where)
        if not (len(item.code) == 3 and item.code.isdigit()):
            raise KeduError(f"{where}: kod świadczenia albo przerwy to 3 cyfry.")
        if item.date_to < item.date_from:
            raise KeduError(f"{where}: koniec okresu przed początkiem.")
        if item.days is not None and not 0 <= item.days <= 999:
            raise KeduError(f"{where}: liczba dni 0–999.")
        if item.amount is not None:
            _amount(item.amount, 5, where, "kwota świadczenia")
        rows.append(_Rsa(identity, code, item, where))
    return rows


def _rsa_block(parent: etree._Element, block_id: int, row: _Rsa) -> None:
    item = row.item
    last, first, id_type, number = row.identity
    block = _el(parent, "III", id_bloku=str(block_id))
    _fields(
        _el(block, "A"), [("p1", last), ("p2", first), ("p3", id_type), ("p4", number)]
    )
    b = _el(block, "B")
    _code_element(b, "p1", row.code)
    amount = (
        _amount(item.amount, 5, row.where, "kwota świadczenia")
        if item.amount is not None
        else None
    )
    _fields(
        b,
        [
            ("p2", item.code),
            ("p3", item.date_from.isoformat()),
            ("p4", item.date_to.isoformat()),
            ("p5", str(item.days) if item.days is not None else None),
            ("p6", amount),
        ],
    )


def _dra(
    root: etree._Element,
    month: KeduMonth,
    payer: tuple[str, str, str],
    identifier: str,
    period: str,
    rows: list[_Rca],
    persons: int,
) -> None:
    items = [row.item for row in rows]
    pension_ee = _sum([i.pension_employee for i in items])
    pension_er = _sum([i.pension_employer for i in items])
    disability_ee = _sum([i.disability_employee for i in items])
    disability_er = _sum([i.disability_employer for i in items])
    sickness_ee = _sum([i.sickness_employee for i in items])
    accident_er = _sum([i.accident_employer for i in items])
    health = _sum([i.health for i in items])
    pension = pension_ee + pension_er
    disability = disability_ee + disability_er
    social = pension + disability + sickness_ee + accident_er
    benefits = month.sickness_benefits + month.accident_benefits
    funds = month.labour_fund + month.fgsp
    balance = social - benefits + health + funds

    def k(value: Decimal, digits: int, label: str) -> str:
        return _amount(value, digits, "DRA", label)

    dra = _el(root, "ZUSDRA", id_dokumentu="1")
    first = _el(dra, "I")
    _el(first, "p1", month.payer.deadline_code)
    _identifier(first, "p2", identifier, period)
    _payer_block(dra, "II", payer)
    _fields(
        _el(dra, "III"),
        [("p1", str(persons)), ("p3", _accident_rate(month.accident_rate))],
    )
    _fields(
        _el(dra, "IV"),
        [
            ("p1", k(pension, 9, "emerytalna razem")),
            ("p2", k(disability, 9, "rentowe razem")),
            ("p3", k(pension + disability, 9, "emerytalna i rentowe razem")),
            ("p4", k(pension_ee, 9, "emerytalna ubezpieczonych")),
            ("p5", k(disability_ee, 9, "rentowe ubezpieczonych")),
            (
                "p6",
                k(pension_ee + disability_ee, 9, "emerytalne i rentowe ubezpieczonych"),
            ),
            ("p7", k(pension_er, 9, "emerytalna płatnika")),
            ("p8", k(disability_er, 9, "rentowe płatnika")),
            ("p9", k(pension_er + disability_er, 9, "emerytalne i rentowe płatnika")),
            *[(f"p{n}", _ZERO) for n in (10, 11, 12, 16, 17, 18)],
            ("p19", k(sickness_ee, 9, "chorobowa razem")),
            ("p20", k(accident_er, 9, "wypadkowa razem")),
            ("p21", k(sickness_ee + accident_er, 9, "chorobowa i wypadkowa razem")),
            ("p22", k(sickness_ee, 9, "chorobowa ubezpieczonych")),
            ("p23", _ZERO),
            ("p24", k(sickness_ee, 9, "chorobowa i wypadkowa ubezpieczonych")),
            ("p25", _ZERO),
            ("p26", k(accident_er, 9, "wypadkowa płatnika")),
            ("p27", k(accident_er, 9, "chorobowa i wypadkowa płatnika")),
            *[(f"p{n}", _ZERO) for n in (28, 29, 30, 35, 36)],
            ("p37", k(social, 10, "składki społeczne do przekazania")),
        ],
    )
    _fields(
        _el(dra, "V"),
        [
            ("p1", k(month.sickness_benefits, 9, "zasiłki chorobowe")),
            ("p2", _ZERO),
            ("p3", k(month.accident_benefits, 9, "świadczenia wypadkowe")),
            ("p4", _ZERO),
            ("p5", k(benefits, 9, "do potrącenia")),
        ],
    )
    _fields(
        _el(dra, "VI"),
        [
            ("p1", _ZERO),
            ("p2", k(health, 9, "zdrowotna ubezpieczonych")),
            ("p3", _ZERO),
            ("p4", _ZERO),
            ("p5", k(health, 9, "zdrowotna do przekazania")),
            ("p7", k(health, 10, "zdrowotna do zapłaty")),
        ],
    )
    _fields(
        _el(dra, "VII"),
        [
            ("p1", k(month.labour_fund, 9, "Fundusz Pracy i FS")),
            ("p2", k(month.fgsp, 9, "FGŚP")),
            ("p3", k(funds, 10, "FP, FS i FGŚP do zapłaty")),
        ],
    )
    _fields(
        _el(dra, "IX"),
        [
            ("p1", k(max(ZERO, -balance), 11, "do zwrotu")),
            ("p2", k(max(ZERO, balance), 11, "do zapłaty")),
        ],
    )
    _el(_el(dra, "XIII"), "p1", month.created_on.isoformat())


def render_month(month: KeduMonth) -> bytes:
    """Miesiąc → KEDU (UTF-8) z ZUS DRA, ZUS RCA i — gdy są przerwy — ZUS RSA."""

    payer = _payer(month.payer)
    period = _period(month.year, month.month)
    if not 1 <= month.declaration_id <= 99:
        raise KeduError("Numer deklaracji za miesiąc: 1–99 (01 = pierwsza).")
    identifier = f"{month.declaration_id:02d}"
    if not month.insured:
        raise KeduError(
            "Miesiąc bez ubezpieczonych — ZUS RCA wymaga co najmniej jednej osoby."
        )
    for label, value in (
        ("Fundusz Pracy i FS", month.labour_fund),
        ("FGŚP", month.fgsp),
        ("zasiłki chorobowe", month.sickness_benefits),
        ("świadczenia wypadkowe", month.accident_benefits),
    ):
        _amount(value, 9, "DRA", label)
    rows = _rca_rows(month.insured)
    breaks = _rsa_rows(month.breaks)
    persons = {(row.identity[2], row.identity[3]) for row in [*rows, *breaks]}

    root = _root(month.created_on)
    _dra(root, month, payer, identifier, period, rows, len(persons))

    rca = _el(root, "ZUSRCA", id_dokumentu="2")
    _identifier(_el(rca, "I"), "p1", identifier, period)
    _payer_block(rca, "II", payer)
    for block_id, row in enumerate(rows, start=1):
        _rca_block(rca, block_id, row)
    _el(_el(rca, "IV"), "p1", month.created_on.isoformat())

    if breaks:
        rsa = _el(root, "ZUSRSA", id_dokumentu="3")
        _identifier(_el(rsa, "I"), "p1", identifier, period)
        _payer_block(rsa, "II", payer)
        for block_id, row in enumerate(breaks, start=1):
            _rsa_block(rsa, block_id, row)
        _el(_el(rsa, "XI"), "p1", month.created_on.isoformat())
    return _serialize(root)


# ── Zgłoszenia: ZUA, ZZA, ZWUA ───────────────────────────────────────────────


def _person_block(parent: etree._Element, item: KeduRegistration, where: str) -> None:
    last, first, id_type, number = _identity(item.person, where)
    block = _el(parent, "III")
    if id_type == "P":
        _el(block, "p1", number)
    else:
        _el(block, "p3", id_type)
        _el(block, "p4", number)
    _fields(block, [("p5", last), ("p6", first), ("p7", item.birth_date.isoformat())])


def _sex(raw: Optional[str], where: str) -> Optional[str]:
    if raw is None:
        return None
    value = {"F": "K"}.get(raw.upper(), raw.upper())
    if value not in ("K", "M"):
        raise KeduError(f"{where}: płeć to K albo M.")
    return value


def _citizenship(raw: Optional[str], where: str) -> Optional[str]:
    if raw is None:
        return None
    value = " ".join(raw.split()).upper()
    if not 1 <= len(value) <= 22:
        raise KeduError(f"{where}: obywatelstwo — do 22 znaków, np. POLSKIE.")
    return value


def _nfz(raw: Optional[str], where: str) -> str:
    value = (raw or "").upper()
    if not _NFZ_RE.fullmatch(value):
        raise KeduError(f"{where}: kod oddziału NFZ — od 01R do 16R.")
    return value


def _occupation(raw: Optional[str], where: str) -> Optional[str]:
    if raw is None:
        return None
    if not (len(raw) == 6 and raw.isdigit()):
        raise KeduError(f"{where}: kod zawodu to 6 cyfr.")
    return raw


def _text(raw: str, limit: int, where: str, label: str) -> Optional[str]:
    value = " ".join((raw or "").split()).upper()
    if len(value) > limit:
        raise KeduError(f"{where}: {label} — do {limit} znaków.")
    return value or None


def _address(
    parent: etree._Element, tag: str, address: KeduAddress, where: str
) -> None:
    postal = _digits(address.postal_code)
    if not (len(postal) == 5 and postal.isdigit()):
        raise KeduError(f"{where}: kod pocztowy to 5 cyfr.")
    city = _text(address.city, 26, where, "miejscowość")
    if city is None:
        raise KeduError(f"{where}: brak miejscowości w adresie.")
    _fields(
        _el(parent, tag),
        [
            ("p1", postal),
            ("p2", city),
            ("p3", _text(address.municipality, 26, where, "gmina")),
            ("p4", _text(address.street, 30, where, "ulica")),
            ("p5", _text(address.house_number, 7, where, "numer domu")),
            ("p6", _text(address.flat_number, 7, where, "numer lokalu")),
        ],
    )


def _flag(value: bool) -> str:
    return "true" if value else "false"


def _zua(doc: etree._Element, item: KeduRegistration, code: str, where: str) -> None:
    nfz = _nfz(item.nfz_code, where)
    sex = _sex(item.sex, where)
    citizenship = _citizenship(item.citizenship, where)
    if citizenship or sex:
        _fields(_el(doc, "IV"), [("p3", citizenship), ("p4", sex)])
    _code_element(_el(doc, "V"), "p1", code)
    _fields(
        _el(doc, "VI"),
        [
            ("p1", item.date_from.isoformat()),
            ("p2", _flag(item.pension)),
            ("p3", _flag(item.disability)),
            ("p4", _flag(item.sickness)),
            ("p5", _flag(item.accident)),
        ],
    )
    _fields(_el(doc, "VII"), [("p1", item.date_from.isoformat()), ("p2", nfz)])
    if item.voluntary_sickness:
        if item.sickness:
            raise KeduError(f"{where}: chorobowe obowiązkowe albo dobrowolne, nie oba.")
        _fields(_el(doc, "VIII"), [("p5", "true"), ("p6", item.date_from.isoformat())])
    occupation = _occupation(item.occupation_code, where)
    if occupation:
        _el(_el(doc, "X"), "p1", occupation)
    if item.address is not None:
        _address(doc, "XI", item.address, where)


def _zza(doc: etree._Element, item: KeduRegistration, code: str, where: str) -> None:
    nfz = _nfz(item.nfz_code, where)
    sex = _sex(item.sex, where)
    citizenship = _citizenship(item.citizenship, where)
    if citizenship or sex:
        _fields(_el(doc, "IV"), [("p3", citizenship), ("p4", sex)])
    title = _el(doc, "V")
    _code_element(title, "p1", code)
    occupation = _occupation(item.occupation_code, where)
    if occupation:
        _el(title, "p2", occupation)
    _fields(_el(doc, "VI"), [("p1", item.date_from.isoformat()), ("p2", nfz)])
    if item.address is not None:
        _address(doc, "VIII", item.address, where)


def _zwua(doc: etree._Element, item: KeduRegistration, code: str, where: str) -> None:
    reason = item.reason_code or ""
    if not (len(reason) == 3 and reason.isdigit()):
        raise KeduError(f"{where}: kod przyczyny wyrejestrowania to 3 cyfry (np. 100).")
    block = _el(doc, "IV")
    _code_element(block, "p1", code)
    _fields(block, [("p2", item.date_from.isoformat()), ("p3", reason)])
    end = item.termination
    if end is None:
        return
    mode = end.mode_code.upper()
    if not _TERMINATION_RE.fullmatch(mode):
        raise KeduError(f"{where}: kod trybu rozwiązania, np. 22R albo 48W.")
    if not (len(end.legal_basis_code) == 3 and end.legal_basis_code.isdigit()):
        raise KeduError(f"{where}: kod podstawy prawnej rozwiązania to 3 cyfry.")
    text = " ".join((end.legal_basis_text or "").split()) or None
    if end.legal_basis_code == "550" and not text:
        raise KeduError(f"{where}: przy kodzie 550 wpisz podstawę prawną rozwiązania.")
    if end.legal_basis_code != "550":
        text = None
    if text is not None and len(text) > 72:
        raise KeduError(f"{where}: podstawa prawna rozwiązania — do 72 znaków.")
    if end.initiator not in (None, 1, 2):
        raise KeduError(f"{where}: strona rozwiązania: 1 pracownik albo 2 pracodawca.")
    _fields(
        _el(doc, "V"),
        [
            ("p1", end.ended_on.isoformat()),
            ("p2", mode),
            ("p3", end.legal_basis_code),
            ("p4", text),
            ("p5", str(end.initiator) if end.initiator is not None else None),
        ],
    )


#: Blok oświadczenia (data wypełnienia) w każdym zgłoszeniu.
_STATEMENT_BLOCK = {"ZUA": "XIV", "ZZA": "XI", "ZWUA": "VI"}


def render_registrations(
    payer: KeduPayer, items: Sequence[KeduRegistration], created_on: date
) -> bytes:
    """Zgłoszenia i wyrejestrowania → jeden plik KEDU (UTF-8), dokument na osobę."""

    payer_data = _payer(payer)
    if not items:
        raise KeduError(
            "Brak zgłoszeń — KEDU musi zawierać co najmniej jeden dokument."
        )
    root = _root(created_on)
    for doc_id, item in enumerate(items, start=1):
        if item.kind not in REGISTRATION_KINDS:
            raise KeduError(
                f"Pozycja {doc_id}: rodzaj zgłoszenia to ZUA, ZZA albo ZWUA."
            )
        where = _where(f"ZUS {item.kind}", doc_id)
        code = _title_code(item.title_code, where)
        doc = _el(root, f"ZUS{item.kind}", id_dokumentu=str(doc_id))
        _el(_el(doc, "I"), "p1", "true")
        _payer_block(doc, "II", payer_data)
        _person_block(doc, item, where)
        if item.kind == "ZUA":
            _zua(doc, item, code, where)
        elif item.kind == "ZZA":
            _zza(doc, item, code, where)
        else:
            _zwua(doc, item, code, where)
        _el(_el(doc, _STATEMENT_BLOCK[item.kind]), "p1", created_on.isoformat())
    return _serialize(root)


__all__ = [
    "ID_TYPES",
    "NAMESPACE",
    "PROGRAM_PRODUCER",
    "PROGRAM_SYMBOL",
    "PROGRAM_VERSION",
    "REGISTRATION_KINDS",
    "SCHEMA_FILE",
    "SCHEMA_SOURCE",
    "SCHEMA_VERIFIED",
    "SCHEMA_VERSION",
    "KeduAddress",
    "KeduBreak",
    "KeduError",
    "KeduInsured",
    "KeduMonth",
    "KeduPayer",
    "KeduPerson",
    "KeduRegistration",
    "KeduTermination",
    "regon_checksum_valid",
    "render_month",
    "render_registrations",
]
