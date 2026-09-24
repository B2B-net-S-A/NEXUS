"""Fakty o osobach z propozycji (`GET /api/jobs/{id}/proposal-facts`).

Część pierwsza — czyste funkcje (bez bazy). Część druga — prawdziwy Postgres
i autoryzacja; baza testowa jest wspólna, więc test zakłada własnego klienta,
rekrutacje i osoby.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from httpx import AsyncClient

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services import proposal_facts
from app.services.proposal_facts import StageRow

T0 = datetime(2026, 5, 1, 10, tzinfo=timezone.utc)


# ── Czyste funkcje ──────────────────────────────────────────────────────────


def test_client_history_picks_the_furthest_job_and_its_outcome():
    rows = [
        # Rekrutacja 1: doszedł do „CV Wysłane”, potem odrzucony.
        StageRow(1, 10, "Java Dev", PipelineStage.new, T0),
        StageRow(1, 10, "Java Dev", PipelineStage.cv_sent, T0 + timedelta(days=2)),
        StageRow(1, 10, "Java Dev", PipelineStage.rejected, T0 + timedelta(days=5)),
        # Rekrutacja 2: tylko „Zweryfikowany” — przegrywa mimo świeższej daty.
        StageRow(1, 11, "Kotlin Dev", PipelineStage.verified, T0 + timedelta(days=30)),
        # Inna osoba — jedynie odrzucona od razu: brak etapu „do przodu”.
        StageRow(2, 12, "QA", PipelineStage.rejected, T0),
    ]
    history = proposal_facts.client_history(rows)
    assert history[1] == {
        "job_id": 10,
        "title": "Java Dev",
        "furthest_stage": "cv_sent",
        "furthest_stage_label": "CV Wysłane",
        "outcome": "rejected",
        "last_moved_at": (T0 + timedelta(days=5)).isoformat(),
    }
    assert 2 not in history


def test_client_history_tie_goes_to_the_fresher_job_and_hired_is_an_outcome():
    rows = [
        StageRow(1, 10, "A", PipelineStage.hired, T0),
        StageRow(1, 11, "B", PipelineStage.hired, T0 + timedelta(days=1)),
        StageRow(3, 13, "C", "screening", None),
    ]
    history = proposal_facts.client_history(rows)
    assert history[1]["job_id"] == 11
    assert history[1]["outcome"] == "hired"
    assert history[3]["outcome"] == "in_progress"
    assert history[3]["last_moved_at"] is None


def test_current_title_falls_back_to_the_first_cv_role():
    candidate = SimpleNamespace(
        linkedin_current_title=None,
        linkedin_current_company=" ",
        experience=[{"role": "Senior Tester", "company": "Firma"}],
    )
    assert proposal_facts.current_title(candidate) == ("Senior Tester", "Firma")
    linkedin = SimpleNamespace(
        linkedin_current_title="Architekt",
        linkedin_current_company="X",
        experience=[{"role": "Stare", "company": "Y"}],
    )
    assert proposal_facts.current_title(linkedin) == ("Architekt", "X")


def test_candidate_facts_redacts_the_rate_and_carries_no_contact():
    candidate = SimpleNamespace(
        id=5,
        linkedin_current_title="Dev",
        linkedin_current_company=None,
        experience=[],
        years_it_experience=7,
        city=None,
        location="Kraków",
        max_onsite_days_per_week=0,
        preferences={"remote_modes": ["remote", 3]},
        availability_status=SimpleNamespace(value="open_to_offers"),
        availability_date=None,
        expected_rate_hourly=Decimal("160"),
        expected_rate_currency="PLN",
        email="x@example.com",
        phone="600",
    )
    facts = proposal_facts.candidate_facts(candidate, include_rate=False, history=None)
    assert facts["expected_rate_hourly"] is None
    assert facts["expected_rate_redacted"] is True
    assert facts["city"] == "Kraków"
    assert facts["remote_modes"] == ["remote"]
    assert facts["availability_status"] == "open_to_offers"
    assert "email" not in facts and "phone" not in facts
    visible = proposal_facts.candidate_facts(candidate, include_rate=True, history=None)
    assert visible["expected_rate_hourly"] == 160.0
    assert visible["expected_rate_currency"] == "PLN"


# ── API ─────────────────────────────────────────────────────────────────────


async def _recruiter_headers() -> dict[str, str]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"facts-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Facts"),
            name="Facts recruiter",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return {"Authorization": f"Bearer {create_access_token(user.id, 'recruiter')}"}


async def test_proposal_facts_endpoint(app_client: AsyncClient, app_auth_headers: dict):
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Facts client {tag}")
        other = Client(name=f"Facts other {tag}")
        db.add_all([client, other])
        await db.flush()
        job = Job(
            title=f"Facts job {tag}", client_id=client.id, status=JobStatus.published
        )
        old_job = Job(
            title=f"Old job {tag}", client_id=client.id, status=JobStatus.closed
        )
        foreign_job = Job(
            title=f"Foreign {tag}", client_id=other.id, status=JobStatus.closed
        )
        person = Candidate(
            name="Fakt",
            lastname=f"A-{tag}",
            email=f"facts-a-{tag}@example.com",
            city="Gdańsk",
            years_it_experience=6,
            linkedin_current_title="Java Developer",
            expected_rate_hourly=Decimal("150"),
        )
        stranger = Candidate(
            name="Fakt", lastname=f"B-{tag}", email=f"facts-b-{tag}@example.com"
        )
        db.add_all([job, old_job, foreign_job, person, stranger])
        await db.flush()
        db.add_all(
            [
                CandidateStage(
                    candidate_id=person.id,
                    job_id=old_job.id,
                    stage=PipelineStage.cv_sent,
                ),
                CandidateStage(
                    candidate_id=stranger.id,
                    job_id=foreign_job.id,
                    stage=PipelineStage.hired,
                ),
            ]
        )
        await db.commit()
        ids = [person.id, stranger.id]
        job_id = job.id
        old_title = old_job.title

    url = f"/api/jobs/{job_id}/proposal-facts"
    params = [("candidate_ids", i) for i in ids]
    as_admin = await app_client.get(url, params=params, headers=app_auth_headers)
    assert as_admin.status_code == 200, as_admin.text
    items = {i["candidate_id"]: i for i in as_admin.json()["items"]}
    assert items[ids[0]]["title"] == "Java Developer"
    assert items[ids[0]]["years_experience"] == 6
    assert items[ids[0]]["expected_rate_hourly"] == 150.0
    assert items[ids[0]]["client_history"]["title"] == old_title
    assert items[ids[0]]["client_history"]["furthest_stage"] == "cv_sent"
    assert "email" not in items[ids[0]]
    # Historia u INNEGO klienta nie jest historią u tego.
    assert items[ids[1]]["client_history"] is None

    recruiter = await _recruiter_headers()
    as_recruiter = await app_client.get(url, params=params, headers=recruiter)
    assert as_recruiter.status_code == 200, as_recruiter.text
    first = next(i for i in as_recruiter.json()["items"] if i["candidate_id"] == ids[0])
    assert first["expected_rate_hourly"] is None
    assert first["expected_rate_redacted"] is True

    too_many = [("candidate_ids", i) for i in range(1, 102)]
    refused = await app_client.get(url, params=too_many, headers=app_auth_headers)
    assert refused.status_code == 422
    assert (await app_client.get(url, params=params)).status_code == 401
