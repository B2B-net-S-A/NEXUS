"""CV parser service (Phase D3).

Takes raw CV text and uses the local Ollama to extract structured facts:
  - years_it_experience (int)
  - current_position (str|None)
  - skills (list of canonical dicts)
  - education (list)
  - languages (list)

Falls back to `_regex_fallback` when Ollama is unavailable, so the service is
usable in dev/CI without a live LLM.

Returns a dict — caller decides which fields to persist. On persist, the
`match_score_cache.mark_stale_for_candidate` hook should be invoked so the
cache recomputes with the fresh skills.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.services.llm_prompts import CV_ENRICHMENT

logger = logging.getLogger(__name__)


_TECH_PATTERN = re.compile(
    r"\b(Python|Java|JavaScript|TypeScript|React|Angular|Vue|Node|Go|Rust|"
    r"C\+\+|C#|Kotlin|Swift|PHP|Ruby|Scala|SQL|PostgreSQL|MySQL|MongoDB|Redis|"
    r"Docker|Kubernetes|AWS|GCP|Azure|Terraform|Kafka|RabbitMQ|Elasticsearch|"
    r"Django|Flask|FastAPI|Spring|Express|Next\.js|GraphQL|REST|gRPC|CI/CD|Git)\b",
    re.I,
)

_YEARS_PATTERN = re.compile(
    r"(\d{1,2})\s*(?:\+\s*)?(?:lat|years?|lata?)\s*(?:doświadczenia|experience|IT|w IT)?",
    re.I,
)


def _regex_fallback(cv_text: str) -> dict[str, Any]:
    """Deterministic heuristic — best-effort extraction without LLM."""
    found_tech = {m.group(0) for m in _TECH_PATTERN.finditer(cv_text)}
    skills = [{"name": t, "level": None, "years": None} for t in list(found_tech)[:20]]

    years_match = _YEARS_PATTERN.search(cv_text)
    years = int(years_match.group(1)) if years_match else None
    if years and years > 50:
        years = None

    # Current position — take line starting with "Senior/Lead/Principal" (rough)
    current_position: Optional[str] = None
    for line in cv_text.splitlines()[:40]:
        line = line.strip()
        if re.match(r"^(Senior|Lead|Principal|Staff|Junior|Mid)\s+[A-Z]", line):
            current_position = line[:100]
            break

    return {
        "years_it_experience": years,
        "current_position": current_position,
        "skills": skills,
        "education": [],
        "languages": [],
        "_source": "regex",
    }


async def _parse_with_ollama(cv_text: str) -> Optional[dict[str, Any]]:
    """Call local Ollama; returns None on any failure so caller can fallback."""
    ollama_host = getattr(settings, "OLLAMA_HOST", None) or getattr(
        settings, "OLLAMA_BASE_URL", None
    )
    if not ollama_host:
        return None
    model = getattr(settings, "OLLAMA_MODEL", "llama3.2")

    prompt = CV_ENRICHMENT.render(cv_text=cv_text[:8000])
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                f"{ollama_host.rstrip('/')}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                },
            )
            resp.raise_for_status()
            payload = (resp.json().get("response") or "").strip()
            data = json.loads(payload)
            if not isinstance(data, dict):
                return None
            data["_source"] = f"ollama:{CV_ENRICHMENT.name}:v{CV_ENRICHMENT.version}"
            return data
    except Exception as e:
        logger.warning(
            "[cv_parser] Ollama call failed (template=%s v%d): %s",
            CV_ENRICHMENT.name,
            CV_ENRICHMENT.version,
            e,
        )
        return None


async def parse_cv(cv_text: str, *, prefer_llm: bool = True) -> dict[str, Any]:
    """
    Extract structured facts from CV text.

    `prefer_llm=True` tries Ollama first, falling back to regex on any error.
    Returns dict with keys: years_it_experience, current_position, skills,
    education, languages, _source.
    """
    if not cv_text or not cv_text.strip():
        return _regex_fallback("")

    if prefer_llm:
        llm = await _parse_with_ollama(cv_text)
        if llm is not None:
            return llm
    return _regex_fallback(cv_text)
