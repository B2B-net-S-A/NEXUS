"""Zgody (0483) — zasady i walidacja bez bazy.

Progi przełożonego per rodzaj, przeliczenie kwoty do progu (netto ×1,23,
co miesiąc ×12, inna waluta = zawsze zatwierdzający), kto decyduje na
którym etapie i kształt wniosku. Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.hr.approvals import rules
from app.services.hr.approvals import service
from app.services.hr.approvals.service import RequestInput

TODAY = date(2026, 10, 20)


def test_missing_or_broken_settings_fall_back_to_default_limits() -> None:
    assert rules.normalize(None).supervisor_limits == rules.DEFAULT_LIMITS
    broken = rules.normalize(
        {"supervisor_limits": {"trip": "dużo", "gift": -5, "other": 800}}
    )
    assert broken.limit_for("trip") == rules.DEFAULT_LIMITS["trip"]
    assert broken.limit_for("gift") == rules.DEFAULT_LIMITS["gift"]
    assert broken.limit_for("other") == 800
    assert broken.final_approver_user_id is None


def test_settings_update_refuses_unknown_kind_and_bad_limit() -> None:
    with pytest.raises(ValueError):
        rules.parse_update({"supervisor_limits": {"car": 100}})
    with pytest.raises(ValueError):
        rules.parse_update({"supervisor_limits": {"trip": 2_000_000}})
    with pytest.raises(ValueError):
        rules.parse_update({"final_approver_user_id": True})
    parsed = rules.parse_update(
        {"final_approver_user_id": 7, "supervisor_limits": {"trip": None}}
    )
    assert parsed.limit_for("trip") is None
    assert parsed.limit_for("gift") == rules.DEFAULT_LIMITS["gift"]
    assert parsed.final_approver_user_id == 7


def test_bonus_and_new_subscription_never_stay_with_the_supervisor() -> None:
    defaults = rules.normalize(None)
    for kind in ("bonus", "subscription"):
        assert not rules.within_supervisor_limit(
            defaults,
            kind,
            Decimal("1"),
            currency="PLN",
            amount_basis="gross",
            recurrence="once",
        )


def test_limit_compares_gross_yearly_pln() -> None:
    limits = rules.ApprovalRules(None, {**rules.DEFAULT_LIMITS, "other": 1200})

    def within(amount: str, **kw) -> bool:
        args = {"currency": "PLN", "amount_basis": "gross", "recurrence": "once"}
        args.update(kw)
        return rules.within_supervisor_limit(limits, "other", Decimal(amount), **args)

    assert within("1200")
    assert not within("1200.01")
    # 1000 netto = 1230 brutto — ponad próg.
    assert not within("1000", amount_basis="net")
    # 100 co miesiąc = 1200 rocznie — na progu; 101 już nie.
    assert within("100", recurrence="monthly")
    assert not within("101", recurrence="monthly")
    # Kwota roczna liczy się tak, jak jest.
    assert within("1200", recurrence="yearly")
    # Inna waluta: bez kursu w NEXUSIE — zawsze zatwierdzający.
    assert not within("1", currency="EUR")


def _spend(**kw) -> RequestInput:
    base = dict(
        kind="trip",
        title="  Wyjazd   do klienta ",
        purpose="Warsztat",
        amount=Decimal("980"),
    )
    base.update(kw)
    return RequestInput(**base)


def test_clean_input_trims_title_and_refuses_bad_values() -> None:
    cleaned = service.clean_input(_spend(), today=TODAY)
    assert cleaned.title == "Wyjazd do klienta"
    assert cleaned.amount == Decimal("980.00")
    for bad in (
        _spend(kind="car"),
        _spend(title="   "),
        _spend(purpose=""),
        _spend(amount=Decimal("0")),
        _spend(amount=Decimal("0.004")),
        _spend(amount=Decimal("NaN")),
        _spend(currency="GBP"),
        _spend(link_url="javascript:alert(1)"),
        _spend(starts_on=date(2026, 10, 23), ends_on=date(2026, 10, 22)),
    ):
        with pytest.raises(service.ApprovalError):
            service.clean_input(bad, today=TODAY)


def test_bonus_needs_person_and_payout_month_in_window() -> None:
    bonus = dict(
        kind="bonus",
        title="Trzy przejęte rekrutacje",
        purpose="Domknęła w 2 tyg.",
        amount=Decimal("1500"),
    )
    with pytest.raises(service.ApprovalError):
        service.clean_input(
            RequestInput(**bonus, payout_year=2026, payout_month=10), today=TODAY
        )
    with pytest.raises(service.ApprovalError):
        service.clean_input(RequestInput(**bonus, beneficiary_user_id=5), today=TODAY)
    for year, month in ((2026, 8), (2027, 1)):
        with pytest.raises(service.ApprovalError):
            service.clean_input(
                RequestInput(
                    **bonus, beneficiary_user_id=5, payout_year=year, payout_month=month
                ),
                today=TODAY,
            )
    cleaned = service.clean_input(
        RequestInput(
            **bonus,
            beneficiary_user_id=5,
            payout_year=2026,
            payout_month=12,
            recurrence="monthly",
            amount_basis="net",
            payer="company_card",
        ),
        today=TODAY,
    )
    # Premia: raz, brutto, bez płatnika — kształt z CHECK-a w bazie.
    assert (cleaned.recurrence, cleaned.amount_basis, cleaned.payer) == (
        "once",
        "gross",
        None,
    )


def _request(**kw) -> SimpleNamespace:
    base = dict(
        requester_user_id=1,
        beneficiary_user_id=None,
        supervisor_user_id=2,
        status="pending_supervisor",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_who_decides_at_each_stage() -> None:
    finals = [9]
    at_supervisor = _request()
    assert service.can_decide(2, at_supervisor, finals)
    assert service.can_decide(
        9, at_supervisor, finals
    )  # zatwierdzający na każdym etapie
    assert not service.can_decide(1, at_supervisor, finals)  # autor
    assert not service.can_decide(3, at_supervisor, finals)
    assert service.deciders_now(at_supervisor, finals) == [2]

    at_final = _request(status="pending_final")
    assert not service.can_decide(2, at_final, finals)
    assert service.can_decide(9, at_final, finals)
    assert service.deciders_now(at_final, finals) == [9]

    for closed in ("approved", "rejected", "returned", "withdrawn"):
        assert not service.can_decide(9, _request(status=closed), finals)
        assert service.deciders_now(_request(status=closed), finals) == []


def test_contract_basis_is_required_for_b2b_and_pending_form_only() -> None:
    assert service.needs_contract_basis("b2b", False) is True
    # Forma „do uzupełnienia” (kartoteka z konta) liczy się jak B2B.
    assert service.needs_contract_basis("uop", True) is True
    assert service.needs_contract_basis("uop", False) is False
    assert service.needs_contract_basis("zlecenie", False) is False


def test_contract_basis_is_a_point_or_annex_number_on_a_bonus() -> None:
    bonus = dict(
        kind="bonus",
        title="Trzy przejęte rekrutacje",
        purpose="Domknęła w 2 tyg.",
        amount=Decimal("1500"),
        beneficiary_user_id=5,
        payout_year=2026,
        payout_month=10,
    )
    cleaned = service.clean_input(
        RequestInput(**bonus, contract_basis="  Aneks nr 3\n z 15.10.2026 "),
        today=TODAY,
    )
    assert cleaned.contract_basis == "Aneks nr 3 z 15.10.2026"
    assert service.clean_input(
        RequestInput(**bonus, contract_basis="  "), today=TODAY
    ).contract_basis is None
    for bad in ("zgodnie z umową", "x" * 199 + "1" * 2):
        with pytest.raises(service.ApprovalError):
            service.clean_input(RequestInput(**bonus, contract_basis=bad), today=TODAY)
    with pytest.raises(service.ApprovalError):
        service.clean_input(_spend(contract_basis="§ 6 umowy"), today=TODAY)


def test_bonus_description_carries_the_contract_basis() -> None:
    assert service.bonus_description(None) == "Premia poza umową"
    assert (
        service.bonus_description("§ 6 ust. 2")
        == "Premia poza umową · podstawa: § 6 ust. 2"
    )
    # B2B i zlecenie: „wynagrodzenie dodatkowe”, nie „premia poza umową” (21.10.2026).
    for form in ("b2b", "zlecenie"):
        assert (
            service.bonus_description("§ 6 ust. 2", form)
            == "Wynagrodzenie dodatkowe · podstawa: § 6 ust. 2"
        )
    assert service.bonus_description(None, "uop") == "Premia poza umową"


def test_nobody_decides_about_own_bonus() -> None:
    bonus = _request(
        status="pending_final", supervisor_user_id=None, beneficiary_user_id=9
    )
    assert not service.can_decide(9, bonus, [9])
    assert service.deciders_now(bonus, [9]) == []


def test_amount_text_reads_like_the_mockup() -> None:
    request = SimpleNamespace(
        amount=Decimal("2880.00"),
        decided_amount=None,
        currency="PLN",
        amount_basis="net",
        recurrence="yearly",
    )
    assert service.amount_text(request) == "2 880 zł netto / rok"
    request.decided_amount = Decimal("1500.50")
    request.amount_basis = "gross"
    request.recurrence = "once"
    assert service.amount_text(request) == "1 500,50 zł brutto"


@pytest.mark.asyncio
async def test_context_months_and_years_start_at_warsaw_midnight() -> None:
    """„NEXUS sprawdził” liczy miesiąc i rok w strefie firmy, jak Finanse
    (audyt 22.10, F103): granice ``decided_at`` to północ w Warszawie, nie
    goła data, którą Postgres rzutuje na północ UTC."""

    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.models.hr_approval import ApprovalRequest

    seen: list[dict] = []

    class _Result:
        def one(self):
            return 0, 0

    class _Db:
        async def execute(self, stmt):
            seen.append(stmt.compile().params)
            return _Result()

    request = ApprovalRequest(kind="training", currency="PLN")
    await service.context_for(
        _Db(), request, today=date(2026, 11, 1), include_bonuses=False
    )
    bounds = {
        value
        for params in seen
        for key, value in params.items()
        if key.startswith("decided_at")
    }
    warsaw = ZoneInfo("Europe/Warsaw")
    expected = {
        datetime(2026, 11, 1, tzinfo=warsaw),
        datetime(2026, 12, 1, tzinfo=warsaw),
        datetime(2026, 1, 1, tzinfo=warsaw),
        datetime(2027, 1, 1, tzinfo=warsaw),
    }
    assert all(isinstance(value, datetime) for value in bounds), bounds
    # Zgoda z 1.11 00:30 w Warszawie (31.10 23:30 UTC) wpada więc do listopada.
    assert bounds == expected
