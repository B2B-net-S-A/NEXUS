"""CV parser service (Phase D3 + Phase D4 — Claude + Phase v4 auto-fill).

Takes raw CV text and uses an LLM to extract structured facts:
  - first_name / last_name (str|None)              — v4
  - email / phone / city (str|None)                — v4
  - years_it_experience (int)
  - current_position (str|None)
  - skills (list of canonical dicts)
  - education (list)
  - languages (list)
  - companies (list of strings) — Phase D4
  - career_summary (str|None) — Phase D4
  - linkedin_url (str|None)
  - _confidence (dict[str, float])                  — v4, per-field certainty

Hierarchy (highest precedence first):
  1. Claude (Anthropic) — best quality, used for production uploads
  2. Ollama (local) — free, used in dev / when ANTHROPIC_API_KEY is unset
  3. regex heuristic — always-on last resort, never fails

Contact-field safety net: after the LLM returns, a deterministic regex pass
(`_apply_contact_fallbacks`) fills in any email/phone/name it missed by
scanning the first ~15 lines of the CV and any standalone email addresses.
Values from the LLM win — the regex only fills in `None` slots.

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
from fastapi.concurrency import run_in_threadpool

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

# Simplified RFC 5322 — sufficient for CV headers; avoids pathological
# edge cases (quoted locals, IP literals) which never appear in CVs.
_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
)

# PL phone numbers: optional +48/48 prefix, then 9 digits with optional
# separators (space, dash, dot, non-breaking space). Captures the raw match —
# callers may normalize to "+48 XXX XXX XXX" if needed.
_PHONE_PL_RE = re.compile(
    r"(?:(?:\+|00)\s*48[\s.\-]*)?"  # optional country code
    r"(?:\d[\s.\-]*){9}",  # exactly 9 digits with separators
)

# Honorific/role tokens that should NOT appear in a detected first/last name.
# Used to filter out heading lines like "CURRICULUM VITAE" or "Senior Developer".
_NAME_REJECT_RE = re.compile(
    r"(?i)\b(cv|curriculum|vitae|resume|senior|lead|junior|mid|"
    r"principal|staff|developer|engineer|manager|architect|profile|summary)\b",
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


def _extract_email_from_text(cv_text: str) -> Optional[str]:
    """Return the first plausible email address in the CV (lowercased)."""
    if not cv_text:
        return None
    match = _EMAIL_RE.search(cv_text)
    return match.group(0).lower() if match else None


def _extract_phone_from_text(cv_text: str) -> Optional[str]:
    """Return the first PL phone match from the CV, trimmed.

    We only accept matches whose digit-only form is 9 or 11 digits (with
    country code) to reduce false positives on salary figures / years.
    """
    if not cv_text:
        return None
    # Scan the top of the CV first — contact info usually sits in the header.
    head = "\n".join(cv_text.splitlines()[:20])
    for source in (head, cv_text):
        for match in _PHONE_PL_RE.finditer(source):
            raw = match.group(0).strip(" .-")
            digits = re.sub(r"\D", "", raw)
            if len(digits) in (9, 11):
                return raw
    return None


def _split_name_from_header(cv_text: str) -> tuple[Optional[str], Optional[str]]:
    """Heuristic: first/last name from the first non-empty CV line.

    Matches lines like "Jan Kowalski" or "JAN KOWALSKI" — two or three
    capitalized tokens, no role/honorific keywords. Returns (first, last)
    or (None, None) if no line qualifies.
    """
    if not cv_text:
        return None, None
    for raw_line in cv_text.splitlines()[:10]:
        line = raw_line.strip()
        if not line or len(line) > 60 or _NAME_REJECT_RE.search(line):
            continue
        # Reject lines that contain digits, emails, phone signs — they're
        # contact info, not a name header.
        if any(ch.isdigit() for ch in line) or "@" in line or "+" in line:
            continue
        tokens = [t for t in re.split(r"[\s,]+", line) if t]
        if not 2 <= len(tokens) <= 4:
            continue
        # Each token must start with an uppercase letter; accept PL diacritics.
        if not all(
            re.match(r"^[A-ZŁŚŻŹĆŃÓĄĘ][\wŁłŚśŻżŹźĆćŃńÓóĄąĘę\-']+$", t) for t in tokens
        ):
            continue
        first = tokens[0]
        last = " ".join(tokens[1:])
        return first, last
    return None, None


def _apply_contact_fallbacks(parsed: dict[str, Any], cv_text: str) -> dict[str, Any]:
    """Fill missing contact fields via regex; preserves LLM values.

    Regex only writes into keys that are currently `None` or missing.
    Sets `_confidence` for regex-filled fields: 0.9 for exact email match,
    0.85 for phone with 9+ digits, 0.6 for name split heuristic.
    """
    out = dict(parsed)
    confidence = dict(out.get("_confidence") or {})

    if not out.get("email"):
        email = _extract_email_from_text(cv_text)
        if email:
            out["email"] = email
            confidence.setdefault("email", 0.9)

    if not out.get("phone"):
        phone = _extract_phone_from_text(cv_text)
        if phone:
            out["phone"] = phone
            confidence.setdefault("phone", 0.85)

    if not out.get("first_name") or not out.get("last_name"):
        first, last = _split_name_from_header(cv_text)
        if first and not out.get("first_name"):
            out["first_name"] = first
            confidence.setdefault("first_name", 0.6)
        if last and not out.get("last_name"):
            out["last_name"] = last
            confidence.setdefault("last_name", 0.6)

    if confidence:
        out["_confidence"] = confidence
    return out


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

    base = {
        "first_name": None,
        "last_name": None,
        "email": None,
        "phone": None,
        "city": None,
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
        "_confidence": {},
        "_source": "regex",
    }
    return _apply_contact_fallbacks(base, cv_text)


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
        # Sync Anthropic SDK call — offload the multi-second network round-trip
        # so it does not block the single-worker event loop.
        message = await run_in_threadpool(
            client.messages.create,
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

    Returns dict with keys: first_name, last_name, email, phone, city,
    years_it_experience, current_position, skills, education, languages,
    companies, career_summary, linkedin_url, _confidence, _source.

    Regex contact fallback fills any missing email/phone/first_name/last_name
    the LLM left empty — LLM values always win.
    """
    if not cv_text or not cv_text.strip():
        return _regex_fallback("")

    if prefer_llm:
        claude = await _parse_with_claude(cv_text)
        if claude is not None:
            return _apply_contact_fallbacks(
                _with_linkedin_fallback(claude, cv_text), cv_text
            )
        ollama = await _parse_with_ollama(cv_text)
        if ollama is not None:
            return _apply_contact_fallbacks(
                _with_linkedin_fallback(ollama, cv_text), cv_text
            )
    return _regex_fallback(cv_text)


def _with_linkedin_fallback(parsed: dict[str, Any], cv_text: str) -> dict[str, Any]:
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
