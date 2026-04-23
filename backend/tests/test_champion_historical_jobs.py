"""Tests for the `historical_jobs` Champion Profile suggestion source (Phase 15).

Two families:
  - Pure-function unit tests for `skill_frequency` and `_build_query_text`
    (no DB, no LLM, no Qdrant).
  - Async service + API tests with Qdrant search, Voyage embed, and Claude
    patched to deterministic fakes.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.historical_jobs_retrieval import (
    HistoricalJobMatch,
    _build_query_text,
    _extract_skill_name,
    skill_frequency,
)


# ── Pure-function tests ─────────────────────────────────────────────────────


def _make_match(
    job_id: int,
    similarity: float,
    must: list,
    nice: list | None = None,
    *,
    champion_profile: dict | None = None,
    seniority: str | None = "senior",
) -> HistoricalJobMatch:
    return HistoricalJobMatch(
        job_id=job_id,
        title=f"Senior Dev #{job_id}",
        similarity=similarity,
        closed_at=None,
        client_id=1,
        client_name="Nordea",
        champion_profile=champion_profile
        or {"project_context": {"about": "Test"}},
        must_skills=must,
        nice_skills=nice or [],
        seniority=seniority,
    )


def test_skill_frequency_empty_sample_returns_zero_counts():
    result = skill_frequency([])
    assert result["n"] == 0
    assert result["must"] == []
    assert result["consistent_must"] == []


def test_skill_frequency_aggregates_and_marks_consistent():
    matches = [
        _make_match(1, 0.9, [{"name": "Python"}, {"name": "AWS"}]),
        _make_match(2, 0.88, [{"name": "Python"}, {"name": "AWS"}]),
        _make_match(3, 0.85, [{"name": "Python"}, {"name": "Kafka"}]),
        _make_match(4, 0.80, [{"name": "Python"}]),
        _make_match(5, 0.75, [{"name": "Go"}]),
    ]
    result = skill_frequency(matches)
    assert result["n"] == 5
    by_name = {entry["name"]: entry for entry in result["must"]}
    assert by_name["Python"]["count"] == 4
    assert by_name["Python"]["fraction"] == pytest.approx(0.8)
    assert by_name["AWS"]["count"] == 2
    assert by_name["Go"]["count"] == 1
    # Python >= 0.6, AWS < 0.6, Go < 0.6
    assert "Python" in result["consistent_must"]
    assert "AWS" not in result["consistent_must"]
    assert "Go" not in result["consistent_must"]


def test_skill_frequency_dedupes_within_single_match_and_handles_case():
    # One match listing Python twice + mixed case should still count as 1.
    matches = [
        _make_match(
            1,
            0.9,
            [{"name": "Python"}, {"name": "python"}, {"name": "PYTHON"}],
        ),
        _make_match(2, 0.85, [{"name": "Python"}]),
    ]
    result = skill_frequency(matches)
    must = {entry["name"].lower(): entry for entry in result["must"]}
    assert must["python"]["count"] == 2
    assert must["python"]["fraction"] == pytest.approx(1.0)


def test_skill_frequency_accepts_bare_strings_and_missing_names():
    matches = [
        _make_match(1, 0.9, ["Python", {"name": "AWS"}, {"level": "senior"}]),
        _make_match(2, 0.85, ["python", "AWS"]),
    ]
    result = skill_frequency(matches)
    names = {entry["name"].lower() for entry in result["must"]}
    assert "python" in names
    assert "aws" in names


def test_skill_frequency_threshold_override():
    matches = [
        _make_match(1, 0.9, [{"name": "Python"}]),
        _make_match(2, 0.9, [{"name": "Python"}]),
    ]
    strict = skill_frequency(matches, threshold=1.01)
    lax = skill_frequency(matches, threshold=0.1)
    assert strict["consistent_must"] == []
    assert "Python" in lax["consistent_must"]


def test_extract_skill_name_variants():
    assert _extract_skill_name({"name": "Python"}) == "Python"
    assert _extract_skill_name("Java") == "Java"
    assert _extract_skill_name({"name": ""}) is None
    assert _extract_skill_name({}) is None
    assert _extract_skill_name(None) is None
    assert _extract_skill_name(123) is None


def test_build_query_text_combines_title_and_truncates_description():
    text = _build_query_text(
        title="Senior Python Dev",
        raw_description="x" * 2000,
    )
    # title preserved, description truncated to 1200 chars
    assert text.startswith("Senior Python Dev")
    assert len(text) <= 1300


def test_build_query_text_handles_missing_description():
    text = _build_query_text(title="Java Developer", raw_description=None)
    assert text == "Java Developer"


def test_build_query_text_empty_inputs_return_empty():
    assert _build_query_text(title="", raw_description="") == ""
    assert _build_query_text(title="   ", raw_description=None) == ""


# ── Async: find_similar_historical_jobs ─────────────────────────────────────


@pytest.mark.asyncio
async def test_find_similar_returns_empty_when_embedding_unavailable():
    """If Voyage and Ollama both fail, retrieval must degrade to []."""
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services import historical_jobs_retrieval

    with patch.object(
        historical_jobs_retrieval, "generate_embedding", new=AsyncMock(return_value=None)
    ):
        result = await historical_jobs_retrieval.find_similar_historical_jobs(
            db=MagicMock(spec=AsyncSession),
            client_id=1,
            title="Senior Python",
            raw_description="desc",
            top_k=5,
        )
    assert result == []


# ── Async: generate_from_historical_jobs ────────────────────────────────────


HISTORICAL_LLM_OUTPUT: dict = {
    "project_context": {
        "value": {
            "about": "Zespół 8 osób buduje core banking dla Nordea ART Payments.",
            "responsibilities": "Projektowanie microserwisów + on-call.",
            "selling_points": "Nowy stack, długoterminowy kontrakt, hybrid 2/5.",
        },
        "confidence": 0.92,
        "rationale": "skopiowano z Job #101 (Nordea — Senior Java, podobieństwo 0.91)",
    },
    "sourcing": {
        "value": {
            "sources": ["linkedin", "referrals"],
            "keywords": "Java, Spring, Kafka, AWS",
            "target_companies": "Swedbank, SEB, Danske Bank",
            "notes": "",
        },
        "confidence": 0.78,
        "rationale": "union z top-3 matches",
    },
    "screening_questions": {
        "value": [
            {
                "id": "q1",
                "question": "Ile lat komercyjnego Javy + Spring Boot?",
                "ideal_answer": "5+",
                "deal_breaker": "mniej niż 3",
            }
        ],
        "confidence": 0.7,
        "rationale": "użyte w 3/4 podobnych rolach",
    },
}


class _FakeAnthropicMessage:
    def __init__(self, text: str):
        self.content = [MagicMock(text=text)]
        self.usage = MagicMock(input_tokens=100, output_tokens=200)


class _FakeAnthropic:
    def __init__(self, *_, **__):
        self.messages = self

    def create(self, **_):
        return _FakeAnthropicMessage(json.dumps(HISTORICAL_LLM_OUTPUT))


@pytest.fixture
def _patch_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-dummy")
    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", _FakeAnthropic)


async def _seed_client_and_job(
    *,
    title: str = "Senior Java Developer",
    status: str = "draft",
    champion_profile: dict | None = None,
    description: str = "",
    must_skills: list | None = None,
    closed: bool = False,
) -> tuple[int, int]:
    """Seed one client + one job. Returns (job_id, client_id)."""
    from datetime import datetime, timezone
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        client = Client(name=f"ClientPhase15-{title[:20]}")
        db.add(client)
        await db.flush()
        job = Job(
            title=title,
            client_id=client.id,
            description=description,
            requirements="",
            must_skills=must_skills or [],
            champion_profile=champion_profile,
        )
        if closed:
            job.status = JobStatus.closed
            job.closed_at = datetime.now(timezone.utc)
        else:
            job.status = JobStatus(status)
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id, client.id


@pytest.mark.asyncio
async def test_generate_from_history_rejects_when_no_matches(
    app_client, app_auth_headers, _patch_anthropic
):
    """Cold-start case: no closed jobs at all → rejected with error_message."""
    job_id, _ = await _seed_client_and_job()

    with patch(
        "app.services.historical_jobs_retrieval.find_similar_historical_jobs",
        new=AsyncMock(return_value=[]),
    ):
        resp = await app_client.post(
            f"/api/jobs/{job_id}/champion-profile/generate-from-history",
            headers=app_auth_headers,
            json={"top_k": 5, "cross_client": False},
        )
    assert resp.status_code == 200, resp.text
    suggestion = resp.json()
    assert suggestion["status"] == "rejected"
    assert suggestion["source_type"] == "historical_jobs"
    assert "Za mało historycznych ofert" in (suggestion["error_message"] or "")


@pytest.mark.asyncio
async def test_generate_from_history_happy_path(
    app_client, app_auth_headers, _patch_anthropic
):
    """With ≥2 matches, LLM is called and payload reflects its output."""
    job_id, client_id = await _seed_client_and_job(
        title="Senior Java Developer",
        description=(
            "Szukamy senior Java developera z doświadczeniem w Spring Boot "
            "i Kafka dla jednego z największych klientów bankowych."
        ),
    )
    # Build two fake historical matches for the LLM prompt context.
    fake_matches = [
        HistoricalJobMatch(
            job_id=101,
            title="Senior Java Developer (Nordea ART Payments)",
            similarity=0.91,
            closed_at=None,
            client_id=client_id,
            client_name="Nordea",
            champion_profile={
                "project_context": {
                    "about": "Nordea ART Payments, zespół 8 osób.",
                    "responsibilities": "On-call, microservices.",
                    "selling_points": "Długi kontrakt.",
                },
                "sourcing": {
                    "sources": ["linkedin"],
                    "keywords": "Java, Spring, Kafka",
                    "target_companies": "Swedbank",
                    "notes": "",
                },
            },
            must_skills=[{"name": "Java"}, {"name": "Spring Boot"}, {"name": "Kafka"}],
            nice_skills=[{"name": "AWS"}],
            seniority="senior",
        ),
        HistoricalJobMatch(
            job_id=102,
            title="Senior Java / Kafka",
            similarity=0.87,
            closed_at=None,
            client_id=client_id,
            client_name="Nordea",
            champion_profile={
                "project_context": {
                    "about": "Nordea Mortgages, zespół 6 osób.",
                    "responsibilities": "Backend services.",
                    "selling_points": "Modern stack.",
                },
            },
            must_skills=[{"name": "Java"}, {"name": "Kafka"}, {"name": "PostgreSQL"}],
            nice_skills=[],
            seniority="senior",
        ),
    ]

    with patch(
        "app.services.champion_draft_service.find_similar_historical_jobs",
        new=AsyncMock(return_value=fake_matches),
    ):
        resp = await app_client.post(
            f"/api/jobs/{job_id}/champion-profile/generate-from-history",
            headers=app_auth_headers,
            json={"top_k": 5, "cross_client": False},
        )

    assert resp.status_code == 200, resp.text
    suggestion = resp.json()
    assert suggestion["status"] == "pending"
    assert suggestion["source_type"] == "historical_jobs"
    assert suggestion["source_ref"] == "101,102"
    sections = {p["section"] for p in suggestion["patches"]}
    assert "project_context" in sections
    project_patch = next(
        p for p in suggestion["patches"] if p["section"] == "project_context"
    )
    assert "skopiowano z Job" in project_patch["rationale"]


@pytest.mark.asyncio
async def test_preview_historical_matches_saved_job(app_client, app_auth_headers):
    """GET preview returns matches + skill_frequency without hitting the LLM."""
    job_id, client_id = await _seed_client_and_job()
    fake_matches = [
        HistoricalJobMatch(
            job_id=201,
            title="Java Dev",
            similarity=0.88,
            closed_at=None,
            client_id=client_id,
            client_name="Nordea",
            champion_profile={"project_context": {"about": "x"}},
            must_skills=[{"name": "Java"}],
            nice_skills=[],
            seniority="senior",
        ),
        HistoricalJobMatch(
            job_id=202,
            title="Java Senior",
            similarity=0.82,
            closed_at=None,
            client_id=client_id,
            client_name="Nordea",
            champion_profile={"project_context": {"about": "y"}},
            must_skills=[{"name": "Java"}, {"name": "Spring"}],
            nice_skills=[],
            seniority="senior",
        ),
    ]
    with patch(
        "app.api.jobs.find_similar_historical_jobs",
        new=AsyncMock(return_value=fake_matches),
        create=True,
    ), patch(
        "app.services.historical_jobs_retrieval.find_similar_historical_jobs",
        new=AsyncMock(return_value=fake_matches),
    ):
        resp = await app_client.get(
            f"/api/jobs/{job_id}/champion-profile/historical-matches?top_k=5",
            headers=app_auth_headers,
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["matches"]) == 2
    assert body["matches"][0]["job_id"] == 201
    assert body["matches"][0]["has_champion_profile"] is True
    assert body["skill_frequency"]["n"] == 2


@pytest.mark.asyncio
async def test_preview_historical_matches_unsaved_role(
    app_client, app_auth_headers
):
    """POST preview without job_id — used by the new-role wizard."""
    # We need at least one client to reference.
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        c = Client(name="WizardClient")
        db.add(c)
        await db.commit()
        await db.refresh(c)
        client_id = c.id

    fake_matches = [
        HistoricalJobMatch(
            job_id=301,
            title="Existing Java Role",
            similarity=0.9,
            closed_at=None,
            client_id=client_id,
            client_name="WizardClient",
            champion_profile={"project_context": {"about": "z"}},
            must_skills=[{"name": "Java"}],
            nice_skills=[],
            seniority="senior",
        ),
    ]
    with patch(
        "app.services.historical_jobs_retrieval.find_similar_historical_jobs",
        new=AsyncMock(return_value=fake_matches),
    ):
        resp = await app_client.post(
            "/api/jobs/champion-profile/historical-matches",
            headers=app_auth_headers,
            json={
                "title": "Senior Java Developer",
                "client_id": client_id,
                "top_k": 3,
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["matches"]) == 1
    assert body["matches"][0]["job_id"] == 301
