"""Płace K7a bez bazy: parametry, PESEL, dane osoby, daty listy, liczenie, przelewy.

Dane fikcyjne. PESEL-e w testach składa ``_pesel`` z wymyślonej daty i numeru
serii — nie należą do nikogo.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from app.services.hr.payroll_lists import (
    lists,
    params,
    payslip_pdf,
    person_data,
    pesel,
    sources,
    transfers,
)
from app.services.hr.payroll_lists.engine import YearToDate
from app.services.hr.payroll_lists.person_data import PersonDataError, Subject

WEIGHTS = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)


def _pesel(born: date, serial: int) -> str:
    month = born.month + {1800: 80, 1900: 0, 2000: 20}[born.year // 100 * 100]
    body = f"{born.year % 100:02d}{month:02d}{born.day:02d}{serial:04d}"
    total = sum(int(d) * w for d, w in zip(body, WEIGHTS))
    return body + str((10 - total % 10) % 10)


WOMAN_1990 = _pesel(date(1990, 3, 3), 1240)  # 4. cyfra serii parzysta = kobieta
MAN_2004 = _pesel(date(2004, 7, 21), 5671)


# ── Parametry ────────────────────────────────────────────────────────────────


def test_seed_parses_and_round_trips() -> None:
    parsed = params.parse(params.SEED_2026)
    assert parsed.minimum_wage == D("4806.00")
    assert parsed.youth_age == 26
    assert params.to_json(parsed)["annual_pension_limit"] == "282600.00"


def test_parameters_refuse_missing_unknown_and_out_of_range() -> None:
    values = dict(params.SEED_2026)
    del values["fgsp_rate"]
    with pytest.raises(params.ParamsError, match="FGŚP"):
        params.parse(values)
    with pytest.raises(params.ParamsError, match="Nieznany"):
        params.parse({**params.SEED_2026, "bonus": "1"})
    with pytest.raises(params.ParamsError, match="Wypadkowa"):
        params.parse({**params.SEED_2026, "accident_employer_rate": "11"})
    with pytest.raises(params.ParamsError, match="całkowita"):
        params.parse({**params.SEED_2026, "youth_age": "26.5"})
    with pytest.raises(params.ParamsError, match="Druga stawka"):
        params.parse({**params.SEED_2026, "pit_rate_high": "10"})
    with pytest.raises(params.ParamsError):
        params.parse({**params.SEED_2026, "health_rate": "abc"})


def test_parameters_accept_comma_and_report_diff() -> None:
    changed = params.normalized({**params.SEED_2026, "accident_employer_rate": "1,93"})
    assert changed["accident_employer_rate"] == "1.93"
    diff = params.diff(params.SEED_2026, changed)
    assert [item["key"] for item in diff] == ["accident_employer_rate"]
    assert diff[0]["before"] == "1.67" and diff[0]["after"] == "1.93"
    assert params.diff(params.SEED_2026, params.SEED_2026) == []


# ── PESEL ────────────────────────────────────────────────────────────────────


def test_pesel_checksum_date_and_sex() -> None:
    assert pesel.checksum_ok(WOMAN_1990)
    assert pesel.birth_date(WOMAN_1990) == date(1990, 3, 3)
    assert pesel.sex(WOMAN_1990) == "F"
    assert pesel.birth_date(MAN_2004) == date(2004, 7, 21)
    assert pesel.sex(MAN_2004) == "M"
    old = _pesel(date(1899, 12, 31), 1)
    assert pesel.birth_date(old) == date(1899, 12, 31)


def test_pesel_errors_never_echo_digits() -> None:
    broken = WOMAN_1990[:-1] + str((int(WOMAN_1990[-1]) + 1) % 10)
    for raw in (broken, "1234", "abcdefghijk"):
        with pytest.raises(pesel.PeselError) as exc:
            pesel.clean(raw)
        # Bez numeru w komunikacie: najwyżej liczby z opisu formatu („11 cyfr”).
        assert re.search(r"[0-9]{3,}", exc.value.message) is None
    assert pesel.clean(f" {WOMAN_1990[:5]} {WOMAN_1990[5:]} ") == WOMAN_1990
    assert pesel.clean("") is None
    assert pesel.masked("1234") == "•••••••1234"


# ── Dane osoby ───────────────────────────────────────────────────────────────


def test_person_data_valid_full_record_has_nothing_missing() -> None:
    data, changed = person_data.apply_changes(
        {},
        {
            "pesel": WOMAN_1990,
            "first_name": "Anna",
            "last_name": "Testowa",
            "address": {
                "voivodeship": "mazowieckie",
                "county": "Warszawa",
                "commune": "Warszawa",
                "city": "Warszawa",
                "street": "Testowa",
                "house_number": "1",
                "postal_code": "00-001",
            },
            "tax_office_code": "1471",
            "zus_title_code": "0110 00",
            "pit2": 12,
            "kup": "increased",
            "reliefs": ["family4"],
            "ppk": {
                "participates": True,
                "employee_rate": "2",
                "employer_extra": "0.5",
            },
        },
    )
    assert data["zus_title_code"] == "011000"
    assert data["address"]["country"] == "PL"
    assert "pesel" in changed and "ppk" in changed
    assert person_data.missing_fields(data, contractor=False) == []
    assert person_data.missing_fields(data, contractor=True) == ["bank_account"]
    tax = person_data.person_tax(data, None)
    assert tax.birth_date == date(1990, 3, 3) and tax.sex == "F"
    assert tax.pit2_fraction == 12 and tax.kup_increased
    assert tax.reliefs == frozenset({"family4"})
    assert tax.ppk is not None and tax.ppk.employer_extra == D("0.50")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"tax_office_code": "14A1"}, "4 cyfry"),
        ({"zus_title_code": "01100"}, "6 cyfr"),
        ({"pit2": 6}, "PIT-2"),
        ({"reliefs": ["young"]}, "Ulgi"),
        ({"address": {"postal_code": "00001"}}, "Kod pocztowy"),
        ({"ppk": {"participates": True, "employee_rate": "3"}}, "PPK"),
        ({"bank_account": "123"}, "26 cyfr"),
        ({"document_number": "AB123456"}, "rodzaj dokumentu"),
        ({"sex": "X"}, "Płeć"),
    ],
)
def test_person_data_refusals(changes: dict, message: str) -> None:
    with pytest.raises(PersonDataError, match=message):
        person_data.apply_changes({}, changes)


def test_birth_date_and_sex_must_match_pesel() -> None:
    with pytest.raises(PersonDataError, match="Data urodzenia"):
        person_data.apply_changes({}, {"pesel": WOMAN_1990, "birth_date": "1991-03-03"})
    with pytest.raises(PersonDataError, match="Płeć"):
        person_data.apply_changes({}, {"pesel": WOMAN_1990, "sex": "M"})


def test_foreigner_identity_by_document() -> None:
    data, _ = person_data.apply_changes(
        {},
        {
            "document_type": "passport",
            "document_number": "xy 1234567",
            "birth_date": "1985-01-02",
            "sex": "M",
        },
    )
    assert data["document_number"] == "XY1234567"
    assert "identity" not in person_data.missing_fields(data, contractor=False)
    assert person_data.birth_date_of(data) == date(1985, 1, 2)


def test_clearing_fields_and_no_change() -> None:
    data, _ = person_data.apply_changes({}, {"pit2": 12, "reliefs": ["return"]})
    cleared, changed = person_data.apply_changes(data, {"pit2": 0, "reliefs": []})
    assert "pit2" not in cleared and "reliefs" not in cleared
    assert set(changed) == {"pit2", "reliefs"}
    same, nothing = person_data.apply_changes(cleared, {"pit2": 0})
    assert nothing == [] and same == cleared


def test_missing_fields_order_and_blocking() -> None:
    missing = person_data.missing_fields({}, contractor=True)
    assert missing[:3] == ["identity", "first_name", "last_name"]
    assert person_data.blocks_calculation(missing) == [
        "identity",
        "first_name",
        "last_name",
    ]
    assert "address" in person_data.blocks_files(missing)
    assert "bank_account" not in person_data.blocks_files(missing)


def test_student_exemption_from_team_profile_capped_by_age() -> None:
    data, _ = person_data.apply_changes({}, {"pesel": MAN_2004})
    profile = SimpleNamespace(
        student_contribution_exempt=True, contribution_exempt_until=None
    )
    tax = person_data.person_tax(data, profile)  # type: ignore[arg-type]
    assert tax.student_exempt_until == date(2030, 7, 20)
    contractor, _ = person_data.apply_changes(
        {}, {"pesel": MAN_2004, "student_exempt_until": "2027-09-30"}
    )
    assert person_data.person_tax(contractor, None).student_exempt_until == date(
        2027, 9, 30
    )


def test_payload_masks_pesel_and_hides_birth_date() -> None:
    data, _ = person_data.apply_changes(
        {},
        {
            "pesel": WOMAN_1990,
            "document_type": "id_card",
            "document_number": "ABC123456",
        },
    )
    record = SimpleNamespace(
        pesel_last4=WOMAN_1990[-4:],
        account_last4=None,
        updated_at=None,
        version=3,
    )
    out = person_data.payload(
        Subject(user_id=7),
        "Anna Testowa",
        record,  # type: ignore[arg-type]
        data,
        editable=True,
        today=date(2026, 11, 14),
    )
    text = repr(out)
    assert WOMAN_1990 not in text
    assert "ABC123456" not in text and out["document_masked"] == "•••456"
    assert out["pesel_masked"] == "•••••••" + WOMAN_1990[-4:]
    assert out["birth_date"] is None and out["sex"] is None
    assert out["first_name"] == "Anna" and out["last_name"] == "Testowa"
    assert out["names_confirmed"] is False


def test_subject_needs_exactly_one_key() -> None:
    with pytest.raises(ValueError):
        Subject()
    with pytest.raises(ValueError):
        Subject(user_id=1, candidate_id=2)
    assert Subject(candidate_id=5).key == "c5"


# ── Daty listy ───────────────────────────────────────────────────────────────


def test_default_pay_date_and_bounds() -> None:
    assert lists.default_pay_date(2026, 10, 10) == date(2026, 11, 10)
    assert lists.default_pay_date(2027, 1, 31) == date(2027, 2, 28)
    assert lists.default_pay_date(2026, 12, 10) == date(2027, 1, 10)
    assert lists.check_pay_date(2026, 10, date(2026, 10, 31)) == date(2026, 10, 31)
    with pytest.raises(lists.PayrollError):
        lists.check_pay_date(2026, 10, date(2026, 9, 30))
    with pytest.raises(lists.PayrollError):
        lists.check_pay_date(2026, 10, date(2027, 1, 1))


def test_deadlines_follow_pay_month_and_skip_weekend() -> None:
    out = lists.deadlines(date(2026, 11, 10))
    assert out["declaration_month"] == "2026-11"
    assert out["zus"] == "2026-12-15"
    # 20.12.2026 to niedziela.
    assert out["pit"] == "2026-12-21"


# ── Liczenie listy bez bazy ──────────────────────────────────────────────────


def _prepared(sources_list, persons, *, ytd=None, ppk=None) -> lists.Prepared:
    period = SimpleNamespace(id=1, year=2026, month=10, close_count=1, status="closed")
    version = SimpleNamespace(
        id=1,
        status="confirmed",
        effective_from=date(2026, 1, 1),
        params=params.SEED_2026,
    )
    return lists.Prepared(
        period=period,  # type: ignore[arg-type]
        pay_date=date(2026, 11, 10),
        version=version,  # type: ignore[arg-type]
        params=params.SEED_PARAMS,
        gathered=sources.Gathered(sources=sources_list, skipped=[], problems=[]),
        persons=persons,
        ytd=ytd or {},
        ppk=ppk or {},
    )


def _src(key: str, person: str, kind: str, gross: str | None, **kw) -> sources.Source:
    return sources.Source(
        key=key,
        person_key=person,
        name=kw.pop("name", "Osoba Testowa"),
        kind=kind,
        source=kw.pop("source", "payroll_line"),
        gross=None if gross is None else D(gross),
        **kw,
    )


FULL = {
    "pesel": WOMAN_1990,
    "first_name": "Anna",
    "last_name": "Testowa",
    "pit2": 12,
}


def test_calculate_flows_year_state_and_flags_own_employer_mandate() -> None:
    prepared = _prepared(
        [
            _src("u1:uop", "u1", "uop", "7800", user_id=1),
            _src("u1:zlecenie", "u1", "zlecenie", "150", user_id=1),
        ],
        {"u1": FULL},
        ytd={"u1": YearToDate(pension_basis=D("100"))},
        ppk={"u1": D("117.00")},
    )
    computed = lists.calculate(prepared)
    uop, mandate = computed
    assert uop.result is not None and uop.result.ppk_employer_taxable == D("117.00")
    assert mandate.result is not None and mandate.result.ppk_employer_taxable == D("0")
    # Pracownik płatnika — bez ryczałtu do 200 zł.
    assert mandate.result.tax_kind == "scale"
    assert mandate.result.ytd_after.pension_basis == D("100") + D("7800") + D("150")
    assert "mandate_own_employer" in mandate.problems
    assert "files_data" in uop.problems
    block = lists.blocking_problems(prepared, computed)
    assert [p["code"] for p in block] == ["mandate_own_employer"]


def test_calculate_without_person_data_blocks_but_still_shows_numbers() -> None:
    prepared = _prepared(
        [_src("k9", "c9", "zlecenie", "7056", candidate_id=9, contract_id=9)], {}
    )
    (line,) = lists.calculate(prepared)
    assert line.result is not None and line.result.net == D("5096.96")
    assert "person_data_missing" in line.problems
    assert lists.blocking(line.problems[0])


def test_calculate_missing_gross_has_no_result() -> None:
    item = _src(
        "k3", "c3", "zlecenie", None, candidate_id=3, contract_id=3, source="missing"
    )
    item.problems.append("gross_missing")
    (line,) = lists.calculate(_prepared([item], {"c3": FULL}))
    assert line.result is None
    assert "gross_missing" in line.problems


def test_totals_split_scale_and_flat_tax() -> None:
    prepared = _prepared(
        [
            _src("u1:uop", "u1", "uop", "7800", user_id=1),
            _src("k2", "c2", "zlecenie", "200", candidate_id=2, contract_id=2),
        ],
        {"u1": FULL, "c2": {**FULL, "pesel": _pesel(date(1980, 1, 1), 33)}},
    )
    totals = lists.totals_of(lists.calculate(prepared), date(2026, 11, 10))
    assert totals["people"] == 2 and totals["lines"] == 2
    assert totals["pit_flat"] == "21"
    assert totals["pit_scale"] == "478"
    assert totals["by_kind"]["uop"]["gross"] == "7800.00"
    assert totals["deadlines"]["pit"] == "2026-12-21"


def test_source_fingerprint_changes_with_amount() -> None:
    first = _src("u1:uop", "u1", "uop", "7800", user_id=1)
    second = _src("u1:uop", "u1", "uop", "7800.01", user_id=1)
    assert first.fingerprint() != second.fingerprint()


# ── Przelewy i paski ─────────────────────────────────────────────────────────


def test_tax_transfer_title_format() -> None:
    lines = transfers.tax_title("5711707392", date(2026, 11, 10), "PIT4R", "LP/2026/10")
    assert "".join(lines) == "/TI/N5711707392/OKR/26M11/SFP/PIT4R/TXT/LP/2026/10"
    assert all(len(line) <= 35 for line in lines)


def test_transfer_sums_split_by_tax_kind() -> None:
    lines = [
        SimpleNamespace(result={"zus_due": "100.00", "pit": "50", "tax_kind": "scale"}),
        SimpleNamespace(result={"zus_due": "10.00", "pit": "21", "tax_kind": "flat"}),
        SimpleNamespace(result={}),
    ]
    out = transfers.sums(lines)  # type: ignore[arg-type]
    assert out == {"zus": D("110.00"), "pit4": D("50"), "pit8ar": D("21")}


def test_payslip_html_has_draft_mark_and_no_identifiers() -> None:
    slip = payslip_pdf.Payslip(
        list_number="LP/2026/10",
        year=2026,
        month=10,
        pay_date=date(2026, 11, 10),
        approved=False,
        person_name="Osoba Testowa",
        kind="uop",
        source_label="„Mój miesiąc” i premie",
        basis={"hours": "168", "hourly_rate": "46.43", "hours_amount": "7800.24"},
        result={
            "gross": "7800.00",
            "net": "5646.86",
            "pit": "478",
            "tax_kind": "scale",
            "notes": ["tax_reduction"],
        },
    )
    html = payslip_pdf.render_html([slip])
    assert "PROJEKT" in html
    assert "5 646,86 zł" in html
    assert "Kwota zmniejszająca z PIT-2." in html
    approved = payslip_pdf.render_html(
        [slip.__class__(**{**slip.__dict__, "approved": True})]
    )
    assert "PROJEKT" not in approved
    assert payslip_pdf.filename("LP/2026/10") == "paski-lp-2026-10.pdf"


def test_nfz_branch_from_voivodeship_or_explicit() -> None:
    data, _ = person_data.apply_changes(
        {}, {"address": {"voivodeship": "Mazowieckie", "city": "Testowo"}}
    )
    assert person_data.nfz_code_of(data) == "07R"
    explicit, _ = person_data.apply_changes(data, {"nfz_code": "12r"})
    assert person_data.nfz_code_of(explicit) == "12R"
    assert person_data.nfz_code_of({}) is None
    with pytest.raises(PersonDataError, match="NFZ"):
        person_data.apply_changes({}, {"nfz_code": "17R"})


def test_work_time_fraction() -> None:
    assert person_data.work_time_of({}) == (1, 1)
    half, changed = person_data.apply_changes({}, {"work_time": "1/2"})
    assert person_data.work_time_of(half) == (1, 2) and changed == ["work_time"]
    full, _ = person_data.apply_changes(half, {"work_time": "1/1"})
    assert "work_time" not in full
    with pytest.raises(PersonDataError, match="etatu"):
        person_data.apply_changes({}, {"work_time": "3/2"})


# ── Mapowanie na pliki KEDU i PIT ────────────────────────────────────────────


def _regon() -> str:
    body = "12345678"
    total = sum(int(d) * w for d, w in zip(body, (8, 9, 2, 3, 4, 5, 6, 7))) % 11
    return body + str(total % 10)


def test_engine_results_render_into_kedu_month() -> None:
    from app.services.hr.payroll_lists import documents, kedu
    from app.services.hr.payroll_lists.engine import Title, calculate

    data, _ = person_data.apply_changes(
        {},
        {
            "pesel": WOMAN_1990,
            "first_name": "Anna",
            "last_name": "Testowa",
            "zus_title_code": "011000",
        },
    )
    result = calculate(
        Title(
            kind="uop",
            gross=D("7800"),
            work_start=date(2026, 10, 1),
            work_end=date(2026, 10, 31),
            pay_date=date(2026, 11, 10),
        ),
        person_data.person_tax(data, None),
        YearToDate(),
        params.SEED_PARAMS,
    )
    insured = kedu.KeduInsured(
        person=documents.kedu_person(data),
        title_code="011000",
        pension_basis=result.pension_basis,
        sickness_basis=result.sickness_basis,
        accident_basis=result.accident_basis,
        pension_employee=result.pension_employee,
        disability_employee=result.disability_employee,
        sickness_employee=result.sickness_employee,
        pension_employer=result.pension_employer,
        disability_employer=result.disability_employer,
        accident_employer=result.accident_employer,
        health_basis=result.health_basis,
        health=result.health,
        work_time=person_data.work_time_of(data),
    )
    xml = kedu.render_month(
        kedu.KeduMonth(
            year=2026,
            month=11,
            payer=kedu.KeduPayer(
                nip="5711707392", regon=_regon(), short_name="FIRMA TEST"
            ),
            insured=[insured],
            labour_fund=result.labour_fund,
            fgsp=result.fgsp,
            accident_rate=D("1.67"),
            created_on=date(2026, 12, 1),
        )
    )
    text = xml.decode("utf-8")
    assert "ZUSDRA" in text and "ZUSRCA" in text
    assert WOMAN_1990 in text  # pełny PESEL tylko w pliku dla ZUS
    assert "761.28" in text and "191.10" in text


def test_registration_items_skip_employee_termination() -> None:
    from app.services.hr.payroll_lists import documents, registrations

    data, _ = person_data.apply_changes(
        {},
        {
            "pesel": MAN_2004,
            "first_name": "Jan",
            "last_name": "Testowy",
            "zus_title_code": "041100",
            "address": {
                "voivodeship": "mazowieckie",
                "city": "Testowo",
                "postal_code": "00-001",
                "house_number": "1",
            },
        },
    )
    start = registrations.RegistrationEvent(
        "ZUA", "c1", None, 1, 1, "Jan Testowy", "zlecenie", date(2026, 11, 3), data, []
    )
    item, reason = documents.registration_item(start)
    assert reason is None and item is not None
    assert item.nfz_code == "07R" and item.sickness is False and item.pension is True
    end = registrations.RegistrationEvent(
        "ZWUA",
        "c1",
        None,
        1,
        1,
        "Jan Testowy",
        "zlecenie",
        date(2026, 11, 30),
        data,
        [],
    )
    item, _ = documents.registration_item(end)
    assert item is not None and item.date_from == date(2026, 12, 1)
    assert item.reason_code == "100"
    employee_end = registrations.RegistrationEvent(
        "ZWUA", "u1", 1, None, None, "Jan Testowy", "uop", date(2026, 11, 30), data, []
    )
    item, reason = documents.registration_item(employee_end)
    assert item is None and "e-Płatniku" in (reason or "")
    missing = registrations.RegistrationEvent(
        "ZUA",
        "c2",
        None,
        2,
        2,
        "Bez Danych",
        "zlecenie",
        date(2026, 11, 3),
        {},
        ["identity"],
    )
    item, reason = documents.registration_item(missing)
    assert item is None and "PESEL" in (reason or "")


def test_pit11_person_and_opening_entries() -> None:
    from app.services.hr.payroll_lists import documents, pit_forms

    data, _ = person_data.apply_changes(
        {},
        {
            "pesel": WOMAN_1990,
            "first_name": "Anna",
            "last_name": "Testowa",
            "tax_office_code": "1471",
            "address": {
                "voivodeship": "mazowieckie",
                "county": "Testowo",
                "commune": "Testowo",
                "city": "Testowo",
                "postal_code": "00-001",
                "house_number": "1",
            },
        },
    )
    person = documents.pit11_person(data)
    assert person.birth_date == date(1990, 3, 3) and person.nip is None
    assert documents.pit11_missing(data, False) == []
    assert (
        documents.pit11_missing(
            {**data, "pesel": None, "document_type": "passport"}, False
        )[-1]
        == "nip"
    )
    entries = documents._opening_entries(
        {
            "uop_revenue": "50000",
            "uop_kup": "2500",
            "uop_social": "6855",
            "uop_advance": "3000",
            "uop_exempt": "0",
        }
    )
    assert len(entries) == 1 and entries[0].kind == "uop"
    assert entries[0].social_deductible == D("6855")
    amounts = pit_forms.pit11_amounts(entries)
    xml = pit_forms.render_pit11(
        2026,
        pit_forms.TaxPayer(
            nip="5711707392", full_name="Firma Testowa S.A.", tax_office_code="1471"
        ),
        person,
        amounts,
    )
    assert b"PIT-11" in xml


def test_number_fields_accept_any_type_without_echo() -> None:
    with pytest.raises(pesel.PeselError) as exc:
        pesel.clean(12345678901)
    assert "12345678901" not in exc.value.message
    data, _ = person_data.apply_changes(
        {}, {"document_type": "passport", "document_number": 123456789}
    )
    assert data["document_number"] == "123456789"


def test_payslip_pdf_renders_when_weasyprint_available() -> None:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        pytest.skip("WeasyPrint bez bibliotek systemowych (pango)")
    slip = payslip_pdf.Payslip(
        list_number="LP/2026/10",
        year=2026,
        month=10,
        pay_date=date(2026, 11, 10),
        approved=True,
        person_name="Osoba Testowa",
        kind="zlecenie",
        source_label="rozliczenie klienta",
        basis={},
        result={
            "gross": "7056.00",
            "net": "5096.96",
            "pit": "601",
            "tax_kind": "scale",
        },
    )
    assert payslip_pdf.render_pdf([slip], employer=True).startswith(b"%PDF")


def test_two_mandates_of_one_person_share_one_monthly_reduction() -> None:
    contractor = {**FULL, "pesel": _pesel(date(1980, 1, 1), 33)}
    prepared = _prepared(
        [
            _src("k1", "c5", "zlecenie", "3000", candidate_id=5, contract_id=1),
            _src("k2", "c5", "zlecenie", "3000", candidate_id=5, contract_id=2),
        ],
        {"c5": contractor},
    )
    first, second = lists.calculate(prepared)
    assert first.result is not None and second.result is not None
    total = first.result.tax_reduction + second.result.tax_reduction
    assert total == D("300.00")
    assert first.result.pit == D("0") and second.result.pit == D("211")


def test_month_state_from_other_lists_blocks_second_reduction() -> None:
    prepared = _prepared(
        [_src("u1:uop", "u1", "uop", "7800", user_id=1)],
        {"u1": FULL},
    )
    prepared.month = {
        "u1": sources.MonthState(reduction_used=D("300"), kup_used=D("250"))
    }
    (line,) = lists.calculate(prepared)
    assert line.result is not None
    assert line.result.tax_reduction == D("0") and line.result.kup == D("0")


def test_fund_equivalent_from_input_or_partial_employment() -> None:
    first, last = date(2026, 10, 1), date(2026, 10, 31)
    manual = _src("u1:uop", "u1", "uop", "3000", user_id=1, source="manual")
    manual.fund_basis = D("6000")
    assert lists.fund_equivalent(manual, None, first, last) == D("6000")
    started = SimpleNamespace(
        work_start_date=date(2026, 10, 16), hired_on=None, last_working_day=None
    )
    half = _src("u2:uop", "u2", "uop", "2400", user_id=2)
    assert lists.fund_equivalent(half, started, first, last) == D("4650.00")
    full = SimpleNamespace(
        work_start_date=date(2025, 1, 1), hired_on=None, last_working_day=None
    )
    assert lists.fund_equivalent(half, full, first, last) == D("2400")
    mandate = _src("u3:zlecenie", "u3", "zlecenie", "2400", user_id=3)
    assert lists.fund_equivalent(mandate, started, first, last) == D("2400")


def test_labour_fund_paid_for_half_month_with_full_month_equivalent() -> None:
    item = _src("u1:uop", "u1", "uop", "3000", user_id=1, source="manual")
    item.fund_basis = D("6000")
    (line,) = lists.calculate(_prepared([item], {"u1": FULL}))
    assert line.result is not None
    assert line.result.labour_fund == D("73.50")


async def test_ppk_due_survives_a_month_without_payout(monkeypatch) -> None:
    """Lista 10 wypłacona 31.10, lista 11 dopiero 10.12 — PPK z października
    wchodzi w grudniu, a zaległa wpłata z Enovy z otwarcia roku też się liczy."""

    october = SimpleNamespace(
        user_id=1,
        candidate_id=None,
        candidate_ref=None,
        person_name="Osoba Testowa",
        result={"ppk_employer": "117.00", "ppk_employer_taxable": "0"},
    )

    async def fake_lines(db, first, last, exclude_list_id):
        return [october] if first <= date(2026, 10, 31) <= last else []

    opening = SimpleNamespace(
        user_id=2,
        candidate_id=None,
        candidate_ref=None,
        amounts={"ppk_employer_pending": "90.50"},
    )

    class FakeDb:
        async def scalars(self, _query):
            return [opening]

    monkeypatch.setattr(sources, "_approved_lines_between", fake_lines)
    due = await sources.ppk_employer_due(
        FakeDb(),  # type: ignore[arg-type]
        pay=date(2026, 12, 10),
        exclude_list_id=None,
    )
    assert due["u1"] == (D("117.00"), "Osoba Testowa")
    assert due["u2"][0] == D("90.50")
    october.result["ppk_employer_taxable"] = "117.00"
    due_after = await sources.ppk_employer_due(
        FakeDb(),  # type: ignore[arg-type]
        pay=date(2026, 12, 10),
        exclude_list_id=None,
    )
    assert "u1" not in due_after
