"""Poranny dzwonek „Do przejrzenia” (audyt 06.10.2026, R3): awaria dzwonka
jednego odbiorcy nie psuje pozostałych.

Ten sam kontrakt co runda 9 (R9-X1-7) dla dawnego skrótu z nowych CV:
każdy odbiorca w osobnym savepoincie, nigdy ``db.rollback()`` całej sesji
(cofałby dzwonki zapisane wcześniej w tym przebiegu).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import job_team
from app.services import proposals_morning_bell as bell


class _Savepoint:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    async def __aenter__(self) -> "_Savepoint":
        self.log.append("savepoint")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self.log.append("savepoint_rollback" if exc_type else "savepoint_release")
        return False


class _Rows:
    def all(self) -> list:
        return []


class _Db:
    def __init__(self) -> None:
        self.log: list[str] = []

    def begin_nested(self) -> _Savepoint:
        return _Savepoint(self.log)

    async def execute(self, *_a, **_k) -> _Rows:
        return _Rows()

    async def rollback(self) -> None:
        self.log.append("SESSION_ROLLBACK")


# 09:00 czasu firmy (Europe/Warsaw, CEST) — w oknie dzwonka.
_MORNING = datetime(2026, 10, 7, 7, 0, tzinfo=timezone.utc)


def _memory_state(monkeypatch) -> dict:
    """Stan dzwonka (``app_settings``) w pamięci testu."""
    state: dict = {}

    async def load(db):
        return dict(state)

    async def save(db, value):
        state.clear()
        state.update(value)

    monkeypatch.setattr(bell, "_load_state", load)
    monkeypatch.setattr(bell, "_save_state", save)
    return state


@pytest.mark.asyncio
async def test_failed_bell_rolls_back_only_its_own_savepoint(monkeypatch) -> None:
    from app.services import notification_triggers

    async def fake_plan(db, since):
        return {1: [101], 2: [202]}

    async def fake_team(db, job_ids):
        return {
            1: [
                job_team.TeamPerson(user_id=10, name="A", role="recruiter", via="owner")
            ],
            2: [
                job_team.TeamPerson(user_id=11, name="B", role="recruiter", via="owner")
            ],
        }

    calls: list[int] = []

    async def fake_emit(db, *, user_id, related_entity_id, **kwargs):
        calls.append(related_entity_id)
        if related_entity_id == 1:
            raise RuntimeError("zapis padł")
        return object()

    monkeypatch.setattr(bell, "_plan", fake_plan)
    _memory_state(monkeypatch)
    monkeypatch.setattr(job_team, "recruiters_for_jobs", fake_team)
    monkeypatch.setattr(notification_triggers, "emit", fake_emit)
    db = _Db()

    sent = await bell.send_morning_bells(db, _MORNING)

    assert calls == [1, 2]
    assert sent == 1
    assert "SESSION_ROLLBACK" not in db.log
    # Plan w swoim savepoincie, potem po jednym na odbiorcę.
    assert db.log == [
        "savepoint",
        "savepoint_release",
        "savepoint",
        "savepoint_rollback",
        "savepoint",
        "savepoint_release",
    ]


@pytest.mark.asyncio
async def test_proposed_recruiter_gets_no_bell(monkeypatch) -> None:
    """Propozycja automatu czekająca na akceptację nie jest Rekruterem."""
    from app.services import notification_triggers

    async def fake_plan(db, since):
        return {1: [101]}

    async def fake_team(db, job_ids):
        return {
            1: [
                job_team.TeamPerson(
                    user_id=10,
                    name="A",
                    role="recruiter",
                    via="assignment",
                    proposed=True,
                )
            ]
        }

    emitted: list[int] = []

    async def fake_emit(db, *, user_id, **kwargs):
        emitted.append(user_id)
        return object()

    monkeypatch.setattr(bell, "_plan", fake_plan)
    _memory_state(monkeypatch)
    monkeypatch.setattr(job_team, "recruiters_for_jobs", fake_team)
    monkeypatch.setattr(notification_triggers, "emit", fake_emit)

    assert await bell.send_morning_bells(_Db(), _MORNING) == 0
    assert emitted == []


@pytest.mark.asyncio
async def test_bell_rings_once_a_day_and_only_in_working_hours(monkeypatch) -> None:
    planned: list[datetime] = []

    async def fake_plan(db, since):
        planned.append(since)
        return {}

    monkeypatch.setattr(bell, "_plan", fake_plan)
    _memory_state(monkeypatch)

    evening = datetime(2026, 10, 7, 17, 30, tzinfo=timezone.utc)  # 19:30 PL
    assert await bell.send_morning_bells(_Db(), evening) == 0
    assert planned == []
    assert await bell.send_morning_bells(_Db(), _MORNING) == 0
    assert await bell.send_morning_bells(_Db(), _MORNING) == 0
    # Pierwszy dzwonek bez zapamiętanego stanu: od 8:00 poprzedniego dnia
    # roboczego (wtorek 6.10 8:00 CEST = 6:00 UTC).
    assert planned == [datetime(2026, 10, 6, 6, 0, tzinfo=timezone.utc)]

    # Następny dzień: okno zaczyna się od poprzedniego dzwonka.
    planned.clear()
    next_morning = _MORNING + timedelta(days=1)
    assert await bell.send_morning_bells(_Db(), next_morning) == 0
    assert planned == [_MORNING]


@pytest.mark.parametrize(
    "now_local,expected_local",
    [
        # Poniedziałek: od piątku 8:00 — propozycje z weekendu się nie gubią.
        ((2026, 10, 12, 9, 0), (2026, 10, 9, 8, 0)),
        # Wtorek po Poniedziałku Wielkanocnym: od Wielkiego Piątku.
        ((2026, 4, 7, 9, 30), (2026, 4, 3, 8, 0)),
        # Zwykły dzień: od 8:00 dnia poprzedniego.
        ((2026, 10, 7, 10, 0), (2026, 10, 6, 8, 0)),
    ],
)
def test_first_bell_window_starts_at_8_on_the_previous_business_day(
    now_local, expected_local
) -> None:
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Europe/Warsaw")
    now = datetime(*now_local, tzinfo=tz)
    assert bell.window_start(now, last_sent_at=None) == datetime(
        *expected_local, tzinfo=tz
    )


def test_window_starts_at_the_previous_bell_but_never_older_than_a_week() -> None:
    last = _MORNING - timedelta(days=3, hours=1)
    assert bell.window_start(_MORNING, last_sent_at=last) == last
    long_ago = _MORNING - timedelta(days=30)
    assert bell.window_start(_MORNING, last_sent_at=long_ago) == (
        _MORNING - timedelta(days=7)
    )


def test_bell_wording() -> None:
    assert bell.people_phrase(1) == "1 nowa osoba"
    assert bell.people_phrase(3) == "3 nowe osoby"
    assert bell.people_phrase(5) == "5 nowych osób"
    assert bell.people_phrase(12) == "12 nowych osób"
    assert bell.people_phrase(22) == "22 nowe osoby"
    assert bell.bell_title(2, "Java Developer") == (
        "Do przejrzenia: 2 nowe osoby — Java Developer"
    )
    assert bell.bell_message(["Anna Nowak", "Jan Kowal", "Ewa Lis"], 5) == (
        "Od wczoraj w „Do przejrzenia”: Anna Nowak, Jan Kowal, Ewa Lis i 2 innych. "
        "Dodaj do „Nowych” albo pomiń z powodem."
    )
    assert bell.bell_message(["Anna Nowak"], 1).startswith(
        "Od wczoraj w „Do przejrzenia”: Anna Nowak. "
    )
