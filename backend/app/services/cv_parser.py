"""CV parser service (Phase D3 + Phase D4 — Claude).

Takes raw CV text and uses an LLM to extract structured facts:
  - years_it_experience (int)
  - current_position (str|None)
  - skills (list of canonical dicts)
  - education (list)
  - languages (list)
  - companies (list of strings) — Phase D4
  - career_summary (str|None) — Phase D4

Hierarchy (highest precedence first):
  1. Claude (Anthropic) — best quality, used for production uploads
  2. Ollama (local) — free, used in dev / when ANTHROPIC_API_KEY is unset
  3. regex heuristic — always-on last resort, never fails

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

# Matches standalone LinkedIn profile URLs embedded in CV text.
# Examples caught: "https://linkedin.com/in/jane-doe", "www.linkedin.com/in/jane",
# "pl.linkedin.com/in/jane-doe/", "linkedin.com/in/jane_doe?foo=bar".
_LINKEDIN_URL_RE = re.compile(
    r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/in/[\w\-%._]+/?",
    re.IGNORECASE,
)


def _extract_linkedin_from_text(cv_text: str) -> Optional[str]:
    """Find the first LinkedIn profile URL in the CV text, or None.

    Used as a regex backstop when the LLM response lacks a `linkedin_url`
    field. Returns the raw match; the caller normalizes via
    `app.services.proxycurl.client.normalize_linkedin_url`.
    """

    if not cv_text:
        return None
    match = _LINKEDIN_URL_RE.search(cv_text)
    return match.group(0) if match else None


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
        # Phase D4: schema consistency with Claude/Ollama output. The frontend
        # reads these fields via optional chaining, but an explicit empty list /
        # null lets UI tell "no data yet" from "legacy record, never enriched".
        "companies": [],
        "career_summary": None,
        "linkedin_url": _extract_linkedin_from_text(cv_text),
        "_source": "regex",
    }


def _strip_json_fences(raw: str) -> str:
    """Strip ```json ... ``` markdown fences that LLMs occasionally emit.

    Mirrors the behaviour in app/api/ai_writer.py:259-263 so both Claude call-
    sites share the same unwrap logic.
    """
    raw = raw.strip()
    if raw.startswith("```"):
        # Drop the opening fence (with or without language tag).
        raw = raw.split("```", 2)
        # parts: ["", "json\n{...}", ""] or ["", "{...}", ""] — take middle.
        raw = raw[1] if len(raw) > 1 else ""
        if raw.lstrip().startswith("json"):
            raw = raw.lstrip()[4:]
    # Also strip trailing backticks if the split above left any behind.
    return raw.strip().rstrip("`").strip()


async def _parse_with_claude(cv_text: str) -> Optional[dict[str, Any]]:
    """Call Anthropic Claude with the versioned CV_ENRICHMENT prompt.

    Returns None on any failure so the caller can fall back to Ollama / regex.
    Never raises upward.
    """
    api_key = settings.ANTHROPIC_API_KEY
    if not api_key or not settings.CV_ENRICHMENT_ENABLED:
        return None

    try:
        import anthropic  # lazy import — keeps cold-start fast when unused
    except ImportError:  # pragma: no cover — requirements.txt pins it
        logger.warning("[cv_parser] anthropic SDK not installed; skipping Claude path")
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)
        user_prompt = CV_ENRICHMENT.render(cv_text=cv_text[:8000])
        message = client.messages.create(
            model=settings.CLAUDE_MODEL_CV,
            max_tokens=2000,
            system=CV_ENRICHMENT.system_prompt or "",
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = message.content[0].text
        unwrapped = _strip_json_fences(raw)
        data = json.loads(unwrapped)
        if not isinstance(data, dict):
            return None
        data["_source"] = f"claude:{CV_ENRICHMENT.name}:v{CV_ENRICHMENT.version}"
        return data
    except Exception as e:
        logger.warning(
            "[cv_parser] Claude call failed (template=%s v%d): %s",
            CV_ENRICHMENT.name,
            CV_ENRICHMENT.version,
            e,
        )
        return None


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

    With `prefer_llm=True` (default) the parser walks the hierarchy
    Claude → Ollama → regex; the first path that returns a non-None result
    wins. With `prefer_llm=False` only the regex heuristic runs (useful for
    deterministic tests and offline environments).

    Returns dict with keys: years_it_experience, current_position, skills,
    education, languages, companies, career_summary, _source.
    """
    if not cv_text or not cv_text.strip():
        return _regex_fallback("")

    if prefer_llm:
        claude = await _parse_with_claude(cv_text)
        if claude is not None:
            return _with_linkedin_fallback(claude, cv_text)
        ollama = await _parse_with_ollama(cv_text)
        if ollama is not None:
            return _with_linkedin_fallback(ollama, cv_text)
    return _regex_fallback(cv_text)


def _with_linkedin_fallback(
    parsed: dict[str, Any], cv_text: str
) -> dict[str, Any]:
    """Backstop: if the LLM missed `linkedin_url`, try the regex on raw text.

    Mutates a shallow copy so callers that re-use the dict don't see the
    fallback sneak in. Keeps the LLM's `_source` unchanged — the regex
    backfill is transparent to downstream bookkeeping.
    """

    if parsed.get("linkedin_url"):
        return parsed
    found = _extract_linkedin_from_text(cv_text)
    if not found:
        return parsed
    out = dict(parsed)
    out["linkedin_url"] = found
    return out
