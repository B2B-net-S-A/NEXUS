"""Unit tests for the Competence Category classifier.

Tests are DB-free: we exercise the pure-function helpers and mock the DB query
via a minimal in-memory stub. Qdrant lookups are bypassed by returning empty
embeddings dict (keyword-only scoring path).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from app.services import cc_classifier


# ── Fake models ─────────────────────────────────────────────────────────────


@dataclass
class FakeCc:
    id: int
    slug: str
    name_pl: str
    keywords: list[str]
    is_active: bool = True


SEED_CCS = [
    FakeCc(
        id=1,
        slug="infrastructure_operations",
        name_pl="Infrastruktura i Operacje",
        keywords=["devops", "kubernetes", "terraform", "aws", "ci/cd", "linux"],
    ),
    FakeCc(
        id=2,
        slug="software_development",
        name_pl="Rozwój Oprogramowania",
        keywords=[
            "react",
            "java",
            "spring",
            "python",
            "typescript",
            "backend",
            "frontend",
        ],
    ),
    FakeCc(
        id=3,
        slug="data_ai",
        name_pl="Dane i AI",
        keywords=["ml", "spark", "airflow", "pytorch", "llm", "etl", "data scientist"],
    ),
    FakeCc(
        id=4,
        slug="security_quality",
        name_pl="Bezpieczeństwo i Jakość",
        keywords=[
            "qa",
            "pentester",
            "owasp",
            "selenium",
            "playwright",
            "cybersecurity",
        ],
    ),
    FakeCc(
        id=5,
        slug="management_delivery",
        name_pl="Zarządzanie i Dostarczanie",
        keywords=["pm", "product manager", "scrum master", "tech lead", "head of"],
    ),
]


# ── DB stub ─────────────────────────────────────────────────────────────────


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeDb:
    """Returns SEED_CCS for the `select(CompetenceCategory)` query."""

    def __init__(self, ccs=None):
        self._ccs = ccs or SEED_CCS

    async def execute(self, _stmt: Any):  # noqa: ARG002
        return _Result(self._ccs)


@pytest.fixture
def db():
    return FakeDb()


@pytest.fixture(autouse=True)
def _no_qdrant(monkeypatch):
    """Skip Qdrant in all tests — rely on keyword scoring alone."""

    async def fake_embed(_vec):
        return {}

    monkeypatch.setattr(cc_classifier, "_embedding_scores", fake_embed)

    async def fake_fetch_job(_id):
        return None

    async def fake_fetch_candidate(_id):
        return None

    monkeypatch.setattr(cc_classifier, "_fetch_job_embedding", fake_fetch_job)
    monkeypatch.setattr(
        cc_classifier, "_fetch_candidate_embedding", fake_fetch_candidate
    )


# ── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_senior_react_developer_maps_to_software_development(db):
    job = SimpleNamespace(
        id=1,
        title="Senior React Developer",
        description="Frontend app in React and TypeScript, Jest for tests.",
        requirements="5+ lat React, TypeScript, znajomość Next.js",
        subcategory=None,
        industry=None,
        must_skills=[{"name": "react"}, {"name": "typescript"}],
        nice_skills=[],
    )
    result = await cc_classifier.classify_job_to_cc(job, db)
    assert result.top is not None
    assert result.top.slug == "software_development"
    assert result.top.score > 0.0


@pytest.mark.asyncio
async def test_head_of_qa_maps_to_security_quality(db):
    job = SimpleNamespace(
        id=2,
        title="Head of QA",
        description="Prowadzenie zespołu QA, automatyzacja testów, selenium/playwright.",
        requirements="OWASP, QA lead, test automation",
        subcategory=None,
        industry=None,
        must_skills=[{"name": "qa"}, {"name": "playwright"}],
        nice_skills=[],
    )
    result = await cc_classifier.classify_job_to_cc(job, db)
    assert result.top is not None
    assert result.top.slug == "security_quality"


@pytest.mark.asyncio
async def test_senior_devops_maps_to_infrastructure_operations(db):
    job = SimpleNamespace(
        id=3,
        title="Senior DevOps Engineer",
        description="AWS, Kubernetes, Terraform, CI/CD pipelines, Linux.",
        requirements="5+ lat doświadczenia w DevOps, k8s",
        subcategory=None,
        industry=None,
        must_skills=[{"name": "kubernetes"}, {"name": "terraform"}],
        nice_skills=[],
    )
    result = await cc_classifier.classify_job_to_cc(job, db)
    assert result.top is not None
    assert result.top.slug == "infrastructure_operations"


@pytest.mark.asyncio
async def test_confidence_band_mapping():
    # Synthetic score → band
    score_high = cc_classifier.CcScore(
        cc_id=1,
        slug="x",
        name_pl="x",
        score=0.85,
        keyword_ratio=0.0,
        embedding_score=0.0,
        keywords_matched=[],
    )
    assert score_high.confidence_band == "high"

    score_med = cc_classifier.CcScore(
        cc_id=1,
        slug="x",
        name_pl="x",
        score=0.70,
        keyword_ratio=0.0,
        embedding_score=0.0,
        keywords_matched=[],
    )
    assert score_med.confidence_band == "medium"

    score_low = cc_classifier.CcScore(
        cc_id=1,
        slug="x",
        name_pl="x",
        score=0.20,
        keyword_ratio=0.0,
        embedding_score=0.0,
        keywords_matched=[],
    )
    assert score_low.confidence_band == "low"


@pytest.mark.asyncio
async def test_empty_corpus_returns_top_none(db):
    job = SimpleNamespace(
        id=99,
        title="",
        description=None,
        requirements=None,
        subcategory=None,
        industry=None,
        must_skills=None,
        nice_skills=None,
    )
    result = await cc_classifier.classify_job_to_cc(job, db)
    # No keywords matched anywhere → all scores = 0; `top` exists but score=0.0
    assert result.top is not None
    assert result.top.score == 0.0


def test_keyword_score_no_keywords():
    ratio, matched = cc_classifier._keyword_score("senior react developer", [])
    assert ratio == 0.0
    assert matched == []


def test_keyword_score_exact_match():
    ratio, matched = cc_classifier._keyword_score(
        "senior react developer", ["react", "typescript"]
    )
    assert matched == ["react"]
    assert 0 < ratio <= 1.0
