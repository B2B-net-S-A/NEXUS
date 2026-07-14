"""Tests for the Champion Profile AI Intake pipeline (Phase 14).

Two families:
  - Pure-function tests for merge logic (no DB, no LLM).
  - Async tests for generate / apply / reject using the in-process
    `app_client` fixture, with the Claude API call patched.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.schemas.champion import ChampionProfile
from app.schemas.champion_suggestion import (
    VALID_SECTIONS,
    patches_from_payload,
    payload_from_profile,
)
from app.services.champion_draft_service import (
    _merge_basics,
    _merge_screening_questions,
    _merge_section,
    _merge_sourcing,
)


# ── Pure-function merge logic ───────────────────────────────────────────────


def test_merge_basics_replaces_non_null_fields():
    current = {
        "onsite_days_per_week": 2,
        "candidate_location_pref": "Warszawa",
        "language": None,
    }
    proposed = {
        "onsite_days_per_week": None,  # should not overwrite
        "candidate_location_pref": "Kraków",  # should overwrite
        "language": "PL, EN B2+",  # should set
    }
    merged = _merge_basics(current, proposed)
    assert merged["onsite_days_per_week"] == 2
    assert merged["candidate_location_pref"] == "Kraków"
    assert merged["language"] == "PL, EN B2+"


def test_merge_sourcing_unions_sources_and_replaces_strings():
    current = {
        "sources": ["linkedin"],
        "keywords": "python",
        "target_companies": "",
        "notes": "existing note",
    }
    proposed = {
        "sources": ["referrals", "linkedin"],  # dedup
        "keywords": "python, fastapi",
        "target_companies": "Acme, Globex",
        "notes": "",  # empty → keep existing
    }
    merged = _merge_sourcing(current, proposed)
    assert sorted(merged["sources"]) == ["linkedin", "referrals"]
    assert merged["keywords"] == "python, fastapi"
    assert merged["target_companies"] == "Acme, Globex"
    assert merged["notes"] == "existing note"


def test_merge_screening_questions_appends_with_dedup():
    current = [
        {"id": "q1", "question": "old q1", "ideal_answer": "", "deal_breaker": ""},
    ]
    proposed = [
        {"id": "q1", "question": "dup", "ideal_answer": "", "deal_breaker": ""},
        {"id": "q2", "question": "new q2", "ideal_answer": "", "deal_breaker": ""},
    ]
    merged = _merge_screening_questions(current, proposed)
    assert len(merged) == 2
    ids = [q["id"] for q in merged]
    assert ids == ["q1", "q2"]
    # original q1 wins
    assert merged[0]["question"] == "old q1"


def test_merge_section_dispatch_for_strings():
    # Non-empty proposed string replaces current.
    assert _merge_section("historical_client_questions", "", "Nowy opis") == "Nowy opis"
    # Empty proposed keeps current.
    assert _merge_section("historical_client_questions", "Obecny", "") == "Obecny"


def test_payload_from_profile_builds_confidence_per_section():
    profile = ChampionProfile()
    profile.project_context.about = "cel projektu"
    conf = {"project_context": 0.85, "basics": 0.0}
    payload = payload_from_profile(profile, confidence=conf)
    assert payload["project_context"]["confidence"] == 0.85
    assert payload["basics"]["confidence"] == 0.0
    assert set(payload.keys()) == set(VALID_SECTIONS)


def test_patches_from_payload_ignores_unknown_sections():
    payload = {
        "basics": {"value": {"onsite_days_per_week": 2}, "confidence": 0.9},
        "bogus": {"value": "x", "confidence": 1.0},  # ignored
    }
    patches = patches_from_payload(payload)
    assert len(patches) == 1
    assert patches[0].section == "basics"
    assert patches[0].confidence == pytest.approx(0.9)


# ── Async service + API tests ───────────────────────────────────────────────


SAMPLE_LLM_OUTPUT = {
    "basics": {
        "onsite_days_per_week": 2,
        "candidate_location_pref": "Warszawa, PL remote",
        "language": "PL, EN B2+",
    },
    "project_context": {
        "about": "Zespół 10 osób buduje platformę fintech.",
        "responsibilities": "Projektowanie i implementacja mikroserwisów.",
        "selling_points": "Nowy stack, wysoki wpływ, dobra kultura inżynierska.",
    },
    "screening_questions": [
        {
            "id": "q1",
            "question": "Ile lat komercyjnego Pythona?",
            "ideal_answer": "5+",
            "deal_breaker": "mniej niż 3",
        }
    ],
    "historical_client_questions": "",
    "internal_consultant_insight": "",
    "sourcing": {
        "sources": ["linkedin"],
        "keywords": "Python, FastAPI, event-driven",
        "target_companies": "Acme",
        "notes": "",
    },
    "_confidence": {
        "basics": 0.8,
        "project_context": 0.9,
        "screening_questions": 0.75,
        "historical_client_questions": 0.0,
        "internal_consultant_insight": 0.0,
        "sourcing": 0.6,
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
        return _FakeAnthropicMessage(json.dumps(SAMPLE_LLM_OUTPUT))


@pytest.fixture
def _patch_anthropic(monkeypatch):
    """Replace `anthropic.Anthropic` with our fake so no real API is hit."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-dummy")
    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", _FakeAnthropic)


