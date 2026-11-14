"""PIT-11, PIT-4R i PIT-8AR jako XML e-Deklaracji (K7a).

Płace liczą zaliczki w NEXUSIE (``engine``), a te funkcje składają z sum roku
pliki do podpisania i wysłania bramką e-Deklaracji: informację PIT-11 dla
osoby oraz deklaracje roczne płatnika PIT-4R (zaliczki ze skali) i PIT-8AR
(podatek ryczałtowy od umów do 200 zł). Funkcje są czyste: bez bazy, sieci
i zegara. ``*_document`` zwraca pozycje formularza — te same czyta wydruk
(``forms_pdf``), więc PDF i XML nie mogą się rozjechać.

Schematy z Centralnego Repozytorium Wzorów Dokumentów Elektronicznych:

* PIT-11 (29), schemat 4-0E (lata od 2024): http://crd.gov.pl/wzor/2024/10/15/13535/
* PIT-4R (13), schemat 1-0E (lata od 2023): http://crd.gov.pl/wzor/2023/11/07/12978/
* PIT-8AR (14), schemat 1-0E (lata od 2024): http://crd.gov.pl/wzor/2024/10/10/13525/

Wynik przechodzi walidację tymi XSD (z typami ``StrukturyDanych`` i słownikami
urzędów skarbowych); podpis i wysyłka — do sprawdzenia przez Płace przy
pierwszym roku (``SCHEMA_VERIFIED`` mówi tylko o XSD). PIT-8AR (14) ma
w schemacie ``kodSystemowy="PT-8AR (14)"`` — tak jest w oficjalnym XSD.

Zasady PIT-11 (objaśnienia ze schematu):

* Część E pokazuje tylko przychód opodatkowany. Ulga dla młodych (art. 21
  ust. 1 pkt 148) idzie do poz. 109–111, ulgi na powrót, 4+ i dla seniora
  (pkt 152–154) — do poz. 114–120; składki od przychodu zwolnionego — poz. 97.
* Wiersze 2 i 7 — przychód opodatkowany osób do 26 lat (rezygnacja z ulgi
  albo przekroczony limit), 3 i 8 — od wieku 60/65 lat; składki od nich —
  poz. 96, pozostałe składki odliczone — poz. 95. Dzieło — wiersz 5.
* Umowy z podatkiem ryczałtowym (do 200 zł) nie trafiają do PIT-11 — do PIT-8AR.
* Przychód, koszty i składki w złotych i groszach, zaliczki i podatek w pełnych
  złotych (art. 63 Ordynacji podatkowej) — kwota z groszami w tych polach to błąd.
* Tylko podatnik z nieograniczonym obowiązkiem podatkowym (poz. 11 = 1).

Błąd danych — ``PitFormError`` z komunikatem po polsku, bez numeru PESEL i NIP.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from lxml import etree

from app.services.hr.payroll_errors import PayrollError
from app.services.hr.payroll_lists.pesel import checksum_ok as pesel_checksum_ok
from app.services.order_client_identity import nip_checksum_valid

#: Wynik walidowany oficjalnymi XSD z crd.gov.pl; wysyłka do e-Deklaracji — niesprawdzona.
SCHEMA_VERIFIED = True
SCHEMA_SOURCE = (
    "crd.gov.pl: PIT-11 (29) 4-0E wzor/2024/10/15/13535, PIT-4R (13) 1-0E "
    "wzor/2023/11/07/12978, PIT-8AR (14) 1-0E wzor/2024/10/10/13525"
)

ZERO = Decimal("0")
CENT = Decimal("0.01")
KINDS: tuple[str, ...] = ("uop", "zlecenie", "dzielo")
#: Ulgi poza ulgą dla młodych → pole wyboru podstawy prawnej w PIT-11.
OTHER_RELIEFS: dict[str, tuple[str, str]] = {
    "return": ("P_118", "art. 21 ust. 1 pkt 152 — ulga na powrót"),
    "family4": ("P_119", "art. 21 ust. 1 pkt 153 — ulga dla rodzin 4+"),
    "senior": ("P_120", "art. 21 ust. 1 pkt 154 — ulga dla seniora"),
}
RELIEFS: tuple[str, ...] = ("youth", *OTHER_RELIEFS)
PURPOSES: dict[str, str] = {"1": "złożenie", "2": "korekta"}

_NIP_PATTERN = re.compile(r"[1-9]((\d[1-9])|([1-9]\d))\d{7}")
_OFFICE_RE = re.compile(r"\d{4}")
_COUNTRY_RE = re.compile(r"[A-Z]{2}")


class PitFormError(PayrollError):
    """Zła dana do formularza PIT — komunikat po polsku, bez numerów osoby."""


@dataclass(frozen=True)
class FormSpec:
    """Stałe wzoru formularza z jego schematu XSD."""

    form: str
    system_code: str
    tax_code: str
    obligation: str
    schema_version: str
    variant: int
    namespace: str
    types_namespace: str
    purpose_position: str
    min_year: int
    payer_role: str
    statement_tag: str
    title: str


PIT11 = FormSpec(
    form="PIT-11",
    system_code="PIT-11 (29)",
    tax_code="PIT",
    obligation="Z",
    schema_version="4-0E",
    variant=29,
    namespace="http://crd.gov.pl/wzor/2024/10/15/13535/",
    types_namespace="http://crd.gov.pl/xml/schematy/dziedzinowe/mf/2024/07/08/eD/DefinicjeTypy/",
    purpose_position="P_7",
    min_year=2024,
    payer_role="Płatnik/Składający",
    statement_tag="Pouczenie",
    title="Informacja o przychodach z innych źródeł oraz o dochodach i pobranych zaliczkach",
)
PIT4R = FormSpec(
    form="PIT-4R",
    system_code="PIT-4R (13)",
    tax_code="PIT",
    obligation="P",
    schema_version="1-0E",
    variant=13,
    namespace="http://crd.gov.pl/wzor/2023/11/07/12978/",
    types_namespace="http://crd.gov.pl/xml/schematy/dziedzinowe/mf/2022/09/13/eD/DefinicjeTypy/",
    purpose_position="P_6",
    min_year=2023,
    payer_role="Płatnik",
    statement_tag="Pouczenia",
    title="Deklaracja roczna o zaliczkach na podatek dochodowy",
)
PIT8AR = FormSpec(
    form="PIT-8AR",
    system_code="PT-8AR (14)",  # tak w oficjalnym schemacie (fixed), nie „PIT-8AR (14)”
    tax_code="PPR",
    obligation="P",
    schema_version="1-0E",
    variant=14,
    namespace="http://crd.gov.pl/wzor/2024/10/10/13525/",
    types_namespace="http://crd.gov.pl/xml/schematy/dziedzinowe/mf/2022/09/13/eD/DefinicjeTypy/",
    purpose_position="P_6",
    min_year=2024,
    payer_role="Płatnik",
    statement_tag="Pouczenia",
    title="Deklaracja roczna o zryczałtowanym podatku dochodowym",
)


@dataclass(frozen=True)
class TaxPayer:
    """Płatnik z osobowością prawną (Podmiot1). Formularze nie mają pola REGON."""

    nip: str
    full_name: str
    #: Urząd skarbowy płatnika — KodUrzedu w PIT-4R i PIT-8AR.
    tax_office_code: str


@dataclass(frozen=True)
class PersonAddress:
    """Adres zamieszkania podatnika (PIT-11 poz. 19–27)."""

    city: str
    country_code: str = "PL"
    voivodeship: str = ""
    county: str = ""
    municipality: str = ""
    street: str = ""
    house_number: str = ""
    flat_number: str = ""
    postal_code: str = ""


@dataclass(frozen=True)
class Pit11Person:
    """Podatnik (Podmiot2): PESEL albo — bez PESEL-u — NIP."""

    last_name: str
    first_name: str
    birth_date: date
    #: Urząd skarbowy podatnika (wg miejsca zamieszkania) — KodUrzedu w PIT-11.
    tax_office_code: str
    pesel: Optional[str] = None
    nip: Optional[str] = None
    address: Optional[PersonAddress] = None


@dataclass(frozen=True)
class Pit11Row:
    """Wiersz części E: przychód, koszty i zaliczka (dochód = przychód − koszty)."""

    revenue: Decimal = ZERO
    kup: Decimal = ZERO
    advance: Decimal = ZERO  # pełne złote

    @property
    def empty(self) -> bool:
        return self.revenue == 0 and self.kup == 0 and self.advance == 0


EMPTY_ROW = Pit11Row()


@dataclass(frozen=True)
class Pit11Amounts:
    """Kwoty roku jednej osoby rozłożone na pozycje PIT-11."""

    employment: Pit11Row = EMPTY_ROW  # wiersz 1, poz. 29–33
    employment_under26: Pit11Row = EMPTY_ROW  # wiersz 2, poz. 36–40
    employment_senior: Pit11Row = EMPTY_ROW  # wiersz 3, poz. 43–47
    personal_services: Pit11Row = EMPTY_ROW  # wiersz 5, poz. 54–57 (umowa o dzieło)
    mandate: Pit11Row = EMPTY_ROW  # wiersz 6, poz. 58–61
    mandate_under26: Pit11Row = EMPTY_ROW  # wiersz 7, poz. 62–65
    mandate_senior: Pit11Row = EMPTY_ROW  # wiersz 8, poz. 66–69
    social: Decimal = ZERO  # poz. 95 — składki odliczone (wiersze 1, 5, 6)
    social_special: Decimal = ZERO  # poz. 96 — składki od wierszy 2, 3, 7, 8
    social_exempt: Decimal = ZERO  # poz. 97 — składki od przychodu zwolnionego
    health: Decimal = ZERO  # poz. 122
    youth_exempt_employment: Decimal = ZERO  # poz. 110 (poz. 109 = suma)
    youth_exempt_mandate: Decimal = ZERO  # poz. 111
    relief_exempt_employment: Decimal = ZERO  # poz. 115 (poz. 114 = suma)
    relief_exempt_mandate: Decimal = ZERO  # poz. 116
    #: Ulgi z poz. 114: "return", "family4", "senior" (poz. 118–120).
    reliefs: frozenset[str] = frozenset()
    #: Poz. 28: 1 zwykłe koszty z jednego stosunku pracy, 3 podwyższone (dojazd).
    kup_code: int = 1


@dataclass(frozen=True)
class Pit11Entry:
    """Jedna pozycja listy płac osoby w roku — pola ``Result`` silnika."""

    kind: str  # uop | zlecenie | dzielo
    revenue: Decimal  # Result.revenue — z przychodem zwolnionym
    exempt_revenue: Decimal = ZERO  # Result.exempt_revenue
    kup: Decimal = ZERO  # Result.kup
    advance: Decimal = ZERO  # Result.pit
    social: Decimal = ZERO  # Result.social_employee
    social_deductible: Decimal = ZERO  # Result.social_deductible
    health: Decimal = ZERO  # Result.health
    #: Result.tax_kind == "flat" — pozycja idzie do PIT-8AR, nie do PIT-11.
    flat_tax: bool = False
    #: Ulga, która zwolniła przychód: youth | family4 | return | senior
    #: (``relief_from_notes(Result.notes)``).
    relief: Optional[str] = None
    #: Wypłata do dnia 26. urodzin włącznie (wiersze 2 i 7).
    under26: bool = False
    #: 60/65 lat w dniu wypłaty i ubezpieczenia społeczne z tej umowy (wiersze 3 i 8).
    senior_age: bool = False


@dataclass(frozen=True)
class Pit4rMonth:
    """Miesiąc pobrania zaliczek (= miesiąc wypłaty), pełne złote."""

    employment_advances: Decimal = ZERO  # wiersz 1: art. 32 — stosunek pracy
    mandate_advances: Decimal = ZERO  # wiersz 3: art. 41 — zlecenie i dzieło (skala)
    employment_taxpayers: int = 0  # wiersz 1: liczba podatników


@dataclass(frozen=True)
class FormField:
    """Pozycja formularza: kod pola, opis, wartość jak w XML i część wydruku."""

    code: str
    label: str
    value: str
    group: str
    kind: str  # "zl_gr" | "zl" | "number" | "choice"
    #: Miesiąc kolumny PIT-4R / PIT-8AR (1–12); ``None`` = pole roczne.
    month: Optional[int] = None


@dataclass(frozen=True)
class FormDocument:
    """Formularz po walidacji: nagłówek, podmioty i pozycje szczegółowe."""

    spec: FormSpec
    year: int
    purpose: str
    office_code: str
    payer_nip: str
    payer_name: str
    fields: tuple[FormField, ...]
    person: Optional[Pit11Person] = None


# ── Walidacja i formaty ──────────────────────────────────────────────────────


def _decimal(value: Decimal, where: str) -> Decimal:
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise PitFormError(f"{where}: to nie jest kwota.") from None
    if not number.is_finite():
        raise PitFormError(f"{where}: to nie jest kwota.")
    if number < 0:
        raise PitFormError(f"{where}: kwota ujemna.")
    return number


def zl_gr(value: Decimal, where: str) -> str:
    """Kwota w złotych i groszach (TKwota2Nieujemna): ``"1234.56"``."""

    number = _decimal(value, where)
    if number != number.quantize(CENT):
        raise PitFormError(f"{where}: więcej niż dwa miejsca po przecinku.")
    text = f"{number.quantize(CENT):.2f}"
    if len(text) - 1 > 16:
        raise PitFormError(f"{where}: kwota za duża.")
    return text


def zl(value: Decimal, where: str) -> str:
    """Kwota w pełnych złotych (TKwotaCNieujemna): ``"1234"``."""

    number = _decimal(value, where)
    if number != number.to_integral_value():
        raise PitFormError(f"{where}: podatek i zaliczki w pełnych złotych.")
    text = str(int(number))
    if len(text) > 14:
        raise PitFormError(f"{where}: kwota za duża.")
    return text


def _year(spec: FormSpec, year: int) -> int:
    if not spec.min_year <= year <= 2050:
        raise PitFormError(
            f"{spec.form}: wzór obejmuje lata od {spec.min_year} do 2050."
        )
    return year


def _purpose(spec: FormSpec, purpose: str) -> str:
    if purpose not in PURPOSES:
        raise PitFormError(f"{spec.form}: cel złożenia 1 (złożenie) albo 2 (korekta).")
    return purpose


def _office(raw: str, where: str) -> str:
    code = (raw or "").strip()
    if not _OFFICE_RE.fullmatch(code):
        raise PitFormError(f"{where}: kod urzędu skarbowego to 4 cyfry.")
    return code


def _nip(raw: str, where: str) -> str:
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if not (_NIP_PATTERN.fullmatch(digits) and nip_checksum_valid(digits)):
        raise PitFormError(f"{where}: NIP to 10 cyfr z poprawną cyfrą kontrolną.")
    return digits


def _token(raw: str, limit: int, where: str, *, required: bool = True) -> str:
    value = " ".join((raw or "").split())
    if required and not value:
        raise PitFormError(f"{where}: pole jest wymagane.")
    if len(value) > limit:
        raise PitFormError(f"{where}: do {limit} znaków.")
    return value


def _payer(payer: TaxPayer, spec: FormSpec) -> tuple[str, str]:
    nip = _nip(payer.nip, f"{spec.form}, płatnik")
    name = _token(payer.full_name, 240, f"{spec.form}, pełna nazwa płatnika")
    return nip, name


def _person(person: Pit11Person) -> Pit11Person:
    where = "PIT-11, podatnik"
    last = _token(person.last_name, 81, f"{where}, nazwisko")
    first = _token(person.first_name, 30, f"{where}, imię")
    if (person.pesel is None) == (person.nip is None):
        raise PitFormError(f"{where}: podaj PESEL albo — bez PESEL-u — NIP.")
    pesel = nip = None
    if person.pesel is not None:
        pesel = "".join(ch for ch in person.pesel if not ch.isspace())
        if not (len(pesel) == 11 and pesel.isdigit() and pesel_checksum_ok(pesel)):
            raise PitFormError(f"{where}: PESEL to 11 cyfr z poprawną cyfrą kontrolną.")
        if len(set(pesel)) == 1:
            raise PitFormError(
                f"{where}: PESEL z jednej powtórzonej cyfry — sprawdź numer."
            )
    else:
        nip = _nip(person.nip or "", where)
        if len(set(nip)) == 1:
            raise PitFormError(
                f"{where}: NIP z jednej powtórzonej cyfry — sprawdź numer."
            )
    if not date(1900, 1, 1) <= person.birth_date <= date(2050, 12, 31):
        raise PitFormError(f"{where}: data urodzenia poza zakresem formularza.")
    office = _office(person.tax_office_code, f"{where}, urząd skarbowy")
    address = None
    if person.address is not None:
        address = _address(person.address)
    return Pit11Person(
        last_name=last,
        first_name=first,
        birth_date=person.birth_date,
        tax_office_code=office,
        pesel=pesel,
        nip=nip,
        address=address,
    )


def _address(raw: PersonAddress) -> PersonAddress:
    where = "PIT-11, adres podatnika"
    country = (raw.country_code or "").strip().upper()
    if not _COUNTRY_RE.fullmatch(country):
        raise PitFormError(f"{where}: kod kraju to dwie litery, np. PL.")
    postal = _token(raw.postal_code, 8, f"{where}, kod pocztowy", required=False)
    if country == "PL" and postal:
        digits = "".join(ch for ch in postal if ch.isdigit())
        if len(digits) != 5:
            raise PitFormError(f"{where}: polski kod pocztowy to 5 cyfr (00-000).")
        postal = f"{digits[:2]}-{digits[2:]}"
    return PersonAddress(
        city=_token(raw.city, 56, f"{where}, miejscowość"),
        country_code=country,
        voivodeship=_token(
            raw.voivodeship, 36, f"{where}, województwo", required=False
        ),
        county=_token(raw.county, 36, f"{where}, powiat", required=False),
        municipality=_token(raw.municipality, 36, f"{where}, gmina", required=False),
        street=_token(raw.street, 65, f"{where}, ulica", required=False),
        house_number=_token(
            raw.house_number, 9, f"{where}, numer domu", required=False
        ),
        flat_number=_token(
            raw.flat_number, 10, f"{where}, numer lokalu", required=False
        ),
        postal_code=postal,
    )


# ── PIT-11: z pozycji listy płac na pozycje formularza ──────────────────────


def relief_from_notes(notes: Sequence[str]) -> Optional[str]:
    """Notatki ``Result`` silnika → ulga, która zwolniła przychód (albo ``None``)."""

    for relief in RELIEFS:
        if f"relief_{relief}" in notes:
            return relief
    return None


_ROW_NAMES: dict[tuple[str, str], str] = {
    ("uop", "plain"): "employment",
    ("uop", "under26"): "employment_under26",
    ("uop", "senior"): "employment_senior",
    ("zlecenie", "plain"): "mandate",
    ("zlecenie", "under26"): "mandate_under26",
    ("zlecenie", "senior"): "mandate_senior",
    ("dzielo", "plain"): "personal_services",
    ("dzielo", "under26"): "personal_services",
    ("dzielo", "senior"): "personal_services",
}
_SPECIAL_ROWS = frozenset(
    {"employment_under26", "employment_senior", "mandate_under26", "mandate_senior"}
)


def pit11_amounts(entries: Sequence[Pit11Entry], *, kup_code: int = 1) -> Pit11Amounts:
    """Pozycje listy płac osoby w roku → kwoty PIT-11 (wiersze E, składki, ulgi)."""

    rows: dict[str, list[Decimal]] = {
        name: [ZERO, ZERO, ZERO] for name in _ROW_NAMES.values()
    }
    social = special = exempt_social = health = ZERO
    youth = {"uop": ZERO, "zlecenie": ZERO}
    other = {"uop": ZERO, "zlecenie": ZERO}
    reliefs: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        where = f"PIT-11, pozycja {index}"
        if entry.kind not in KINDS:
            raise PitFormError(f"{where}: rodzaj umowy uop, zlecenie albo dzielo.")
        if entry.flat_tax:
            continue
        exempt = entry.exempt_revenue
        if exempt > entry.revenue:
            raise PitFormError(f"{where}: przychód zwolniony większy od przychodu.")
        if exempt > 0:
            if entry.kind == "dzielo":
                raise PitFormError(f"{where}: umowa o dzieło nie ma ulg zwalniających.")
            if entry.relief == "youth":
                youth[entry.kind] += exempt
            elif entry.relief in OTHER_RELIEFS:
                other[entry.kind] += exempt
                reliefs.add(entry.relief)
            else:
                raise PitFormError(f"{where}: przychód zwolniony bez rodzaju ulgi.")
        exempt_social += entry.social - entry.social_deductible
        health += entry.health
        taxable = entry.revenue - exempt
        if taxable == 0 and entry.kup == 0 and entry.advance == 0:
            continue
        group = (
            "under26" if entry.under26 else "senior" if entry.senior_age else "plain"
        )
        name = _ROW_NAMES[(entry.kind, group)]
        row = rows[name]
        row[0] += taxable
        row[1] += entry.kup
        row[2] += entry.advance
        if name in _SPECIAL_ROWS:
            special += entry.social_deductible
        else:
            social += entry.social_deductible
    built = {name: Pit11Row(*values) for name, values in rows.items()}
    return Pit11Amounts(
        **built,
        social=social,
        social_special=special,
        social_exempt=exempt_social,
        health=health,
        youth_exempt_employment=youth["uop"],
        youth_exempt_mandate=youth["zlecenie"],
        relief_exempt_employment=other["uop"],
        relief_exempt_mandate=other["zlecenie"],
        reliefs=frozenset(reliefs),
        kup_code=kup_code,
    )


#: Wiersze części E: (pole Pit11Amounts, numer wiersza, opis, poz. przychodu).
_PIT11_ROWS: tuple[tuple[str, int, str, int], ...] = (
    ("employment", 1, "Należności ze stosunku pracy", 29),
    ("employment_under26", 2, "Stosunek pracy — podatnicy do 26 lat", 36),
    ("employment_senior", 3, "Stosunek pracy — od wieku emerytalnego", 43),
    (
        "personal_services",
        5,
        "Działalność wykonywana osobiście, w tym umowa o dzieło",
        54,
    ),
    ("mandate", 6, "Umowa zlecenia", 58),
    ("mandate_under26", 7, "Umowa zlecenia — podatnicy do 26 lat", 62),
    ("mandate_senior", 8, "Umowa zlecenia — seniorzy bez emerytury", 66),
)
#: Odstęp poz. zaliczki od poz. przychodu (wiersze 1–3 mają poz. „dochód zwolniony”).
_ADVANCE_OFFSET = {1: 4, 2: 4, 3: 4, 5: 3, 6: 3, 7: 3, 8: 3}
_KUP_CODES = {
    1: "z jednego stosunku pracy",
    2: "z więcej niż jednego stosunku pracy",
    3: "z jednego stosunku pracy, podwyższone (dojazd)",
    4: "z więcej niż jednego stosunku pracy, podwyższone (dojazd)",
}


def _pit11_fields(amounts: Pit11Amounts) -> list[FormField]:
    fields: list[FormField] = []

    def add(code: str, label: str, value: str, group: str, kind: str) -> None:
        fields.append(FormField(code, label, value, group, kind))

    add(
        "P_11",
        "Rodzaj obowiązku podatkowego: nieograniczony (rezydent)",
        "1",
        "Podatnik",
        "choice",
    )
    if amounts.kup_code not in _KUP_CODES:
        raise PitFormError("PIT-11: informacja o kosztach (poz. 28) to 1–4.")
    for attr, number, title, first in _PIT11_ROWS:
        row: Pit11Row = getattr(amounts, attr)
        if row.empty:
            continue
        where = f"PIT-11, wiersz {number}"
        group = f"E. Wiersz {number} — {title}"
        income = _decimal(row.revenue, where) - _decimal(row.kup, where)
        if income < 0:
            raise PitFormError(f"{where}: koszty wyższe od przychodu.")
        if number == 1:
            add(
                "P_28",
                f"Koszty uzyskania: {_KUP_CODES[amounts.kup_code]}",
                str(amounts.kup_code),
                group,
                "choice",
            )
        add(f"P_{first}", "Przychód", zl_gr(row.revenue, where), group, "zl_gr")
        add(
            f"P_{first + 1}",
            "Koszty uzyskania przychodów",
            zl_gr(row.kup, where),
            group,
            "zl_gr",
        )
        add(f"P_{first + 2}", "Dochód", zl_gr(income, where), group, "zl_gr")
        add(
            f"P_{first + _ADVANCE_OFFSET[number]}",
            "Zaliczka pobrana przez płatnika",
            zl(row.advance, where),
            group,
            "zl",
        )
    social_group = "Składki na ubezpieczenia społeczne"
    for code, label, value in (
        ("P_95", "Odliczone od dochodu (wiersze 1, 5, 6)", amounts.social),
        ("P_96", "Od przychodu z wierszy 2, 3, 7, 8", amounts.social_special),
        (
            "P_97",
            "Od przychodu zwolnionego (poz. 110, 111, 115, 116)",
            amounts.social_exempt,
        ),
    ):
        if value:
            add(
                code,
                label,
                zl_gr(value, f"PIT-11, poz. {code[2:]}"),
                social_group,
                "zl_gr",
            )
    exempt_group = "Przychody zwolnione od podatku"
    youth = amounts.youth_exempt_employment + amounts.youth_exempt_mandate
    if youth:
        add(
            "P_109",
            "Ulga dla młodych (art. 21 ust. 1 pkt 148) — razem",
            zl_gr(youth, "PIT-11, poz. 109"),
            exempt_group,
            "zl_gr",
        )
        for code, label, value in (
            ("P_110", "w tym ze stosunku pracy", amounts.youth_exempt_employment),
            ("P_111", "w tym z umów zlecenia", amounts.youth_exempt_mandate),
        ):
            if value:
                add(
                    code,
                    label,
                    zl_gr(value, f"PIT-11, poz. {code[2:]}"),
                    exempt_group,
                    "zl_gr",
                )
    other = amounts.relief_exempt_employment + amounts.relief_exempt_mandate
    unknown = set(amounts.reliefs) - set(OTHER_RELIEFS)
    if unknown:
        raise PitFormError("PIT-11: ulgi z poz. 114 to return, family4 i senior.")
    if other and not amounts.reliefs:
        raise PitFormError(
            "PIT-11: przychód zwolniony z poz. 114 bez podstawy prawnej ulgi."
        )
    if other:
        add(
            "P_114",
            "Ulga na powrót, 4+, dla seniora (art. 21 ust. 1 pkt 152–154) — razem",
            zl_gr(other, "PIT-11, poz. 114"),
            exempt_group,
            "zl_gr",
        )
        for code, label, value in (
            ("P_115", "w tym ze stosunku pracy", amounts.relief_exempt_employment),
            ("P_116", "w tym z umów zlecenia", amounts.relief_exempt_mandate),
        ):
            if value:
                add(
                    code,
                    label,
                    zl_gr(value, f"PIT-11, poz. {code[2:]}"),
                    exempt_group,
                    "zl_gr",
                )
        for relief, (code, label) in OTHER_RELIEFS.items():
            if relief in amounts.reliefs:
                add(code, f"Podstawa prawna: {label}", "1", exempt_group, "choice")
    other_group = "Pozostałe"
    add("P_121", "Dołączono informację PIT-R: nie", "2", other_group, "choice")
    if amounts.health:
        add(
            "P_122",
            "Składki na ubezpieczenie zdrowotne pobrane przez płatnika",
            zl_gr(amounts.health, "PIT-11, poz. 122"),
            other_group,
            "zl_gr",
        )
    return fields


def pit11_document(
    year: int,
    payer: TaxPayer,
    person: Pit11Person,
    amounts: Pit11Amounts,
    purpose: str = "1",
) -> FormDocument:
    """PIT-11 po walidacji — wspólne źródło XML i wydruku."""

    nip, name = _payer(payer, PIT11)
    clean = _person(person)
    return FormDocument(
        spec=PIT11,
        year=_year(PIT11, year),
        purpose=_purpose(PIT11, purpose),
        office_code=clean.tax_office_code,
        payer_nip=nip,
        payer_name=name,
        fields=tuple(_pit11_fields(amounts)),
        person=clean,
    )


# ── PIT-4R i PIT-8AR: miesiące ───────────────────────────────────────────────


def _months(spec: FormSpec, months: Mapping[int, object]) -> None:
    bad = [m for m in months if not (isinstance(m, int) and 1 <= m <= 12)]
    if bad:
        raise PitFormError(f"{spec.form}: miesiące to liczby 1–12.")


def _correction(fields: list[FormField], purpose: str) -> None:
    if purpose == "2":
        fields.append(
            FormField(
                "P_7",
                "Rodzaj korekty: art. 81 Ordynacji podatkowej",
                "1",
                "Korekta",
                "choice",
            )
        )


def _monthly(
    group: str,
    label: str,
    kind: str,
    position: Callable[[int], int],
    values: Mapping[int, str],
) -> list[FormField]:
    return [
        FormField(f"P_{position(m)}", label, values[m], group, kind, month=m)
        for m in range(1, 13)
    ]


PIT4R_ROWS = {
    1: "Zaliczki od dochodów ze stosunku pracy (art. 32)",
    3: "Zaliczki od umów zlecenia i o dzieło (art. 41)",
    5: "Suma pobranych zaliczek z wierszy 1–4",
    10: "Pobrany podatek do przekazania do urzędu skarbowego",
    12: "Podatek podlegający przekazaniu do urzędu skarbowego",
}


def _pit4r_fields(months: Mapping[int, Pit4rMonth], purpose: str) -> list[FormField]:
    _months(PIT4R, months)
    data = {m: months.get(m, Pit4rMonth()) for m in range(1, 13)}
    for m, item in data.items():
        if item.employment_taxpayers < 0:
            raise PitFormError(f"PIT-4R, miesiąc {m}: liczba podatników nieujemna.")

    def money(attr: str) -> dict[int, str]:
        return {
            m: zl(getattr(item, attr), f"PIT-4R, miesiąc {m}")
            for m, item in data.items()
        }

    employment = money("employment_advances")
    mandate = money("mandate_advances")
    totals = {m: str(int(employment[m]) + int(mandate[m])) for m in range(1, 13)}
    counts = {m: str(item.employment_taxpayers) for m, item in data.items()}
    fields: list[FormField] = []
    _correction(fields, purpose)
    row = {n: f"{n}. {title}" for n, title in PIT4R_ROWS.items()}
    if any(
        item.employment_advances or item.employment_taxpayers for item in data.values()
    ):
        # Kolejność w schemacie: liczba I–VI, zaliczki I–VI, liczba VII–XII, zaliczki VII–XII.
        fields += _monthly(
            row[1],
            "W. 1 — liczba podatników",
            "number",
            lambda m: 9 + m if m <= 6 else 15 + m,
            counts,
        )
        fields += _monthly(
            row[1],
            "W. 1 — zaliczki ze stosunku pracy",
            "zl",
            lambda m: 15 + m if m <= 6 else 21 + m,
            employment,
        )
    if any(item.mandate_advances for item in data.values()):
        fields += _monthly(
            row[3], "W. 3 — zaliczki ze zleceń i dzieł", "zl", lambda m: 45 + m, mandate
        )
    fields += _monthly(row[5], "W. 5 — suma zaliczek", "zl", lambda m: 69 + m, totals)
    fields += _monthly(
        row[10], "W. 10 — pobrany podatek", "zl", lambda m: 121 + m, totals
    )
    fields += _monthly(row[12], "W. 12 — do wpłaty", "zl", lambda m: 145 + m, totals)
    fields.append(
        FormField(
            "P_158",
            "Pomniejszenie zaliczek (art. 26eb ustawy): nie",
            "2",
            "D. Pomniejszenie zaliczek",
            "choice",
        )
    )
    return fields


def pit4r_document(
    year: int, payer: TaxPayer, months: Mapping[int, Pit4rMonth], purpose: str = "1"
) -> FormDocument:
    """PIT-4R po walidacji — wspólne źródło XML i wydruku."""

    nip, name = _payer(payer, PIT4R)
    clean_purpose = _purpose(PIT4R, purpose)
    return FormDocument(
        spec=PIT4R,
        year=_year(PIT4R, year),
        purpose=clean_purpose,
        office_code=_office(payer.tax_office_code, "PIT-4R, urząd skarbowy płatnika"),
        payer_nip=nip,
        payer_name=name,
        fields=tuple(_pit4r_fields(months, clean_purpose)),
    )


PIT8AR_ROWS = {
    6: "Umowy zlecenia i o dzieło do 200 zł z osobą niebędącą pracownikiem "
    "(art. 30 ust. 1 pkt 5a)",
    36: "Suma pobranego zryczałtowanego podatku z wierszy 1–35",
    38: "Zryczałtowany podatek do przekazania do urzędu skarbowego",
}


def _pit8ar_fields(months: Mapping[int, Decimal], purpose: str) -> list[FormField]:
    _months(PIT8AR, months)
    data = {m: months.get(m, ZERO) for m in range(1, 13)}
    whole = {m: zl(value, f"PIT-8AR, miesiąc {m}") for m, value in data.items()}
    # Wiersze 36 i 38 mają w schemacie typ kwoty z groszami.
    with_cents = {m: f"{whole[m]}.00" for m in range(1, 13)}
    fields: list[FormField] = []
    _correction(fields, purpose)
    row = {n: f"{n}. {title}" for n, title in PIT8AR_ROWS.items()}
    if any(data.values()):
        fields += _monthly(
            row[6], "W. 6 — umowy do 200 zł", "zl", lambda m: 69 + m, whole
        )
    fields += _monthly(
        row[36], "W. 36 — suma podatku", "zl_gr", lambda m: 429 + m, with_cents
    )
    fields += _monthly(
        row[38], "W. 38 — do przekazania", "zl_gr", lambda m: 453 + m, with_cents
    )
    fields.append(
        FormField(
            "P_466",
            "Pomniejszenie podatku (art. 26eb ustawy): nie",
            "2",
            "D. Pomniejszenie podatku",
            "choice",
        )
    )
    return fields


def pit8ar_document(
    year: int, payer: TaxPayer, months: Mapping[int, Decimal], purpose: str = "1"
) -> FormDocument:
    """PIT-8AR po walidacji — wspólne źródło XML i wydruku."""

    nip, name = _payer(payer, PIT8AR)
    clean_purpose = _purpose(PIT8AR, purpose)
    return FormDocument(
        spec=PIT8AR,
        year=_year(PIT8AR, year),
        purpose=clean_purpose,
        office_code=_office(payer.tax_office_code, "PIT-8AR, urząd skarbowy płatnika"),
        payer_nip=nip,
        payer_name=name,
        fields=tuple(_pit8ar_fields(months, clean_purpose)),
    )


# ── XML ──────────────────────────────────────────────────────────────────────


def render(document: FormDocument) -> bytes:
    """Formularz → XML e-Deklaracji (UTF-8)."""

    spec = document.spec
    ns = spec.namespace

    def sub(
        parent: etree._Element, tag: str, text: Optional[str] = None, **attrs: str
    ) -> etree._Element:
        node = etree.SubElement(parent, f"{{{ns}}}{tag}", attrs)
        if text is not None:
            node.text = text
        return node

    root = etree.Element(
        f"{{{ns}}}Deklaracja", nsmap={None: ns, "etd": spec.types_namespace}
    )
    header = sub(root, "Naglowek")
    sub(
        header,
        "KodFormularza",
        spec.form,
        kodSystemowy=spec.system_code,
        kodPodatku=spec.tax_code,
        rodzajZobowiazania=spec.obligation,
        wersjaSchemy=spec.schema_version,
    )
    sub(header, "WariantFormularza", str(spec.variant))
    sub(header, "CelZlozenia", document.purpose, poz=spec.purpose_position)
    sub(header, "Rok", str(document.year))
    sub(header, "KodUrzedu", document.office_code)
    payer = sub(sub(root, "Podmiot1", rola=spec.payer_role), "OsobaNiefizyczna")
    sub(payer, "NIP", document.payer_nip)
    sub(payer, "PelnaNazwa", document.payer_name)
    person = document.person
    if person is not None:
        subject = sub(root, "Podmiot2", rola="Podatnik")
        identity = sub(subject, "OsobaFizyczna")
        if person.pesel is not None:
            sub(identity, "PESEL", person.pesel)
        else:
            sub(identity, "NIP", person.nip)
        sub(identity, "ImiePierwsze", person.first_name)
        sub(identity, "Nazwisko", person.last_name)
        sub(identity, "DataUrodzenia", person.birth_date.isoformat())
        address = person.address
        if address is not None:
            node = sub(subject, "AdresZamieszkania", rodzajAdresu="RAD")
            sub(node, "KodKraju", address.country_code, poz="P_19A")
            for tag, value in (
                ("Wojewodztwo", address.voivodeship),
                ("Powiat", address.county),
                ("Gmina", address.municipality),
            ):
                if value:
                    sub(node, tag, value)
            for tag, value, position in (
                ("Ulica", address.street, "P_23"),
                ("NrDomu", address.house_number, "P_24"),
                ("NrLokalu", address.flat_number, "P_25"),
                ("Miejscowosc", address.city, "P_26"),
                ("KodPocztowy", address.postal_code, "P_27"),
            ):
                if value:
                    sub(node, tag, value, poz=position)
    details = sub(root, "PozycjeSzczegolowe")
    for item in sorted(document.fields, key=lambda f: int(f.code[2:])):
        sub(details, item.code, item.value)
    sub(root, spec.statement_tag, "1")
    return etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", pretty_print=True
    )


def render_pit11(
    year: int,
    payer: TaxPayer,
    person: Pit11Person,
    amounts: Pit11Amounts,
    purpose: str = "1",
) -> bytes:
    return render(pit11_document(year, payer, person, amounts, purpose))


def render_pit4r(
    year: int, payer: TaxPayer, months: Mapping[int, Pit4rMonth], purpose: str = "1"
) -> bytes:
    return render(pit4r_document(year, payer, months, purpose))


def render_pit8ar(
    year: int, payer: TaxPayer, months: Mapping[int, Decimal], purpose: str = "1"
) -> bytes:
    return render(pit8ar_document(year, payer, months, purpose))


__all__ = [
    "EMPTY_ROW",
    "KINDS",
    "OTHER_RELIEFS",
    "PIT11",
    "PIT4R",
    "PIT4R_ROWS",
    "PIT8AR",
    "PIT8AR_ROWS",
    "PURPOSES",
    "RELIEFS",
    "SCHEMA_SOURCE",
    "SCHEMA_VERIFIED",
    "FormDocument",
    "FormField",
    "FormSpec",
    "Pit11Amounts",
    "Pit11Entry",
    "Pit11Person",
    "Pit11Row",
    "Pit4rMonth",
    "PersonAddress",
    "PitFormError",
    "TaxPayer",
    "pit11_amounts",
    "pit11_document",
    "pit4r_document",
    "pit8ar_document",
    "relief_from_notes",
    "render",
    "render_pit11",
    "render_pit4r",
    "render_pit8ar",
    "zl",
    "zl_gr",
]
