"""Raporty KPI mailem (plan PR3, 23.09.2026) — zegar zamrożony w teście.

Pokrywa: poniedziałek 8:00 (tydzień ISO), 1. dzień roboczy miesiąca (święto
i weekend na początku miesiąca), rodzaj wyłączony = zero wysyłek i zero
znacznika, restart = brak duplikatu (UNIQUE kind+period_key w bazie).
Klucze okresów są w losowym, dalekim roku — baza testowa nie jest czyszczona.
"""

from __future__ import annotations

import random
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.kpi_email_report_run import KpiEmailReportRun
from app.models.user import User, UserRole
from app.tasks import kpi_email_reports as reports

WAW = ZoneInfo("Europe/Warsaw")


def _at(day: date, hour: int, minute: int = 5) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=WAW)


def _far_monday() -> date:
    """Poniedziałek między 8. a 14. dniem miesiąca.

    Pierwszy dzień roboczy miesiąca wypada najpóźniej 4. (weekend + święto),
    więc tego dnia należny jest tylko raport tygodniowy. Losowy poniedziałek
    bywał 1. dniem roboczym i wynik dostawał też ``board_monthly_report``.
    """
    base = date(2700 + random.randint(0, 250), random.randint(1, 12), 8)
    return base + timedelta(days=-base.weekday() % 7)


# ── Kiedy raport jest należny ────────────────────────────────────────────────


def test_weekly_is_due_on_monday_from_8_for_the_closed_week() -> None:
    monday = date(2026, 9, 28)
    assert reports.weekly_period_key(_at(monday, 8)) == "2026-W39"
    assert reports.weekly_period_key(_at(monday, 7, 59)) is None
    assert reports.weekly_period_key(_at(monday + timedelta(days=1), 9)) is None


def test_monthly_is_due_on_the_first_business_day() -> None:
    # 1.11.2026 to niedziela → pierwszy dzień roboczy 2.11.
    assert reports.monthly_period_key(_at(date(2026, 11, 1), 9)) is None
    assert reports.monthly_period_key(_at(date(2026, 11, 2), 8)) == "2026-10"
    # 1.01.2026 to święto (czwartek) → pierwszy dzień roboczy 2.01.
    assert reports.monthly_period_key(_at(date(2026, 1, 1), 9)) is None
    assert reports.monthly_period_key(_at(date(2026, 1, 2), 8)) == "2025-12"
    assert reports.monthly_period_key(_at(date(2026, 1, 2), 7)) is None
    assert reports.monthly_period_key(_at(date(2026, 6, 1), 10)) == "2026-05"


def test_rendered_texts_are_polish_and_carry_the_numbers() -> None:
    subject, text = reports.render_weekly(
        {
            "rows": [
                {
                    "user_name": "Anna",
                    "first_verifications": 12,
                    "first_recommendations": 5,
                    "first_placements": 1,
                    "candidates_added": 20,
                }
            ],
            "totals": {"first_verifications": 12, "first_placements": 1},
        },
        "21.09–27.09.2026",
    )
    assert subject == "KPI zespołu — tydzień 21.09–27.09.2026"
    assert "Anna: 12 / 5 / 1 / 20" in text
    subject, text = reports.render_board(
        {"kpis": {"placements": 7, "finance": {"margin_monthly_pln": 123456}}},
        {
            "metrics": [
                {
                    "label": "Marża",
                    "unit": "pln",
                    "series": {"2026": [None] * 8 + [100] + [None] * 3},
                }
            ]
        },
        2026,
        9,
    )
    assert subject == "Podsumowanie Rady — wrzesień 2026"
    assert "Placementy: 7" in text
    assert "Marża / mc: 123 456 zł" in text
    assert "Marża: 100 zł (rok wcześniej —)" in text


# ── Pętla: OFF, wysyłka, restart ─────────────────────────────────────────────


class _Outbox:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def __call__(self, to, subject, text, html=None) -> bool:
        self.sent.append((to, subject))
        return True


@pytest.fixture
def outbox(monkeypatch) -> _Outbox:
    box = _Outbox()
    monkeypatch.setattr("app.services.email.send_email", box)
    monkeypatch.setattr("app.services.email.email_channel_enabled", lambda: True)
    return box


async def _runs(kind: str, key: str) -> list[KpiEmailReportRun]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(KpiEmailReportRun).where(
                        KpiEmailReportRun.kind == kind,
                        KpiEmailReportRun.period_key == key,
                    )
                )
            )
            .scalars()
            .all()
        )


@pytest.mark.asyncio
async def test_disabled_kind_sends_nothing_and_claims_nothing(outbox) -> None:
    monday = _far_monday()
    result = await reports.run_once(_at(monday, 8))
    assert result == {reports.WEEKLY_KIND: "disabled"}
    assert outbox.sent == []
    key = reports.weekly_period_key(_at(monday, 8))
    assert await _runs(reports.WEEKLY_KIND, key) == []


@pytest.mark.asyncio
async def test_weekly_report_goes_out_once_even_after_restart(
    outbox, monkeypatch, routine_notification_email_enabled
) -> None:
    async with AsyncSessionLocal() as db:
        hor = User(
            email=f"kpi-report-hor-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("x"),
            name="HoR raport",
            role=UserRole.head_of_recruitment,
            is_active=True,
        )
        db.add(hor)
        await db.commit()
        await db.refresh(hor)

    async def only_this_hor(db, roles):
        return [await db.get(User, hor.id)]

    monkeypatch.setattr(reports, "_recipients", only_this_hor)
    monday = _far_monday()
    now = _at(monday, 8)
    key = reports.weekly_period_key(now)

    assert await reports.run_once(now) == {reports.WEEKLY_KIND: "sent"}
    assert [to for to, _ in outbox.sent] == [hor.email]
    assert outbox.sent[0][1].startswith("KPI zespołu — tydzień ")

    # Restart kontenera = ten sam tick jeszcze raz: znacznik w bazie blokuje.
    assert await reports.run_once(_at(monday, 9)) == {
        reports.WEEKLY_KIND: "already_claimed"
    }
    assert len(outbox.sent) == 1
    runs = await _runs(reports.WEEKLY_KIND, key)
    assert [(r.status, r.recipients, r.sent) for r in runs] == [("sent", 1, 1)]


@pytest.mark.asyncio
async def test_monthly_report_on_first_business_day(
    outbox, monkeypatch, routine_notification_email_enabled
) -> None:
    async def fake_mails(db, now_local, period_key):
        return [reports._Mail("rada@example.com", f"Rada {period_key}", "treść")]

    monkeypatch.setattr(reports, "_monthly_mails", fake_mails)
    year = 2700 + random.randint(0, 250)
    day = reports.first_business_day(year, 6)
    result = await reports.run_once(_at(day, 8))
    assert result[reports.MONTHLY_KIND] == "sent"
    assert outbox.sent[-1] == ("rada@example.com", f"Rada {year}-05")
    assert await reports.run_once(_at(day, 10)) == {
        **({reports.WEEKLY_KIND: "already_claimed"} if day.weekday() == 0 else {}),
        reports.MONTHLY_KIND: "already_claimed",
    }
