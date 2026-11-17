"""Lata w punkcie 1 i daty stanowisk — uwagi QC R2–R3 (17.11.2026), bez bazy."""

from __future__ import annotations

from datetime import date

import pytest

from app.services import cv_finding_dismissals as dismissals
from app.services import cv_qc as qc
from app.services import cv_source_dates
from app.services import cv_tenure_checks as tenure
from app.services import dz_review as dz

TODAY = date(2026, 11, 17)


def _role(title: str, dates: str, employer: str = "Firma Testowa") -> str:
    return (
        f'<p data-cv-section="role"><b>{title}</b> {dates}</p>'
        f'<p data-cv-section="employer">{employer}</p>'
        "<ul><li><p>Utrzymanie systemów.</p></li></ul>"
    )


def _cv(point: str, *roles: str) -> str:
    return (
        "<h1>DevOps Engineer – Jan K.</h1>"
        '<h2 data-cv-section="why_points">Dlaczego nasz kandydat</h2>'
        f"<ul><li><p>{point}</p></li><li><p>Drugi punkt.</p></li></ul>"
        '<h2 data-cv-section="experience">Doświadczenie</h2>' + "".join(roles)
    )


DEVOPS = _cv(
    "Ponad 7 lat doświadczenia w rolach Cloud Operations Engineer i DevOps "
    "Engineer: utrzymanie Azure.",
    _role("Cloud Operations Engineer", "08.2019 – obecnie", "Acme Cloud"),
    _role("Junior L2 Support", "06.2018 – 07.2019", "Beta Serwis"),
)


def _checks(html: str, original: str = "") -> dict[str, dict]:
    data = qc.QcInput(
        must=[],
        nice=[],
        blocks=dz.html_blocks(html),
        has_cv=True,
        bold_known=True,
        original_text=original,
        experience=[],
        job_title="DevOps Engineer",
        today=TODAY,
    )
    return {c["key"]: c for c in qc.compute_checks(data)}


# ── Lata w punkcie 1 ────────────────────────────────────────────────────────


def test_point_one_shows_role_sum_and_whole_tenure_with_a_proposal() -> None:
    check = _checks(DEVOPS)["years_breakdown"]
    assert check["status"] == "fail" and check["severity"] == "warning"
    item = check["items"][0]
    assert item["fix"] == "tenure_split" and item["term"] == "Ponad 7 lat"
    view = item["tenure"]
    # 08.2019 – 11.2026 = 88 mies.; 06.2018 – 07.2019 = 14 mies.; razem 102.
    assert (view["matched_months"], view["total_months"]) == (88, 102)
    assert [(r["title"], r["months"], r["matched"]) for r in view["roles"]] == [
        ("Cloud Operations Engineer", 88, True),
        ("Junior L2 Support", 14, False),
    ]
    assert item["proposal"] == (
        "Ponad 8 lat w IT, w tym ponad 7 lat jako Cloud Operations Engineer"
    )
    assert "7 lat 4 mies." in item["detail"] and "8 lat 6 mies." in item["detail"]
    assert "years_breakdown" not in qc.BLOCKING_KEYS


def test_gap_under_a_year_is_information_not_a_task() -> None:
    html = _cv(
        "Ponad 7 lat doświadczenia jako Cloud Operations Engineer.",
        _role("Cloud Operations Engineer", "08.2019 – obecnie"),
        _role("Stażysta IT", "01.2019 – 06.2019"),
    )
    check = _checks(html)["years_breakdown"]
    assert check["status"] == "pass" and not check["items"]
    info = check["info"][0]
    assert info["fix"] is None and info["proposal"] is None
    assert info["tenure"]["total_months"] - info["tenure"]["matched_months"] < 12


def test_role_without_dates_is_listed_but_not_counted() -> None:
    html = _cv(
        "Ponad 7 lat doświadczenia jako Cloud Operations Engineer.",
        _role("Cloud Operations Engineer", "08.2019 – obecnie"),
        _role("Administrator sieci", ""),
        _role("Technik IT", "01.2016 – 12.2017"),
    )
    view = _checks(html)["years_breakdown"]["items"][0]["tenure"]
    assert view["roles"][1] == {
        "title": "Administrator sieci",
        "dates": None,
        "months": None,
        "matched": False,
    }
    assert view["total_months"] == 88 + 24


def test_ongoing_role_counts_to_this_month_and_overlaps_count_once() -> None:
    html = _cv(
        "5 lat doświadczenia jako Backend Developer.",
        _role("Backend Developer", "01.2022 – obecnie"),
        # Równoległy kontrakt B2B w tym samym czasie nie dokłada stażu.
        _role("Backend Developer", "06.2023 – 12.2024", "Druga Firma"),
        _role("Frontend Developer", "01.2018 – 12.2021"),
    )
    view = _checks(html)["years_breakdown"]["items"][0]["tenure"]
    assert view["matched_months"] == 59  # 01.2022 – 11.2026
    assert view["total_months"] == 48 + 59
    item = _checks(html)["years_breakdown"]["items"][0]
    assert item["proposal"] == (
        "Ponad 8 lat w IT, w tym ponad 4 lata jako Backend Developer"
    )


