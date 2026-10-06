"""Poranny dzwonek „Do przejrzenia” (audyt 06.10.2026, R3): awaria dzwonka
jednego odbiorcy nie psuje pozostałych.

Ten sam kontrakt co runda 9 (R9-X1-7) dla dawnego skrótu z nowych CV:
każdy odbiorca w osobnym savepoincie, nigdy ``db.rollback()`` całej sesji
(cofałby dzwonki zapisane wcześniej w tym przebiegu).
"""

from __future__ import annotations

from datetime import datetime, timezone

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


@pytest.mark.asyncio
async def test_failed_bell_rolls_back_only_its_own_savepoint(monkeypatch) -> None:
    from app.services import notification_triggers

    async def fake_plan(db, now):
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
    monkeypatch.setattr(bell, "_DONE_FOR", None)
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

    async def fake_plan(db, now):
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
    monkeypatch.setattr(bell, "_DONE_FOR", None)
    monkeypatch.setattr(job_team, "recruiters_for_jobs", fake_team)
    monkeypatch.setattr(notification_triggers, "emit", fake_emit)

    assert await bell.send_morning_bells(_Db(), _MORNING) == 0
    assert emitted == []


@pytest.mark.asyncio
async def test_bell_rings_once_a_day_and_only_in_working_hours(monkeypatch) -> None:
    planned: list[datetime] = []

    async def fake_plan(db, now):
        planned.append(now)
        return {}

    monkeypatch.setattr(bell, "_plan", fake_plan)
    monkeypatch.setattr(bell, "_DONE_FOR", None)

    evening = datetime(2026, 10, 7, 17, 30, tzinfo=timezone.utc)  # 19:30 PL
    assert await bell.send_morning_bells(_Db(), evening) == 0
    assert planned == []
    assert await bell.send_morning_bells(_Db(), _MORNING) == 0
    assert await bell.send_morning_bells(_Db(), _MORNING) == 0
    assert planned == [_MORNING]


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
