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


async def _no_weekly_mails(db, now_local):
    return []


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
    monkeypatch.setattr(reports, "_weekly_mails", _no_weekly_mails)
    year = 2700 + random.randint(0, 250)
    day = reports.first_business_day(year, 6)
    result = await reports.run_once(_at(day, 8))
    assert result[reports.MONTHLY_KIND] == "sent"
    assert outbox.sent[-1] == ("rada@example.com", f"Rada {year}-05")
    assert await reports.run_once(_at(day, 10)) == {
        **({reports.WEEKLY_KIND: "already_claimed"} if day.weekday() == 0 else {}),
        reports.MONTHLY_KIND: "already_claimed",
    }


def test_board_report_never_goes_to_head_of_recruitment() -> None:
    """Mail zarządu niesie przychód i marżę — HoR ich nie widzi (24.09.2026)."""
    assert UserRole.head_of_recruitment not in reports._BOARD_ROLES
    assert set(reports._BOARD_ROLES) == {UserRole.admin, UserRole.finance}


# ── Runda 7 (R7-N5-2): otwarty bezpiecznik nie gubi raportu ─────────────────


def test_deliver_reports_deferred_when_sender_refused_temporarily(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "M365_APP_MAIL_ENABLED", True)
    monkeypatch.setattr(
        "app.services.notification_delivery.guarded_send", lambda *a, **k: False
    )
    monkeypatch.setattr(
        "app.services.notification_delivery.last_send_policy_blocked", lambda: False
    )
    monkeypatch.setattr(
        "app.services.m365.app_mail.last_delivery_deferred", lambda: True
    )
    mail = reports._Mail("rada@example.com", "s", "t")
    assert reports._deliver(reports.MONTHLY_KIND, datetime.now(WAW), mail) == (
        "deferred"
    )
    # Blokada polityki to nie odroczenie — raport nie ma wyjść.
    monkeypatch.setattr(
        "app.services.notification_delivery.last_send_policy_blocked", lambda: True
    )
    assert reports._deliver(reports.MONTHLY_KIND, datetime.now(WAW), mail) == ("failed")


@pytest.mark.asyncio
async def test_deferred_recipients_are_retried_on_next_tick(
    outbox, monkeypatch, routine_notification_email_enabled
) -> None:
    async def fake_mails(db, now_local, period_key):
        return [
            reports._Mail("a@example.com", f"Rada {period_key}", "treść"),
            reports._Mail("b@example.com", f"Rada {period_key}", "treść"),
        ]

    outcomes = {"a@example.com": ["sent"], "b@example.com": ["deferred", "sent"]}
    delivered: list[str] = []

    def fake_deliver(kind, now_utc, mail):
        outcome = outcomes[mail.to].pop(0)
        if outcome == "sent":
            delivered.append(mail.to)
        return outcome

    monkeypatch.setattr(reports, "_monthly_mails", fake_mails)
    monkeypatch.setattr(reports, "_weekly_mails", _no_weekly_mails)
    monkeypatch.setattr(reports, "_deliver", fake_deliver)
    year = 2700 + random.randint(0, 250)
    day = reports.first_business_day(year, 7)
    key = f"{year}-06"

    first = await reports.run_once(_at(day, 8))
    assert first[reports.MONTHLY_KIND] == "sent"
    assert delivered == ["a@example.com"]

    second = await reports.run_once(_at(day, 8, 15))
    assert second[reports.MONTHLY_KIND] == "sent"
    # Drugi raz wyszedł wyłącznie mail odroczony — bez duplikatu do „a”.
    assert delivered == ["a@example.com", "b@example.com"]
    runs = await _runs(reports.MONTHLY_KIND, key)
    assert [(r.status, r.recipients, r.sent) for r in runs] == [("sent", 2, 2)]

    third = await reports.run_once(_at(day, 8, 25))
    assert third[reports.MONTHLY_KIND] == "already_claimed"


@pytest.mark.asyncio
async def test_new_period_drops_stale_pending_of_the_same_kind(
    outbox, monkeypatch, routine_notification_email_enabled
) -> None:
    """R8-V3-10: odroczeni z poprzedniego okresu nie wiszą w `app_settings`
    na zawsze — nowy okres tego samego raportu sprząta stare wpisy."""
    from app.models.app_setting import AppSetting

    async def fake_mails(db, now_local, period_key):
        return [reports._Mail("rada@example.com", f"Rada {period_key}", "t")]

    monkeypatch.setattr(reports, "_monthly_mails", fake_mails)
    monkeypatch.setattr(reports, "_weekly_mails", _no_weekly_mails)
    year = 2700 + random.randint(0, 250)
    stale = reports._pending_key(reports.MONTHLY_KIND, f"{year}-01")
    other_kind = f"{reports._PENDING_PREFIX}other_report:{year}-01"
    async with AsyncSessionLocal() as db:
        for key in (stale, other_kind):
            await db.merge(AppSetting(key=key, value={"to": ["x@example.com"]}))
        await db.commit()

    day = reports.first_business_day(year, 3)
    result = await reports.run_once(_at(day, 8))
    assert result[reports.MONTHLY_KIND] == "sent"
    async with AsyncSessionLocal() as db:
        assert await db.get(AppSetting, stale) is None
        # Inny rodzaj raportu nie jest ruszany.
        assert await db.get(AppSetting, other_kind) is not None
        await db.delete(await db.get(AppSetting, other_kind))
        await db.commit()


# ── Runda 9 (R9-N6-3): raport nie przepada po awarii liczenia ani restarcie ──


def _r9_year() -> int:
    return 2951 + random.randint(0, 48)


