"""Podpowiedź organizatora prepu i właściciel sprawy „brak prepu” — tylko osoby
aktywne z dostępem do rekrutacji (runda 6 audytu, X3/IC-2).

Nieaktywny Delivery Lead był podpowiadany do Prepu 1: okno „Zaplanuj prep”
nie pokazywało wtedy nikogo, a zapis kończył się 422 „Organizator jest
nieaktywny”; kolejka i dzwonek „brak prepu” szły na konto osoby, która odeszła.

Runda 7 (R7-V3-2 / R7-N10-3): kolejka „Czeka na Ciebie” (``GET
/api/board-tasks`` z pulpitu każdego) liczyła tę podpowiedź osobno dla każdego
brakującego prepu — 4–8 zapytań na parę. Liczba zapytań ma być stała.
Runda 7 (X3): sprawa „prep słaby / bez nagrania” organizatora, który odszedł,
wraca do podpowiedzi zamiast przepadać.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models.user import UserRole
from app.services import interview_slots, prep_attention, prep_meetings
from app.services.interview_cycle import EventRef, PairSnapshot

NOW = datetime(2026, 9, 29, 8, 0, tzinfo=timezone.utc)


def _user(uid: int, *, active: bool = True, role: UserRole = UserRole.recruiter):
    return SimpleNamespace(
        id=uid,
        is_active=active,
        has_any_role=lambda *roles: role in roles,
    )


class _Rows:
    def __init__(self, items):
        self._items = items

    def all(self):
        return list(self._items)


class _Db:
    """Udaje bazę dla ścieżki kolejki prepów i liczy KAŻDE zapytanie."""

    def __init__(self, *, pairs, jobs, users, owners=(), verifiers=()):
        self.pairs = pairs
        self.jobs = {job.id: job for job in jobs}
        self.users = {user.id: user for user in users}
        self.owners = list(owners)  # (cid, jid, user_id)
        self.verifiers = list(verifiers)
        self.calls = 0

    @staticmethod
    def _tables(statement) -> list:
        return [
            getattr(getattr(col, "table", None), "name", None)
            for col in statement.selected_columns
        ]

    async def execute(self, statement):
        self.calls += 1
        tables = self._tables(statement)
        if tables[0] == "calendar_events":
            return _Rows(self.pairs)
        if tables[0] == "recruitment_processes":
            return _Rows(self.owners)
        if tables[0] == "candidate_stages":
            return _Rows(self.verifiers)
        if tables[0] == "jobs":
            return _Rows([(j.id, j.recruiter_id) for j in self.jobs.values()])
        raise AssertionError(f"nieoczekiwane zapytanie: {tables}")

    async def scalars(self, statement):
        self.calls += 1
        tables = self._tables(statement)
        if tables[0] == "users":
            return _Rows(self.users.values())
        if tables[0] == "jobs" and len(tables) == 1:
            return _Rows(self.jobs.keys())
        if tables[0] == "jobs":
            return _Rows(self.jobs.values())
        raise AssertionError(f"nieoczekiwane zapytanie: {tables}")

    # Ścieżka sprzed rundy 7 (pojedyncze zapytania) — żeby test umiał ją
    # zmierzyć i pokazać, że rośnie z liczbą par.
    async def scalar(self, statement):
        self.calls += 1
        return None

    async def get(self, model, key):
        self.calls += 1
        return self.users.get(key) or self.jobs.get(key)


def _job(jid: int, *, dl=44, recruiter=33):
    return SimpleNamespace(id=jid, delivery_lead_id=dl, recruiter_id=recruiter)


def _interview_snapshot(cid: int, jid: int, preps=()) -> PairSnapshot:
    snap = PairSnapshot(candidate_id=cid, job_id=jid, preps=list(preps))
    snap.interview = EventRef(
        id=1000 + cid,
        start=NOW + timedelta(days=2),
        end=None,
        title="R",
        status="scheduled",
    )
    return snap


def _patch_snapshots(monkeypatch, snaps: dict):
    async def snapshots(db, pairs, **kw):
        return {pair: snaps[pair] for pair in pairs}

    monkeypatch.setattr(prep_attention, "load_snapshots", snapshots)


@pytest.mark.asyncio
async def test_inactive_delivery_lead_is_not_suggested_for_prep_1():
    job = _job(5, dl=44, recruiter=33)
    db = _Db(
        pairs=[],
        jobs=[job],
        users=[_user(33), _user(44, active=False)],
        owners=[(1, 5, 33)],
    )
    assert (
        await prep_meetings.suggest_organizer_id(db, job=job, candidate_id=1, prep_no=1)
        == 33
    )
    db.users[44] = _user(44, role=UserRole.delivery_lead)
    assert (
        await prep_meetings.suggest_organizer_id(db, job=job, candidate_id=1, prep_no=1)
        == 44
    )
    assert (
        await prep_meetings.suggest_organizer_id(db, job=job, candidate_id=1, prep_no=2)
        == 33
    )


@pytest.mark.asyncio
async def test_default_recruiter_keeps_the_owner_verifier_recruiter_order():
    db = _Db(
        pairs=[],
        jobs=[_job(5, recruiter=35)],
        users=[_user(31, active=False), _user(32), _user(35)],
        owners=[(1, 5, 31)],
        verifiers=[(1, 5, 32)],
    )
    # Właściciel procesu odszedł → pierwszy weryfikator.
    assert (
        await interview_slots.default_recruiter_id(db, candidate_id=1, job_id=5) == 32
    )
    db.users[31] = _user(31)
    assert (
        await interview_slots.default_recruiter_id(db, candidate_id=1, job_id=5) == 31
    )


@pytest.mark.asyncio
async def test_missing_prep_owner_uses_the_same_suggestion(monkeypatch):
    _patch_snapshots(monkeypatch, {(1, 5): _interview_snapshot(1, 5)})
    db = _Db(
        pairs=[(1, 5)],
        jobs=[_job(5, dl=44, recruiter=33)],
        users=[_user(33), _user(44, active=False)],
    )
    items = await prep_attention.load_prep_attention(db, NOW)
    assert {(a.prep_no, a.owner_id) for a in items} == {(1, 33), (2, 33)}


async def _count_queries(monkeypatch, n: int) -> int:
    pairs = [(cid, 100 + cid) for cid in range(1, n + 1)]
    _patch_snapshots(monkeypatch, {p: _interview_snapshot(*p) for p in pairs})
    db = _Db(
        pairs=pairs,
        jobs=[_job(jid, dl=44, recruiter=33) for _cid, jid in pairs],
        users=[_user(33), _user(44, role=UserRole.delivery_lead)],
        owners=[(cid, jid, 33) for cid, jid in pairs],
        verifiers=[(cid, jid, 33) for cid, jid in pairs],
    )
    items = await prep_attention.load_prep_attention(db, NOW)
    assert len(items) == 2 * n
    return db.calls


@pytest.mark.asyncio
async def test_board_tasks_prep_queue_runs_a_constant_number_of_queries(monkeypatch):
    """R7-V3-2: 1 para i 25 par = ta sama liczba zapytań."""
    assert await _count_queries(monkeypatch, 1) == await _count_queries(monkeypatch, 25)


@pytest.mark.asyncio
async def test_weak_prep_of_an_organizer_who_left_goes_to_the_suggestion(monkeypatch):
    """X3: organizator prepu słabego odszedł → sprawa do DL-a (Prep 1)."""
    prep = EventRef(
        id=7,
        start=NOW - timedelta(days=1),
        end=None,
        title="Prep 1",
        status="completed",
        prep_no=1,
        ordinal=1,
        transcript_status="ready",
        review_status="ok",
        review_level="weak",
        owner_id=50,
    )
    _patch_snapshots(monkeypatch, {(1, 5): _interview_snapshot(1, 5, [prep])})
    db = _Db(
        pairs=[(1, 5)],
        jobs=[_job(5, dl=44, recruiter=33)],
        users=[
            _user(33),
            _user(44, role=UserRole.delivery_lead),
            _user(50, active=False),
        ],
    )
    items = await prep_attention.load_prep_attention(db, NOW)
    assert [(a.prep_no, a.owner_id) for a in items if a.reason == "weak"] == [(1, 44)]

    db.users[50] = _user(50)
    items = await prep_attention.load_prep_attention(db, NOW)
    assert [a.owner_id for a in items if a.reason == "weak"] == [50]
