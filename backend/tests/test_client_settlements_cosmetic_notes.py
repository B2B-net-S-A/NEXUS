"""Kosmetyka raportu przy dobrym MD nie zatrzymuje automatu „Bez uwag” (decyzja
Artura z 25.11.2026). Bez bazy, dane fikcyjne w układzie przypadków z próby VI–X
2026, w których MD z raportu były równe fakturze Finansów:

* BNP: wiersze opisu prac ≠ SUMA, a SUMA = godziny dni (4 przypadki);
* BIK: wiersze z datami z szablonu zeszłego roku (1);
* BNP i PKO: szablon z innym miesiącem w nagłówku (2).

Każdy przypadek ma bliźniaka z podobną uwagą, który dalej blokuje, bo brakuje
dowodu, że to rozliczany miesiąc albo że MD się zgadzają.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from typing import Any, Optional

import pytest

from app.services.client_settlements import (
    engine,
    rcp_checks,
    rules_catalog,
    template_month,
    timesheet,
    timesheet_bik,
    timesheet_pko,
)
from app.services.client_settlements.rcp_bnp import DAYS, ParsedRcp, SummaryRow

JUNE, JULY, AUG, OCT, NOV = "2026-06", "2026-07", "2026-08", "2026-10", "2026-11"
PERSON = "Anna Testowa"


def _rules(**levels: str) -> dict[str, dict[str, Any]]:
    rules = rules_catalog.effective(None)
    rules["proof.month"]["level"] = "block"
    rules["proof.name_match"]["level"] = "warn"
    rules["fields.md_hours"]["level"] = "block"
    for key, level in levels.items():
        rules[key.replace("__", ".")]["level"] = level
    return rules


def _checks(result: rcp_checks.ProofResult) -> dict[str, dict[str, Any]]:
    return {c["title"]: c for g in result.groups for c in g["checks"]}


# ── Kalendarz szablonu ──────────────────────────────────────────────────────


def test_dni_robocze_miesiaca_bez_swiat():
    # Boże Ciało 2026 to 4 czerwca; 11 listopada to święto.
    assert 4 not in template_month.workdays(JUNE)
    assert len(template_month.workdays(JUNE)) == 21
    assert 11 not in template_month.workdays(NOV)
    assert len(template_month.workdays(OCT)) == 22


def test_uklad_dni_musi_pasowac_do_miesiaca_a_nie_do_szablonu():
    june = template_month.workdays(JUNE)
    assert template_month.days_fit(june, JUNE, "2026-01")
    # Dni pasujące do obu kalendarzy niczego nie dowodzą.
    assert not template_month.days_fit({1, 2}, OCT, "2026-09")
    # Godziny w sobotę rozliczanego miesiąca: to nie jest jego układ.
    assert not template_month.days_fit({3}, OCT)
    assert not template_month.days_fit(set(), OCT)
    assert not template_month.days_fit(june, JUNE, "????-01")


def test_pelny_miesiac_bez_kolumn_dni():
    # Sierpień 2026: 21 dni roboczych, lipiec: 23.
    assert template_month.full_month(D("168"), D("8"), AUG, JULY)
    assert not template_month.full_month(D("160"), D("8"), AUG, JULY)
    # Czerwiec 2026 też ma 21 dni roboczych: 168 h pasuje do obu.
    assert not template_month.full_month(D("168"), D("8"), AUG, JUNE)


# ── BNP: wiersze opisu prac ≠ SUMA ──────────────────────────────────────────


def _grid(days: set[int], hours: str = "8.0") -> tuple[D, ...]:
    return tuple(D(hours) if d in days else D("0") for d in range(1, DAYS + 1))


def _rcp(
    *,
    month: Optional[str] = OCT,
    days: Optional[set[int]] = None,
    rows: tuple[str, ...] = ("15.6", "15.6", "6.4", "6.4"),
    extra: tuple[str, ...] = (),
    summa: str = "22",
    declared: Optional[str] = "22",
    weekday: Optional[tuple[D, ...]] = None,
    grid: Optional[tuple[D, ...]] = None,
) -> ParsedRcp:
    if grid is None:
        grid = _grid(days if days is not None else set(template_month.workdays(OCT)))
    summary = tuple(
        SummaryRow("Prace DevOps", D(md), "ORD", "SX01929") for md in rows
    ) + tuple(
        SummaryRow("Godziny dodatkowe w sobotę", D(md), "ORD", "SX01929")
        for md in extra
    )
    return ParsedRcp(
        source="pdf",
        month=month,
        last_name="Testowa",
        first_name="Anna",
        role="Devops",
        order_number=None,
        check_ok=True,
        weekday_hours=grid if weekday is None else weekday,
        day_totals=grid,
        total_hours=sum(grid, D("0")) if grid else D("176"),
        declared_md=None if declared is None else D(declared),
        summary=summary,
        summary_total=D(summa),
        travel_total=None,
    )


def _bnp(parsed: ParsedRcp, month: str = OCT, **kw: Any) -> rcp_checks.ProofResult:
    return rcp_checks.evaluate(
        parsed,
        [],
        mime=rcp_checks.PDF,
        month=month,
        person_name=PERSON,
        has_mail=True,
        rules=kw.pop("rules", None) or _rules(),
        **kw,
    )


@pytest.mark.parametrize(
    "rows",
    [
        # Wiersze zdublowane w tekście PDF: 44 MD przy SUMA 22.
        ("15.6", "15.6", "6.4", "6.4"),
        # Jeden wiersz z liczbą sprzed poprawki: 15 MD przy SUMA 22.
        ("15",),
    ],
)
def test_bnp_wiersze_inne_niz_suma_przy_sumie_rownej_godzinom_dni_nie_blokuja(rows):
    result = _bnp(_rcp(rows=rows))
    note = _checks(result)["Wiersze opisu prac nie sumują się do SUMA"]
    assert note["state"] == "none"
    assert note["notice"] == rcp_checks.NOTE_ROWS_SUM
    assert note["detail"].startswith("Wiersze: ")
    assert "SUMA: 22 MD" in note["detail"]
    assert not result.warn and not result.blocking
    assert result.md_regular == D("22") and result.md_extra is None


def _workdays_without(month: str, *days: int) -> set[int]:
    return set(template_month.workdays(month)) - set(days)


@pytest.mark.parametrize(
    "parsed",
    [
        # SUMA 22 MD, a w dniach 168 h (21 MD): rozbieżność godzin, nie kosmetyka.
        _rcp(days=_workdays_without(OCT, 30)),
        # Wiersze „Godziny dodatkowe”: podziału na pracę dodatkową nie da się ufać.
        _rcp(rows=("15",), extra=("1",)),
        # Godziny w sobotę ponad „Godziny w tygodniu”.
        _rcp(
            days=set(template_month.workdays(OCT)) | {3},
            weekday=_grid(set(template_month.workdays(OCT))),
            summa="23",
            declared="23",
        ),
        # „Total MD's” inne niż SUMA.
        _rcp(declared="21"),
        # Puste dni wypadły z tekstu PDF: bez siatki 31 dni nie ma czego porównać.
        _rcp(grid=()),
    ],
    ids=["godziny-dni", "praca-dodatkowa", "sobota", "total-md", "bez-siatki"],
)
def test_bnp_wiersze_inne_niz_suma_bez_dowodu_dalej_daja_uwage(parsed):
    result = _bnp(parsed)
    check = _checks(result)["Wiersze opisu prac nie sumują się do SUMA"]
    assert check["state"] == "warn" and "notice" not in check
    assert result.warn


def test_bnp_godziny_w_swieto_to_nie_kosmetyka():
    # 11 listopada w siatce jak dzień roboczy: dni nie pasują do kalendarza miesiąca.
    days = set(template_month.workdays(NOV)) | {11}
    parsed = _rcp(month=NOV, days=days, summa=str(len(days)), declared=str(len(days)))
    result = _bnp(parsed, NOV)
    assert (
        _checks(result)["Wiersze opisu prac nie sumują się do SUMA"]["state"] == "warn"
    )


# ── BNP: szablon z innym miesiącem w polu „Rozliczenie” ─────────────────────


def _june_in_january_template(**kw: Any) -> ParsedRcp:
    # RCP za czerwiec na szablonie ze styczniem w polu „Rozliczenie”.
    base = dict(
        month="2026-01",
        days=set(template_month.workdays(JUNE)),
        rows=("21",),
        summa="21",
        declared="21",
    )
    base.update(kw)
    return _rcp(**base)


def test_bnp_szablon_z_innym_miesiacem_przy_miesiacu_z_nazwy_pliku_nie_blokuje():
    result = _bnp(_june_in_january_template(), JUNE, named_month=JUNE)
    checks = _checks(result)
    note = checks["Szablon z innym miesiącem w nagłówku"]
    assert note["state"] == "none"
    assert note["notice"] == rcp_checks.NOTE_TEMPLATE_MONTH
    assert note["detail"].startswith("W polu Rozliczenie: 2026-01.")
    assert "RCP za inny miesiąc" not in checks
    assert not result.blocking and not result.warn
    assert result.md_regular == D("21")


@pytest.mark.parametrize(
    ("parsed", "month", "named"),
    [
        # Nazwa pliku i temat bez miesiąca (okres zgadnięty z daty maila).
        (_june_in_january_template(), JUNE, None),
        # Nazwa pliku wskazuje miesiąc z szablonu.
        (_june_in_january_template(), JUNE, "2026-01"),
        # Dni 1–2 to dni robocze i października, i września: brak dowodu.
        (
            _rcp(month="2026-09", days={1, 2}, rows=("2",), summa="2", declared="2"),
            OCT,
            OCT,
        ),
        # Praca dodatkowa: jej dni i zgody liczą się od miesiąca z szablonu.
        (_june_in_january_template(rows=("20",), extra=("1",)), JUNE, JUNE),
    ],
    ids=["bez-miesiaca-z-nazwy", "nazwa-z-szablonu", "oba-kalendarze", "nadgodziny"],
)
def test_bnp_szablon_z_innym_miesiacem_bez_dowodu_dalej_blokuje(parsed, month, named):
    result = _bnp(parsed, month, named_month=named)
    assert _checks(result)["RCP za inny miesiąc"]["state"] == "fail"
    assert result.blocking


def test_bnp_wylaczona_kontrola_miesiaca_niczego_nie_dopisuje():
    result = _bnp(
        _june_in_january_template(),
        JUNE,
        named_month=JUNE,
        rules=_rules(proof__month="off"),
    )
    checks = _checks(result)
    assert "RCP za inny miesiąc" not in checks
    assert "Szablon z innym miesiącem w nagłówku" not in checks


# ── PKO: nagłówek z innego miesiąca ─────────────────────────────────────────

PKO_FILE = "TimeSheet 2607 - Testowa Ola PZ000001 Sierpień 2026.xlsm"


def _pko_old(header: str, hours: timedelta) -> timesheet_pko.ParsedPko:
    rows: list[list[object]] = [
        ["Nazwisko i Imię Kontraktora", "Testowa Ola"],
        [
            "Lp.",
            "Miesiąc realizacji usług",
            "Numer projektu / formacji",
            "Numer zadania projektowego / Tematu formacji",
            "Rezultat/dostarczona funkcjonalność",
            f"Liczba godzin realizacji usług {header}",
        ],
        [1, "czerwiec", "J0001", "T-1", "Testy", hours],
        [None, None, None, None, "Całkowity czas", hours],
    ]
    parsed = timesheet_pko.parse_rows(rows)
    assert parsed is not None
    return parsed


def _pko_dates(year: int, month: int, worked: set[int]) -> timesheet_pko.ParsedPko:
    """Nowszy szablon: kolumny dni z datami miesiąca z szablonu."""

    last = calendar.monthrange(year, month)[1]
    days = [datetime(year, month, d) for d in range(1, last + 1)]
    rows: list[list[object]] = [
        ["Nazwisko i Imię Kontraktora", "Testowa Ola"],
        [
            "Lp.",
            "Miesiąc rozliczenia",
            "Numer projektu / formacji",
            "Numer zadania projektowego / Tematu formacji",
            "Rezultat/dostarczona funkcjonalność",
            "RAZEM 2026 wrzesień",
            *days,
        ],
        [
            1,
            None,
            "J0001",
            "T-1",
            "Testy",
            None,
            *[timedelta(hours=8) if d.day in worked else None for d in days],
        ],
    ]
    parsed = timesheet_pko.parse_rows(rows)
    assert parsed is not None and parsed.month_from_dates
    return parsed


def _pko(
    parsed: timesheet_pko.ParsedPko, month: str, named: Optional[str]
) -> rcp_checks.ProofResult:
    return timesheet_pko.evaluate(
        parsed,
        month=month,
        person_name="Ola Testowa",
        rules=_rules(),
        working_days=len(template_month.workdays(month)),
        file_name=PKO_FILE,
        named_month=named,
    )


def test_pko_naglowek_z_lipca_przy_sierpniu_z_nazwy_i_pelnym_miesiacu_nie_blokuje():
    # Starszy szablon bez kolumn dni: 168 h to pełny sierpień (21 dni), nie lipiec (23).
    parsed = _pko_old("lipiec 2026", timedelta(days=7))
    result = _pko(parsed, AUG, AUG)
    note = _checks(result)["Szablon z innym miesiącem w nagłówku"]
    assert note["notice"] == rcp_checks.NOTE_TEMPLATE_MONTH
    assert note["detail"].startswith("W nagłówku: lipiec 2026.")
    assert not result.blocking and not result.warn
    assert result.md_regular == D("21.000")
    # Akceptacja „Akceptuję” bez liczby liczy się za sierpień.
    assert timesheet_pko.sheet_month(parsed, AUG, PKO_FILE, AUG, D("8")) == AUG


@pytest.mark.parametrize(
    ("header", "hours", "named"),
    [
        ("lipiec 2026", timedelta(days=7), None),
        # 160 h: nie pełny sierpień, więc nie wiadomo, za który miesiąc.
        ("lipiec 2026", timedelta(days=6, hours=16), AUG),
        # Czerwiec też ma 21 dni roboczych: 168 h pasuje do obu miesięcy.
        ("czerwiec 2026", timedelta(days=7), AUG),
    ],
    ids=["bez-miesiaca-z-nazwy", "niepelny-miesiac", "oba-kalendarze"],
)
def test_pko_naglowek_z_innego_miesiaca_bez_dowodu_dalej_blokuje(header, hours, named):
    parsed = _pko_old(header, hours)
    result = _pko(parsed, AUG, named)
    assert _checks(result)["Time Sheet za inny miesiąc"]["state"] == "fail"
    assert result.blocking
    assert timesheet_pko.sheet_month(parsed, AUG, PKO_FILE, named, D("8")) != AUG


def test_pko_nowy_szablon_z_dniami_pazdziernika_na_datach_wrzesnia():
    parsed = _pko_dates(2026, 9, set(template_month.workdays(OCT)))
    result = _pko(parsed, OCT, OCT)
    note = _checks(result)["Szablon z innym miesiącem w nagłówku"]
    assert note["notice"] == rcp_checks.NOTE_TEMPLATE_MONTH
    assert "dni z godzinami" in note["detail"]
    assert not result.blocking
    # Dni 1–2 pasują do obu miesięcy: zostaje blokada.
    ambiguous = _pko(_pko_dates(2026, 9, {1, 2}), OCT, OCT)
    assert _checks(ambiguous)["Time Sheet za inny miesiąc"]["state"] == "fail"


# ── BIK: daty wierszy z szablonu ────────────────────────────────────────────


def _bik(
    days: list[Optional[date]], month_field: Optional[str] = "lipiec 2026"
) -> timesheet_bik.ParsedBik:
    rows: list[list[object]] = [
        ["Rozliczenie czasu pracy"],
        ["Imię i nazwisko", "Jan Testowy"],
        ["Miesiąc", month_field],
        ["Numer jiry", "Nazwa zadania", "Data", "Liczba godzin"],
        *[
            [
                f"ABC-{i}",
                "Implementacja",
                None if day is None else datetime.combine(day, datetime.min.time()),
                8,
            ]
            for i, day in enumerate(days)
        ],
        ["Suma godzin", 8 * len(days)],
    ]
    parsed = timesheet_bik.parse_rows(rows)
    assert parsed is not None
    return parsed


def _bik_eval(parsed: timesheet_bik.ParsedBik) -> rcp_checks.ProofResult:
    return timesheet_bik.evaluate(
        parsed,
        month=JULY,
        person_name="Jan Testowy",
        rules=_rules(),
        working_days=23,
    )


# Dni robocze lipca 2026 bez 6.07 (dzień wolny): 22 dni, a 13, 20 i 27 to
# w lipcu 2025 niedziele.
JULY_DAYS = sorted(set(template_month.workdays(JULY)) - {6})


def test_bik_daty_z_szablonu_zeszlego_roku_przy_polu_miesiac_nie_blokuja():
    parsed = _bik([date(2025, 7, d) for d in JULY_DAYS])
    assert timesheet_bik.template_dates_month(parsed, JULY) == "2025-07"
    result = _bik_eval(parsed)
    note = _checks(result)["Wiersze z datą spoza miesiąca: 22"]
    assert note["state"] == "none"
    assert note["notice"] == rcp_checks.NOTE_ROW_DATES
    assert note["detail"].startswith("Daty z szablonu: lipiec 2025.")
    assert not result.warn and not result.blocking
    assert result.md_regular == D("22.000")


@pytest.mark.parametrize(
    "days",
    [
        # Część wierszy z lipca 2026, część z lipca 2025.
        [date(2026, 7, d) for d in JULY_DAYS[:11]]
        + [date(2025, 7, d) for d in JULY_DAYS[11:]],
        # Dni 1–3 to dni robocze lipca 2026 i lipca 2025: brak dowodu.
        [date(2025, 7, d) for d in (1, 2, 3)],
        # Wiersz bez daty.
        [date(2025, 7, d) for d in JULY_DAYS] + [None],
    ],
    ids=["dwa-miesiace", "oba-kalendarze", "wiersz-bez-daty"],
)
def test_bik_daty_spoza_miesiaca_bez_dowodu_dalej_daja_uwage(days):
    result = _bik_eval(_bik(days))
    (check,) = [
        c
        for c in _checks(result).values()
        if c["title"].startswith("Wiersze z datą spoza miesiąca")
    ]
    assert check["state"] == "warn" and "notice" not in check
    assert result.warn


def test_bik_inne_pole_miesiac_nie_jest_kosmetyka():
    parsed = _bik([date(2025, 7, d) for d in JULY_DAYS], month_field="czerwiec 2026")
    assert timesheet_bik.template_dates_month(parsed, JULY) is None


# ── Time Sheet: dotychczasowe informacje dają komunikat konsultantowi ──────


def test_time_sheet_daty_z_szablonu_maja_klucz_informacji():
    rows: list[list[object]] = [
        [None, "Time Sheet"],
        [None, "Project Name", "Produkt API"],
        [None, "Consultant(s)", "Jan Testowy"],
        [None, "Date from", datetime(2026, 9, 1)],
        [None, "Date to", datetime(2026, 9, 30)],
        [None, "Date", "Project", "Description", "Total Hours", "Billable"],
        *[[None, datetime(2026, 6, d), "ALFA", "Testy", 8, 8] for d in (1, 2, 3)],
        [None, None, None, "Total Hours", 24],
    ]
    parsed = timesheet.parse_rows([rows])
    assert parsed is not None
    result = timesheet.evaluate(
        parsed,
        month="2026-09",
        person_name="Jan Testowy",
        has_mail=False,
        rules=_rules(),
        working_days=22,
    )
    note = _checks(result)["Daty wierszy z innego miesiąca: 2026-06"]
    assert (note["state"], note["notice"]) == ("none", rcp_checks.NOTE_ROW_DATES)
    assert not result.warn and not result.blocking


# ── Status: informacja nie zmienia „Bez uwag” ──────────────────────────────


def _status(proof: rcp_checks.ProofResult) -> str:
    order = engine.OrderState(
        order_id=1,
        number="Z0001",
        md_total=D("100"),
        md_available=D("100"),
        rate_cost=D("500"),
        rate_revenue=D("600"),
    )
    result = engine.compute(
        engine.Inputs(
            md_regular=proof.md_regular,
            md_extra=proof.md_extra,
            rules=rules_catalog.effective(None),
            order=order,
            proof=proof,
        )
    )
    return result.status


def test_informacja_zostaje_na_karcie_a_rozliczenie_jest_bez_uwag():
    relaxed = _bnp(_rcp(rows=("15",)))
    assert _status(relaxed) == "ok"
    still = _bnp(_rcp(rows=("15",), extra=("1",)))
    assert _status(still) == "warnings"
