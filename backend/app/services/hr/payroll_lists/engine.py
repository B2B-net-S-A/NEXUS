"""Silnik brutto → netto (K7a) — czyste funkcje, bez bazy i bez zegara.

Jedno wywołanie ``calculate`` liczy jedną pozycję listy płac: umowę o pracę,
zlecenie albo dzieło jednej osoby w jednym miesiącu. Stan narastający roku
(``YearToDate``: podstawa emerytalna i rentowych, podstawa opodatkowania
skalą, przychód zwolniony z ulg) przychodzi z wejścia, a wynik niesie stan po
tej pozycji — lista liczy osoby po kolei i przekazuje go dalej.

Reguły (do potwierdzenia przez Płace na porównaniu z Enovą):

* **Miesiąc składek i podatku** = miesiąc dnia wypłaty (przychód powstaje przy
  wypłacie). Wiek do ulg liczymy na dzień wypłaty: ulga dla młodych obejmuje
  przychód wypłacony do dnia 26. urodzin włącznie.
* **Składki ZUS** — każda osobno, zaokrąglona do grosza (HALF_UP). Emerytalna
  i rentowe od podstawy z rocznym limitem 30-krotności (narastająco u płatnika),
  chorobowa, wypadkowa, FP i FGŚP bez tego limitu. FP tylko, gdy podstawa
  w przeliczeniu na miesiąc (``Title.labour_fund_basis``, domyślnie podstawa
  pozycji) jest nie niższa od minimalnego wynagrodzenia; FP i FGŚP nie płaci
  się od miesiąca po osiągnięciu wieku 55/60 lat ani do daty zwolnienia osoby.
* **Zlecenie:** emerytalna i rentowe obowiązkowe (chyba że zbieg tytułów —
  ``pension_insurance=False``: wtedy tylko zdrowotna), chorobowa dobrowolna
  z podstawą do 250% przeciętnego wynagrodzenia, wypadkowa przy emerytalnej.
  Uczeń/student do 26 lat — bez składek i zdrowotnej do ``student_exempt_until``
  (najpóźniej dzień przed 26. urodzinami); miesiąc, w którym zwolnienie się
  kończy, dzielimy dniami kalendarzowymi okresu pracy.
* **Zdrowotna** 9% od przychodu minus składki społeczne osoby; nie odlicza się
  jej od podatku.
* **PIT:** podstawa = przychód opodatkowany − składki społeczne przypadające na
  niego − koszty uzyskania, zaokrąglona do pełnych złotych; zaliczka też do
  pełnych złotych (art. 63 Ordynacji podatkowej). UoP: skala 12%/32%
  z progiem liczonym narastająco od podstaw tego roku, koszty zryczałtowane
  (zwykłe albo podwyższone), kwota zmniejszająca wg PIT-2 (1/12, 1/24, 1/36).
  Zlecenie i dzieło: 12% (bez progu — rozlicza zeznanie roczne), koszty 20%
  przychodu po składkach, PIT-2 jak przy UoP. Należność do 200 zł z umowy
  zlecenia albo o dzieło u płatnika, który nie jest pracodawcą osoby —
  podatek ryczałtowy 12% od przychodu po składkach, bez kosztów i PIT-2.
* **Ulgi** (dla młodych, 4+, na powrót, dla seniora) — wspólny roczny limit
  przychodu zwolnionego; UoP i zlecenie, nie dzieło. W miesiącu przekroczenia
  limitu składki społeczne odliczamy proporcjonalnie do części opodatkowanej,
  koszty UoP w pełnej kwocie (do wysokości dochodu).
* **PPK:** podstawa = przychód oskładkowany bez limitu 30-krotności. Wpłata
  osoby obniża wypłatę; wpłata pracodawcy jest przychodem osoby w miesiącu
  przekazania do instytucji — lista dolicza ją przez ``ppk_employer_taxable``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from app.services.hr.payroll_lists.params import Params

ZERO = Decimal("0")
CENT = Decimal("0.01")
ONE = Decimal("1")
HUNDRED = Decimal("100")

KINDS: tuple[str, ...] = ("uop", "zlecenie", "dzielo")
RELIEFS: tuple[str, ...] = ("family4", "return", "senior")
PIT2_FRACTIONS: tuple[int, ...] = (0, 12, 24, 36)

#: Oznaczenia wyniku → zdanie na ekranie i w pasku (bez kwot i danych osoby).
NOTE_LABELS: dict[str, str] = {
    "pension_limit": "Roczny limit podstawy emerytalnej i rentowych — składki od części albo wcale.",
    "pit_threshold": "Część podstawy ponad próg skali — zaliczka 32%.",
    "relief_youth": "Ulga dla młodych.",
    "relief_family4": "Ulga dla rodzin 4+.",
    "relief_return": "Ulga na powrót.",
    "relief_senior": "Ulga dla seniora.",
    "relief_limit": "Przekroczony roczny limit ulg — podatek od nadwyżki.",
    "youth_ended": "26 lat skończone przed dniem wypłaty — ta wypłata bez ulgi dla młodych.",
    "senior_age_not_reached": "Ulga dla seniora zgłoszona przed osiągnięciem wieku — nie zastosowana.",
    "student": "Uczeń lub student do 26 lat — bez składek ZUS i zdrowotnej.",
    "student_partial": "Zwolnienie studenckie kończy się w tym miesiącu — składki od części przychodu.",
    "pension_other_title": "Zbieg tytułów — tylko składka zdrowotna.",
    "labour_fund_below_minimum": "Podstawa poniżej minimalnego wynagrodzenia — bez Funduszu Pracy.",
    "labour_fund_age": "Wiek 55/60 lat — bez Funduszu Pracy i FGŚP.",
    "labour_fund_exempt": "Zwolnienie z Funduszu Pracy do daty z danych osoby.",
    "fgsp_exempt": "Zwolnienie z FGŚP do daty z danych osoby.",
    "sickness_cap": "Podstawa dobrowolnej chorobowej obcięta do limitu 250%.",
    "flat_tax": "Należność do limitu ryczałtu — podatek ryczałtowy, bez kosztów i PIT-2.",
    "tax_reduction": "Kwota zmniejszająca z PIT-2.",
    "kup_increased": "Podwyższone koszty uzyskania.",
    "ppk": "Wpłaty PPK.",
}


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def whole(value: Decimal) -> Decimal:
    """Pełne złote: końcówki poniżej 50 gr w dół, od 50 gr w górę (art. 63 OP)."""

    return value.quantize(ONE, rounding=ROUND_HALF_UP)


def pct(basis: Decimal, rate: Decimal) -> Decimal:
    if basis <= 0 or rate <= 0:
        return ZERO
    return money(basis * rate / HUNDRED)


def birthday(born: date, years: int) -> date:
    """Dzień ``years``-tych urodzin (29 lutego → 1 marca w roku nieprzestępnym)."""

    try:
        return born.replace(year=born.year + years)
    except ValueError:
        return date(born.year + years, 3, 1)


def age_reached(born: Optional[date], years: int, on: date) -> bool:
    return born is not None and birthday(born, years) <= on


@dataclass(frozen=True)
class Ppk:
    """Uczestnictwo w PPK: wpłaty w procentach podstawy."""

    employee_rate: Decimal  # podstawowa osoby (obniżona 0,5–2 na deklarację)
    employee_extra: Decimal = ZERO  # dodatkowa osoby, do 2
    employer_extra: Decimal = ZERO  # dodatkowa pracodawcy, do 2,5


@dataclass(frozen=True)
class PersonTax:
    """Dane osoby potrzebne silnikowi — bez PESEL-u i danych adresowych."""

    birth_date: Optional[date] = None
    sex: Optional[str] = None  # "F" | "M"
    pit2_fraction: int = 0  # 0 = bez PIT-2; 12, 24, 36 = mianownik kwoty zmniejszającej
    kup_increased: bool = False
    reliefs: frozenset[str] = frozenset()  # family4, return, senior
    youth_relief_waived: bool = False
    student_exempt_until: Optional[date] = None
    ppk: Optional[Ppk] = None
    labour_fund_exempt_until: Optional[date] = None
    fgsp_exempt_until: Optional[date] = None


@dataclass(frozen=True)
class Title:
    """Jedna pozycja listy: tytuł wypłaty, kwota brutto i okres pracy."""

    kind: str
    gross: Decimal
    work_start: date
    work_end: date
    pay_date: date
    #: Zlecenie: obowiązkowe emerytalne i rentowe (False = zbieg, tylko zdrowotna).
    pension_insurance: bool = True
    #: Zlecenie: dobrowolne chorobowe.
    sickness_voluntary: bool = False
    #: Zlecenie: wypadkowe (przy emerytalnej).
    accident_insurance: bool = True
    #: False, gdy osoba jest pracownikiem płatnika (wtedy bez ryczałtu do 200 zł).
    flat_tax_allowed: bool = True
    #: Wpłata pracodawcy PPK doliczana do przychodu w tym miesiącu.
    ppk_employer_taxable: Decimal = ZERO
    #: Podstawa osoby u płatnika w miesiącu w przeliczeniu na pełny miesiąc
    #: (warunek Funduszu Pracy); ``None`` = podstawa tej pozycji.
    labour_fund_basis: Optional[Decimal] = None


@dataclass(frozen=True)
class YearToDate:
    """Stan roku podatkowego u płatnika przed pozycją."""

    pension_basis: Decimal = ZERO
    tax_base: Decimal = ZERO
    relief_revenue: Decimal = ZERO

    def to_json(self) -> dict[str, str]:
        return {
            "pension_basis": str(self.pension_basis),
            "tax_base": str(self.tax_base),
            "relief_revenue": str(self.relief_revenue),
        }


@dataclass(frozen=True)
class Result:
    kind: str
    gross: Decimal
    insured_gross: Decimal
    pension_basis: Decimal
    sickness_basis: Decimal
    accident_basis: Decimal
    fund_basis: Decimal
    health_basis: Decimal
    pension_employee: Decimal
    disability_employee: Decimal
    sickness_employee: Decimal
    social_employee: Decimal
    health: Decimal
    revenue: Decimal
    exempt_revenue: Decimal
    taxable_revenue: Decimal
    social_deductible: Decimal
    kup: Decimal
    tax_base: Decimal
    tax_reduction: Decimal
    tax_kind: str  # scale | flat | exempt | none
    pit: Decimal
    ppk_basis: Decimal
    ppk_employee: Decimal
    ppk_employer: Decimal
    ppk_employer_taxable: Decimal
    net: Decimal
    pension_employer: Decimal
    disability_employer: Decimal
    accident_employer: Decimal
    labour_fund: Decimal
    fgsp: Decimal
    employer_social: Decimal
    employer_cost: Decimal
    zus_due: Decimal
    ytd_after: YearToDate
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_json(self) -> dict[str, object]:
        out: dict[str, object] = {}
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if isinstance(value, Decimal):
                out[name] = str(value)
            elif isinstance(value, YearToDate):
                out[name] = value.to_json()
            elif isinstance(value, tuple):
                out[name] = list(value)
            else:
                out[name] = value
        return out


def _insured_part(
    gross: Decimal, start: date, end: date, exempt_until: Optional[date]
) -> Decimal:
    """Część przychodu po końcu zwolnienia studenckiego (dniami okresu pracy)."""

    if exempt_until is None or exempt_until < start:
        return gross
    if exempt_until >= end:
        return ZERO
    days = (end - start).days + 1
    insured_days = (end - exempt_until).days
    return money(gross * insured_days / days)


def student_exempt_until(person: PersonTax, params: Params) -> Optional[date]:
    """Koniec zwolnienia: data z kartoteki, najpóźniej dzień przed 26. urodzinami."""

    if person.student_exempt_until is None:
        return None
    if person.birth_date is None:
        return person.student_exempt_until
    last = birthday(person.birth_date, params.youth_age) - timedelta(days=1)
    return min(person.student_exempt_until, last)


def _age_exempt_from_funds(person: PersonTax, params: Params, pay_date: date) -> bool:
    """FP i FGŚP: od miesiąca po miesiącu, w którym osoba osiągnęła wiek 55/60."""

    if person.birth_date is None or person.sex not in ("F", "M"):
        return False
    years = (
        params.labour_fund_exempt_age_female
        if person.sex == "F"
        else params.labour_fund_exempt_age_male
    )
    reached = birthday(person.birth_date, years)
    return (reached.year, reached.month) < (pay_date.year, pay_date.month)


def _youth_applies(person: PersonTax, params: Params, pay_date: date) -> bool:
    if person.youth_relief_waived or person.birth_date is None:
        return False
    return pay_date <= birthday(person.birth_date, params.youth_age)


def _senior_age(person: PersonTax, params: Params, pay_date: date) -> bool:
    if person.sex not in ("F", "M"):
        return False
    years = params.senior_age_female if person.sex == "F" else params.senior_age_male
    return age_reached(person.birth_date, years, pay_date)


def tax_reduction(person: PersonTax, params: Params) -> Decimal:
    if person.pit2_fraction not in (12, 24, 36):
        return ZERO
    return money(params.tax_reduction_annual / Decimal(person.pit2_fraction))


def calculate(
    title: Title, person: PersonTax, ytd: YearToDate, params: Params
) -> Result:
    """Brutto → składki, zdrowotna, zaliczka PIT, PPK, do wypłaty i koszt pracodawcy."""

    if title.kind not in KINDS:
        raise ValueError(f"nieznany rodzaj pozycji: {title.kind!r}")
    if title.work_end < title.work_start:
        raise ValueError("koniec okresu pracy przed początkiem")
    gross = money(title.gross)
    if gross < 0:
        raise ValueError("brutto ujemne")
    notes: list[str] = []
    kind = title.kind

    # ── Ubezpieczenia: od jakiej części przychodu i które ─────────────────────
    if kind == "uop":
        insured = gross
        pension_on = sickness_on = accident_on = health_on = insured > 0
        sickness_cap: Optional[Decimal] = None
    elif kind == "zlecenie":
        exempt_until = student_exempt_until(person, params)
        insured = _insured_part(gross, title.work_start, title.work_end, exempt_until)
        if exempt_until is not None and gross > 0:
            if insured == 0:
                notes.append("student")
            elif insured < gross:
                notes.append("student_partial")
        pension_on = title.pension_insurance and insured > 0
        if not title.pension_insurance and insured > 0:
            notes.append("pension_other_title")
        sickness_on = pension_on and title.sickness_voluntary
        accident_on = pension_on and title.accident_insurance
        health_on = insured > 0
        sickness_cap = params.voluntary_sickness_monthly_cap
    else:
        insured = ZERO
        pension_on = sickness_on = accident_on = health_on = False
        sickness_cap = None

    if pension_on:
        room = max(ZERO, params.annual_pension_limit - ytd.pension_basis)
        pension_basis = min(insured, room)
        if pension_basis < insured:
            notes.append("pension_limit")
    else:
        pension_basis = ZERO
    if sickness_on:
        sickness_basis = insured
        if sickness_cap is not None and sickness_basis > sickness_cap:
            sickness_basis = sickness_cap
            notes.append("sickness_cap")
    else:
        sickness_basis = ZERO
    accident_basis = insured if accident_on else ZERO
    fund_basis = insured if pension_on else ZERO

    pension_employee = pct(pension_basis, params.pension_employee_rate)
    disability_employee = pct(pension_basis, params.disability_employee_rate)
    sickness_employee = pct(sickness_basis, params.sickness_employee_rate)
    social_employee = pension_employee + disability_employee + sickness_employee
    health_basis = max(ZERO, insured - social_employee) if health_on else ZERO
    health = pct(health_basis, params.health_rate)

    pension_employer = pct(pension_basis, params.pension_employer_rate)
    disability_employer = pct(pension_basis, params.disability_employer_rate)
    accident_employer = pct(accident_basis, params.accident_employer_rate)
    labour_fund = ZERO
    fgsp = ZERO
    if fund_basis > 0:
        age_exempt = _age_exempt_from_funds(person, params, title.pay_date)
        if age_exempt:
            notes.append("labour_fund_age")
        fund_check = (
            title.labour_fund_basis
            if title.labour_fund_basis is not None
            else fund_basis
        )
        lf_manual = (
            person.labour_fund_exempt_until is not None
            and title.pay_date <= person.labour_fund_exempt_until
        )
        fgsp_manual = (
            person.fgsp_exempt_until is not None
            and title.pay_date <= person.fgsp_exempt_until
        )
        if lf_manual:
            notes.append("labour_fund_exempt")
        if fgsp_manual:
            notes.append("fgsp_exempt")
        if not age_exempt and not lf_manual:
            if fund_check >= params.minimum_wage:
                labour_fund = pct(fund_basis, params.labour_fund_rate)
            else:
                notes.append("labour_fund_below_minimum")
        if not age_exempt and not fgsp_manual:
            fgsp = pct(fund_basis, params.fgsp_rate)

    # ── PPK ──────────────────────────────────────────────────────────────────
    ppk_on = person.ppk is not None and (
        (kind == "uop" and insured > 0) or (kind == "zlecenie" and pension_on)
    )
    ppk_basis = insured if ppk_on else ZERO
    if ppk_on and person.ppk is not None:
        ppk_employee = pct(
            ppk_basis, person.ppk.employee_rate + person.ppk.employee_extra
        )
        ppk_employer = pct(
            ppk_basis, params.ppk_employer_rate + person.ppk.employer_extra
        )
        notes.append("ppk")
    else:
        ppk_employee = ppk_employer = ZERO

    # ── PIT ──────────────────────────────────────────────────────────────────
    ppk_taxable = money(max(ZERO, title.ppk_employer_taxable))
    revenue = gross + ppk_taxable
    relief_codes: list[str] = []
    if kind in ("uop", "zlecenie") and revenue > 0:
        if _youth_applies(person, params, title.pay_date):
            relief_codes.append("relief_youth")
        elif (
            person.birth_date is not None
            and not person.youth_relief_waived
            and title.work_start
            <= birthday(person.birth_date, params.youth_age)
            < title.pay_date
        ):
            # 26. urodziny w miesiącu pracy albo przed wypłatą — ta wypłata już z PIT.
            notes.append("youth_ended")
        for relief in RELIEFS:
            if relief not in person.reliefs:
                continue
            if relief == "senior" and not _senior_age(person, params, title.pay_date):
                notes.append("senior_age_not_reached")
                continue
            relief_codes.append(f"relief_{relief}")
    exempt = ZERO
    if relief_codes:
        room = max(ZERO, params.relief_annual_limit - ytd.relief_revenue)
        exempt = min(revenue, room)
        if exempt > 0:
            notes.extend(relief_codes)
        if exempt < revenue:
            notes.append("relief_limit")
    taxable = revenue - exempt
    if taxable <= 0 or revenue <= 0:
        social_deductible = ZERO
    elif exempt == 0:
        social_deductible = social_employee
    else:
        social_deductible = money(social_employee * taxable / revenue)

    kup = ZERO
    base = ZERO
    reduction = ZERO
    flat = (
        kind in ("zlecenie", "dzielo")
        and title.flat_tax_allowed
        and 0 < gross <= params.flat_tax_limit
    )
    if taxable <= 0:
        tax_kind = "exempt" if exempt > 0 else "none"
        pit = ZERO
    elif flat:
        tax_kind = "flat"
        notes.append("flat_tax")
        base = whole(max(ZERO, taxable - social_deductible))
        pit = whole(base * params.flat_tax_rate / HUNDRED)
    else:
        tax_kind = "scale"
        income = max(ZERO, taxable - social_deductible)
        if kind == "uop":
            kup_amount = (
                params.kup_increased if person.kup_increased else params.kup_standard
            )
            if person.kup_increased:
                notes.append("kup_increased")
            kup = min(kup_amount, income)
        else:
            kup = pct(income, params.kup_mandate_rate)
        base = whole(max(ZERO, income - kup))
        reduction = tax_reduction(person, params)
        if reduction > 0:
            notes.append("tax_reduction")
        if kind == "uop":
            low_room = max(ZERO, params.pit_threshold - ytd.tax_base)
            low = min(base, low_room)
            high = base - low
            if high > 0:
                notes.append("pit_threshold")
            raw = (
                low * params.pit_rate_low / HUNDRED
                + high * params.pit_rate_high / HUNDRED
                - reduction
            )
        else:
            raw = base * params.pit_rate_low / HUNDRED - reduction
        pit = whole(max(ZERO, raw))

    net = gross - social_employee - health - pit - ppk_employee
    employer_social = (
        pension_employer + disability_employer + accident_employer + labour_fund + fgsp
    )
    employer_cost = gross + employer_social + ppk_employer
    zus_due = social_employee + health + employer_social
    ytd_after = YearToDate(
        pension_basis=ytd.pension_basis + pension_basis,
        tax_base=ytd.tax_base
        + (base if kind == "uop" and tax_kind == "scale" else ZERO),
        relief_revenue=ytd.relief_revenue + exempt,
    )
    return Result(
        kind=kind,
        gross=gross,
        insured_gross=insured,
        pension_basis=pension_basis,
        sickness_basis=sickness_basis,
        accident_basis=accident_basis,
        fund_basis=fund_basis,
        health_basis=health_basis,
        pension_employee=pension_employee,
        disability_employee=disability_employee,
        sickness_employee=sickness_employee,
        social_employee=social_employee,
        health=health,
        revenue=revenue,
        exempt_revenue=exempt,
        taxable_revenue=taxable,
        social_deductible=social_deductible,
        kup=kup,
        tax_base=base,
        tax_reduction=reduction if tax_kind == "scale" else ZERO,
        tax_kind=tax_kind,
        pit=pit,
        ppk_basis=ppk_basis,
        ppk_employee=ppk_employee,
        ppk_employer=ppk_employer,
        ppk_employer_taxable=ppk_taxable,
        net=net,
        pension_employer=pension_employer,
        disability_employer=disability_employer,
        accident_employer=accident_employer,
        labour_fund=labour_fund,
        fgsp=fgsp,
        employer_social=employer_social,
        employer_cost=employer_cost,
        zus_due=zus_due,
        ytd_after=ytd_after,
        notes=tuple(dict.fromkeys(notes)),
    )


__all__ = [
    "KINDS",
    "NOTE_LABELS",
    "PIT2_FRACTIONS",
    "RELIEFS",
    "PersonTax",
    "Ppk",
    "Result",
    "Title",
    "YearToDate",
    "age_reached",
    "birthday",
    "calculate",
    "money",
    "pct",
    "student_exempt_until",
    "tax_reduction",
    "whole",
]
