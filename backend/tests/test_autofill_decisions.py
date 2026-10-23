"""Decyzja o osobie od systemu (silnik „Nowi na 20”, 23.10.2026).

Kontrakty:

- termin to 2 PEŁNE dni robocze (weekend i święta się nie liczą);
- rekrutacja bez rekrutera czeka bez terminu, a dni liczą się od przypisania;
- „Dzwonię” zapisuje decyzję na stałe (pierwsza wygrywa), tylko na wejściu
  z silnika;
- Tablica niesie plakietkę ``entry_autofill`` wyłącznie dla wejścia
  ``system``, a ``/claim`` zapisuje decyzję.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_autofill_pool import JobAutofillPool
from app.models.job_work_assignment import JobWorkAssignment
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User, UserRole
from app.services import autofill_decisions as decisions
from app.services import new_column_autofill as autofill
from app.services.process_entry_meta import autofill_badge

_WARSAW = ZoneInfo("Europe/Warsaw")


def _at(day: int, month: int = 10, hour: int = 10) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=_WARSAW).astimezone(timezone.utc)


# ── reguła bez bazy ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("start", "now", "days"),
    [
        (_at(21), _at(21, hour=18), 0),  # środa → ta sama środa
        (_at(21), _at(22), 1),  # → czwartek
        (_at(21), _at(23), 2),  # → piątek
        (_at(23), _at(26), 1),  # piątek → poniedziałek (weekend się nie liczy)
        (_at(10, 11), _at(12, 11), 1),  # 11.11 święto
    ],
)
def test_business_days_skip_weekends_and_holidays(start, now, days):
    assert decisions.business_days_since(start, now) == days


def test_waiting_days_start_at_the_later_of_entry_and_recruiter():
    meta = {"kind": "autofill", "score": 70}
    # Bez rekrutera — bez terminu.
    assert (
        decisions.waiting_days(
            meta=meta, entered_at=_at(19), recruiter_since=None, now=_at(23)
        )
        is None
    )
    # Rekruter przypisany w czwartek: liczy się od czwartku, nie od dodania.
    assert (
        decisions.waiting_days(
            meta=meta, entered_at=_at(19), recruiter_since=_at(22), now=_at(23)
        )
        == 1
    )
    assert (
        decisions.waiting_days(
            meta=meta, entered_at=_at(19), recruiter_since=_at(1), now=_at(21)
        )
        == 2
    )
    decided = {**meta, "decided_at": _at(20).isoformat()}
    assert (
        decisions.waiting_days(
            meta=decided, entered_at=_at(19), recruiter_since=_at(1), now=_at(23)
        )
        is None
    )


def test_record_call_keeps_the_first_decision_and_ignores_other_entries():
    process = SimpleNamespace(entry_meta={"kind": "autofill", "score": 81})
    assert decisions.record_call(process, 7, _at(21)) is True
    first = process.entry_meta
    assert first["decision"] == "call" and first["decided_by"] == 7
    assert decisions.record_call(process, 8, _at(22)) is False
    assert process.entry_meta["decided_by"] == 7
    other = SimpleNamespace(entry_meta={"kind": "auto_match", "score": 70})
    assert decisions.record_call(other, 7, _at(21)) is False
    assert "decided_at" not in other.entry_meta


def test_badge_carries_only_known_fields():
    meta = {
        "kind": "autofill",
        "score": 80.6,
        "matched_must": ["Java", 5],
        "missing_must": ["AWS"],
        "rate_from_hourly": None,
        "availability_date": "2026-11-01",
        "run_id": "secret-run",
    }
    badge = autofill_badge(meta, waiting_days=2)
    assert badge == {
        "score": 81,
        "matched_must": ["Java", "5"],
        "missing_must": ["AWS"],
        "rate_known": False,
        "availability_known": True,
        "decided": False,
        "waiting_days": 2,
        "decision_due": True,
    }
    assert (
        autofill_badge({"kind": "auto_match", "score": 70}, waiting_days=None) is None
    )
    assert autofill_badge({"kind": "autofill"}, waiting_days=None) is None


# ── baza ────────────────────────────────────────────────────────────────────


async def _user(role: UserRole = UserRole.recruiter) -> tuple[int, str, str]:
    tag = uuid.uuid4().hex[:8]
    email = f"afd-{role.value}-{tag}@example.com"
    password = f"T3st_{tag}!Dec"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"AFD {tag}",
            role=role,
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        return user.id, email, password


async def _job(recruiter_id: int | None) -> int:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"AFD client {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"AFD job {tag}",
            client_id=client.id,
            status=JobStatus.published,
            work_state="searching",
            recruiter_id=recruiter_id,
        )
        db.add(job)
        await db.commit()
        return job.id


async def test_recruiter_since_prefers_the_earliest_active_assignment():
    recruiter, _, _ = await _user()
    with_assignment = await _job(None)
    owner_only = await _job(recruiter)
    nobody = await _job(None)
    async with AsyncSessionLocal() as db:
        db.add(
            JobWorkAssignment(
                job_id=with_assignment,
                user_id=recruiter,
                role="recruiter",
                source="manual",
                state="active",
                assigned_at=_at(20),
            )
        )
        await db.commit()
        since = await decisions.recruiter_since_for_jobs(
            db, [with_assignment, owner_only, nobody]
        )
    assert since[with_assignment] == _at(20)
    assert owner_only in since
    assert nobody not in since


@pytest_asyncio.fixture
async def api_client():
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


async def test_board_shows_the_system_badge_and_claim_records_the_call(
    api_client, monkeypatch
):
    monkeypatch.setattr(autofill, "TARGET", 1)
    recruiter, email, password = await _user()
    job_id = await _job(recruiter)
    async with AsyncSessionLocal() as db:
        candidate = Candidate(name="Od", lastname=f"Systemu-{uuid.uuid4().hex[:6]}")
        db.add(candidate)
        await db.flush()
        db.add(
            JobAutofillPool(
                job_id=job_id,
                candidate_id=candidate.id,
                score=Decimal("81"),
                run_id="run-afd",
                evidence={"matched_must": ["Java"], "missing_must": []},
            )
        )
        await db.commit()
        candidate_id = candidate.id
    async with AsyncSessionLocal() as db:
        assert await autofill.fill_job(db, job_id, now=datetime.now(timezone.utc)) == [
            candidate_id
        ]
        await db.commit()

    login = await api_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    board = await api_client.get(f"/api/pipeline/kanban/{job_id}", headers=headers)
    assert board.status_code == 200, board.text
    cards = [
        item
        for column in board.json()["columns"]
        for item in column["items"]
        if item["candidate_id"] == candidate_id
    ]
    assert len(cards) == 1
    card = cards[0]
    assert card["entry_source"] == "system"
    assert card["entry_autofill"]["score"] == 81
    assert card["entry_autofill"]["matched_must"] == ["Java"]
    assert card["entry_autofill"]["decided"] is False
    assert card.get("claim_user_id") is None

    claim = await api_client.post(
        "/api/pipeline/claim",
        headers=headers,
        json={"candidate_id": candidate_id, "job_id": job_id},
    )
    assert claim.status_code == 200, claim.text
    async with AsyncSessionLocal() as db:
        process = await db.scalar(
            select(RecruitmentProcess).where(
                RecruitmentProcess.candidate_id == candidate_id,
                RecruitmentProcess.job_id == job_id,
            )
        )
    assert process.entry_meta["decision"] == "call"
    assert process.entry_meta["decided_by"] == recruiter
