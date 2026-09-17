"""Przypomnienie o wydarzeniu: okno per wydarzenie i odporność na restart.

Dwie historie w jednym pliku.

1. **Restart (sierpień 2026).** Okno było ograniczone z OBU stron
   (`start_time >= now+14min AND <= now+16min`), co dawało każdemu wydarzeniu
   120-sekundowy przedział kwalifikowalności. Każda przerwa między tickami
   dłuższa niż 2 minuty (Coolify przebudowuje backend przy każdym pushu na
   main) gubiła BEZPOWROTNIE pasmo startów. Dolna granica to teraz `now`.
   Duplikatów to nie tworzy: at-most-once gwarantuje trwały stempel
   `reminder_sent_at` + `SELECT ... FOR UPDATE SKIP LOCKED`.

2. **Martwy wybór (audyt 17.09.2026).** Formularz dawał „5/10/30/60 min przed",
   a pętla miała sztywne 16 minut i treść „Za 15 minut". Okno liczy się teraz
   z `reminder_minutes` wydarzenia (sufit doba), wpisy całodniowe i `0` nie
   dostają przypomnienia, a link prowadzi do TEGO wydarzenia.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.api.calendar import _minutes_pl, reminder_due

BACKEND = Path(__file__).resolve().parents[1]
CALENDAR = BACKEND / "app/api/calendar.py"

UTC = timezone.utc


def _source_of(name: str, length: int = 3000) -> str:
    source = CALENDAR.read_text(encoding="utf-8")
    at = source.index(name)
    return source[at : at + length]


# ── Kształt skanu (czytany ze źródła — to on idzie do bazy) ─────────────────


def test_scan_has_no_lower_bound_at_fourteen_minutes() -> None:
    body = _source_of("async def _due_reminder_ids")
    assert "minutes=14" not in body, (
        "dolna granica okna nie może wrócić — to ona zamieniała każdy restart "
        "dłuższy niż 2 minuty w bezpowrotnie utracone przypomnienia"
    )
    assert re.search(r"start_time\s*>\s*now", body), (
        "skan musi mieć granicę `> now` (a nie `>= now+14min`), żeby pierwszy "
        "tick po restarcie dogonił wszystko, co przespał"
    )


def test_window_is_per_event_not_a_fixed_sixteen_minutes() -> None:
    body = _source_of("async def _due_reminder_ids")
    assert "minutes=16" not in body, (
        "sztywne 16 minut robiło wybór w formularzu martwym"
    )
    assert "make_interval" in body and "reminder_minutes" in body
    assert "REMINDER_MAX_MINUTES" in body, (
        "górna granica doby zostaje — bez niej skan czytałby wydarzenia oddalone o tygodnie"
    )
    assert "all_day.is_(False)" in body
    assert "reminder_minutes > 0" in body


def test_loop_uses_the_shared_predicate() -> None:
    body = _source_of("async def calendar_reminder_loop")
    assert "_due_reminder_ids(db, now)" in body


def test_cycle_handler_reports_at_error_level() -> None:
    """Sentry ma `event_level=logging.ERROR` — na WARNING trwale padający cykl
    nie wygenerowałby żadnego zdarzenia i przypomnienia po prostu przestałyby
    przychodzić."""
    body = _source_of("async def calendar_reminder_loop")
    assert "logger.exception(" in body
    assert 'logger.warning(f"Calendar reminder loop error' not in body


def test_notification_links_to_the_event_in_both_places() -> None:
    body = _source_of("async def _dispatch_reminder", 4000)
    assert 'link = f"/calendar?event={event.id}"' in body
    assert body.count("link=link") == 2, (
        "kontrola dostępu i zapisane powiadomienie muszą oceniać TEN SAM link"
    )
    assert 'link="/calendar"' not in body


# ── Czysty predykat ─────────────────────────────────────────────────────────


def test_event_survives_a_six_minute_backend_outage() -> None:
    """Scenariusz z produkcji: rozmowa o 14:00, deploy 13:41-13:47."""
    start = datetime(2026, 8, 21, 14, 0, tzinfo=UTC)
    first_tick_after_restart = datetime(2026, 8, 21, 13, 47, tzinfo=UTC)

    old = (
        first_tick_after_restart + timedelta(minutes=14)
        <= start
        <= first_tick_after_restart + timedelta(minutes=16)
    )
    assert old is False
    assert reminder_due(start, 15, first_tick_after_restart) is True


def test_event_already_started_is_not_picked_up() -> None:
    start = datetime(2026, 8, 21, 14, 0, tzinfo=UTC)
    tick = datetime(2026, 8, 21, 14, 5, tzinfo=UTC)
    assert reminder_due(start, 15, tick) is False


@pytest.mark.parametrize(
    ("minutes", "lead", "expected"),
    [
        (5, timedelta(minutes=5), True),
        (5, timedelta(minutes=6), False),
        (60, timedelta(minutes=59), True),
        (60, timedelta(minutes=60), True),
        (60, timedelta(minutes=61), False),
        (15, timedelta(minutes=16), False),
        (0, timedelta(minutes=1), False),
        (5000, timedelta(hours=23), True),
        (5000, timedelta(hours=25), False),
    ],
)
def test_window_follows_the_chosen_minutes(
    minutes: int, lead: timedelta, expected: bool
) -> None:
    start = datetime(2026, 9, 21, 14, 0, tzinfo=UTC)
    assert reminder_due(start, minutes, start - lead) is expected


def test_polish_minute_plurals() -> None:
    assert _minutes_pl(1) == "1 minutę"
    assert _minutes_pl(3) == "3 minuty"
    assert _minutes_pl(5) == "5 minut"
    assert _minutes_pl(12) == "12 minut"
    assert _minutes_pl(22) == "22 minuty"


# ── Na bazie: skan i zapisany link ──────────────────────────────────────────


async def _seed_user() -> int:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"reminder-{tag}@example.com",
            password_hash=hash_password(f"R3m_{tag}!pw"),
            name=f"Reminder {tag}",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user.id


async def _seed_event(user_id: int, *, lead: timedelta, **extra) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.calendar_event import CalendarEvent, EventStatus, EventType

    start = datetime.now(UTC) + lead
    async with AsyncSessionLocal() as db:
        event = CalendarEvent(
            title=f"Przypomnienie {uuid.uuid4().hex[:6]}",
            event_type=EventType.interview,
            start_time=start,
            end_time=start + timedelta(hours=1),
            status=EventStatus.scheduled,
            created_by=user_id,
            **extra,
        )
        db.add(event)
        await db.commit()
        return event.id


async def test_scan_picks_events_by_their_own_window() -> None:
    from app.api.calendar import _due_reminder_ids
    from app.core.database import AsyncSessionLocal

    user_id = await _seed_user()
    five_due = await _seed_event(user_id, lead=timedelta(minutes=4), reminder_minutes=5)
    five_early = await _seed_event(
        user_id, lead=timedelta(minutes=20), reminder_minutes=5
    )
    hour_due = await _seed_event(
        user_id, lead=timedelta(minutes=50), reminder_minutes=60
    )
    all_day = await _seed_event(
        user_id, lead=timedelta(minutes=4), reminder_minutes=15, all_day=True
    )
    zero = await _seed_event(user_id, lead=timedelta(minutes=1), reminder_minutes=0)

    async with AsyncSessionLocal() as db:
        due = set(await _due_reminder_ids(db, datetime.now(UTC)))

    assert five_due in due
    assert hour_due in due
    assert five_early not in due
    assert all_day not in due, "urlop z Outlooka nie budzi przypomnienia o 01:45"
    assert zero not in due


async def test_dispatch_stores_a_link_to_the_event() -> None:
    from sqlalchemy import select

    from app.api.calendar import _dispatch_reminder
    from app.core.database import AsyncSessionLocal
    from app.models.notification import Notification

    user_id = await _seed_user()
    event_id = await _seed_event(
        user_id, lead=timedelta(minutes=4, seconds=30), reminder_minutes=5
    )

    with patch("app.api.ws.notify_user", new=AsyncMock()):
        await _dispatch_reminder(event_id)

    async with AsyncSessionLocal() as db:
        notes = (
            await db.scalars(
                select(Notification).where(Notification.user_id == user_id)
            )
        ).all()
    assert len(notes) == 1
    assert notes[0].link == f"/calendar?event={event_id}"
    assert notes[0].message.startswith("Za 5 minut:") or notes[0].message.startswith(
        "Za 4 minuty:"
    ), notes[0].message
