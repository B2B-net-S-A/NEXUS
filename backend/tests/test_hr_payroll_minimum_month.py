"""Minimalna stawka na zleceniu w raporcie miesiąca płac (D7, 17.10.2026).

Zapis stawki sprawdza minimum tylko w roku ``effective_from``, więc stawka
z grudnia na minimum starego roku obowiązuje dalej w styczniu, gdy minimum
jest wyższe — tak samo po usunięciu kroku nowego roku (stary krok przejmuje
jego okres). Raport miesiąca (``GET /api/hr/payroll/months/{y}/{m}`` →
``warnings``) ostrzega o każdej osobie na zleceniu, której stawka obowiązująca
w miesiącu jest niższa niż minimum roku tego miesiąca, a zamknięcie miesiąca
wymaga potwierdzenia tego ostrzeżenia jak pozostałych. W komunikacie liczba
osób i minimum z Ustawień, bez stawek osób.

Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import delete, text

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.app_setting import AppSetting
from app.models.hr_payroll import EmployeeRate
from app.services.hr.payroll_rates import MINIMUM_RATES_SETTING
from tests.test_hr_time_support import (  # noqa: F401 — fikstury
    grant,
    headers,
    make_user,
    time_on,
)

PAYROLL = "/api/hr/payroll"
CODE = "below_minimum_rate"


async def _approved_timesheet(db, user_id: int, year: int, month: int, days) -> None:
    sheet = (
        await db.execute(
            text(
                "INSERT INTO timesheets (user_id, year, month, status) "
                "VALUES (:u, :y, :m, 'approved') RETURNING id"
            ),
            {"u": user_id, "y": year, "m": month},
        )
    ).scalar_one()
    for day in days:
        await db.execute(
            text(
                "INSERT INTO timesheet_entries (timesheet_id, work_date, hours, "
                "description) VALUES (:t, :d, 8, 'Praca')"
            ),
            {"t": sheet, "d": date(year, month, day)},
        )


async def _set_minimums(year: int) -> None:
    """Minimum starego roku 30,50, nowego 31,40 (zmyślone jak w ustawieniu)."""

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(AppSetting).where(AppSetting.key == MINIMUM_RATES_SETTING)
        )
        db.add(
            AppSetting(
                key=MINIMUM_RATES_SETTING,
                value={str(year - 1): "30.50", str(year): "31.40"},
            )
        )
        await db.commit()


async def _cleanup(user_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(EmployeeRate).where(EmployeeRate.user_id.in_(user_ids)))
        await db.execute(
            delete(AppSetting).where(AppSetting.key == MINIMUM_RATES_SETTING)
        )
        await db.commit()


def _minimum_warning(body: dict) -> dict | None:
    return next((w for w in body.get("warnings") or [] if w["code"] == CODE), None)


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_rate_from_previous_year_below_new_minimum_is_a_month_warning(
    app_client,
) -> None:
    year = business_today().year
    await _set_minimums(year)
    async with AsyncSessionLocal() as db:
        payroll = await make_user(db, "finance", profile=False)
        await grant(db, payroll, "payroll")
        mandate = await make_user(db, employment_type="zlecenie")
        exact = await make_user(db, employment_type="zlecenie")
        contractor = await make_user(db, employment_type="b2b")
        await _approved_timesheet(db, mandate.id, year, 1, (5, 7, 8))
        await db.commit()
    h = headers(payroll)
    try:
        for user, amount in (
            (mandate, "30.50"),
            (exact, "31.40"),
            (contractor, "20.00"),
        ):
            saved = await app_client.post(
                f"{PAYROLL}/people/{user.id}/rates",
                json={"hourly_rate": amount, "effective_from": f"{year - 1}-12-01"},
                headers=h,
            )
            # Minimum starego roku = 30,50 → zapis bez błędu i bez ostrzeżenia.
            assert saved.status_code == 201, saved.text
            assert saved.json()["warning"] is None

        month = await app_client.get(f"{PAYROLL}/months/{year}/1", headers=h)
        assert month.status_code == 200, month.text
        body = month.json()
        assert body["status"] == "open"
        warning = _minimum_warning(body)
        assert warning is not None, body.get("warnings")
        flagged = {p["user_id"] for p in warning["people"]}
        assert mandate.id in flagged
        # Stawka równa minimum i B2B (bez minimalnej stawki) — bez ostrzeżenia.
        assert exact.id not in flagged and contractor.id not in flagged
        assert "31,40 zł/h" in warning["message"]
        # Bez stawki osoby w komunikacie.
        assert "30,50" not in warning["message"] and "30.50" not in str(warning)

        # Zamknięcie bez potwierdzenia zatrzymuje się na tym ostrzeżeniu.
        refused = await app_client.post(
            f"{PAYROLL}/months/{year}/1/close", json={}, headers=h
        )
        assert refused.status_code == 409, refused.text
        detail = refused.json()["detail"]
        assert detail["code"] == "close_warnings"
        assert CODE in {w["code"] for w in detail["warnings"]}
    finally:
        await _cleanup([mandate.id, exact.id, contractor.id])


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_deleting_new_year_step_leaves_rate_below_minimum_warned(
    app_client,
) -> None:
    year = business_today().year
    await _set_minimums(year)
    async with AsyncSessionLocal() as db:
        payroll = await make_user(db, "finance", profile=False)
        await grant(db, payroll, "payroll")
        mandate = await make_user(db, employment_type="zlecenie")
        await db.commit()
    h = headers(payroll)
    try:
        old = await app_client.post(
            f"{PAYROLL}/people/{mandate.id}/rates",
            json={"hourly_rate": "30.50", "effective_from": f"{year - 1}-12-01"},
            headers=h,
        )
        assert old.status_code == 201, old.text
        new = await app_client.post(
            f"{PAYROLL}/people/{mandate.id}/rates",
            json={"hourly_rate": "31.40", "effective_from": f"{year}-01-01"},
            headers=h,
        )
        assert new.status_code == 201, new.text
        before = await app_client.get(f"{PAYROLL}/months/{year}/1", headers=h)
        warning = _minimum_warning(before.json())
        assert warning is None or mandate.id not in {
            p["user_id"] for p in warning["people"]
        }

        # Bezpośredni zapis poniżej minimum nowego roku to dalej 422…
        direct = await app_client.post(
            f"{PAYROLL}/people/{mandate.id}/rates",
            json={"hourly_rate": "30.50", "effective_from": f"{year}-01-01"},
            headers=h,
        )
        assert direct.status_code == 422
        # …a usunięcie kroku nowego roku daje ten sam stan — z ostrzeżeniem w raporcie.
        gone = await app_client.delete(f"{PAYROLL}/rates/{new.json()['id']}", headers=h)
        assert gone.status_code == 204
        after = await app_client.get(f"{PAYROLL}/months/{year}/1", headers=h)
        assert after.status_code == 200, after.text
        warning = _minimum_warning(after.json())
        assert warning is not None, after.json().get("warnings")
        assert mandate.id in {p["user_id"] for p in warning["people"]}
    finally:
        await _cleanup([mandate.id])