async def _create_job(app_client, app_auth_headers):
    """Seed a minimal client + job directly through the DB.

    We bypass POST /api/jobs here because the broader app has response-model
    validation that is orthogonal to what we want to test (and which is
    flaky in the test environment due to legacy migrations).
    """
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        client = Client(name="TestClient Sp. z o.o.")
        db.add(client)
        await db.flush()
        job = Job(
            title="Senior Python Developer",
            client_id=client.id,
            description="",
            requirements="",
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


@pytest.mark.asyncio
async def test_generate_and_apply_happy_path(
    app_client, app_auth_headers, _patch_anthropic
):
    job_id = await _create_job(app_client, app_auth_headers)

    # Generate draft from JD.
    resp = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/generate-from-jd",
        headers=app_auth_headers,
        json={
            "raw_description": (
                "Szukamy senior Python developera do naszego zespołu fintech. "
                "Wymagamy minimum 5 lat doświadczenia z FastAPI, PostgreSQL "
                "i architekturą event-driven. Praca hybrydowa w Warszawie, "
                "2 dni w biurze."
            )
        },
    )
    assert resp.status_code == 200, resp.text
    suggestion = resp.json()
    assert suggestion["status"] == "pending"
    assert suggestion["source_type"] == "jd_paste"
    sections = {p["section"] for p in suggestion["patches"]}
    assert {"basics", "project_context", "screening_questions"} <= sections

    suggestion_id = suggestion["id"]

    # Apply only project_context.
    apply_resp = await app_client.post(
        f"/api/champion-suggestions/{suggestion_id}/apply",
        headers=app_auth_headers,
        json={"accepted_sections": ["project_context"]},
    )
    assert apply_resp.status_code == 200, apply_resp.text
    body = apply_resp.json()
    assert body["status"] == "partially_accepted"

    # Verify champion_profile got the project_context section.
    prof_resp = await app_client.get(
        f"/api/jobs/{job_id}/champion-profile",
        headers=app_auth_headers,
    )
    assert prof_resp.status_code == 200
    profile = prof_resp.json()["champion_profile"]
    assert profile["project_context"]["about"].startswith("Zespół 10 osób")
    # basics stayed empty (we didn't accept it).
    assert profile["basics"]["onsite_days_per_week"] in (None, 0) or (
        profile["basics"]["candidate_location_pref"] in (None, "")
    )


@pytest.mark.asyncio
async def test_apply_rejects_when_not_pending(
    app_client, app_auth_headers, _patch_anthropic
):
    job_id = await _create_job(app_client, app_auth_headers)
    resp = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/generate-from-jd",
        headers=app_auth_headers,
        json={
            "raw_description": "Opis stanowiska wystarczająco długi do walidacji przez Pydantic min_length=50."
        },
    )
    sid = resp.json()["id"]

    # Reject once.
    r1 = await app_client.post(
        f"/api/champion-suggestions/{sid}/reject",
        headers=app_auth_headers,
    )
    assert r1.status_code == 200
    assert r1.json()["status"] == "rejected"

    # Applying a non-pending suggestion must 409.
    r2 = await app_client.post(
        f"/api/champion-suggestions/{sid}/apply",
        headers=app_auth_headers,
        json={"accepted_sections": ["project_context"]},
    )
    assert r2.status_code == 409, r2.text


