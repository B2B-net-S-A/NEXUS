"""Płace — poprawki po audycie A2 (19.10.2026), testy bez bazy.

* nowa stawka domyka tylko stawkę trwającą w jej dniu (luka z importu
  Compassa zostaje luką, a nie wypełnia się starą stawką),
* kwoty premii i stawek zaokrąglane HALF_UP (jak raport płac), zakres
  sprawdzany na wyniku zaokrąglenia — 0,004 to błąd 422, a nie 500 z CHECK-a,
* logi automatu premii niosą klasę wyjątku, nie treść: DETAIL Postgresa
  („Failing row contains (…)”) pokazuje kwoty z wiersza.

Dane fikcyjne.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from app.api import hr_payroll as hr_payroll_api
from app.models.hr_payroll import EmployeeRate
from app.services.hr import job_runs, payroll_jobs, placement_bonuses
from app.services.hr.modules import HrModule
from app.services.hr.payroll_access import PayrollViewer
from app.services.hr.payroll_bonuses import clean_amount
from app.services.hr.payroll_errors import PayrollError
from app.services.hr.payroll_rates import rate_to_close, validate_rate

SECRET_AMOUNT = "1234.56"


def _integrity_error() -> IntegrityError:
    return IntegrityError(
        "INSERT INTO hr_bonuses (amount) VALUES ($1)",
        {"amount": SECRET_AMOUNT},
        Exception(
            'new row violates check constraint "ck_hr_bonuses_amount"\n'
            f"DETAIL:  Failing row contains (1, {SECRET_AMOUNT}, PLN)."
        ),
    )


class _FakeDb:
    """Sesja na tyle, na ile dotykają jej ścieżki błędów automatu premii."""

    def __init__(self, scalar: Any = None, row: Any = None) -> None:
        self._scalar = scalar
        self._row = row
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def scalar(self, *_args, **_kwargs) -> Any:
        return self._scalar

    async def execute(self, *_args, **_kwargs) -> Any:
        row = self._row

        class _Result:
            def one(self) -> Any:
                return row

            def first(self) -> Any:
                return row

        return _Result()

    @asynccontextmanager
    async def begin_nested(self):
        yield self


async def _payroll_module_on(_db) -> dict:
    return {HrModule.payroll: True}


async def _raise_integrity(*_args, **_kwargs):
    raise _integrity_error()


# ── 1. Luka w historii stawek ─────────────────────────────────────────────────


def _rate(start: date, end: date | None) -> EmployeeRate:
    return EmployeeRate(
        user_id=1,
        hourly_rate=Decimal("100.00"),
        currency="PLN",
        effective_from=start,
        effective_to=end,
    )


def test_new_rate_after_gap_does_not_close_old_rate() -> None:
    ended = _rate(date(2026, 1, 1), date(2026, 3, 31))
    assert rate_to_close([ended], date(2026, 6, 1)) is None


def test_new_rate_closes_open_or_overlapping_rate() -> None:
    open_rate = _rate(date(2026, 1, 1), None)
    assert rate_to_close([open_rate], date(2026, 6, 1)) is open_rate
    planned_end = _rate(date(2026, 1, 1), date(2026, 8, 31))
    assert rate_to_close([planned_end], date(2026, 6, 1)) is planned_end
    # Koniec dokładnie w dniu nowej stawki też ją pokrywa.
    same_day = _rate(date(2026, 1, 1), date(2026, 6, 1))
    assert rate_to_close([same_day], date(2026, 6, 1)) is same_day


def test_only_latest_earlier_rate_is_considered() -> None:
    older = _rate(date(2025, 1, 1), date(2025, 12, 31))
    gap_end = _rate(date(2026, 1, 1), date(2026, 3, 31))
    assert rate_to_close([older, gap_end], date(2026, 6, 1)) is None
    assert rate_to_close([], date(2026, 6, 1)) is None


# ── 2. Zaokrąglenie kwot ──────────────────────────────────────────────────────


@pytest.mark.parametrize("amount", ["0.004", "0.001", "0", "-1", "1000000.01"])
def test_bonus_amount_out_of_range_after_rounding_is_validation_error(
    amount: str,
) -> None:
    with pytest.raises(PayrollError):
        clean_amount(Decimal(amount))


def test_bonus_amount_rounds_half_up() -> None:
    assert clean_amount(Decimal("100.125")) == Decimal("100.13")
    assert clean_amount(Decimal("0.005")) == Decimal("0.01")
    assert clean_amount(Decimal("1000000")) == Decimal("1000000.00")


def test_rate_rounds_half_up_like_payroll_report() -> None:
    assert validate_rate(Decimal("45.125"), "PLN")[0] == Decimal("45.13")
    assert validate_rate(Decimal("45.135"), "pln") == (Decimal("45.14"), "PLN")


# ── 3. Logi bez treści wierszy ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bonus_job_failure_logs_class_not_row_content(
    monkeypatch, caplog
) -> None:
    finished: dict[str, Any] = {}

    async def _claim(*_args, **_kwargs) -> int:
        return 1

    async def _finish(_db, _run_id, **kwargs) -> None:
        finished.update(kwargs)

    monkeypatch.setattr(payroll_jobs.hr_modules, "load_modules", _payroll_module_on)
    monkeypatch.setattr(job_runs, "claim", _claim)
    monkeypatch.setattr(job_runs, "finish", _finish)
    monkeypatch.setattr(payroll_jobs, "refresh_proposals", _raise_integrity)
    db = _FakeDb()
    caplog.set_level(logging.DEBUG)

    result = await payroll_jobs.run_once(db, today=date(2026, 10, 19))

    assert result == {"error": "IntegrityError"}
    assert finished["status"] == "failed"
    assert db.rollbacks == 1
    assert "IntegrityError" in caplog.text
    assert SECRET_AMOUNT not in caplog.text


@pytest.mark.asyncio
async def test_placement_sync_failure_logs_class_not_row_content(
    monkeypatch, caplog
) -> None:
    async def _contracts(*_args, **_kwargs) -> list[int]:
        return [7]

    async def _calendar(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(placement_bonuses, "contracts_to_reconcile", _contracts)
    monkeypatch.setattr(placement_bonuses, "load_bonus_calendar", _calendar)
    monkeypatch.setattr(placement_bonuses, "reconcile_contract", _raise_integrity)
    caplog.set_level(logging.DEBUG)

    totals = await placement_bonuses.sync_placements(
        _FakeDb(row=(None, None)), today=date(2026, 10, 19), rules=object()
    )

    assert totals["errors"] == 1
    assert "IntegrityError" in caplog.text
    assert SECRET_AMOUNT not in caplog.text


@pytest.mark.asyncio
async def test_contract_hook_failure_logs_class_not_row_content(
    monkeypatch, caplog
) -> None:
    class _Contract:
        id = 7

    monkeypatch.setattr(
        placement_bonuses.hr_modules, "load_modules", _payroll_module_on
    )
    monkeypatch.setattr(placement_bonuses, "reconcile_contract", _raise_integrity)
    caplog.set_level(logging.DEBUG)

    result = await placement_bonuses.on_contract_ended(_FakeDb(), _Contract())

    assert result == {"error": "IntegrityError"}
    assert "IntegrityError" in caplog.text
    assert SECRET_AMOUNT not in caplog.text


@pytest.mark.asyncio
async def test_reconcile_before_approval_logs_class_not_row_content(
    monkeypatch, caplog
) -> None:
    monkeypatch.setattr(
        hr_payroll_api.placement_bonuses, "reconcile_contract", _raise_integrity
    )
    viewer = PayrollViewer(user_id=1, payroll=True, admin=False, report_ids=frozenset())
    db = _FakeDb(scalar=7, row=(7, 2))
    caplog.set_level(logging.DEBUG)

    await hr_payroll_api._reconcile_before_approval(db, viewer, 5)

    assert db.rollbacks == 1
    assert "IntegrityError" in caplog.text
    assert SECRET_AMOUNT not in caplog.text


# ── 4. Zatwierdzenie: zakres przed zapisem ────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "viewer",
    [
        # Obcy: ani Płace, ani przełożony odbiorcy.
        PayrollViewer(user_id=9, payroll=False, admin=False, report_ids=frozenset()),
        # Płace, ale premia dla samego siebie.
        PayrollViewer(user_id=2, payroll=True, admin=False, report_ids=frozenset()),
    ],
)
async def test_reconcile_before_approval_skips_bonus_out_of_scope(
    monkeypatch, viewer: PayrollViewer
) -> None:
    calls: list[int] = []

    async def _reconcile(_db, contract_id, **_kwargs):
        calls.append(contract_id)
        return {}

    monkeypatch.setattr(
        hr_payroll_api.placement_bonuses, "reconcile_contract", _reconcile
    )
    db = _FakeDb(scalar=7, row=(7, 2))

    await hr_payroll_api._reconcile_before_approval(db, viewer, 5)

    assert calls == []
    assert db.commits == 0
