"""Runda 9 (R9-N6-2): DL rekrutacji dla Ligi DL, celu DL i raportu DL.

Decyzja Artura 27.09.2026: nieaktywne konto albo konto bez roli Delivery Leada
nie jest DL-em rekrutacji — jej placementy i zapytania idą do głównego DL-a
klienta (aktywnego, z rolą DL). Lustro `job_delivery_lead_fill._HEADS`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.api import reports
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services import competitions


def test_active_dl_with_role_keeps_the_job() -> None:
    fallback = reports.DlFallback({7: 99}, frozenset({5, 99}))
    assert reports._resolve_dl_id(5, 7, fallback) == 5


def test_inactive_or_non_dl_account_falls_back_to_client_head() -> None:
    fallback = reports.DlFallback({7: 99}, frozenset({99}))
    assert reports._resolve_dl_id(5, 7, fallback) == 99
    # Bez głównego DL-a klienta rekrutacja nie ma DL-a.
    assert reports._resolve_dl_id(5, 8, fallback) is None
    assert reports._resolve_dl_id(None, 7, fallback) == 99


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


@pytest.mark.asyncio
async def test_fallback_map_uses_active_dl_heads_only() -> None:
    seen: list[str] = []

    async def fake_execute(stmt, *_a, **_k):
        sql = str(stmt)
        seen.append(sql)
        if "is_head" in sql:
            return _Result([SimpleNamespace(client_id=7, dl_id=99)])
        return _Result([SimpleNamespace(id=99), SimpleNamespace(id=5)])

    fallback = await reports._dl_head_fallback_map(SimpleNamespace(execute=fake_execute))
    assert dict(fallback) == {7: 99}
    assert fallback.eligible_dl_ids == frozenset({5, 99})
    heads_sql = next(s for s in seen if "is_head" in s)
    assert "u.is_active" in heads_sql and "delivery_lead" in heads_sql


# ── Na bazie (CI) ─────────────────────────────────────────────────────────


def _at(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 10, 0, tzinfo=timezone.utc)


async def _user(db, *, role: UserRole, is_active: bool = True) -> User:
    user = User(
        email=f"r9-dl-{uuid.uuid4().hex[:10]}@example.com",
        password_hash=hash_password("x"),
        name="DL runda 9",
        role=role,
        is_active=is_active,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "job_dl_role, job_dl_active",
    [(UserRole.delivery_lead, False), (UserRole.recruiter, True)],
)
async def test_league_credits_client_head_when_job_dl_is_not_a_dl(
    job_dl_role, job_dl_active
) -> None:
    year = 3000 + int(uuid.uuid4().hex[:6], 16) % 900
    async with AsyncSessionLocal() as db:
        former = await _user(db, role=job_dl_role, is_active=job_dl_active)
        head = await _user(db, role=UserRole.delivery_lead)
        client = Client(name=f"R9 DL {uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        db.add(
            DeliveryLeadClientAssignment(
                client_id=client.id, delivery_lead_user_id=head.id, is_head=True
            )
        )
        job = Job(
            title="R9 DL rekrutacja",
            client_id=client.id,
            delivery_lead_id=former.id,
            closed_at=_at(year, 8, 30),
        )
        cand = Candidate(name="R9", lastname=f"DL-{uuid.uuid4().hex[:8]}")
        db.add_all([job, cand])
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage.hired,
                moved_at=_at(year, 8, 10),
                moved_by=head.id,
            )
        )
        await db.commit()

        start, end = competitions.quarter_bounds(year, 3)
        placements, requests = await competitions.dl_portfolio_counts(
            db, start=start, end=end
        )
    assert placements.get(head.id) == 1
    assert requests.get(head.id) == 1
    assert former.id not in placements
    assert former.id not in requests
