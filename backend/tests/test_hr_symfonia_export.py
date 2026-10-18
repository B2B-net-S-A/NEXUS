"""Paczka dla Symfonii ERP Kadry i Płace (R5): zdarzenia XML, premie, zlecenia, PDF.

Zakres: tylko zamknięty miesiąc (409); XML w windows-1250 z osobą po GUID-zie
z Symfonii albo nazwisku i imieniu, urlop przez weekend jako jeden zakres,
pół dnia z godzinami, nadgodziny z godzinami, L4 tylko po włączeniu ustawienia;
premie UoP w kolumnach ze słownika, zlecenia z brutto z zamrożonej linii
i datą wypłaty; osoba bez identyfikatora poza plikami i na liście „do
zrobienia”; plik zdarzeń (rodzaj nieobecności, D6) tylko dla Kadr, kwoty tylko
dla Płac. PESEL-u nie ma nigdzie. Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import io
import zipfile
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from openpyxl import load_workbook
from sqlalchemy import delete, text

from app.api import hr_payments
from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now
from app.models.hr_leave import LeaveRequest, LeaveRequestDay
from app.models.hr_payroll import HrBonus
from app.services.hr import payroll_time_bridge, symfonia_export
from app.services.hr_foundation_schema import HR_MODULES_SETTING
from tests.hr import payments_fixtures as fx

PREFIX = "/api/hr/payments"
GUID = "2099071c-84e5-4aaf-aa70-57d2d40afffa"
YEAR, MONTH = 2026, 9


@pytest_asyncio.fixture
async def client():
    from app.main import app

    mounted = any(getattr(r, "path", "").startswith(PREFIX) for r in app.routes)
    target = app
    if not mounted:
        target = FastAPI()
        target.include_router(hr_payments.router, prefix=PREFIX)
    async with AsyncClient(
        transport=ASGITransport(app=target), base_url="http://testserver"
    ) as http:
        yield http


@pytest_asyncio.fixture
async def env():
    modules = await fx.get_setting(HR_MODULES_SETTING)
    payments = await fx.get_setting(fx.SETTING_KEY)
    await fx.modules(True)
    await fx.set_setting(fx.SETTING_KEY, None)
    await fx.wipe()
    created: list[int] = []
    yield created
    async with AsyncSessionLocal() as db:
        if created:
            await db.execute(
                text(
                    "DELETE FROM timesheet_entries WHERE timesheet_id IN "
                    "(SELECT id FROM timesheets WHERE user_id = ANY(:ids))"
                ),
                {"ids": created},
            )
            await db.execute(
                text("DELETE FROM timesheets WHERE user_id = ANY(:ids)"),
                {"ids": created},
            )
            await db.execute(
                delete(LeaveRequest).where(LeaveRequest.user_id.in_(created))
            )
        await db.commit()
    await fx.wipe()
    await fx.set_setting(fx.SETTING_KEY, payments)
    await fx.set_setting(HR_MODULES_SETTING, modules)


async def _leave(db, user, leave_type, days, *, half_day=None, fraction="1.0"):
    request = LeaveRequest(
        user_id=user.id,
        leave_type=leave_type,
        status="approved",
        start_date=days[0],
        end_date=days[-1],
        half_day=half_day,
        paid_days=Decimal("0"),
        unpaid_days=Decimal("0"),
    )
    db.add(request)
    await db.flush()
    for day in days:
        db.add(
            LeaveRequestDay(
                leave_request_id=request.id,
                user_id=user.id,
                day=day,
                fraction=Decimal(fraction),
                paid=leave_type == "vacation",
                active=True,
            )
        )
    await db.flush()


async def _timesheet(db, user, entries):
    row = await db.execute(
        text(
            "INSERT INTO timesheets (user_id, year, month, status) "
            "VALUES (:u, :y, :m, 'approved') RETURNING id"
        ),
        {"u": user.id, "y": YEAR, "m": MONTH},
    )
    timesheet_id = row.scalar_one()
    for day, hours in entries:
        await db.execute(
            text(
                "INSERT INTO timesheet_entries (timesheet_id, work_date, hours, description) "
                "VALUES (:t, :d, :h, 'Praca w biurze')"
            ),
            {"t": timesheet_id, "d": day, "h": Decimal(hours)},
        )


async def _bonus(db, recipient, assigner, category, amount, currency="PLN"):
    db.add(
        HrBonus(
            recipient_user_id=recipient.id,
            proposed_by=assigner.id,
            amount=Decimal(amount),
            currency=currency,
            category=category,
            period_year=YEAR,
            period_month=MONTH,
            status="assigned",
            source="manual",
            assigned_by=assigner.id,
            assigned_at=local_now(),
        )
    )


async def _month(created: list[int]):
    async with AsyncSessionLocal() as db:
        admin = await fx.make_user(db, "admin", name="Adam Administrator")
        finance = await fx.make_user(db, "finance", name="Filip Finansowy")
        hr = await fx.make_user(
            db, "recruiter", name="Ewa Kadry", permissions=("people_admin",)
        )
        anna = await fx.make_user(
            db,
            "employee",
            name="Anna Maria Przykładowa",
            profile={"employment_type": "uop", "work_start_date": date(2026, 9, 7)},
        )
        borys = await fx.make_user(
            db, "employee", name="Borys Wzorcowy", profile={"employment_type": "uop"}
        )
        celina = await fx.make_user(
            db,
            "employee",
            name="Celina Testowa",
            profile={
                "employment_type": "zlecenie",
                "work_start_date": date(2026, 3, 1),
                "student_contribution_exempt": True,
                "contribution_exempt_until": date(2026, 10, 15),
            },
        )
        twin_a = await fx.make_user(
            db, "employee", name="Jan Imiennik", profile={"employment_type": "uop"}
        )
        twin_b = await fx.make_user(
            db, "employee", name="Jan Imiennik", profile={"employment_type": "uop"}
        )
        ola = await fx.make_user(
            db, "employee", name="Ola Nowak", profile={"employment_type": "b2b"}
        )
        created.extend([anna.id, borys.id, celina.id, twin_a.id, twin_b.id, ola.id])
        await fx.set_billing(db, anna, symfonia_id=GUID)
        await fx.set_billing(db, celina, symfonia_id="E-0042")
        await fx.set_billing(db, twin_a, symfonia_id="E-0101")
        await fx.set_billing(db, twin_b, symfonia_id="E-0102")
        period = await fx.closed_period(db, YEAR, MONTH)
        for person, form in (
            (anna, "uop"),
            (borys, "uop"),
            (twin_a, "uop"),
            (twin_b, "uop"),
        ):
            await fx.line(
                db, period, person, employment_type=form, total="700.00", bonus="700.00"
            )
        await fx.line(
            db,
            period,
            celina,
            employment_type="zlecenie",
            total="2944.00",
            hours="92",
            rate="32.00",
        )
        await fx.line(
            db,
            period,
            ola,
            employment_type="b2b",
            total="17160.00",
            hours="160",
            rate="95",
        )
        # Urlop pt 11.09 + pn 14.09 (weekend pomiędzy) = jeden zakres.
        await _leave(db, anna, "vacation", [date(2026, 9, 11), date(2026, 9, 14)])
        await _leave(
            db,
            anna,
            "on_demand",
            [date(2026, 9, 18)],
            half_day="afternoon",
            fraction="0.5",
        )
        await _leave(db, anna, "sick_leave", [date(2026, 9, 21), date(2026, 9, 22)])
        await _leave(db, anna, "training", [date(2026, 9, 24)])
        await _leave(db, twin_a, "vacation", [date(2026, 9, 25)])
        await _timesheet(db, anna, [(date(2026, 9, 2), "10"), (date(2026, 9, 3), "8")])
        await _bonus(db, anna, finance, "sales", "500.00")
        await _bonus(db, anna, finance, "league", "200.00")
        await _bonus(db, anna, finance, "custom", "100.00", currency="EUR")
        await db.commit()
    return admin, finance, hr, anna


def _zip(content: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


@pytest.mark.asyncio
async def test_open_month_is_refused(client, env):
    async with AsyncSessionLocal() as db:
        finance = await fx.make_user(db, "finance")
        await db.commit()
    response = await client.get(
        f"{PREFIX}/symfonia/{YEAR}/{MONTH}/package.zip", headers=fx.headers(finance)
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "period_open"


@pytest.mark.asyncio
async def test_full_package_for_payroll_and_hr(client, env):
    admin, _finance, _hr, _anna = await _month(env)
    response = await client.get(
        f"{PREFIX}/symfonia/{YEAR}/{MONTH}/package.zip", headers=fx.headers(admin)
    )
    assert response.status_code == 200, response.text
    assert "symfonia-2026-09.zip" in response.headers["content-disposition"]
    files = _zip(response.content)
    assert set(files) == {
        "zdarzenia_2026-09.xml",
        "premie_2026-09.xlsx",
        "zlecenia_rozliczenia_2026-09.xlsx",
        "zestawienie_2026-09.pdf",
    }

    raw_xml = files["zdarzenia_2026-09.xml"]
    assert raw_xml.startswith(b'<?xml version="1.0" encoding="windows-1250"')
    xml = raw_xml.decode("windows-1250")
    assert "<surname>Przykładowa</surname>" in xml and "<name>Anna Maria</name>" in xml
    assert "<guid>{2099071C-84E5-4AAF-AA70-57D2D40AFFFA}</guid>" in xml
    assert "<name>Urlop wypoczynkowy</name>" in xml
    assert 'begin="2026-09-11" end="2026-09-14"/>' in xml
    # Pół dnia po południu: 12:00–16:00 (dzień od 8:00).
    assert 'begin="2026-09-18" end="2026-09-18" start="12:00:0" stop="16:00:0"' in xml
    # Nadgodziny 2 h po normie 8 h.
    assert 'begin="2026-09-02" end="2026-09-02" start="16:00:0" stop="18:00:0"' in xml
    # L4 domyślnie z e-ZLA, imiennicy bez GUID-u i osoby bez identyfikatora poza plikiem.
    assert "Choroba" not in xml and "2026-09-21" not in xml
    assert "Imiennik" not in xml and "Wzorcowy" not in xml
    assert "Ola" not in xml and "Celina" not in xml

    bonuses = load_workbook(io.BytesIO(files["premie_2026-09.xlsx"])).active
    header = [cell.value for cell in bonuses[1]]
    assert header == [
        "Nazwisko",
        "Imię",
        "Identyfikator",
        "Data od",
        "Data do",
        "Premia Liga Mistrzów",
        "Premia sprzedażowa",
    ]
    values = [cell.value for cell in bonuses[2]]
    assert values[:3] == ["Przykładowa", "Anna Maria", GUID]
    assert values[3].date() == date(2026, 9, 1) and values[4].date() == date(
        2026, 9, 30
    )
    assert values[5:] == [200.0, 500.0]
    assert bonuses.max_row == 2

    mandates = load_workbook(
        io.BytesIO(files["zlecenia_rozliczenia_2026-09.xlsx"])
    ).active
    row = [cell.value for cell in mandates[2]]
    assert row[:5] == ["Testowa", "Celina", "E-0042", "zlecenie", "przelew"]
    assert row[5].date() == date(2026, 3, 1)
    assert row[6].date() == date(2026, 10, 10)
    assert row[7:10] == [2944.0, 92.0, 32.0]
    assert mandates.max_row == 2

    assert files["zestawienie_2026-09.pdf"].startswith(b"%PDF")


@pytest.mark.asyncio
async def test_preview_lists_manual_work(client, env):
    admin, *_ = await _month(env)
    preview = await client.get(
        f"{PREFIX}/symfonia/{YEAR}/{MONTH}/preview", headers=fx.headers(admin)
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    todo = " ".join(body["todo"])
    assert "Borys Wzorcowy: brak identyfikatora z Symfonii" in todo
    assert "Jan Imiennik: imiennik bez GUID-u" in todo
    assert "Anna Maria Przykładowa: nowa osoba od 07.09.2026" in todo
    assert (
        "Celina Testowa: zwolnienie ze składek (student do 26 lat) kończy się 15.10.2026"
        in todo
    )
    assert "premia w walucie innej niż PLN" in todo
    assert "„Urlop szkoleniowy”" in todo
    assert any("e-ZLA" in note for note in body["notes"])
    assert any("B2B (1 os.)" in note for note in body["notes"])
    assert body["totals"] == {
        "Premie · Premia Liga Mistrzów": "200.00",
        "Premie · Premia sprzedażowa": "500.00",
        "Zlecenia · brutto": "2944.00",
    }
    assert body["includes_events"] is True and body["includes_amounts"] is True


@pytest.mark.asyncio
async def test_sick_leave_exported_when_payroll_does_not_use_ezla(client, env):
    admin, *_ = await _month(env)
    await fx.set_setting(fx.SETTING_KEY, {"symfonia": {"export_sick_leave": True}})
    files = _zip(
        (
            await client.get(
                f"{PREFIX}/symfonia/{YEAR}/{MONTH}/package.zip",
                headers=fx.headers(admin),
            )
        ).content
    )
    xml = files["zdarzenia_2026-09.xml"].decode("windows-1250")
    assert "<name>Choroba zwykła</name>" in xml
    assert 'begin="2026-09-21" end="2026-09-22"' in xml


@pytest.mark.asyncio
async def test_payroll_without_hr_gets_no_absence_types(client, env):
    _admin, finance, _hr, _anna = await _month(env)
    response = await client.get(
        f"{PREFIX}/symfonia/{YEAR}/{MONTH}/package.zip", headers=fx.headers(finance)
    )
    files = _zip(response.content)
    assert "zdarzenia_2026-09.xml" not in files
    assert "premie_2026-09.xlsx" in files
    preview = (
        await client.get(
            f"{PREFIX}/symfonia/{YEAR}/{MONTH}/preview", headers=fx.headers(finance)
        )
    ).json()
    assert preview["includes_events"] is False
    assert not any("Urlop szkoleniowy" in item for item in preview["todo"])
    assert any("uprawnieniem „Kadry”" in note for note in preview["notes"])


@pytest.mark.asyncio
async def test_hr_without_payroll_gets_no_amounts(client, env):
    _admin, _finance, hr, _anna = await _month(env)
    response = await client.get(
        f"{PREFIX}/symfonia/{YEAR}/{MONTH}/package.zip", headers=fx.headers(hr)
    )
    files = _zip(response.content)
    assert set(files) == {"zdarzenia_2026-09.xml", "zestawienie_2026-09.pdf"}
    preview = (
        await client.get(
            f"{PREFIX}/symfonia/{YEAR}/{MONTH}/preview", headers=fx.headers(hr)
        )
    ).json()
    assert "totals" not in preview
    assert preview["includes_amounts"] is False


@pytest.mark.asyncio
async def test_overtime_per_day_matches_payroll_report(client, env):
    _admin, _finance, _hr, anna = await _month(env)
    async with AsyncSessionLocal() as db:
        days = await symfonia_export.overtime_days(db, YEAR, MONTH, [anna.id])
        report = await payroll_time_bridge.approved_hours(db, YEAR, MONTH)
    assert days[anna.id] == [(date(2026, 9, 2), Decimal("2.00"))]
    assert sum(extra for _day, extra in days[anna.id]) == report[anna.id].overtime_hours
