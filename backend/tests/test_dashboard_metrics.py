"""Własna metryka pulpitu — liczenie i uprawnienia (0336).

Kontrakty:

- ruchy w pipeline liczą PIERWSZE wejście pary na etap (reguła D2, widok
  ``analytics_first_milestones``) — powrót na etap nie dubluje wyniku;
- „moje" = tylko ruchy tej osoby; szerszy zakres niż pozwala konto = 403
  ``metric_scope_denied`` (kafelek mówi „brak dostępu", nie pokazuje zera);
- brak sekcji źródła = 403 z nazwą sekcji;
- kwoty: rekruter nie liczy wcale, Delivery Lead tylko klientów z portfela
  (klient spoza portfela = odmowa całości, nie częściowa suma);
- oś tygodni ma KAŻDY tydzień okna, także pusty.

Baza jest wspólna i nieczyszczona, więc każdy test tworzy własnych
użytkowników i klientów i filtruje po nich.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"
)

URL = "/api/dashboard-metrics/evaluate"


async def _login(role: str = "recruiter", *, sections: dict | None = None):
    import app.models  # noqa: F401
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token
    from app.models.section_permission import UserSectionOverride
    from app.models.user import User, UserRole

    marker = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"metric-{marker}@example.com",
            name=f"Metryka {marker}",
            role=UserRole(role),
            roles=[role],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.flush()
        for section, access in (sections or {}).items():
            db.add(UserSectionOverride(user_id=user.id, section=section, access=access))
        await db.commit()
        uid = user.id
    return {"Authorization": f"Bearer {create_access_token(uid, role)}"}, uid


async def _seed_moves(mover_id: int, *, stages: list[str], when: datetime):
    """Jeden klient, jedna rekrutacja, jeden kandydat przechodzący przez etapy."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    marker = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"metric-client-{marker}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Metryka {marker}", client_id=client.id, status=JobStatus.published
        )
        cand = Candidate(name="Ala", lastname=f"Mx{marker}")
        db.add_all([job, cand])
        await db.flush()
        for i, stage in enumerate(stages):
            db.add(
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=job.id,
                    stage=PipelineStage(stage),
                    moved_by=mover_id,
                    moved_at=when + timedelta(minutes=i),
                )
            )
        await db.commit()
        return client.id


def _moves(client_id: int, **over) -> dict:
    body = {
        "source": "pipeline_moves",
        "measure": "first_reach",
        "stage": "cv_sent",
        "filters": {"author": "me", "client_ids": [client_id]},
        "group_by": "none",
        "period": "last_30_days",
    }
    body.update(over)
    return body


@needs_db
@pytest.mark.asyncio
async def test_first_reach_counts_a_pair_once_even_after_returning_to_the_stage(
    app_client,
):
    headers, uid = await _login()
    when = datetime.now(timezone.utc) - timedelta(days=2)
    client_id = await _seed_moves(
        uid, stages=["cv_sent", "interview", "cv_sent"], when=when
    )

    resp = await app_client.post(URL, headers=headers, json=_moves(client_id))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["value"] == 1.0
    assert body["unit"] == "count"
    assert body["scope_applied"] == "me"


@needs_db
@pytest.mark.asyncio
async def test_me_does_not_count_someone_elses_moves(app_client):
    headers, _ = await _login()
    _, other = await _login()
    when = datetime.now(timezone.utc) - timedelta(days=1)
    client_id = await _seed_moves(other, stages=["cv_sent"], when=when)

    resp = await app_client.post(URL, headers=headers, json=_moves(client_id))
    assert resp.status_code == 200
    assert resp.json()["value"] == 0.0


@needs_db
@pytest.mark.asyncio
async def test_recruiter_asking_for_the_whole_company_is_denied_not_zeroed(app_client):
    headers, _ = await _login()
    body = _moves(1)
    body["filters"]["author"] = "all"
    resp = await app_client.post(URL, headers=headers, json=body)
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "metric_scope_denied"
    assert "moje" in resp.json()["detail"]["message"]