def test_english_point_gets_an_english_proposal() -> None:
    html = _cv(
        "11 years of experience as an IT Project Manager, leading delivery.",
        _role("IT Project Manager", "01.2015 – obecnie"),
        _role("Business Analyst", "01.2012 – 12.2014"),
    )
    item = _checks(html)["years_breakdown"]["items"][0]
    assert item["proposal"] == (
        "Over 14 years in IT, including over 11 years as IT Project Manager"
    )


def test_point_already_split_does_not_get_a_second_proposal() -> None:
    html = _cv(
        "Ponad 8 lat w IT, w tym ponad 7 lat jako Cloud Operations Engineer.",
        _role("Cloud Operations Engineer", "08.2019 – obecnie"),
        _role("Junior L2 Support", "06.2018 – 07.2019"),
    )
    check = _checks(html)["years_breakdown"]
    assert check["status"] == "pass" and check["info"][0]["proposal"] is None


def test_no_role_named_in_point_one_shows_only_the_whole_tenure() -> None:
    html = _cv(
        "Ponad 5 lat doświadczenia w administracji chmurą.",
        _role("Cloud Operations Engineer", "08.2019 – obecnie"),
    )
    check = _checks(html)["years_breakdown"]
    assert check["status"] == "pass"
    assert check["info"][0]["tenure"]["matched_months"] is None
    assert "żadna rola" in check["info"][0]["detail"]


@pytest.mark.parametrize(
    "html",
    [
        _cv("Doświadczenie w Azure.", _role("Cloud Engineer", "2019 – obecnie")),
        # CV wklejone bez znaczników stanowisk — role tylko zgadywane.
        "<ul><li><p>5 lat doświadczenia jako Tester.</p></li></ul>"
        "<p>Tester 2019 – obecnie</p>",
        _cv("5 lat doświadczenia jako Tester.", _role("Tester", "")),
    ],
)
def test_years_breakdown_skips_without_figure_markers_or_dates(html: str) -> None:
    assert _checks(html)["years_breakdown"]["status"] == "skip"


def test_tenure_split_replaces_only_the_phrase_and_is_not_in_bulk() -> None:
    def run(*, bulk: bool):
        return qc.transform_html(
            DEVOPS,
            [{"action": "tenure_split"}],
            must=[],
            nice=[],
            fixes={},
            experience=[],
            bulk=bulk,
            today=TODAY,
        )

    out, applied, skipped = run(bulk=False)
    assert applied and not skipped
    assert (
        "<p>Ponad 8 lat w IT, w tym ponad 7 lat jako Cloud Operations Engineer: "
        "utrzymanie Azure.</p>"
    ) in out
    assert "Drugi punkt." in out and "08.2019 – obecnie" in out
    # Po poprawce uwaga nie wraca z propozycją.
    assert _checks(out)["years_breakdown"]["status"] == "pass"
    out, applied, skipped = run(bulk=True)
    assert out == DEVOPS and not applied and skipped[0]["code"] == "not_in_bulk"


def test_tenure_split_with_formatting_inside_the_phrase_is_left_to_the_recruiter() -> (
    None
):
    html = DEVOPS.replace("Ponad 7 lat", "<b>Ponad 7 lat</b>")
    out, count = qc.tenure_split_html(html, today=TODAY)
    assert (out, count) == (html, 0)


def test_keep_years_is_a_reason_only_for_the_breakdown() -> None:
    assert dismissals.validate_reason("kept_years", None, check_key="years_breakdown")[
        0
    ] == ("kept_years")
    assert "kept_years" not in dismissals.QC_WRONG_REASONS
    with pytest.raises(dismissals.DismissError):
        dismissals.validate_reason("kept_years", None, check_key="role_order")


def test_breakdown_key_survives_the_next_month() -> None:
    first = _checks(DEVOPS)["years_breakdown"]["items"][0]["key"]
    later = qc.compute_checks(
        qc.QcInput(
            must=[],
            nice=[],
            blocks=dz.html_blocks(DEVOPS),
            has_cv=True,
            bold_known=True,
            original_text="",
            experience=[],
            job_title="DevOps Engineer",
            today=date(2026, 12, 20),
        )
    )
    assert {c["key"]: c for c in later}["years_breakdown"]["items"][0]["key"] == first


# ── Data końca przed datą startu ────────────────────────────────────────────

REVERSED = _cv(
    "Ponad 5 lat doświadczenia jako Tester.",
    _role("Tester", "08.2021 – 09.2019", "Gamma"),
    _role("Tester", "10.2021 – obecnie", "Delta"),
)