@pytest.mark.asyncio
async def test_failed_build_is_retried_on_next_tick(
    outbox, monkeypatch, routine_notification_email_enabled
) -> None:
    calls = {"n": 0}

    async def flaky_mails(db, now_local, period_key):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("chwilowa awaria")
        return [reports._Mail("rada-r9@example.com", f"Rada {period_key}", "t")]

    monkeypatch.setattr(reports, "_monthly_mails", flaky_mails)
    year = _r9_year()
    day = reports.first_business_day(year, 9)
    key = f"{year}-08"

    first = await reports.run_once(_at(day, 8))
    assert first[reports.MONTHLY_KIND] == "failed"
    second = await reports.run_once(_at(day, 8, 15))
    assert second[reports.MONTHLY_KIND] == "sent"
    assert [to for to, _ in outbox.sent] == ["rada-r9@example.com"]
    runs = await _runs(reports.MONTHLY_KIND, key)
    assert [(r.status, r.recipients, r.sent) for r in runs] == [("sent", 1, 1)]


async def _seed_claim(key: str, *, age_minutes: int) -> None:
    from sqlalchemy import func as sa_func

    async with AsyncSessionLocal() as db:
        db.add(
            KpiEmailReportRun(
                kind=reports.MONTHLY_KIND,
                period_key=key,
                status="claimed",
                claimed_at=(await db.scalar(select(sa_func.now())))
                - timedelta(minutes=age_minutes),
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_stale_claim_after_restart_is_taken_over(
    outbox, monkeypatch, routine_notification_email_enabled
) -> None:
    async def fake_mails(db, now_local, period_key):
        return [reports._Mail("rada-r9b@example.com", f"Rada {period_key}", "t")]

    monkeypatch.setattr(reports, "_monthly_mails", fake_mails)
    # Dzień testu bywa poniedziałkiem: bez tego raport tygodniowy idzie do
    # wszystkich HoR na wspólnej bazie CI i psuje asercje skrzynki.
    monkeypatch.setattr(reports, "_weekly_mails", _no_weekly_mails)
    year = _r9_year()
    day = reports.first_business_day(year, 10)
    key = f"{year}-09"
    await _seed_claim(key, age_minutes=reports.STALE_CLAIM_MINUTES + 10)

    result = await reports.run_once(_at(day, 9))
    assert result[reports.MONTHLY_KIND] == "sent"
    assert [to for to, _ in outbox.sent] == ["rada-r9b@example.com"]
    runs = await _runs(reports.MONTHLY_KIND, key)
    assert [(r.status, r.sent) for r in runs] == [("sent", 1)]


@pytest.mark.asyncio
async def test_fresh_claim_is_left_to_the_running_container(
    outbox, monkeypatch, routine_notification_email_enabled
) -> None:
    async def fake_mails(db, now_local, period_key):
        return [reports._Mail("rada-r9c@example.com", f"Rada {period_key}", "t")]

    monkeypatch.setattr(reports, "_monthly_mails", fake_mails)
    # Dzień testu bywa poniedziałkiem: bez tego raport tygodniowy idzie do
    # wszystkich HoR na wspólnej bazie CI i psuje asercje skrzynki.
    monkeypatch.setattr(reports, "_weekly_mails", _no_weekly_mails)
    year = _r9_year()
    day = reports.first_business_day(year, 11)
    key = f"{year}-10"
    await _seed_claim(key, age_minutes=1)

    result = await reports.run_once(_at(day, 9))
    assert result[reports.MONTHLY_KIND] == "already_claimed"
    assert outbox.sent == []
    # Sprzątanie: znacznik zakończony, nie „w toku” na wspólnej bazie.
    async with AsyncSessionLocal() as db:
        run = (
            await db.execute(
                select(KpiEmailReportRun).where(
                    KpiEmailReportRun.kind == reports.MONTHLY_KIND,
                    KpiEmailReportRun.period_key == key,
                )
            )
        ).scalar_one()
        run.status = "skipped"
        run.finished_at = datetime.now(WAW)
        await db.commit()


@pytest.mark.asyncio
async def test_interrupted_send_resumes_only_remaining_recipients(
    outbox, monkeypatch, routine_notification_email_enabled
) -> None:
    from app.models.app_setting import AppSetting

    async def fake_mails(db, now_local, period_key):
        return [
            reports._Mail("a-r9@example.com", f"Rada {period_key}", "t"),
            reports._Mail("b-r9@example.com", f"Rada {period_key}", "t"),
        ]

    monkeypatch.setattr(reports, "_monthly_mails", fake_mails)
    # Dzień testu bywa poniedziałkiem: bez tego raport tygodniowy idzie do
    # wszystkich HoR na wspólnej bazie CI i psuje asercje skrzynki.
    monkeypatch.setattr(reports, "_weekly_mails", _no_weekly_mails)
    year = _r9_year()
    day = reports.first_business_day(year, 12)
    key = f"{year}-11"
    await _seed_claim(key, age_minutes=reports.STALE_CLAIM_MINUTES + 10)
    async with AsyncSessionLocal() as db:
        await db.merge(
            AppSetting(
                key=reports._pending_key(reports.MONTHLY_KIND, key),
                value={"to": ["b-r9@example.com"]},
            )
        )
        await db.commit()

    result = await reports.run_once(_at(day, 9))
    assert result[reports.MONTHLY_KIND] == "sent"
    assert [to for to, _ in outbox.sent] == ["b-r9@example.com"]
    async with AsyncSessionLocal() as db:
        assert (
            await db.get(AppSetting, reports._pending_key(reports.MONTHLY_KIND, key))
            is None
        )