@needs_db
@pytest.mark.asyncio
async def test_funnel_groups_by_stage_in_pipeline_order(app_client):
    headers, uid = await _login()
    when = datetime.now(timezone.utc) - timedelta(days=3)
    client_id = await _seed_moves(
        uid, stages=["cv_sent", "interview", "hired"], when=when
    )

    body = _moves(client_id, stage=None, group_by="stage")
    resp = await app_client.post(URL, headers=headers, json=body)
    assert resp.status_code == 200, resp.text
    series = resp.json()["series"]
    assert [s["key"] for s in series] == ["cv_sent", "interview", "hired"]
    assert [s["label"] for s in series] == ["CV wysłane", "Rozmowa", "Zatrudnieni"]


@needs_db
@pytest.mark.asyncio
async def test_week_axis_has_every_week_even_empty_ones(app_client):
    headers, uid = await _login()
    when = datetime.now(timezone.utc) - timedelta(days=1)
    client_id = await _seed_moves(uid, stages=["cv_sent"], when=when)

    body = _moves(
        client_id, group_by="week", period="last_8_weeks", compare_previous=True
    )
    resp = await app_client.post(URL, headers=headers, json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["series"]) >= 8
    assert sum(s["value"] for s in data["series"]) == 1.0
    assert data["value"] == 1.0
    assert data["previous_value"] == 0.0


@needs_db
@pytest.mark.asyncio
async def test_source_without_section_access_says_which_section(app_client):
    headers, _ = await _login(sections={"sourcing": "none"})
    body = {
        "source": "candidates",
        "measure": "new",
        "filters": {"author": "me"},
        "period": "last_7_days",
    }
    resp = await app_client.post(URL, headers=headers, json=body)
    assert resp.status_code == 403
    assert "Kandydaci" in resp.json()["detail"]["message"]


@needs_db
@pytest.mark.asyncio
async def test_recruiter_cannot_count_money(app_client):
    headers, _ = await _login()
    body = {"source": "finance", "measure": "margin", "period": "this_month"}
    resp = await app_client.post(URL, headers=headers, json=body)
    assert resp.status_code == 403


@needs_db
@pytest.mark.asyncio
async def test_delivery_lead_outside_portfolio_gets_nothing_not_a_partial_sum(
    app_client,
):
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.team_structure import (
        DeliveryLeadClientAssignment,
    )

    headers, uid = await _login("delivery_lead")
    async with AsyncSessionLocal() as db:
        mine = Client(name=f"dl-mine-{uuid.uuid4().hex[:8]}")
        foreign = Client(name=f"dl-foreign-{uuid.uuid4().hex[:8]}")
        db.add_all([mine, foreign])
        await db.flush()
        db.add(
            DeliveryLeadClientAssignment(delivery_lead_user_id=uid, client_id=mine.id)
        )
        await db.commit()
        mine_id, foreign_id = mine.id, foreign.id

    body = {
        "source": "finance",
        "measure": "revenue",
        "filters": {"client_ids": [mine_id, foreign_id]},
        "period": "this_month",
    }
    resp = await app_client.post(URL, headers=headers, json=body)
    assert resp.status_code == 403
    assert "portfela" in resp.json()["detail"]["message"]

    body["filters"]["client_ids"] = [mine_id]
    ok = await app_client.post(URL, headers=headers, json=body)
    assert ok.status_code == 200, ok.text
    assert ok.json()["unit"] == "pln"


@needs_db
@pytest.mark.asyncio
async def test_catalog_marks_unavailable_sources_with_a_reason(app_client):
    headers, _ = await _login()
    resp = await app_client.get("/api/dashboard-metrics/catalog", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    finance = next(s for s in data["sources"] if s["key"] == "finance")
    assert finance["available"] is False and finance["reason"]
    assert data["authors"] == ["me"]


def test_definition_rejects_combinations_the_engine_cannot_count():
    from pydantic import ValidationError

    from app.services.custom_metrics.definition import MetricDefinition

    bad = [
        {"source": "pipeline_moves", "measure": "first_reach"},  # brak etapu
        {"source": "pipeline_moves", "measure": "first_reach", "stage": "screening"},
        {"source": "jobs", "measure": "open_now", "group_by": "week"},
        {"source": "contracts", "measure": "started", "group_by": "recruiter"},
        {"source": "candidates", "measure": "new", "stage": "cv_sent"},
        {"source": "finance", "measure": "margin", "filters": {"job_ids": [1]}},
        {"source": "jobs", "measure": "drop table"},
    ]
    for body in bad:
        with pytest.raises(ValidationError):
            MetricDefinition.model_validate(body)
