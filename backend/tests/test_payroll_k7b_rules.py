"""K7b: pensja UoP, wynagrodzenie chorobowe, urlopowe i ekwiwalent — reguły bez bazy.

Kwoty fikcyjne (repo publiczne). Liczby policzone ręcznie według przepisów
opisanych w ``salary.py`` — do potwierdzenia na porównaniu z Enovą.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal as D

import pytest

from app.services.hr.payroll_lists import engine, params, salary
from app.services.hr.payroll_lists.salary import Absence, BasisMonth, MonthInput

P = params.SEED_PARAMS


def full_history(year: int, month: int, amount: str = "8000", months: int = 12):
    out = []
    for n in range(1, months + 1):
        y, m = salary.shift_month(year, month, -n)
        out.append(
            BasisMonth(
                year=y,
                month=m,
                fixed_paid=D(amount),
                fixed_full=D(amount),
                variable=D("0"),
                nominal_hours=D("160"),
                worked_hours=D("160"),
                paid_hours=D("160"),
            )
        )
    return tuple(out)


def november(**changes) -> MonthInput:
    base = MonthInput(
        year=2026,
        month=11,
        monthly_salary=D("8000"),
        fte=D("1"),
        employed_from=date(2020, 1, 1),
        employed_to=date(2099, 12, 31),
        hired_on=date(2020, 1, 1),
        insured_since=date(2020, 1, 1),
        history=full_history(2026, 11),
    )
    return replace(base, **changes)


def sick(start: date, end: date, rate: str = "80", key: str = "a", **kw) -> Absence:
    return Absence(
        key=key, leave_type="sick_leave", start=start, end=end, sick_rate=rate, **kw
    )


def leave(kind: str, days: list[date], key: str = "u") -> Absence:
    return Absence(
        key=key,
        leave_type=kind,
        start=days[0],
        end=days[-1],
        days=tuple((day, D("1")) for day in days),
    )


# ── Kalendarz ───────────────────────────────────────────────────────────────


def test_wymiar_counts_saturday_holidays_and_skips_sunday_ones() -> None:
    # Listopad 2026: 21 dni pon.–pt., 11.11 w środę; 1.11 w niedzielę nie obniża.
    assert salary.nominal_hours(date(2026, 11, 1), date(2026, 11, 30), D("1")) == D(
        "160"
    )
    # Sierpień 2026: 15.08 w sobotę obniża wymiar o 8 h (21 dni pon.–pt. → 20).
    assert salary.wymiar_days(date(2026, 8, 1), date(2026, 8, 31)) == 20
    assert salary.nominal_hours(date(2026, 11, 1), date(2026, 11, 30), D("0.5")) == D(
        "80"
    )


def test_leave_coefficient_2026_matches_seed() -> None:
    assert salary.leave_coefficient(2026) == D("20.92")
    assert P.leave_coefficient == D("20.92")


# ── Pensja ──────────────────────────────────────────────────────────────────


def test_full_month_is_the_salary() -> None:
    pay = salary.month_pay(november(), P)
    assert pay.gross == D("8000.00")
    assert pay.salary_part == D("8000.00")
    assert pay.sick_pay == 0
    assert "salary" in pay.notes
    assert pay.basis.full_month and pay.basis.worked_hours == D("160")


def test_start_mid_month_uses_hours_method() -> None:
    # Start 16.11 (pon.): poza umową 2–13.11 = 9 dni wymiaru (11.11 święto) = 72 h.
    pay = salary.month_pay(
        november(employed_from=date(2026, 11, 16), hired_on=date(2026, 11, 16)), P
    )
    assert pay.salary_part == D("8000.00") - D("3600.00")
    assert pay.reductions == {"hours": "3600.00"}
    assert not pay.basis.full_month


def test_unpaid_leave_cuts_hours_and_vacation_does_not() -> None:
    unpaid = leave("unpaid_leave", [date(2026, 11, 2), date(2026, 11, 3)])
    vacation = leave("vacation", [date(2026, 11, 4), date(2026, 11, 5)], key="v")
    pay = salary.month_pay(november(absences=(unpaid, vacation)), P)
    assert pay.salary_part == D("7200.00")  # 8000 − 8000/160 × 16
    assert pay.worked_hours == D("128")  # 160 − 16 bezpłatnego − 16 urlopu
    assert pay.paid_hours == D("144")


# ── Wynagrodzenie chorobowe ─────────────────────────────────────────────────


def test_sick_pay_80_percent_from_twelve_months() -> None:
    pay = salary.month_pay(
        november(absences=(sick(date(2026, 11, 9), date(2026, 11, 13)),)), P
    )
    (part,) = pay.sick
    assert part.base == D("6903.20")  # 8000 − 13,71%
    assert part.daily == D("184.09")  # 6903,20 × 80% / 30
    assert part.paid_days == 5
    assert pay.sick_pay == D("920.45")
    assert pay.salary_part == D("6666.67")  # 8000 − 8000/30 × 5
    assert pay.gross == D("7587.12")
    assert pay.social_exempt == D("920.45")
    assert dict(pay.sick_days_by_year) == {2026: 5}
    assert "sick_pay" in pay.notes and not pay.problems


def test_sick_pay_100_percent_when_marked() -> None:
    pay = salary.month_pay(
        november(absences=(sick(date(2026, 11, 9), date(2026, 11, 10), rate="100"),)), P
    )
    assert pay.sick[0].daily == D("230.11")  # 6903,20 / 30


def test_waiting_period_pays_nothing_and_cuts_by_hours() -> None:
    hired = date(2026, 11, 2)
    pay = salary.month_pay(
        november(
            employed_from=hired,
            hired_on=hired,
            insured_since=hired,
            history=(),
            absences=(sick(date(2026, 11, 10), date(2026, 11, 14)),),
        ),
        P,
    )
    (part,) = pay.sick
    assert part.waiting_days == 5 and part.paid_days == 0
    assert pay.sick_pay == 0
    # 10, 12, 13.11 to dni wymiaru (11.11 święto, 14.11 sobota) = 24 h; od 2.11 umowa całość.
    assert pay.salary_part == D("8000.00") - D("1200.00")
    assert "sick_waiting" in pay.notes


def test_waiting_period_exemption_from_person_or_absence() -> None:
    hired = date(2026, 11, 2)
    common = dict(employed_from=hired, hired_on=hired, insured_since=hired, history=())
    l4 = sick(date(2026, 11, 10), date(2026, 11, 11))
    by_person = salary.month_pay(
        november(waiting_exempt=True, absences=(l4,), **common), P
    )
    by_mark = salary.month_pay(
        november(absences=(replace(l4, waiting_exempt=True),), **common), P
    )
    assert by_person.sick[0].paid_days == by_mark.sick[0].paid_days == 2
    assert "sick_base_salary" in by_person.notes  # bez pełnego miesiąca — z pensji


def test_yearly_limit_then_zus_benefit_and_z3_problem() -> None:
    pay = salary.month_pay(
        november(
            sick_days_used=((2026, 30),),
            absences=(sick(date(2026, 11, 9), date(2026, 11, 13)),),
        ),
        P,
    )
    (part,) = pay.sick
    assert (part.paid_days, part.zus_days) == (3, 2)
    assert pay.problems == ("z3_needed",)
    # Pensja: 1/30 za wszystkie 5 dni (§ 11 ust. 2 — także dni zasiłku).
    assert pay.salary_part == D("6666.67")


def test_benefit_payer_makes_zus_days_a_blocking_manual_case() -> None:
    payer = replace(P, benefit_payer=1)
    pay = salary.month_pay(
        november(
            sick_days_used=((2026, 33),),
            absences=(sick(date(2026, 11, 9), date(2026, 11, 9)),),
        ),
        payer,
    )
    assert pay.problems == ("benefit_payer_manual",)


def test_fourteen_days_from_year_after_fiftieth_birthday() -> None:
    assert salary.sick_limit(date(1975, 6, 1), 2026, P) == 14
    assert (
        salary.sick_limit(date(1976, 6, 1), 2026, P) == 33
    )  # 50 lat w 2026 — jeszcze 33
    assert salary.sick_limit(None, 2026, P) == 33


def test_care_benefit_from_zus_from_first_day() -> None:
    pay = salary.month_pay(
        november(absences=(sick(date(2026, 11, 9), date(2026, 11, 10), rate="zus"),)), P
    )
    assert pay.sick_pay == 0 and pay.sick[0].zus_days == 2
    assert dict(pay.sick_days_by_year) == {}  # nie zjada limitu pracodawcy
    assert pay.problems == ("z3_needed",)


def test_whole_month_sick_means_no_salary() -> None:
    pay = salary.month_pay(
        november(absences=(sick(date(2026, 10, 20), date(2026, 12, 5)),)), P
    )
    assert pay.salary_part == 0
    assert pay.sick[0].paid_days == 30
    assert pay.sick_pay == D("5522.70")  # 184,09 × 30


def test_sick_and_unpaid_leave_two_steps() -> None:
    absences = (
        leave("unpaid_leave", [date(2026, 11, 2)]),
        sick(date(2026, 11, 9), date(2026, 11, 10)),
    )
    pay = salary.month_pay(november(absences=absences), P)
    # 8000 − 8000/160 × 8 − 8000/30 × 2
    assert pay.salary_part == D("8000") - D("400.00") - D("533.33")


def test_base_skips_months_below_half_and_supplements_partial() -> None:
    history = list(full_history(2026, 11))
    # Październik: przepracowane 60 z 160 h (mniej niż połowa) — wypada.
    history[0] = replace(
        history[0], fixed_paid=D("3000"), paid_hours=D("60"), worked_hours=D("60")
    )
    # Wrzesień: 120 z 160 h — uzupełniony do pełnej pensji.
    history[1] = replace(
        history[1], fixed_paid=D("6000"), paid_hours=D("120"), worked_hours=D("120")
    )
    base, notes = salary.sick_base(
        history,
        year=2026,
        month=11,
        hired_on=date(2020, 1, 1),
        monthly_salary=D("8000"),
        fte=D("1"),
        params=P,
    )
    assert base == D("6903.20") and notes == []


def test_base_from_all_months_when_none_reaches_half() -> None:
    history = [
        replace(row, fixed_paid=D("2000"), paid_hours=D("40"), worked_hours=D("40"))
        for row in full_history(2026, 11)
    ]
    base, notes = salary.sick_base(
        history,
        year=2026,
        month=11,
        hired_on=date(2020, 1, 1),
        monthly_salary=D("8000"),
        fte=D("1"),
        params=P,
    )
    assert "sick_base_all_months" in notes
    assert base == D("6903.20")  # stałe uzupełnione do pełnego miesiąca


def test_base_never_below_minimum_wage_after_contributions() -> None:
    base, notes = salary.sick_base(
        full_history(2026, 11, amount="4000"),
        year=2026,
        month=11,
        hired_on=date(2020, 1, 1),
        monthly_salary=D("4000"),
        fte=D("1"),
        params=P,
    )
    assert base == D("4806.00") - D("658.90")
    assert notes == ["sick_base_minimum"]


def test_base_only_from_full_months_after_hiring() -> None:
    history = full_history(2026, 11)  # 12 miesięcy po 8000, ale zatrudnienie od 15.09
    base, notes = salary.sick_base(
        history,
        year=2026,
        month=11,
        hired_on=date(2026, 9, 15),
        monthly_salary=D("9000"),
        fte=D("1"),
        params=P,
    )
    assert base == D("6903.20") and notes == []  # tylko październik (pełny)
    base, notes = salary.sick_base(
        (),
        year=2026,
        month=11,
        hired_on=date(2026, 11, 2),
        monthly_salary=D("9000"),
        fte=D("1"),
        params=P,
    )
    assert base == D("7766.10") and notes == ["sick_base_salary"]


def test_base_reused_within_three_months() -> None:
    previous = salary.PreviousSick(last_day=date(2026, 9, 20), base=D("7000.00"))
    pay = salary.month_pay(
        november(
            previous_sick=previous,
            absences=(sick(date(2026, 11, 9), date(2026, 11, 9)),),
        ),
        P,
    )
    assert pay.sick[0].base == D("7000.00") and "sick_base_reused" in pay.notes
    far = salary.PreviousSick(last_day=date(2026, 8, 5), base=D("7000.00"))
    pay = salary.month_pay(
        november(
            previous_sick=far, absences=(sick(date(2026, 11, 9), date(2026, 11, 9)),)
        ),
        P,
    )
    assert pay.sick[0].base == D("6903.20")


def test_sick_base_override_from_payroll_wins() -> None:
    pay = salary.month_pay(
        november(
            sick_base_override=D("5000"),
            absences=(sick(date(2026, 11, 9), date(2026, 11, 9)),),
        ),
        P,
    )
    assert pay.sick[0].base == D("5000.00")


def test_unknown_sick_rate_and_bad_input_refused() -> None:
    with pytest.raises(ValueError):
        salary.month_pay(
            november(absences=(sick(date(2026, 11, 9), date(2026, 11, 9), rate="70"),)),
            P,
        )
    with pytest.raises(ValueError):
        salary.month_pay(november(fte=D("0")), P)
    with pytest.raises(ValueError):
        salary.month_pay(november(employed_to=date(2026, 10, 31)), P)


# ── Urlopowe i ekwiwalent ───────────────────────────────────────────────────


def test_leave_pay_for_variable_components_from_three_months() -> None:
    history = tuple(replace(row, variable=D("1600")) for row in full_history(2026, 11))
    vacation = leave("vacation", [date(2026, 11, 2), date(2026, 11, 3)])
    pay = salary.month_pay(
        november(history=history, absences=(vacation,), variable=D("1200")), P
    )
    assert pay.leave_variable == D("160.00")  # 4800 / 480 h × 16 h
    assert pay.gross == D("8000") + D("160.00") + D("1200")
    assert pay.basis.leave_variable == D("160.00")
    assert "leave_variable" in pay.notes


def test_force_majeure_pays_half() -> None:
    absence = leave("force_majeure", [date(2026, 11, 2)])
    pay = salary.month_pay(november(absences=(absence,)), P)
    assert pay.salary_part == D("7800.00")  # połowa z 8 h × 50 zł


def test_bonuses_and_other_stay_outside_bases() -> None:
    pay = salary.month_pay(november(bonuses=D("3000"), other=D("500")), P)
    assert pay.gross == D("11500.00")
    assert pay.basis.sick_amount == D("8000.00")


def test_equivalent_per_hour_rule() -> None:
    assert salary.equivalent_amount(
        monthly_salary=D("6000"),
        variable_average=D("0"),
        fte=D("1"),
        days=D("10"),
        params=P,
    ) == D("2868.00")  # 6000/20,92 = 286,81; /8 = 35,85; × 80 h
    half = salary.equivalent_amount(
        monthly_salary=D("3000"),
        variable_average=D("0"),
        fte=D("0.5"),
        days=D("10"),
        params=P,
    )
    assert half == D("2868.00")  # współczynnik 10,46


def test_equivalent_on_list_when_contract_ends() -> None:
    pay = salary.month_pay(
        november(employed_to=date(2026, 11, 30), equivalent_days=D("5")), P
    )
    assert pay.equivalent == D("1912.00")  # 8000/20,92 = 382,41; /8 = 47,80; × 40 h
    assert "equivalent" in pay.notes


def test_unused_leave_proportional_in_year_of_leaving() -> None:
    days, over = salary.unused_leave_days(
        entitlement=D("26"),
        carried_over=D("2"),
        used_before=D("0"),
        used_paid=D("10"),
        year=2026,
        employed_from=date(2020, 1, 1),
        employed_to=date(2026, 6, 10),
    )
    assert (days, over) == (D("5"), False)  # 26 × 6/12 = 13, + 2 − 10
    days, over = salary.unused_leave_days(
        entitlement=D("20"),
        carried_over=D("0"),
        used_before=D("0"),
        used_paid=D("12"),
        year=2026,
        employed_from=date(2026, 3, 15),
        employed_to=date(2026, 7, 2),
    )
    assert (days, over) == (D("0"), True)  # 20 × 5/12 = 8,33 → 9 < 12


# ── Silnik: wynagrodzenie chorobowe bez składek społecznych ─────────────────


def test_engine_sick_pay_without_social_but_with_health_and_pit() -> None:
    title = engine.Title(
        kind="uop",
        gross=D("7587.12"),
        social_exempt=D("920.45"),
        work_start=date(2026, 11, 1),
        work_end=date(2026, 11, 30),
        pay_date=date(2026, 12, 10),
    )
    result = engine.calculate(title, engine.PersonTax(), engine.YearToDate(), P)
    assert result.insured_gross == D("6666.67")
    assert result.pension_basis == D("6666.67")
    assert result.social_employee == D("650.67") + D("100.00") + D("163.33")
    # Zdrowotna od całego przychodu po składkach (z chorobowym).
    assert result.health_basis == D("7587.12") - result.social_employee
    assert result.revenue == D("7587.12")


def test_engine_whole_month_sick_pay_has_health_only() -> None:
    title = engine.Title(
        kind="uop",
        gross=D("5522.70"),
        social_exempt=D("5522.70"),
        work_start=date(2026, 11, 1),
        work_end=date(2026, 11, 30),
        pay_date=date(2026, 12, 10),
    )
    result = engine.calculate(title, engine.PersonTax(), engine.YearToDate(), P)
    assert result.social_employee == 0 and result.employer_social == 0
    assert result.health == D("497.04")
    assert result.pit > 0


def test_engine_refuses_social_exempt_outside_uop_or_above_gross() -> None:
    common = dict(
        work_start=date(2026, 11, 1),
        work_end=date(2026, 11, 30),
        pay_date=date(2026, 12, 10),
    )
    with pytest.raises(ValueError):
        engine.calculate(
            engine.Title(
                kind="zlecenie", gross=D("100"), social_exempt=D("10"), **common
            ),
            engine.PersonTax(),
            engine.YearToDate(),
            P,
        )
    with pytest.raises(ValueError):
        engine.calculate(
            engine.Title(kind="uop", gross=D("100"), social_exempt=D("101"), **common),
            engine.PersonTax(),
            engine.YearToDate(),
            P,
        )


# ── Parametry K7b ───────────────────────────────────────────────────────────


def test_versions_saved_before_k7b_parse_with_defaults() -> None:
    old = {k: v for k, v in params.SEED_2026.items() if k not in params.LATER_DEFAULTS}
    parsed = params.parse(old)
    assert parsed.sick_pay_rate == D("80") and parsed.sick_pay_days_limit == 33
    assert params.to_json(parsed)["leave_coefficient"] == "20.92"
    with pytest.raises(params.ParamsError, match="dni w roku"):
        params.parse({**params.SEED_2026, "sick_pay_days_limit": "0"})
    with pytest.raises(params.ParamsError):
        params.parse({**params.SEED_2026, "benefit_payer": "2"})


# ── Porównanie z Enovą i dekret LP (bez bazy) ───────────────────────────────

ENOVA_CSV = "\r\n".join(
    [
        "Pracownik;Razem brutto;Emerytalne prac.;Rentowe prac.;Chorobowe;Zdrowotne;"
        "Zaliczka podatku;PPK pracownika;Do wypłaty;Emerytalne pracodawca;Rentowe pracodawca;"
        "Wypadkowe;FP;FGŚP;PPK pracodawcy",
        "Testowa Anna;10000,00;976,00;150,00;245,00;776,61;588,00;200,00;7064,39;976,00;650,00;"
        "167,00;245,00;10,00;150,00",
        "Przykładowy Jan;8000,00;780,80;120,00;196,00;621,29;470,00;0;5811,91;780,80;520,00;"
        "133,60;196,00;8,00;0",
    ]
).encode("utf-8")

NEXUS_RESULT = {
    "gross": "10000.00",
    "pension_employee": "976.00",
    "disability_employee": "150.00",
    "sickness_employee": "245.00",
    "health": "776.61",
    "pit": "588.00",
    "ppk_employee": "200.00",
    "net": "7064.39",
    "pension_employer": "976.00",
    "disability_employer": "650.00",
    "accident_employer": "167.00",
    "labour_fund": "245.00",
    "fgsp": "10.00",
    "ppk_employer": "150.00",
}


class _Line:
    def __init__(self, line_id: int, name: str, result: dict) -> None:
        self.id = line_id
        self.person_name = name
        self.result = result


def test_compare_matches_people_by_name_tokens_and_reports_grosze() -> None:
    from app.services.hr.payroll_lists import enova_compare, ledger_post
    from app.services.ledger import payroll_lists as enova

    parsed = enova.parse(ENOVA_CSV)
    anna = ledger_post.row_of(_Line(1, "Anna Testowa", NEXUS_RESULT))
    other = ledger_post.row_of(
        _Line(2, "Ktoś Spoza", {**NEXUS_RESULT, "pit": "589.00", "net": "7063.39"})
    )
    result = enova_compare.compare_rows([anna, other], parsed)
    assert result["summary"] == {
        "matched": 1,
        "equal": 1,
        "different": 0,
        "only_nexus": 1,
        "only_enova": 1,
        "all_equal": False,
        "file_errors": 0,
    }
    assert result["only_enova"][0]["person"] == "Przykładowy Jan"
    off = ledger_post.row_of(
        _Line(3, "Anna Testowa", {**NEXUS_RESULT, "pit": "589.00", "net": "7063.39"})
    )
    result = enova_compare.compare_rows([off], parsed)
    person = result["people"][0]
    assert person["equal"] is False
    assert {f["key"]: f["diff"] for f in person["fields"] if f["diff"]} == {
        "pit": 100,
        "net": -100,
    }


def test_compare_sums_several_nexus_lines_of_one_person() -> None:
    from app.services.hr.payroll_lists import enova_compare, ledger_post
    from app.services.ledger import payroll_lists as enova

    half = {key: str(D(value) / 2) for key, value in NEXUS_RESULT.items()}
    parsed = enova.parse(ENOVA_CSV)
    rows = [ledger_post.row_of(_Line(n, "Anna Testowa", half)) for n in (1, 2)]
    person = enova_compare.compare_rows(rows, parsed)["people"][0]
    assert person["nexus_lines"] == 2
    assert person["fields"][0]["key"] == "gross" and person["fields"][0]["diff"] == 0


def test_nexus_lp_rows_give_the_same_decree_as_enova_file() -> None:
    from app.services.hr.payroll_lists import ledger_post
    from app.services.ledger import payroll_lists as enova
    from app.services.ledger.settings import PayrollAccounts

    accounts = PayrollAccounts(
        wages_account="404",
        insurance_account="405",
        settlement_account="231",
        zus_account="229",
        pit_account="225",
        ppk_account="234",
    )
    nexus = ledger_post.row_of(_Line(1, "Anna Testowa", NEXUS_RESULT))
    enova_rows = [
        row for row in enova.parse(ENOVA_CSV).rows if row.person == "Testowa Anna"
    ]
    ours, problems = enova.decree([nexus], accounts)
    theirs, _ = enova.decree(enova_rows, accounts)
    assert not problems
    assert [(row.side, row.account, row.amount) for row in ours] == [
        (row.side, row.account, row.amount) for row in theirs
    ]


# ── Poprawki po przeglądzie K7b (16.11.2026) ───────────────────────────────


def test_unused_leave_does_not_prorate_a_pool_already_prorated_at_start() -> None:
    # Start 1.07, pula od Kadr 13 dni (26 × 6/12), odejście 30.09: 13 × 3/6 = 6,5 → 7.
    days, over = salary.unused_leave_days(
        entitlement=D("13"),
        carried_over=D("0"),
        used_before=D("0"),
        used_paid=D("0"),
        year=2026,
        employed_from=date(2026, 7, 1),
        employed_to=date(2026, 9, 30),
    )
    assert (days, over) == (D("7"), False)


def test_labour_fund_condition_counts_bonuses_and_full_month_salary() -> None:
    pay = salary.month_pay(
        november(monthly_salary=D("2500"), fte=D("0.5"), bonuses=D("2500")), P
    )
    assert pay.gross == D("5000.00") and pay.fund_basis == D("5000.00")
    title = engine.Title(
        kind="uop",
        gross=pay.gross,
        work_start=date(2026, 11, 1),
        work_end=date(2026, 11, 30),
        pay_date=date(2026, 12, 10),
        labour_fund_basis=pay.fund_basis,
    )
    result = engine.calculate(title, engine.PersonTax(), engine.YearToDate(), P)
    assert result.labour_fund == D("122.50")
    # L4 pół miesiąca: pensja pomniejszona, ale warunek FP na pensji za pełny miesiąc.
    sick_half = salary.month_pay(
        november(absences=(sick(date(2026, 11, 1), date(2026, 11, 15)),)), P
    )
    assert sick_half.fund_basis == D("8000.00")


def test_compare_is_not_green_with_unreadable_rows_or_missing_columns() -> None:
    from app.services.hr.payroll_lists import enova_compare, ledger_post
    from app.services.ledger import payroll_lists as enova

    broken = ENOVA_CSV.decode().replace("780,80;120,00", "780,80;xx").encode()
    anna = ledger_post.row_of(_Line(1, "Anna Testowa", NEXUS_RESULT))
    result = enova_compare.compare_rows([anna], enova.parse(broken))
    assert result["summary"]["equal"] == 1 and result["summary"]["file_errors"] == 1
    assert result["summary"]["all_equal"] is False
    no_pit = "\r\n".join(
        [
            "Pracownik;Razem brutto;Emerytalne prac.;Rentowe prac.;Chorobowe;Zdrowotne;"
            "PPK pracownika;Do wypłaty",
            "Testowa Anna;10000,00;976,00;150,00;245,00;776,61;200,00;7652,39",
        ]
    ).encode()
    result = enova_compare.compare_rows(
        [
            ledger_post.row_of(
                _Line(1, "Anna Testowa", {**NEXUS_RESULT, "pit": "0", "net": "7652.39"})
            )
        ],
        enova.parse(no_pit),
    )
    assert result["summary"]["all_equal"] is False
    assert any("Zaliczka PIT" in text for text in result["problems"])