def test_reversed_dates_are_a_task_with_the_swapped_period() -> None:
    check = _checks(REVERSED)["role_dates_reversed"]
    assert check["status"] == "fail"
    item = check["items"][0]
    assert (item["fix"], item["role_index"], item["role"]) == (
        "swap_dates",
        0,
        "Tester · Gamma",
    )
    assert (item["term"], item["proposal"]) == (
        "08.2021 – 09.2019",
        "09.2019 – 08.2021",
    )
    # Odwrócona rola nie wchodzi do stażu w punkcie 1.
    roles = _checks(REVERSED)["years_breakdown"]
    view = (roles["items"] or roles["info"])[0]["tenure"]
    assert view["roles"][0]["months"] is None


@pytest.mark.parametrize(
    ("dates", "reversed_"),
    [
        ("05.2021 – 03.2021", True),
        ("2021 – 2019", True),
        ("03.2021 – 2021", False),  # rok bez miesiąca nie przeczy
        ("2021 – 2021", False),
        ("09.2019 – obecnie", False),
        ("2019-03 - 2020-01", False),
    ],
)
def test_reversed_period_rule(dates: str, reversed_: bool) -> None:
    period = cv_source_dates.line_period(f"Tester {dates}")
    assert period is not None and cv_source_dates.is_reversed(period) is reversed_


def test_swap_dates_fixes_one_role_and_keeps_bold() -> None:
    out, applied, skipped = qc.transform_html(
        REVERSED,
        [{"action": "swap_dates", "role_index": 0}],
        must=[],
        nice=[],
        fixes={},
        experience=[],
        bulk=False,
    )
    assert applied and not skipped
    assert "<b>Tester</b> 09.2019 – 08.2021" in out
    assert _checks(out)["role_dates_reversed"]["status"] == "pass"
    out, applied, skipped = qc.transform_html(
        out,
        [{"action": "swap_dates", "role_index": 0}],
        must=[],
        nice=[],
        fixes={},
        experience=[],
        bulk=False,
    )
    assert not applied and skipped[0]["message"] == qc.SWAP_NOTHING


def test_swap_dates_keeps_the_separator_and_year_month_order() -> None:
    period = cv_source_dates.line_period("Tester 2021-08 do 2019-09")
    assert period is not None and tenure.swapped(period) == "2019-09 do 2021-08"


# ── Rola z samym rokiem ─────────────────────────────────────────────────────

YEAR_ONLY = _cv(
    "Ponad 5 lat doświadczenia jako Analityk.",
    _role("Analityk danych", "2021 – obecnie", "Omega Analytics"),
    _role("Młodszy analityk", "2018 – 2020", "Sigma Data"),
)


def test_year_only_role_points_to_months_in_the_original() -> None:
    original = (
        "Analityk danych, Omega Analytics, 04.2021 – obecnie. "
        "Młodszy analityk, Sigma Data, 2018 – 2020."
    )
    check = _checks(YEAR_ONLY, original)["role_year_only"]
    assert check["status"] == "fail" and len(check["items"]) == 1
    item = check["items"][0]
    assert (item["fix"], item["role_index"], item["term"]) == (
        "show_original",
        0,
        "2021 – obecnie",
    )
    assert "„04.2021 – obecnie”" in item["detail"]


def test_year_only_falls_back_to_a_month_in_that_year_anywhere() -> None:
    original = "Doświadczenie: Sigma Data od marca 2018, później April 2020 projekt."
    check = _checks(YEAR_ONLY, original)["role_year_only"]
    items = {i["role_index"]: i for i in check["items"]}
    assert 1 in items and "„marca 2018”" in items[1]["detail"]


def test_year_only_passes_and_skips() -> None:
    assert (
        _checks(YEAR_ONLY, "Analityk 2021 – obecnie, 2018 – 2020")["role_year_only"][
            "status"
        ]
        == "pass"
    )
    assert _checks(YEAR_ONLY, "")["role_year_only"]["status"] == "skip"
    with_months = YEAR_ONLY.replace("2021 – obecnie", "04.2021 – obecnie").replace(
        "2018 – 2020", "01.2018 – 12.2020"
    )
    assert (
        _checks(with_months, "04.2021 – obecnie")["role_year_only"]["status"] == "pass"
    )


def test_new_checks_stay_warnings_in_contract_order() -> None:
    keys = [
        c["key"]
        for c in qc.compute_checks(
            qc.QcInput(
                must=[],
                nice=[],
                blocks=dz.html_blocks(DEVOPS),
                has_cv=True,
                bold_known=True,
                original_text="",
                experience=[],
                job_title="DevOps Engineer",
                today=TODAY,
            )
        )
    ]
    assert keys == [*qc.BLOCKING_KEYS, *qc.WARNING_KEYS]
    assert keys[-3:] == ["years_breakdown", "role_dates_reversed", "role_year_only"]


def test_many_roles_stay_cheap() -> None:
    roles = [
        _role(f"Rola {n}", f"01.{1990 + n % 30} – 12.{1990 + n % 30}")
        for n in range(300)
    ]
    html = _cv("Ponad 5 lat doświadczenia jako Rola 1.", *roles)
    view = _checks(html)["years_breakdown"]
    assert (
        len((view["items"] or view["info"])[0]["tenure"]["roles"])
        == tenure.ROLES_LISTED
    )