# ── Fuzzy matcher (Fireflies → Job) ────────────────────────────────────────


class _FakeClient:
    def __init__(self, name: str, website: str | None = None):
        self.name = name
        self.website = website


class _FakeJob:
    def __init__(
        self, id: int, title: str, client: _FakeClient | None, status="published"
    ):
        self.id = id
        self.title = title
        self.client = client
        from app.models.job import JobStatus

        self.status = JobStatus.draft if status == "draft" else JobStatus.published


def test_token_set_ratio_is_order_insensitive():
    from app.services.fireflies_job_matcher import _token_set_ratio

    a = _token_set_ratio("Senior Python Developer", "developer python senior")
    assert a > 0.9


# ── CloudTalk webhook (Phase 14 / Faza C) ──────────────────────────────────


@pytest.mark.asyncio
async def test_cloudtalk_webhook_dry_run_returns_ok(app_client, monkeypatch):
    """With `CLOUDTALK_WEBHOOK_ENABLED` unset, webhook runs in dry-run mode
    and returns 200 without touching the DB."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "CLOUDTALK_ENABLED", False)
    resp = await app_client.post(
        "/api/calls/webhook",
        json={"call": {"id": "ct-1", "phone": "+48123456789"}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "dry-run"
    assert body["enabled"] is False


@pytest.mark.asyncio
async def test_cloudtalk_webhook_rejects_invalid_hmac(app_client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "CLOUDTALK_ENABLED", True)
    monkeypatch.setattr(settings, "CLOUDTALK_WEBHOOK_SECRET", "s3cr3t")
    resp = await app_client.post(
        "/api/calls/webhook",
        headers={"X-CloudTalk-Signature": "totally-wrong"},
        json={"call": {"id": "ct-2"}},
    )
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_cloudtalk_webhook_accepts_valid_hmac(app_client, monkeypatch):
    import hashlib
    import hmac
    import json

    from app.core.config import settings

    monkeypatch.setattr(settings, "CLOUDTALK_ENABLED", True)
    monkeypatch.setattr(settings, "CLOUDTALK_WEBHOOK_SECRET", "s3cr3t")
    body = json.dumps({"call": {"id": "ct-3", "phone": "+48000000000"}}).encode()
    sig = hmac.new(b"s3cr3t", body, hashlib.sha256).hexdigest()
    resp = await app_client.post(
        "/api/calls/webhook",
        headers={
            "X-CloudTalk-Signature": sig,
            "Content-Type": "application/json",
        },
        content=body,
    )
    assert resp.status_code == 200, resp.text
    # No candidate with that phone → no Call row created, but status ok.
    assert resp.json()["status"] == "ok"


def test_domain_boost_matches_client_website_host():
    from app.services.fireflies_job_matcher import _domain_boost

    c = _FakeClient(name="Acme", website="https://acme.com/about")
    boost = _domain_boost(c, ["jan@acme.com", "other@example.org"])
    assert boost == 1.0
    # No matching domain
    assert _domain_boost(c, ["jan@other.com"]) == 0.0


@pytest.mark.asyncio
async def test_regenerate_supersedes_previous_pending(
    app_client, app_auth_headers, _patch_anthropic
):
    job_id = await _create_job(app_client, app_auth_headers)
    body = {
        "raw_description": "Opis stanowiska wystarczająco długi do walidacji przez Pydantic min_length=50."
    }

    r1 = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/generate-from-jd",
        headers=app_auth_headers,
        json=body,
    )
    assert r1.status_code == 200
    first_id = r1.json()["id"]

    r2 = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/generate-from-jd",
        headers=app_auth_headers,
        json=body,
    )
    assert r2.status_code == 200
    second_id = r2.json()["id"]
    assert second_id != first_id

    # Older suggestion should have been marked `superseded`.
    list_resp = await app_client.get(
        f"/api/jobs/{job_id}/champion-profile/suggestions",
        headers=app_auth_headers,
    )
    items = {s["id"]: s["status"] for s in list_resp.json()["items"]}
    assert items[first_id] == "superseded"
    assert items[second_id] == "pending"
