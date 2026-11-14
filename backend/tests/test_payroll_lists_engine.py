"""Silnik brutto → netto (K7a): przypadki brzegowe na parametrach 2026.

Dane fikcyjne — bez osób i prawdziwych kwot. Dwa pierwsze przypadki odtwarzają
liczby z makiety „Płace — lista płac” (13.11.2026), policzone ręcznie.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal as D

import pytest

from app.services.hr.payroll_lists import engine
from app.services.hr.payroll_lists.engine import PersonTax, Ppk, Title, YearToDate
from app.services.hr.payroll_lists.params import SEED_PARAMS as P

OCT_START = date(2026, 10, 1)
OCT_END = date(2026, 10, 31)
PAY = date(2026, 11, 10)
ADULT = date(1990, 3, 3)


def title(kind: str = "uop", gross: str = "7800", **kw: object) -> Title:
    base = dict(
        kind=kind,
        gross=D(gross),
        work_start=OCT_START,
        work_end=OCT_END,
        pay_date=PAY,
    )
    base.update(kw)
    return Title(**base)  # type: ignore[arg-type]


def person(**kw: object) -> PersonTax:
    base: dict[str, object] = {"birth_date": ADULT, "sex": "M"}
    base.update(kw)
    return PersonTax(**base)  # type: ignore[arg-type]


def calc(t: Title, p: PersonTax, ytd: YearToDate | None = None) -> engine.Result:
    return engine.calculate(t, p, ytd or YearToDate(), P)


# ── Makieta: UoP i zlecenie ──────────────────────────────────────────────────


def test_uop_with_pit2_matches_mockup() -> None:
    r = calc(title("uop", "7800"), person(pit2_fraction=12))
    assert r.pension_employee == D("761.28")
    assert r.disability_employee == D("117.00")
    assert r.sickness_employee == D("191.10")
    assert r.social_employee == D("1069.38")
    assert r.health == D("605.76")
    assert r.kup == D("250.00")
    assert r.tax_base == D("6481")
    assert r.tax_reduction == D("300.00")
    assert r.pit == D("478")
    assert r.net == D("5646.86")
    assert r.employer_social == D("1597.44")
    assert r.employer_cost == D("9397.44")
    assert r.zus_due == D("1069.38") + D("605.76") + D("1597.44")
    assert r.tax_kind == "scale"


def test_mandate_without_pit2_matches_mockup() -> None:
    r = calc(title("zlecenie", "7056"), person())
    assert r.social_employee == D("794.51")
    assert r.sickness_employee == D("0")
    assert r.health == D("563.53")
    assert r.kup == D("1252.30")
    assert r.tax_base == D("5009")
    assert r.pit == D("601")
    assert r.net == D("5096.96")
    assert r.accident_employer == D("117.84")
    assert r.labour_fund == D("172.87")
    assert r.fgsp == D("7.06")
    assert r.employer_social == D("1445.08")


# ── PIT-2, koszty, próg ─────────────────────────────────────────────────────


def test_pit2_lowers_advance_by_monthly_reduction() -> None:
    without = calc(title("uop", "7800"), person())
    with_pit2 = calc(title("uop", "7800"), person(pit2_fraction=12))
    assert without.pit == D("778")
    assert without.tax_reduction == D("0")
    assert without.pit - with_pit2.pit == D("300")
    half = calc(title("uop", "7800"), person(pit2_fraction=24))
    third = calc(title("uop", "7800"), person(pit2_fraction=36))
    assert (half.tax_reduction, third.tax_reduction) == (D("150.00"), D("100.00"))
    assert (half.pit, third.pit) == (D("628"), D("678"))


def test_pit2_also_on_mandate() -> None:
    r = calc(title("zlecenie", "7056"), person(pit2_fraction=12))
    assert r.pit == D("301")


def test_increased_kup_on_employment() -> None:
    r = calc(title("uop", "7800"), person(pit2_fraction=12, kup_increased=True))
    assert r.kup == D("300.00")
    assert r.tax_base == D("6431")
    assert r.pit == D("472")
    assert "kup_increased" in r.notes


def test_kup_never_makes_income_negative() -> None:
    r = calc(title("uop", "200"), person())
    assert r.kup == D("200") - r.social_employee
    assert r.tax_base == D("0")
    assert r.pit == D("0")


def test_pit_threshold_crossed_in_month() -> None:
    ytd = YearToDate(tax_base=D("118000"))
    r = calc(title("uop", "20000"), person(pit2_fraction=12), ytd)
    assert r.social_employee == D("2742.00")
    assert r.tax_base == D("17008")
    # 2000 × 12% + 15008 × 32% − 300 = 4742,56 → 4743
    assert r.pit == D("4743")
    assert "pit_threshold" in r.notes
    assert r.ytd_after.tax_base == D("135008")


def test_threshold_does_not_apply_to_mandate() -> None:
    ytd = YearToDate(tax_base=D("200000"))
    r = calc(title("zlecenie", "7056"), person(), ytd)
    assert r.pit == D("601")
    assert "pit_threshold" not in r.notes
    assert r.ytd_after.tax_base == D("200000")


# ── Fundusz Pracy przy podstawie poniżej płacy minimalnej ────────────────────


def test_below_minimum_wage_no_labour_fund_but_fgsp() -> None:
    r = calc(title("uop", "3000"), person())
    assert r.labour_fund == D("0")
    assert r.fgsp == D("3.00")
    assert "labour_fund_below_minimum" in r.notes


def test_minimum_wage_exactly_pays_labour_fund() -> None:
    r = calc(title("uop", "4806"), person())
    assert r.labour_fund == D("117.75")
    assert "labour_fund_below_minimum" not in r.notes


def test_part_month_uses_full_month_equivalent_for_labour_fund() -> None:
    r = calc(title("uop", "2403", labour_fund_basis=D("4806")), person())
    assert r.labour_fund == D("58.87")


def test_labour_fund_and_fgsp_end_month_after_age() -> None:
    woman = person(birth_date=date(1971, 5, 10), sex="F")
    same_month = calc(title("uop", "7800", pay_date=date(2026, 5, 28)), woman)
    next_month = calc(title("uop", "7800", pay_date=date(2026, 6, 10)), woman)
    assert same_month.labour_fund > 0 and same_month.fgsp > 0
    assert next_month.labour_fund == D("0") and next_month.fgsp == D("0")
    assert "labour_fund_age" in next_month.notes


def test_manual_fund_exemption_until_date() -> None:
    p = person(labour_fund_exempt_until=date(2026, 12, 31))
    r = calc(title("uop", "7800"), p)
    assert r.labour_fund == D("0")
    assert r.fgsp == D("7.80")


# ── Limit 30-krotności ───────────────────────────────────────────────────────


def test_pension_limit_crossed_within_month() -> None:
    ytd = YearToDate(pension_basis=D("270000"))
    r = calc(title("uop", "20000"), person(pit2_fraction=12), ytd)
    assert r.pension_basis == D("12600")
    assert r.pension_employee == D("1229.76")
    assert r.disability_employee == D("189.00")
    assert r.sickness_employee == D("490.00")
    assert r.pension_employer == D("1229.76")
    assert r.disability_employer == D("819.00")
    # Wypadkowa, FP i FGŚP bez limitu.
    assert r.accident_employer == D("334.00")
    assert r.labour_fund == D("490.00")
    assert r.fgsp == D("20.00")
    assert r.health == D("1628.21")
    assert r.ytd_after.pension_basis == D("282600")
    assert "pension_limit" in r.notes


def test_after_limit_no_pension_contributions() -> None:
    ytd = YearToDate(pension_basis=D("282600"))
    r = calc(title("uop", "20000"), person(), ytd)
    assert r.pension_basis == D("0")
    assert r.pension_employee == r.disability_employee == D("0")
    assert r.sickness_employee == D("490.00")
    assert r.labour_fund == D("490.00")


# ── Ulga dla młodych i 26. urodziny ─────────────────────────────────────────


def test_young_person_paid_before_26th_birthday_is_exempt() -> None:
    young = person(birth_date=date(2000, 11, 15))
    r = calc(title("uop", "7800"), young)
    assert r.tax_kind == "exempt"
    assert r.pit == D("0")
    assert r.exempt_revenue == D("7800.00")
    assert r.kup == D("0")
    assert r.social_employee == D("1069.38")
    assert r.health == D("605.76")
    assert r.net == D("7800") - D("1069.38") - D("605.76")
    assert "relief_youth" in r.notes


def test_26th_birthday_in_month_before_payday_is_taxed() -> None:
    turned = person(birth_date=date(2000, 10, 20), pit2_fraction=12)
    r = calc(title("uop", "7800"), turned)
    assert r.tax_kind == "scale"
    assert r.pit == D("478")
    assert "youth_ended" in r.notes


def test_paid_on_26th_birthday_still_exempt() -> None:
    turned = person(birth_date=date(2000, 11, 10))
    r = calc(title("uop", "7800"), turned)
    assert r.tax_kind == "exempt"


def test_youth_relief_waived_on_request() -> None:
    young = person(birth_date=date(2003, 1, 1), youth_relief_waived=True)
    r = calc(title("uop", "7800"), young)
    assert r.tax_kind == "scale"


def test_relief_limit_crossed_within_month() -> None:
    young = person(birth_date=date(2003, 1, 1), pit2_fraction=12)
    ytd = YearToDate(relief_revenue=D("80000"))
    r = calc(title("uop", "10000"), young, ytd)
    assert r.exempt_revenue == D("5528.00")
    assert r.taxable_revenue == D("4472.00")
    # Składki odliczane w części przypadającej na przychód opodatkowany.
    assert r.social_deductible == D("613.11")
    assert r.kup == D("250.00")
    assert r.tax_base == D("3609")
    assert r.pit == D("133")
    assert r.ytd_after.relief_revenue == D("85528.00")
    assert "relief_limit" in r.notes


def test_family_relief_shares_limit_and_skips_contract_for_work() -> None:
    parent = person(reliefs=frozenset({"family4"}))
    uop = calc(title("uop", "7800"), parent)
    work = calc(title("dzielo", "5000"), parent)
    assert uop.tax_kind == "exempt" and "relief_family4" in uop.notes
    assert work.tax_kind == "scale"


def test_senior_relief_requires_age() -> None:
    early = person(birth_date=date(1964, 1, 1), sex="M", reliefs=frozenset({"senior"}))
    ok = person(birth_date=date(1960, 1, 1), sex="M", reliefs=frozenset({"senior"}))
    assert calc(title("uop", "7800"), early).tax_kind == "scale"
    assert "senior_age_not_reached" in calc(title("uop", "7800"), early).notes
    assert calc(title("uop", "7800"), ok).tax_kind == "exempt"


# ── Zlecenie: student, chorobowa, zbieg, ryczałt ────────────────────────────


def test_student_mandate_without_zus_and_health() -> None:
    student = person(
        birth_date=date(2005, 1, 1), student_exempt_until=date(2027, 6, 30)
    )
    r = calc(title("zlecenie", "3000"), student)
    assert r.social_employee == D("0")
    assert r.health == D("0")
    assert r.employer_social == D("0")
    assert r.pit == D("0")
    assert r.net == D("3000.00")
    assert r.employer_cost == D("3000.00")
    assert "student" in r.notes


def test_student_exemption_ending_mid_month_splits_by_days() -> None:
    student = person(
        birth_date=date(2005, 1, 1), student_exempt_until=date(2026, 10, 15)
    )
    r = calc(title("zlecenie", "3100"), student)
    assert r.insured_gross == D("1600.00")
    assert r.social_employee == D("180.16")
    assert r.health == D("127.79")
    assert "student_partial" in r.notes


def test_26th_birthday_caps_student_exemption() -> None:
    student = person(
        birth_date=date(2000, 10, 16), student_exempt_until=date(2027, 6, 30)
    )
    assert engine.student_exempt_until(student, P) == date(2026, 10, 15)
    r = calc(title("zlecenie", "3100", pay_date=date(2026, 10, 31)), student)
    assert r.insured_gross == D("1600.00")


def test_mandate_with_voluntary_sickness() -> None:
    without = calc(title("zlecenie", "7056"), person())
    with_sickness = calc(title("zlecenie", "7056", sickness_voluntary=True), person())
    assert with_sickness.sickness_employee == D("172.87")
    assert with_sickness.social_employee == without.social_employee + D("172.87")
    assert with_sickness.net < without.net


def test_voluntary_sickness_basis_capped() -> None:
    r = calc(title("zlecenie", "30000", sickness_voluntary=True), person())
    assert r.sickness_basis == D("23550.00")
    assert r.sickness_employee == D("576.98")
    assert "sickness_cap" in r.notes


def test_mandate_other_title_only_health() -> None:
    r = calc(title("zlecenie", "5000", pension_insurance=False), person())
    assert r.social_employee == D("0")
    assert r.health == D("450.00")
    assert r.employer_social == D("0")
    assert "pension_other_title" in r.notes


def test_mandate_up_to_200_is_flat_tax() -> None:
    r = calc(title("zlecenie", "200.00"), person(pit2_fraction=12))
    assert r.tax_kind == "flat"
    assert r.social_employee == D("22.52")
    assert r.health == D("15.97")
    assert r.kup == D("0")
    assert r.tax_base == D("177")
    assert r.pit == D("21")
    assert r.tax_reduction == D("0")
    assert r.net == D("140.51")


def test_mandate_above_200_back_on_scale() -> None:
    r = calc(title("zlecenie", "200.01"), person())
    assert r.tax_kind == "scale"
    assert r.kup == D("35.50")
    assert r.tax_base == D("142")
    assert r.pit == D("17")


def test_no_flat_tax_for_own_employee() -> None:
    r = calc(title("zlecenie", "150", flat_tax_allowed=False), person())
    assert r.tax_kind == "scale"


def test_young_small_mandate_is_exempt_not_flat() -> None:
    r = calc(title("zlecenie", "150"), person(birth_date=date(2004, 1, 1)))
    assert r.tax_kind == "exempt"
    assert r.pit == D("0")


# ── Dzieło ───────────────────────────────────────────────────────────────────


def test_contract_for_work_no_zus_no_health() -> None:
    r = calc(title("dzielo", "5000"), person())
    assert r.social_employee == r.health == r.employer_social == D("0")
    assert r.kup == D("1000.00")
    assert r.tax_base == D("4000")
    assert r.pit == D("480")
    assert r.net == D("4520.00")


# ── PPK ──────────────────────────────────────────────────────────────────────


def test_ppk_contributions_and_taxed_employer_part() -> None:
    member = person(pit2_fraction=12, ppk=Ppk(employee_rate=D("2")))
    r = calc(title("uop", "7800"), member)
    assert r.ppk_employee == D("156.00")
    assert r.ppk_employer == D("117.00")
    assert r.net == D("5646.86") - D("156.00")
    assert r.employer_cost == D("7800") + D("1597.44") + D("117.00")
    later = calc(title("uop", "7800", ppk_employer_taxable=D("117.00")), member)
    assert later.revenue == D("7917.00")
    assert later.tax_base == D("6598")
    assert later.pit == D("492")
    assert later.net == D("7800") - D("1069.38") - D("605.76") - D("492") - D("156.00")


def test_ppk_skipped_for_mandate_without_pension_insurance() -> None:
    member = person(ppk=Ppk(employee_rate=D("2")))
    r = calc(title("zlecenie", "5000", pension_insurance=False), member)
    assert r.ppk_employee == r.ppk_employer == D("0")


# ── Granice wejścia ─────────────────────────────────────────────────────────


def test_zero_gross_gives_zeros() -> None:
    r = calc(title("uop", "0"), person(pit2_fraction=12))
    assert r.net == r.pit == r.employer_cost == r.zus_due == D("0")


def test_unknown_kind_and_bad_period_refused() -> None:
    with pytest.raises(ValueError):
        calc(title("b2b", "100"), person())
    with pytest.raises(ValueError):
        calc(title("uop", "100", work_end=date(2026, 9, 30)), person())
    with pytest.raises(ValueError):
        calc(title("uop", "-1"), person())


def test_rounding_helpers() -> None:
    assert engine.whole(D("0.5")) == D("1")
    assert engine.whole(D("1.49")) == D("1")
    assert engine.pct(D("7056"), D("1.67")) == D("117.84")
    assert engine.birthday(date(2004, 2, 29), 22) == date(2026, 3, 1)


def test_result_json_round_trip_is_text() -> None:
    r = calc(title("uop", "7800"), person(pit2_fraction=12))
    data = r.to_json()
    assert data["net"] == "5646.86"
    assert data["ytd_after"] == {
        "pension_basis": "7800.00",
        "tax_base": "6481",
        "relief_revenue": "0",
    }
    assert isinstance(data["notes"], list)


def test_parameters_change_flows_into_result() -> None:
    higher_accident = replace(P, accident_employer_rate=D("2.00"))
    r = engine.calculate(title("uop", "7800"), person(), YearToDate(), higher_accident)
    assert r.accident_employer == D("156.00")


# ── Raz na miesiąc: kwota zmniejszająca i koszty UoP ────────────────────────


def test_reduction_and_kup_already_used_this_month() -> None:
    p = person(pit2_fraction=12)
    used = calc(title("uop", "7800", reduction_used=D("300"), kup_used=D("250")), p)
    assert used.tax_reduction == D("0")
    assert used.kup == D("0")
    # 7800 − 1069,38 = 6730,62 → 6731 × 12% = 807,72 → 808
    assert used.pit == D("808")
    partial = calc(title("uop", "7800", reduction_used=D("100")), p)
    assert partial.tax_reduction == D("200.00")
    assert partial.pit == D("578")


def test_reduction_never_exceeds_tax_of_the_line() -> None:
    small = calc(title("zlecenie", "1000"), person(pit2_fraction=12))
    assert small.pit == D("0")
    assert small.tax_reduction < D("300")
