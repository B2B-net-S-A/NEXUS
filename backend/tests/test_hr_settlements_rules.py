"""Rozliczenia zespołu — reguły bez bazy: terminy, problemy, słowa stanu, pozycje.

Dane fikcyjne. Przypadki brzegowe: luty i grudzień przy dniu wypłaty, zła
wartość w ustawieniach, różnica jednego grosza, rachunek bez źródła, suma
pozycji „Do faktury” równa linii płac co do grosza.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.hr_payroll import HrBonus
from app.services.hr import billing_details, settlements_rules as rules
from app.services.hr.settlements_items import build_items
from tests.hr_settlements_seed import fake_account


@pytest.mark.parametrize(
    ("year", "month", "day", "expected"),
    [
        (2026, 10, 10, date(2026, 11, 10)),
        (2026, 12, 10, date(2027, 1, 10)),  # grudzień → styczeń następnego roku
        (2027, 1, 31, date(2027, 2, 28)),  # 31. w lutym = ostatni dzień miesiąca
        (2028, 1, 31, date(2028, 2, 29)),  # rok przestępny
        (2026, 10, "zły", date(2026, 11, 10)),  # zła wartość → domyślny 10.
        (2026, 10, 0, date(2026, 11, 10)),
        (2026, 10, 32, date(2026, 11, 10)),
        (2026, 10, True, date(2026, 11, 10)),
    ],
)
def test_payout_date_is_day_of_next_month(year, month, day, expected) -> None:
    assert rules.payout_date(year, month, day) == expected


def test_invoice_due_counts_from_ksef_number_day() -> None:
    assert rules.invoice_due_date(date(2026, 11, 4), 14) == date(2026, 11, 18)
    assert rules.invoice_due_date(date(2026, 11, 4), None) == date(2026, 11, 18)
    assert rules.invoice_due_date(date(2026, 12, 20), 30) == date(2027, 1, 19)
    assert rules.invoice_due_date(date(2026, 11, 4), 0) == date(2026, 11, 4)


def test_one_grosz_is_a_problem_and_zero_is_not() -> None:
    assert rules.problems_of(
        employment_type="b2b", discrepancy=Decimal("0.01"), account_source="white_list"
    ) == ("amount",)
    assert rules.problems_of(
        employment_type="b2b", discrepancy=Decimal("-0.01"), account_source="white_list"
    ) == ("amount",)
    assert (
        rules.problems_of(
            employment_type="b2b",
            discrepancy=Decimal("0.00"),
            account_source="white_list",
        )
        == ()
    )


def test_account_outside_white_list_or_missing_needs_second_person() -> None:
    for source in ("manual", None):
        assert rules.problems_of(
            employment_type="b2b", discrepancy=Decimal("0"), account_source=source
        ) == ("white_list",)
    # Zlecenie i UoP nie mają faktury ani białej listy.
    assert (
        rules.problems_of(
            employment_type="zlecenie", discrepancy=Decimal("5"), account_source=None
        )
        == ()
    )


def test_override_kind_prefers_amount() -> None:
    assert rules.override_kind_for(("amount", "white_list")) == "amount"
    assert rules.override_kind_for(("white_list",)) == "white_list"
    assert rules.override_kind_for(()) is None


def test_status_words_follow_the_form() -> None:
    assert rules.status_label("ready", "b2b") == "Zgodna"
    assert rules.status_label("approved", "b2b") == "Do zapłaty"
    assert rules.status_label("ready", "zlecenie") == "Kwota policzona"
    assert rules.status_label("approved", "uop") == "Przekazano do listy płac"
    assert rules.status_label("paid", "zlecenie") == "Wypłacono"
    assert rules.initial_status("b2b") == "awaiting_document"
    assert rules.initial_status("zlecenie") == "ready"
    assert rules.amount_basis("b2b") == "net" and rules.amount_basis("uop") == "gross"


def test_net_total_sums_original_and_corrections() -> None:
    assert rules.net_total([Decimal("14540.00"), Decimal("-120.00")]) == Decimal(
        "14420.00"
    )
    assert rules.net_total([]) == Decimal("0.00")


def _bonus(amount: str, bonus_id: int = 1) -> HrBonus:
    return HrBonus(
        id=bonus_id,
        recipient_user_id=1,
        amount=Decimal(amount),
        currency="PLN",
        category="recruiter",
        period_year=2026,
        period_month=10,
        status="assigned",
        description="Placement: Data Engineer",
    )


def test_b2b_items_split_paid_days_and_sum_to_the_line() -> None:
    # 168 h, z czego 8 h to płatny dzień przerwy; stawka z groszami, żeby dwa
    # zaokrąglenia mogły się rozjechać — suma ma zostać co do grosza.
    hours, rate = Decimal("168.00"), Decimal("95.33")
    hours_amount = (hours * rate).quantize(Decimal("0.01"))
    items = build_items(
        employment_type="b2b",
        year=2026,
        month=10,
        hours=hours,
        hourly_rate=rate,
        hours_amount=hours_amount,
        paid_break_hours=Decimal("8"),
        paid_break_days=1,
        bonuses=[_bonus("1200.00")],
    )
    assert [item.kind for item in items] == ["hours", "paid_days", "bonus"]
    assert items[0].hours == Decimal("160.00")
    assert "1 dzień" in items[1].label
    assert sum(item.amount for item in items) == hours_amount + Decimal("1200.00")


def test_mandate_has_no_paid_days_and_no_hours_without_rate() -> None:
    items = build_items(
        employment_type="zlecenie",
        year=2026,
        month=10,
        hours=Decimal("92"),
        hourly_rate=Decimal("32.00"),
        hours_amount=Decimal("2944.00"),
        paid_break_hours=Decimal("8"),
        paid_break_days=1,
        bonuses=[],
    )
    assert [item.kind for item in items] == ["hours"]
    assert items[0].amount == Decimal("2944.00")
    assert (
        build_items(
            employment_type="b2b",
            year=2026,
            month=10,
            hours=Decimal("10"),
            hourly_rate=None,
            hours_amount=None,
            paid_break_hours=Decimal("0"),
            paid_break_days=0,
            bonuses=[_bonus("500.00")],
        )[0].kind
        == "bonus"
    )


def _fake_pesel(prefix: str = "9912317654") -> str:
    """Zmyślone 10 cyfr + cyfra kontrolna PESEL-u (nie jest niczyim numerem)."""

    weights = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
    total = sum(int(d) * w for d, w in zip(prefix, weights))
    return prefix + str((10 - total % 10) % 10)


_PESEL = _fake_pesel()
_NOT_PESEL = _PESEL[:-1] + str((int(_PESEL[-1]) + 1) % 10)


@pytest.mark.parametrize(
    ("value", "pesel"),
    [(_PESEL, True), (_NOT_PESEL, False), ("1234", False), ("A1B2C3", False)],
)
def test_pesel_is_recognised_and_refused_as_symfonia_id(value, pesel) -> None:
    assert billing_details.looks_like_pesel(value) is pesel
    if pesel:
        with pytest.raises(billing_details.BillingError):
            billing_details.clean_symfonia_id(value)
    elif value.isalnum():
        assert billing_details.clean_symfonia_id(value) == value


def test_symfonia_id_accepts_guid_and_rejects_spaces() -> None:
    guid = "{3F2504E0-4F89-11D3-9A0C-0305E82C3301}"
    assert billing_details.clean_symfonia_id(f"  {guid} ") == guid
    assert billing_details.clean_symfonia_id("") is None
    with pytest.raises(billing_details.BillingError):
        billing_details.clean_symfonia_id("ma spację")


def test_bad_account_message_never_echoes_the_number() -> None:
    good = fake_account()
    bad = good[:-1] + str((int(good[-1]) + 1) % 10)  # suma kontrolna się nie zgadza
    with pytest.raises(billing_details.BillingError) as caught:
        billing_details.clean_account(f"PL {bad}")
    assert bad[-8:] not in str(caught.value.detail)
    assert caught.value.__cause__ is None
    assert billing_details.clean_account(f"PL{good[:2]} {good[2:]}") == good


# ── Po przeglądzie (17/18.10): zgodność po netto, płatność po brutto ──────────


def _amounts(*rows: tuple[str, str, str]) -> list[tuple[Decimal, Decimal, Decimal]]:
    return [tuple(Decimal(value) for value in row) for row in rows]


def test_brutto_musi_wynikac_z_netto_i_vat_co_do_grosza() -> None:
    assert not rules.gross_problem(
        _amounts(("16400.00", "3772.00", "20172.00")), vat_status="active"
    )
    # P_15 podmienione — netto się zgadza, do zapłaty poszłoby brutto.
    assert rules.gross_problem(
        _amounts(("16400.00", "3772.00", "201720.00")), vat_status="active"
    )
    assert not rules.gross_problem(
        _amounts(("100.00", "23.00", "123.01")), vat_status="active"
    )
    assert rules.gross_problem(
        _amounts(("100.00", "23.00", "123.02")), vat_status="active"
    )
    assert not rules.gross_problem([], vat_status=None)


def test_vat_najwyzej_23_procent_i_tylko_u_czynnego_podatnika() -> None:
    assert rules.gross_problem(
        _amounts(("100.00", "24.00", "124.00")), vat_status="active"
    )
    for status in ("exempt", "unregistered", None):
        assert rules.gross_problem(
            _amounts(("100.00", "23.00", "123.00")), vat_status=status
        )
        assert not rules.gross_problem(
            _amounts(("100.00", "0.00", "100.00")), vat_status=status
        )
    # Korekta znosi VAT faktury pierwotnej — liczy się suma.
    assert not rules.gross_problem(
        _amounts(("100.00", "23.00", "123.00"), ("-100.00", "-23.00", "-123.00")),
        vat_status="exempt",
    )


def test_problem_brutto_dziala_jak_roznica_kwoty() -> None:
    assert rules.problems_of(
        employment_type="b2b",
        discrepancy=Decimal("0.00"),
        account_source="white_list",
        gross_issue=True,
    ) == ("gross",)
    assert (
        rules.problems_of(
            employment_type="zlecenie",
            discrepancy=None,
            account_source=None,
            gross_issue=True,
        )
        == ()
    )
    assert rules.override_kind_for(("gross", "white_list")) == "amount"


def test_uznanie_rachunku_nie_obejmuje_problemu_z_kwota() -> None:
    assert rules.override_covers("amount", ("amount", "gross", "white_list"))
    assert rules.override_covers("white_list", ("white_list",))
    assert not rules.override_covers("white_list", ("gross", "white_list"))
    assert not rules.override_covers("white_list", ("amount",))
    assert not rules.override_covers(None, ())
