"""Parametry płac (K7a) — jedna wersja to pełny zestaw obowiązujący od daty.

Wersje leżą w ``payroll_parameter_versions`` (``values`` = słownik klucz →
tekst liczby). Lista płac bierze wersję z najpóźniejszą datą nie późniejszą
niż dzień wypłaty i zapamiętuje jej numer, więc późniejsza zmiana parametrów
nie przelicza zatwierdzonej listy.

Zasiew 2026 (``SEED_2026``) jest „do potwierdzenia przez Płace”: wartości
z ustaw i obwieszczeń na 2026 r., stopa wypadkowa to stawka dla płatników do
9 ubezpieczonych — firmowa stopa z zawiadomienia ZUS może być inna.

Klucze są po angielsku (warstwa techniczna), etykiety po polsku (ekran,
historia zmian). Procenty zapisujemy jak w przepisach: ``"9.76"`` = 9,76%.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.hr.payroll_errors import PayrollError


class ParamsError(PayrollError):
    """Zła wartość parametru — komunikat po polsku, bez wyjątku źródłowego."""


@dataclass(frozen=True)
class ParamSpec:
    label: str
    group: str
    unit: str  # "%", "zł", "lat", "×"
    low: Decimal
    high: Decimal
    integer: bool = False


def _spec(
    label: str, group: str, unit: str, low: str, high: str, *, integer: bool = False
) -> ParamSpec:
    return ParamSpec(label, group, unit, Decimal(low), Decimal(high), integer)


#: Kolejność = kolejność na ekranie parametrów.
SPECS: dict[str, ParamSpec] = {
    "pension_employee_rate": _spec("Emerytalna — pracownik", "ZUS", "%", "0", "30"),
    "pension_employer_rate": _spec("Emerytalna — pracodawca", "ZUS", "%", "0", "30"),
    "disability_employee_rate": _spec("Rentowe — pracownik", "ZUS", "%", "0", "20"),
    "disability_employer_rate": _spec("Rentowe — pracodawca", "ZUS", "%", "0", "20"),
    "sickness_employee_rate": _spec("Chorobowa — pracownik", "ZUS", "%", "0", "10"),
    "accident_employer_rate": _spec("Wypadkowa — stopa firmy", "ZUS", "%", "0.4", "10"),
    "labour_fund_rate": _spec(
        "Fundusz Pracy i Fundusz Solidarnościowy", "ZUS", "%", "0", "10"
    ),
    "fgsp_rate": _spec("FGŚP", "ZUS", "%", "0", "5"),
    "health_rate": _spec("Zdrowotna", "ZUS", "%", "0", "20"),
    "annual_pension_limit": _spec(
        "Roczny limit podstawy emerytalnej i rentowych (30-krotność)",
        "ZUS",
        "zł",
        "1000",
        "10000000",
    ),
    "voluntary_sickness_monthly_cap": _spec(
        "Limit podstawy dobrowolnej chorobowej (250% przeciętnego wynagrodzenia)",
        "ZUS",
        "zł",
        "1000",
        "1000000",
    ),
    "minimum_wage": _spec(
        "Minimalne wynagrodzenie", "Płaca minimalna", "zł", "100", "100000"
    ),
    "minimum_hourly_rate": _spec(
        "Minimalna stawka godzinowa", "Płaca minimalna", "zł", "1", "1000"
    ),
    "pit_rate_low": _spec("Skala PIT — pierwsza stawka", "PIT", "%", "0", "50"),
    "pit_rate_high": _spec("Skala PIT — druga stawka", "PIT", "%", "0", "60"),
    "pit_threshold": _spec("Próg skali PIT (rocznie)", "PIT", "zł", "1000", "10000000"),
    "tax_reduction_annual": _spec(
        "Kwota zmniejszająca podatek (rocznie)", "PIT", "zł", "0", "100000"
    ),
    "kup_standard": _spec(
        "Koszty uzyskania — zwykłe (miesięcznie)", "PIT", "zł", "0", "10000"
    ),
    "kup_increased": _spec(
        "Koszty uzyskania — podwyższone (miesięcznie)", "PIT", "zł", "0", "10000"
    ),
    "kup_mandate_rate": _spec(
        "Koszty uzyskania — zlecenie i dzieło", "PIT", "%", "0", "50"
    ),
    "relief_annual_limit": _spec(
        "Limit ulg: dla młodych, 4+, na powrót, dla seniora (rocznie)",
        "PIT",
        "zł",
        "0",
        "10000000",
    ),
    "flat_tax_limit": _spec(
        "Zlecenie i dzieło do kwoty — podatek ryczałtowy", "PIT", "zł", "0", "100000"
    ),
    "flat_tax_rate": _spec("Podatek ryczałtowy", "PIT", "%", "0", "50"),
    "ppk_employee_rate": _spec(
        "PPK — wpłata podstawowa pracownika", "PPK", "%", "0", "10"
    ),
    "ppk_employer_rate": _spec(
        "PPK — wpłata podstawowa pracodawcy", "PPK", "%", "0", "10"
    ),
    "youth_age": _spec(
        "Ulga dla młodych — do ukończenia", "Wiek", "lat", "18", "40", integer=True
    ),
    "labour_fund_exempt_age_female": _spec(
        "Bez FP i FGŚP od wieku — kobiety", "Wiek", "lat", "40", "80", integer=True
    ),
    "labour_fund_exempt_age_male": _spec(
        "Bez FP i FGŚP od wieku — mężczyźni", "Wiek", "lat", "40", "80", integer=True
    ),
    "senior_age_female": _spec(
        "Ulga dla seniora od wieku — kobiety", "Wiek", "lat", "40", "90", integer=True
    ),
    "senior_age_male": _spec(
        "Ulga dla seniora od wieku — mężczyźni", "Wiek", "lat", "40", "90", integer=True
    ),
}

#: Wartości na 2026 r. — do potwierdzenia przez Płace (zasiew migracji 0703).
SEED_2026: dict[str, str] = {
    "pension_employee_rate": "9.76",
    "pension_employer_rate": "9.76",
    "disability_employee_rate": "1.50",
    "disability_employer_rate": "6.50",
    "sickness_employee_rate": "2.45",
    "accident_employer_rate": "1.67",
    "labour_fund_rate": "2.45",
    "fgsp_rate": "0.10",
    "health_rate": "9.00",
    "annual_pension_limit": "282600.00",
    "voluntary_sickness_monthly_cap": "23550.00",
    "minimum_wage": "4806.00",
    "minimum_hourly_rate": "31.40",
    "pit_rate_low": "12",
    "pit_rate_high": "32",
    "pit_threshold": "120000.00",
    "tax_reduction_annual": "3600.00",
    "kup_standard": "250.00",
    "kup_increased": "300.00",
    "kup_mandate_rate": "20",
    "relief_annual_limit": "85528.00",
    "flat_tax_limit": "200.00",
    "flat_tax_rate": "12",
    "ppk_employee_rate": "2.0",
    "ppk_employer_rate": "1.5",
    "youth_age": "26",
    "labour_fund_exempt_age_female": "55",
    "labour_fund_exempt_age_male": "60",
    "senior_age_female": "60",
    "senior_age_male": "65",
}
SEED_EFFECTIVE_FROM = "2026-01-01"
SEED_NOTE = (
    "Zasiew 2026 z ustaw i obwieszczeń — do potwierdzenia przez Płace "
    "(stopa wypadkowa: stawka do 9 ubezpieczonych, sprawdź zawiadomienie ZUS)."
)


@dataclass(frozen=True)
class Params:
    pension_employee_rate: Decimal
    pension_employer_rate: Decimal
    disability_employee_rate: Decimal
    disability_employer_rate: Decimal
    sickness_employee_rate: Decimal
    accident_employer_rate: Decimal
    labour_fund_rate: Decimal
    fgsp_rate: Decimal
    health_rate: Decimal
    annual_pension_limit: Decimal
    voluntary_sickness_monthly_cap: Decimal
    minimum_wage: Decimal
    minimum_hourly_rate: Decimal
    pit_rate_low: Decimal
    pit_rate_high: Decimal
    pit_threshold: Decimal
    tax_reduction_annual: Decimal
    kup_standard: Decimal
    kup_increased: Decimal
    kup_mandate_rate: Decimal
    relief_annual_limit: Decimal
    flat_tax_limit: Decimal
    flat_tax_rate: Decimal
    ppk_employee_rate: Decimal
    ppk_employer_rate: Decimal
    youth_age: int
    labour_fund_exempt_age_female: int
    labour_fund_exempt_age_male: int
    senior_age_female: int
    senior_age_male: int


_FIELD_NAMES = tuple(item.name for item in fields(Params))
assert set(_FIELD_NAMES) == set(SPECS) == set(SEED_2026), "klucze parametrów"


def _number(key: str, raw: Any) -> Decimal:
    spec = SPECS[key]
    if isinstance(raw, bool) or raw is None:
        raise ParamsError(f"{spec.label}: podaj liczbę.")
    text = str(raw).strip().replace(" ", "").replace(",", ".")
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ParamsError(f"{spec.label}: podaj liczbę.") from None
    if not value.is_finite():
        raise ParamsError(f"{spec.label}: podaj liczbę.")
    if spec.integer and value != value.to_integral_value():
        raise ParamsError(f"{spec.label}: liczba całkowita.")
    if value.as_tuple().exponent < -4:  # type: ignore[operator]
        raise ParamsError(f"{spec.label}: najwyżej 4 miejsca po przecinku.")
    if not spec.low <= value <= spec.high:
        raise ParamsError(
            f"{spec.label}: od {spec.low} do {spec.high} {spec.unit}".rstrip() + "."
        )
    return value


def parse(values: Mapping[str, Any]) -> Params:
    """Słownik z bazy albo z formularza → ``Params``; brak klucza albo zła wartość = 422."""

    if not isinstance(values, Mapping):
        raise ParamsError("Parametry płac: zły format.")
    unknown = sorted(set(values) - set(SPECS))
    if unknown:
        raise ParamsError("Nieznany parametr płac.")
    missing = [SPECS[key].label for key in SPECS if key not in values]
    if missing:
        raise ParamsError(f"Brakuje parametru: {missing[0]}.")
    parsed: dict[str, Any] = {}
    for key in SPECS:
        number = _number(key, values[key])
        parsed[key] = int(number) if SPECS[key].integer else number
    if parsed["pit_rate_high"] < parsed["pit_rate_low"]:
        raise ParamsError("Druga stawka skali PIT nie może być niższa od pierwszej.")
    if parsed["kup_increased"] < parsed["kup_standard"]:
        raise ParamsError(
            "Podwyższone koszty uzyskania nie mogą być niższe od zwykłych."
        )
    return Params(**parsed)


def to_json(params: Params) -> dict[str, str]:
    return {key: str(getattr(params, key)) for key in SPECS}


def normalized(values: Mapping[str, Any]) -> dict[str, str]:
    """Zapis do bazy: walidacja i jednolity tekst liczb."""

    return to_json(parse(values))


def diff(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[dict[str, str]]:
    """Zmienione parametry: klucz, etykieta, przed, po (do historii zmian)."""

    out: list[dict[str, str]] = []
    for key, spec in SPECS.items():
        old = before.get(key)
        new = after.get(key)
        try:
            same = (
                old is not None
                and new is not None
                and Decimal(str(old)) == Decimal(str(new))
            )
        except InvalidOperation:
            same = False
        if not same:
            out.append(
                {
                    "key": key,
                    "label": spec.label,
                    "unit": spec.unit,
                    "before": "" if old is None else str(old),
                    "after": "" if new is None else str(new),
                }
            )
    return out


def catalog() -> list[dict[str, str]]:
    """Opis pól dla ekranu (kolejność, grupy, jednostki, zakresy)."""

    return [
        {
            "key": key,
            "label": spec.label,
            "group": spec.group,
            "unit": spec.unit,
            "min": str(spec.low),
            "max": str(spec.high),
            "integer": "1" if spec.integer else "0",
        }
        for key, spec in SPECS.items()
    ]


SEED_PARAMS = parse(SEED_2026)

__all__ = [
    "ParamSpec",
    "Params",
    "ParamsError",
    "SEED_2026",
    "SEED_EFFECTIVE_FROM",
    "SEED_NOTE",
    "SEED_PARAMS",
    "SPECS",
    "catalog",
    "diff",
    "normalized",
    "parse",
    "to_json",
]
