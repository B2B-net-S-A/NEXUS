"""Forma współpracy w całym module (etap 2, D1, D4, D6–D9, 17.10.2026).

* słownik słów według formy (``employment_terms``) i PDF raportu godzin,
* D6 — pula płatnych dni nie dla zlecenia,
* D7 — minimalna stawka godzinowa na zleceniu i archiwum potwierdzeń godzin
  (3 lata od terminu wypłaty, art. 8c),
* D8 — uczeń/student na zleceniu: znacznik, data końca zwolnienia ze składek,
  przypomnienie dla Płac i Kadr 30 dni wcześniej,
* D9 — staż do urlopu na umowie o pracę i podpowiedź wymiaru 20/26.

Dane fikcyjne (repo jest publiczne), kwoty zmyślone.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.hr_ops import HrJobRun
from app.models.hr_payroll import EmployeeRate
from app.models.hr_profile import EmployeeProfile
from app.models.hr_time import Timesheet, TimesheetEntry
from app.models.notification import Notification, NotificationType
from app.services.hr import (
    student_reminders,
    time_entries,
    time_fill,
    time_hooks,
    time_retention,
)
from app.services.hr.employment_terms import (
    BACKEND_TERMS,
    EMPLOYMENT_TERMS,
    bonus_message,
    form_of,
    reports_absence,
    terms,
)
from app.services.hr.leave_policy import statutory_entitlement
from app.services.hr.payroll_periods import add_months
from app.services.hr.time_entries import TimeConflict
from app.services.hr.time_hash import HashEntry, compute_timesheet_hash
from app.services.hr.time_pdf import PdfEntry, PdfTimesheet, render_html
from tests.test_hr_time_support import (  # noqa: F401 — fikstury
    grant,
    headers,
    make_user,
    time_on,
)

ADMIN = "/api/hr/admin"
PAYROLL = "/api/hr/payroll"


# ── Słownik ───────────────────────────────────────────────────────────────────


def test_every_form_has_the_same_words_and_no_form_means_uop() -> None:
    assert set(EMPLOYMENT_TERMS) == {"uop", "b2b", "zlecenie"} == set(BACKEND_TERMS)
    assert form_of(None) == form_of("nieznana") == "uop"
    assert terms(None)["absence"] == "urlop"
    assert terms("b2b")["absence"] == "przerwa w świadczeniu usług"
    assert terms("zlecenie")["timesheet"] == "Potwierdzenie godzin"
    assert (
        terms("b2b")["coordinator"] == terms("zlecenie")["coordinator"] == "koordynator"
    )
    assert terms("uop")["coordinator"] == "przełożony"
    assert [reports_absence(f) for f in ("uop", "b2b", "zlecenie", None)] == [
        False,
        True,
        True,
        False,
    ]
    # Słowa B2B i zlecenia nie mówią „urlop” ani „wniosek” (D4).
    for form in ("b2b", "zlecenie"):
        text = " ".join(terms(form).values()).lower()
        assert "urlop" not in text and "wniosek" not in text and "przełożon" not in text
        # Ani „nadgodzin”, ani „premii” (decyzja Artura 21.10.2026).
        assert "nadgodzin" not in text and "premi" not in text


def test_overtime_and_bonus_words_follow_the_contract() -> None:
    assert terms("uop")["overtime"] == "nadgodziny"
    assert (
        terms("b2b")["overtime"] == terms("zlecenie")["overtime"] == "godziny ponad 8 h"
    )
    assert terms("uop")["bonus_new_title"] == "Masz nową premię"
    assert terms("b2b")["bonus_new_title"] == "Masz nowe wynagrodzenie dodatkowe"
    assert bonus_message("uop", "październik 2026") == (
        "Premia za październik 2026. Szczegóły w „Moim czasie” → Premie."
    )
    assert bonus_message("b2b", "październik 2026", cancelled=True) == (
        "Wynagrodzenie dodatkowe za październik 2026 zostało anulowane. "
        "Szczegóły w „Moim czasie” → Wynagrodzenie dodatkowe."
    )
    assert bonus_message(None, "maj 2026", cancelled=True) == (
        "Premia za maj 2026 została anulowana. Szczegóły w „Moim czasie” → Premie."
    )
    assert time_fill_hours_error("b2b").endswith(
        "godziny ponad 8 h wpisuje się w dniu, z krótkim opisem."
    )
    assert time_fill_hours_error("uop").endswith(
        "nadgodziny wpisuje się w dniu, z uzasadnieniem."
    )


def time_fill_hours_error(form: str) -> str:
    with pytest.raises(time_entries.TimeError) as caught:
        time_fill.fill_hours(Decimal("9"), form=form)
    return str(caught.value)


def _sheet(form: str, *, overtime: bool = False) -> PdfTimesheet:
    return PdfTimesheet(
        person_name="Anna Przykładowa",
        person_email="anna@example.com",
        employment_type=form,
        year=2026,
        month=9,
        pdf_hash="a" * 64,
        approved_at=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc),
        approved_by_name="Jan Przykładowy",
        entries=[PdfEntry("2026-09-01", Decimal("8"), None, "Sourcing", overtime)],
    )


def test_timesheet_pdf_speaks_the_language_of_the_contract() -> None:
    uop = render_html(_sheet("uop"))
    assert "<h1>Ewidencja czasu pracy</h1>" in uop and "Pracownik" in uop
    b2b = render_html(_sheet("b2b"))
    assert "<h1>Raport godzin</h1>" in b2b and "Wykonawca" in b2b
    assert "Pracownik" not in b2b and "Zaakceptował" not in b2b
    mandate = render_html(_sheet("zlecenie"))
    assert "<h1>Potwierdzenie liczby godzin</h1>" in mandate
    assert "art. 8b ustawy o minimalnym wynagrodzeniu" in mandate
    assert "Zleceniobiorca" in mandate and "Pracownik" not in mandate
    # Godziny ponad 8 h: przy UoP „nadgodziny”, przy B2B i zleceniu bez tego słowa.
    assert "Dni z nadgodzinami" in render_html(_sheet("uop", overtime=True))
    for form in ("b2b", "zlecenie"):
        html = render_html(_sheet(form, overtime=True))
        assert "nadgodzin" not in html and "Dni z godzinami ponad 8 h" in html


# ── D6, D8, D9: kartoteka i pula ──────────────────────────────────────────────


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_paid_pool_is_refused_on_mandate_and_seniority_suggests_20_or_26(
    app_client,
) -> None:
    async with AsyncSessionLocal() as db:
        hr = await make_user(db, "recruiter", profile=False)
        await grant(db, hr, "people_admin")
        # Podpowiedź 20/26 zdradza formę — widzą ją Kadry z Płacami (19.10.2026).
        await grant(db, hr, "payroll")
        mandate = await make_user(db, employment_type="zlecenie")
        contractor = await make_user(db, employment_type="b2b")
        senior = await make_user(db, employment_type="uop", leave_seniority_years=12)
        junior = await make_user(db, employment_type="uop", leave_seniority_years=3)
        await db.commit()
    h = headers(hr)

    def url(user, year=2091):
        return f"{ADMIN}/profiles/{user.id}/entitlements/{year}"

    refused = await app_client.put(
        url(mandate), json={"entitlement_days": 5}, headers=h
    )
    assert refused.status_code == 422
    assert "zlecenie" in refused.json()["detail"]
    carried = await app_client.put(
        url(mandate), json={"entitlement_days": None, "carried_over_days": 2}, headers=h
    )
    assert carried.status_code == 422
    no_pool = await app_client.put(
        url(mandate), json={"entitlement_days": None}, headers=h
    )
    assert no_pool.status_code == 200

    b2b = await app_client.put(
        url(contractor), json={"entitlement_days": 10}, headers=h
    )
    assert b2b.status_code == 200
    assert b2b.json()["suggested_entitlement_days"] is None
    long = await app_client.put(url(senior), json={"entitlement_days": 26}, headers=h)
    assert long.json()["suggested_entitlement_days"] == 26
    short = await app_client.put(url(junior), json={"entitlement_days": 20}, headers=h)
    assert short.json()["suggested_entitlement_days"] == 20
    assert statutory_entitlement("uop", None) is None
    assert (
        statutory_entitlement("uop", 10) == 26 and statutory_entitlement("uop", 9) == 20
    )
    assert statutory_entitlement("b2b", 15) is None


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_student_flag_only_on_mandate_and_uop_fields_only_on_uop(
    app_client,
) -> None:
    async with AsyncSessionLocal() as db:
        hr = await make_user(db, "recruiter", profile=False)
        await grant(db, hr, "people_admin")
        # Daty zależne od formy widzą Finanse (19.10.2026) — Kadry z Płacami.
        await grant(db, hr, "payroll")
        person = await make_user(db, employment_type="zlecenie")
        contractor = await make_user(db, employment_type="b2b")
        worker = await make_user(db, employment_type="uop")
        await db.commit()
    h = headers(hr)

    def url(user):
        return f"{ADMIN}/profiles/{user.id}"

    on_b2b = await app_client.patch(
        url(contractor), json={"student_contribution_exempt": True}, headers=h
    )
    assert on_b2b.status_code == 422
    assert "zlecenie" in on_b2b.json()["detail"]
    date_only = await app_client.patch(
        url(person), json={"contribution_exempt_until": "2091-06-30"}, headers=h
    )
    assert date_only.status_code == 422
    student = await app_client.patch(
        url(person),
        json={
            "student_contribution_exempt": True,
            "contribution_exempt_until": "2091-06-30",
        },
        headers=h,
    )
    assert student.status_code == 200, student.text
    body = student.json()
    assert body["student_contribution_exempt"] is True
    assert body["contribution_exempt_until"] == "2091-06-30"
    assert body["contributions_from"] == "2091-07-01"
    seniority = await app_client.patch(
        url(person), json={"leave_seniority_years": 5}, headers=h
    )
    assert seniority.status_code == 422

    # Zmiana formy zdejmuje znacznik (Płace nie dostaną przypomnienia o B2B).
    moved = await app_client.patch(
        url(person), json={"employment_type": "b2b"}, headers=h
    )
    assert moved.status_code == 200
    assert moved.json()["student_contribution_exempt"] is False
    assert moved.json()["contribution_exempt_until"] is None

    future = (business_today() + timedelta(days=3)).isoformat()
    refused = await app_client.patch(
        url(worker), json={"zus_certificate_received_on": future}, headers=h
    )
    assert refused.status_code == 422
    too_long = await app_client.patch(
        url(worker), json={"leave_seniority_years": 61}, headers=h
    )
    assert too_long.status_code == 422
    ok = await app_client.patch(
        url(worker),
        json={"leave_seniority_years": 11, "zus_certificate_received_on": "2026-05-04"},
        headers=h,
    )
    assert ok.status_code == 200
    assert ok.json()["suggested_entitlement_days"] == 26
    assert ok.json()["zus_certificate_received_on"] == "2026-05-04"


@pytest.mark.asyncio
async def test_exempt_date_without_flag_is_refused_by_the_database() -> None:
    async with AsyncSessionLocal() as db:
        user = await make_user(db, profile=False)
        db.add(
            EmployeeProfile(
                user_id=user.id,
                employment_type="zlecenie",
                contribution_exempt_until=date(2091, 6, 30),
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_structure_and_team_show_when_contributions_start(app_client) -> None:
    async with AsyncSessionLocal() as db:
        hr = await make_user(db, "recruiter", profile=False)
        await grant(db, hr, "people_admin")
        # Formę w Strukturze widzą admin i Finanse (19.10.2026).
        await grant(db, hr, "payroll")
        boss = await make_user(db, "delivery_lead", employment_type="uop")
        student = await make_user(
            db,
            employment_type="zlecenie",
            manager_user_id=boss.id,
            student_contribution_exempt=True,
            contribution_exempt_until=date(2091, 6, 30),
        )
        await db.commit()
    tree = await app_client.get("/api/hr/structure", headers=headers(hr))
    assert tree.status_code == 200
    row = next(p for p in tree.json()["people"] if p["user_id"] == student.id)
    assert row["student"] is True and row["contributions_from"] == "2091-07-01"
    team = await app_client.get("/api/hr/team", headers=headers(boss))
    assert team.status_code == 200, team.text
    member = next(p for p in team.json()["people"] if p["user_id"] == student.id)
    # Przełożony widzi sam znacznik; datę — Finanse w Strukturze (19.10.2026).
    assert member["student"] is True and "contributions_from" not in member


# ── D8: przypomnienie o końcu zwolnienia ze składek ──────────────────────────


async def _lifecycle_bells(user_id: int) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list(
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == user_id,
                    Notification.notification_type
                    == NotificationType.hr_lifecycle_task,
                )
            )
        )


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_student_reminder_goes_once_to_payroll_and_hr_30_days_ahead() -> None:
    today = date(2091, 5, 20)
    async with AsyncSessionLocal() as db:
        payroll = await make_user(db, "finance", profile=False)
        await grant(db, payroll, "payroll")
        hr = await make_user(db, "recruiter", profile=False)
        await grant(db, hr, "people_admin")
        due = await make_user(
            db,
            employment_type="zlecenie",
            student_contribution_exempt=True,
            contribution_exempt_until=today + timedelta(days=10),
        )
        later = await make_user(
            db,
            employment_type="zlecenie",
            student_contribution_exempt=True,
            contribution_exempt_until=today + timedelta(days=31),
        )
        gone = await make_user(
            db,
            employment_type="zlecenie",
            student_contribution_exempt=True,
            contribution_exempt_until=today - timedelta(days=1),
        )
        await db.commit()

    try:
        async with AsyncSessionLocal() as db:
            first = await student_reminders.student_contribution_reminders(
                db, today=today
            )
        assert first["status"] == "ok" and first["sent"] >= 1
        for recipient in (payroll, hr):
            bells = [
                bell
                for bell in await _lifecycle_bells(recipient.id)
                if bell.link == f"/people/{due.id}"
            ]
            assert len(bells) == 1
            assert due.name in bells[0].title
            assert "zł" not in bells[0].message
            assert not any(
                bell.link in (f"/people/{later.id}", f"/people/{gone.id}")
                for bell in await _lifecycle_bells(recipient.id)
            )
        async with AsyncSessionLocal() as db:
            again = await student_reminders.student_contribution_reminders(
                db, today=today
            )
        assert again["sent"] == 0 and again["already"] >= 1
        assert (
            len(
                [
                    bell
                    for bell in await _lifecycle_bells(hr.id)
                    if bell.link == f"/people/{due.id}"
                ]
            )
            == 1
        )
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(HrJobRun).where(HrJobRun.kind == student_reminders.JOB_KIND)
            )
            await db.commit()


# ── D7: minimalna stawka na zleceniu ─────────────────────────────────────────


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_mandate_rate_below_the_yearly_minimum_is_refused(app_client) -> None:
    today = business_today()
    this_month = today.replace(day=1)
    next_year = date(today.year + 1, 1, 1)
    async with AsyncSessionLocal() as db:
        payroll = await make_user(db, "finance", profile=False)
        await grant(db, payroll, "payroll")
        outsider = await make_user(db, "recruiter")
        mandate = await make_user(db, employment_type="zlecenie")
        contractor = await make_user(db, employment_type="b2b")
        await db.commit()
    h = headers(payroll)
    year = str(today.year)
    try:
        assert (
            await app_client.get(
                f"{PAYROLL}/settings/minimum-rates", headers=headers(outsider)
            )
        ).status_code == 403
        defaults = await app_client.get(f"{PAYROLL}/settings/minimum-rates", headers=h)
        assert defaults.status_code == 200
        assert {"year": 2026, "hourly_rate": "31.40"} in defaults.json()["rates"]
        assert {"year": 2025, "hourly_rate": "30.50"} in defaults.json()["rates"]
        bad = await app_client.put(
            f"{PAYROLL}/settings/minimum-rates",
            json={"rates": {"1999": "10"}},
            headers=h,
        )
        assert bad.status_code == 422
        zero = await app_client.put(
            f"{PAYROLL}/settings/minimum-rates", json={"rates": {year: "0"}}, headers=h
        )
        assert zero.status_code == 422
        saved = await app_client.put(
            f"{PAYROLL}/settings/minimum-rates",
            json={"rates": {year: "31.40"}},
            headers=h,
        )
        assert saved.status_code == 200
        assert saved.json()["rates"] == [{"year": today.year, "hourly_rate": "31.40"}]

        def rate(user, amount, start=this_month):
            return app_client.post(
                f"{PAYROLL}/people/{user.id}/rates",
                json={"hourly_rate": amount, "effective_from": start.isoformat()},
                headers=h,
            )

        low = await rate(mandate, "31.39")
        assert low.status_code == 422
        assert low.json()["detail"] == (
            f"Minimalna stawka na zleceniu w {today.year} to 31,40 zł/h brutto."
        )
        exact = await rate(mandate, "31.40")
        assert exact.status_code == 201, exact.text
        assert exact.json()["warning"] is None
        # Rok bez minimum w tabeli — zapis z ostrzeżeniem, bez blokady.
        unknown = await rate(mandate, "20.00", next_year)
        assert unknown.status_code == 201, unknown.text
        assert "nie jest ustawiona" in unknown.json()["warning"]
        # B2B nie ma minimalnej stawki godzinowej.
        b2b = await rate(contractor, "10.00")
        assert b2b.status_code == 201 and b2b.json()["warning"] is None
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(EmployeeRate).where(
                    EmployeeRate.user_id.in_([mandate.id, contractor.id])
                )
            )
            from app.models.app_setting import AppSetting
            from app.services.hr.payroll_rates import MINIMUM_RATES_SETTING

            row = await db.get(AppSetting, MINIMUM_RATES_SETTING)
            if row is not None:
                await db.delete(row)
            await db.commit()


# ── D7: archiwum potwierdzeń godzin (art. 8c) ─────────────────────────────────


def test_payment_due_and_retention_dates() -> None:
    assert time_retention.payment_due(2026, 12) == date(2027, 1, 31)
    assert time_retention.payment_due(2026, 1) == date(2026, 2, 28)
    assert time_retention.retention_until(2026, 1) == date(2029, 2, 28)
    # Termin 29.02 przechodzi na 28.02 roku bez dnia przestępnego.
    assert time_retention.payment_due(2028, 1) == date(2028, 2, 29)
    assert time_retention.retention_until(2028, 1) == date(2031, 2, 28)

    def frozen(form="zlecenie", status="approved", today=date(2026, 11, 1)):
        return time_retention.frozen(
            employment_type=form, status=status, year=2026, month=9, today=today
        )

    assert frozen() is True  # wypłata do 31.10, dziś 01.11
    assert frozen(today=date(2026, 10, 31)) is False  # jeszcze przed terminem
    assert frozen(today=date(2029, 10, 31)) is True
    assert frozen(today=date(2029, 11, 1)) is False  # po 3 latach
    assert frozen(form="b2b") is False and frozen(status="submitted") is False


async def _approved_sheet(db, worker, boss, year: int, month: int) -> Timesheet:
    entries = [HashEntry(f"{year}-{month:02d}-02", 8, None, "Sourcing")]
    sheet = Timesheet(
        user_id=worker.id,
        year=year,
        month=month,
        status="approved",
        approved_by=boss.id,
        approved_at=datetime.now(timezone.utc),
        pdf_hash=compute_timesheet_hash(entries),
    )
    db.add(sheet)
    await db.flush()
    db.add(
        TimesheetEntry(
            timesheet_id=sheet.id,
            work_date=date(year, month, 2),
            hours=Decimal("8"),
            description="Sourcing",
        )
    )
    await db.flush()
    return sheet


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_paid_mandate_confirmation_cannot_be_revoked_or_trimmed(
    app_client,
) -> None:
    today = business_today()
    past = add_months(today.year, today.month, -3)  # termin wypłaty minął
    async with AsyncSessionLocal() as db:
        boss = await make_user(db, "recruiter", employment_type="uop")
        mandate = await make_user(
            db, employment_type="zlecenie", manager_user_id=boss.id
        )
        contractor = await make_user(db, employment_type="b2b", manager_user_id=boss.id)
        fresh = await make_user(db, employment_type="zlecenie", manager_user_id=boss.id)
        old = await _approved_sheet(db, mandate, boss, *past)
        b2b = await _approved_sheet(db, contractor, boss, *past)
        current = await _approved_sheet(db, fresh, boss, today.year, today.month)
        await db.commit()

    refused = await app_client.post(
        f"/api/hr/time/timesheets/{old.id}/revoke", headers=headers(boss)
    )
    assert refused.status_code == 409
    assert "art. 8c" in refused.json()["detail"]
    for sheet in (b2b, current):
        done = await app_client.post(
            f"/api/hr/time/timesheets/{sheet.id}/revoke", headers=headers(boss)
        )
        assert done.status_code == 200, done.text

    async with AsyncSessionLocal() as db:
        sheet = await db.get(Timesheet, old.id)
        entry = await db.scalar(
            select(TimesheetEntry).where(TimesheetEntry.timesheet_id == old.id)
        )
        profile = await db.scalar(
            select(EmployeeProfile).where(EmployeeProfile.user_id == mandate.id)
        )
        with pytest.raises(TimeConflict):
            await time_entries.delete_entry(
                db, timesheet=sheet, subject=profile, entry=entry
            )
        # Zgłoszona później nieobecność nie zdejmuje godzin z archiwum.
        day = date(past[0], past[1], 2)
        result = await time_hooks.on_leave_approved(db, mandate.id, [day])
        assert result["locked_conflicts"] == [f"{past[0]}-{past[1]:02d}"]
        await db.rollback()
    async with AsyncSessionLocal() as db:
        assert await db.scalar(
            select(TimesheetEntry.id).where(TimesheetEntry.timesheet_id == old.id)
        )
        assert (await db.get(Timesheet, old.id)).status == "approved"
