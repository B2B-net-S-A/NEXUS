"""Tests for AI-generated job criteria (must/nice skills).

Covers the P0 fixes in ``app.api.recommendations``:
  1. ``_generate_criteria_with_ollama`` resolves the host via ``OLLAMA_BASE_URL``
     (the config var that actually exists) — the old code only checked the
     never-defined ``OLLAMA_HOST`` and so always fell through to the heuristic.
  2. A successful Ollama call stamps ``_source`` so refresh/preview report
     "ollama" instead of always "heuristic".
  3. ``_fallback_criteria_from_text`` extracts ONLY recognised tech tokens and
     never persists raw requirement prose as a skill; output is deterministic.
"""

from __future__ import annotations

import httpx

from app.api.recommendations import (
    _fallback_criteria_from_text,
    _generate_criteria_with_ollama,
)
from app.core.config import settings
from app.models.job import Job


# ── Ollama path: host resolution + _source stamping ────────────────────────


class _FakeResponse:
    def __init__(self, response_text: str) -> None:
        self._text = response_text

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"response": self._text}


class _FakeAsyncClient:
    """Stand-in for ``httpx.AsyncClient`` — records the URL it POSTs to."""

    posted_url: str | None = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def post(self, url: str, json: dict | None = None) -> _FakeResponse:
        type(self).posted_url = url
        return _FakeResponse(
            '{"must_skills": [{"name": "Java", "level": null}], '
            '"nice_skills": [{"name": "AWS", "level": null}]}'
        )


async def test_ollama_uses_base_url_and_stamps_source(monkeypatch):
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://ollama.test:11434")
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.posted_url = None

    job = Job(title="Senior Java Developer", description="", requirements="Java, AWS")
    result = await _generate_criteria_with_ollama(job)

    assert result is not None
    # host resolved from OLLAMA_BASE_URL (not the non-existent OLLAMA_HOST)
    assert _FakeAsyncClient.posted_url == "http://ollama.test:11434/api/generate"
    # source stamped so endpoints report "ollama"
    assert result["_source"].startswith("ollama:")
    assert result["must_skills"] == [{"name": "Java", "level": None}]
    assert result["nice_skills"] == [{"name": "AWS", "level": None}]


async def test_ollama_returns_none_when_no_host_configured(monkeypatch):
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "")
    monkeypatch.delattr(settings, "OLLAMA_HOST", raising=False)

    job = Job(title="Dev", description="", requirements="")
    assert await _generate_criteria_with_ollama(job) is None


# ── Heuristic fallback: tech-only, no prose, deterministic ─────────────────


def test_fallback_extracts_only_tech_tokens_no_prose():
    job = Job(
        title="Senior Java Developer",
        description="",
        requirements=(
            "- Java 17\n"
            "- English B2\n"
            "- Agile\n"
            "- Scrum\n"
            "- Docker\n"
            "- Bardzo dobra znajomość języka angielskiego\n"
            "- B2B cooperation"
        ),
    )
    result = _fallback_criteria_from_text(job)
    names = [s["name"] for s in result["must_skills"]] + [
        s["name"] for s in result["nice_skills"]
    ]
    lowered = [n.lower() for n in names]

    # real technologies are captured
    assert "java" in lowered
    assert "docker" in lowered
    # non-tech criteria and prose are NEVER persisted as skills
    assert "english b2" not in lowered
    assert "agile" not in lowered
    assert "scrum" not in lowered
    assert "b2b cooperation" not in lowered
    assert all("znajomość" not in n.lower() for n in names)
    # every persisted skill is a single recognised tech token (no long prose)
    assert all(len(n) <= 20 for n in names)


def test_fallback_is_deterministic_and_ordered():
    job = Job(
        title="Dev",
        description="Python Java Go Rust Docker Kubernetes AWS Redis Kafka",
        requirements="",
    )
    first = _fallback_criteria_from_text(job)
    second = _fallback_criteria_from_text(job)
    assert first == second  # old set-based impl was non-deterministic
    assert first["must_skills"][0]["name"] == "Python"  # first-seen order


def test_fallback_splits_must_then_nice():
    job = Job(
        title="",
        description=(
            "Python Java Go Rust Docker Kubernetes AWS Azure GCP Redis Kafka Django"
        ),
        requirements="",
    )
    result = _fallback_criteria_from_text(job)
    assert len(result["must_skills"]) == 8  # first 8 → must
    assert 1 <= len(result["nice_skills"]) <= 6  # overflow → nice
    must_names = {s["name"] for s in result["must_skills"]}
    nice_names = {s["name"] for s in result["nice_skills"]}
    assert must_names.isdisjoint(nice_names)  # no token in both lists


def test_fallback_dedupes_repeated_tokens():
    job = Job(title="Python dev", description="Python Python python", requirements="Python")
    result = _fallback_criteria_from_text(job)
    all_names = [s["name"] for s in result["must_skills"] + result["nice_skills"]]
    assert len(all_names) == 1  # de-duplicated case-insensitively
