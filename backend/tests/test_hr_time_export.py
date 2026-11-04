"""Eksport godzin do CSV (luka z Compassa, 18.10.2026).

Część bez bazy: zakres miesięcy, kolumny, separator, BOM, formuły, D6.
Część z bazą: bramki tras (osoba, przełożony, Kadry, Płace, obcy) i treść
pliku. Miesiąc testowy: marzec 2031. Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.hr_ops import HrAuditEvent
from app.models.hr_time import Timesheet, TimesheetEntry
from app.models.user import User
from app.services.hr import time_export
from app.services.hr.time_entries import TimeError
from tests.test_hr_time_support import (  # noqa: F401 — fikstury
    grant,
    headers,
    make_user,
    time_on,
)

Y, M = 2031, 3
BASE = f"/api/hr/time/me/{Y}/{M}"


def _rows(content: bytes) -> list[list[str]]:
    assert content.startswith("﻿".encode("utf-8"))
    text = content.decode("utf-8-sig")
    assert "\r\n" in text
    return list(csv.reader(io.StringIO(text), delimiter=";"))


# ── Bez bazy ──────────────────────────────────────────────────────────────────


def test_range_is_validated_like_compass():
    first, last = time_export.parse_range("2031-01", "2031-03")
    assert (first.year, first.month, last.month) == (2031, 1, 3)
    same = time_export.parse_range("2031-03", "2031-03")
    assert same[0] == same[1]
    for bad in (("2031-3", "x"), ("2031-13", "2031-13"), ("abcd-ef", "2031-01")):
        with pytest.raises(TimeError):
            time_export.parse_range(*bad)
    with pytest.raises(TimeError, match="przed miesiącem"):
        time_export.parse_range("2031-04", "2031-03")
    time_export.parse_range("2030-01", "2031-12")  # 24 miesiące — wolno
    with pytest.raises(TimeError, match="24"):
        time_export.parse_range("2030-01", "2032-01")


def _entry(**values) -> TimesheetEntry:
    base = dict(
        work_date=date(Y, M, 3),
        hours=Decimal("7.50"),
        project="Alfa",
        description="Rekrutacje",
        source="manual",
        is_overtime=False,
        overtime_reason=None,
    )
    return TimesheetEntry(**{**base, **values})


def _sheet(status: str = "approved") -> Timesheet:
    return Timesheet(user_id=1, year=Y, month=M, status=status)


def _person() -> User:
    return User(email="anna@example.com", name="Anna Przykładowa")


def test_csv_has_compass_columns_semicolons_bom_and_polish_numbers():
    content = time_export._render(
        [
            (_entry(), _sheet(), _person()),
            (
                _entry(
                    work_date=date(Y, M, 4),
                    hours=Decimal("10"),
                    project=None,
                    is_overtime=True,
                    overtime_reason="Wdrożenie po godzinach",
                ),
                _sheet("submitted"),
                _person(),
            ),
        ],
        show_leave_source=True,
    )
    rows = _rows(content)
    assert rows[0] == list(time_export.COLUMNS)
    assert rows[1] == [
        "Anna Przykładowa",
        "anna@example.com",
        "2031",
        "03",
        "zaakceptowany",
        "2031-03-03",
        "7,50",
        "Alfa",
        "Rekrutacje",
        "wpis",
        "",
        "",
    ]
    assert rows[2][4] == "wysłany"
    assert rows[2][6] == "10,00"
    assert rows[2][7] == ""
    assert rows[2][10:] == ["tak", "Wdrożenie po godzinach"]
    # Bez stawek i kwot — moduł czasu ich nie zna.
    assert not any("zł" in cell or "stawk" in cell.lower() for cell in rows[0])


def test_formula_in_description_is_neutralised():
    rows = _rows(
        time_export._render(
            [
                (
                    _entry(description='=HYPERLINK("https://example.com")'),
                    _sheet(),
                    _person(),
                )
            ],
            show_leave_source=True,
        )
    )
    assert rows[1][8].startswith("'=")


def test_paid_pool_source_is_hidden_from_a_reader_outside_d6():
    paid = _entry(source="leave_paid", description="Praca standardowa", project=None)
    shown = _rows(
        time_export._render([(paid, _sheet(), _person())], show_leave_source=True)
    )
    hidden = _rows(
        time_export._render([(paid, _sheet(), _person())], show_leave_source=False)
    )
    assert shown[1][9] == "płatny dzień z puli"
    assert hidden[1][9] == "wpis automatyczny"


# ── Z bazą ────────────────────────────────────────────────────────────────────


def _entry_json(day: int, hours: float, description: str = "Praca nad rekrutacjami"):
    return {
        "work_date": date(Y, M, day).isoformat(),
        "hours": hours,
        "description": description,
    }


async def _team():
    async with AsyncSessionLocal() as db:
        boss = await make_user(db, "recruiter")
        worker = await make_user(db, "employee", manager_user_id=boss.id)
        await db.commit()
    return boss, worker


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_own_csv_and_range(app_client) -> None:
    _, worker = await _team()
    h = headers(worker)
    for day, hours in ((3, 8), (4, 6.5)):
        added = await app_client.post(
            f"{BASE}/entries", json=_entry_json(day, hours), headers=h
        )
        assert added.status_code == 201, added.text
    april = await app_client.post(
        "/api/hr/time/me/2031/4/entries",
        json={"work_date": "2031-04-01", "hours": 8, "description": "Kwiecień"},
        headers=h,
    )
    assert april.status_code == 201
    response = await app_client.get(
        "/api/hr/time/me/export.csv",
        params={"from": "2031-03", "to": "2031-03"},
        headers=h,
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert "godziny-anna-przykladowa" in response.headers["content-disposition"]
    rows = _rows(response.content)
    assert [row[5] for row in rows[1:]] == ["2031-03-03", "2031-03-04"]
    assert rows[1][4] == "szkic"
    both = await app_client.get(
        "/api/hr/time/me/export.csv",
        params={"from": "2031-03", "to": "2031-04"},
        headers=h,
    )
    assert len(_rows(both.content)) == 4
    bad = await app_client.get(
        "/api/hr/time/me/export.csv",
        params={"from": "2031-04", "to": "2031-03"},
        headers=h,
    )
    assert bad.status_code == 422


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_person_csv_follows_the_pdf_reader_scope(app_client) -> None:
    boss, worker = await _team()
    await app_client.post(
        f"{BASE}/entries", json=_entry_json(3, 8), headers=headers(worker)
    )
    async with AsyncSessionLocal() as db:
        hr = await make_user(db, "recruiter", profile=False)
        await grant(db, hr, "people_admin")
        stranger = await make_user(db, "recruiter")
        outsider = await make_user(db, "recruiter", profile=False)
        await db.commit()
    path = f"/api/hr/time/people/{worker.id}/export.csv"
    params = {"from": "2031-03", "to": "2031-03"}
    for reader in (boss, hr):
        ok = await app_client.get(path, params=params, headers=headers(reader))
        assert ok.status_code == 200, ok.text
        assert _rows(ok.content)[1][0] == worker.name
    # Kartoteka bez zespołu — 404 bez zdradzania, że osoba istnieje.
    foreign = await app_client.get(path, params=params, headers=headers(stranger))
    assert foreign.status_code == 404
    # Bez kartoteki i bez uprawnień — bramka jak przy PDF.
    refused = await app_client.get(path, params=params, headers=headers(outsider))
    assert refused.status_code == 403
    async with AsyncSessionLocal() as db:
        trail = list(
            await db.scalars(
                select(HrAuditEvent).where(
                    HrAuditEvent.subject_user_id == worker.id,
                    HrAuditEvent.action == "timesheet_csv_exported",
                )
            )
        )
    assert {event.actor_user_id for event in trail} == {boss.id, hr.id}
    assert trail[0].details["rows"] == 1


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_team_month_csv_for_payroll_and_hr_only(app_client) -> None:
    boss, worker = await _team()
    await app_client.post(
        f"{BASE}/entries", json=_entry_json(5, 4, "Analiza"), headers=headers(worker)
    )
    async with AsyncSessionLocal() as db:
        payroll = await make_user(db, "finance", profile=False)
        await grant(db, payroll, "payroll")
        await db.commit()
    path = f"/api/hr/time/export/{Y}/{M}/csv"
    refused = await app_client.get(path, headers=headers(boss))
    assert refused.status_code == 403
    # Audyt 19.10.2026 (zgłoszenie z testów produkcji): odmowa eksportu CSV
    # mówiła o „paczce PDF-ów”.
    assert "PDF" not in refused.json()["detail"]
    response = await app_client.get(path, headers=headers(payroll))
    assert response.status_code == 200, response.text
    assert "godziny-2031-03.csv" in response.headers["content-disposition"]
    mine = [row for row in _rows(response.content)[1:] if row[1] == worker.email]
    assert mine == [
        [
            worker.name,
            worker.email,
            "2031",
            "03",
            "szkic",
            "2031-03-05",
            "4,00",
            "",
            "Analiza",
            "wpis",
            "",
            "",
        ]
    ]
    bad = await app_client.get(
        f"/api/hr/time/export/{Y}/13/csv", headers=headers(payroll)
    )
    assert bad.status_code == 422
