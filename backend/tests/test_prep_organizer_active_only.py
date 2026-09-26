"""Podpowiedź organizatora prepu i właściciel sprawy „brak prepu” — tylko osoby
aktywne z dostępem do rekrutacji (runda 6 audytu, X3/IC-2).

Nieaktywny Delivery Lead był podpowiadany do Prepu 1: okno „Zaplanuj prep”
nie pokazywało wtedy nikogo, a zapis kończył się 422 „Organizator jest
nieaktywny”; kolejka i dzwonek „brak prepu” szły na konto osoby, która odeszła.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services import interview_slots, prep_attention, prep_meetings
from app.services.interview_cycle import EventRef, PairSnapshot


def _eligible(*ids):
    async def check(db, user_id, job_id):
        return user_id in ids

    return check


async def _recruiter(db, *, candidate_id, job_id):
    return 33


@pytest.mark.asyncio
async def test_inactive_delivery_lead_is_not_suggested_for_prep_1(monkeypatch):
    monkeypatch.setattr(interview_slots, "default_recruiter_id", _recruiter)
    job = SimpleNamespace(id=5, delivery_lead_id=44)

    monkeypatch.setattr(interview_slots, "slot_recruiter_eligible", _eligible(33))
    assert (
        await prep_meetings.suggest_organizer_id(
            None, job=job, candidate_id=1, prep_no=1
        )
        == 33
    )
    monkeypatch.setattr(interview_slots, "slot_recruiter_eligible", _eligible(33, 44))
    assert (
        await prep_meetings.suggest_organizer_id(
            None, job=job, candidate_id=1, prep_no=1
        )
        == 44
    )


class _Rows:
    def __init__(self, items):
        self._items = items

    def all(self):
        return list(self._items)


class _Db:
    def __init__(self, job):
        self._job = job

    async def execute(self, _statement):
        return _Rows([(1, 5)])

    async def scalars(self, _statement):
        return _Rows([self._job])


@pytest.mark.asyncio
async def test_missing_prep_owner_uses_the_same_suggestion(monkeypatch):
    now = datetime(2026, 9, 29, 8, 0, tzinfo=timezone.utc)
    snap = PairSnapshot(candidate_id=1, job_id=5)
    snap.interview = EventRef(
        id=9, start=now + timedelta(days=2), end=None, title="R", status="scheduled"
    )

    async def snapshots(db, pairs, **kw):
        return {(1, 5): snap}

    monkeypatch.setattr(prep_attention, "load_snapshots", snapshots)
    monkeypatch.setattr(interview_slots, "default_recruiter_id", _recruiter)
    monkeypatch.setattr(interview_slots, "slot_recruiter_eligible", _eligible(33))
    items = await prep_attention.load_prep_attention(
        _Db(SimpleNamespace(id=5, delivery_lead_id=44, recruiter_id=33)), now
    )
    assert {(a.prep_no, a.owner_id) for a in items} == {(1, 33), (2, 33)}
