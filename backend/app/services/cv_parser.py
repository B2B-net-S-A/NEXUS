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
  1. deterministic text/contact extraction
  2. versioned gateway route (Haiku, explicit Sonnet escalation in v2)
  3. regex heuristic marked for human review after provider/schema failure

Contact-field safety net: after the LLM returns, a deterministic regex pass
(`_apply_contact_fallbacks`) fills in any email/phone/name it missed by
scanning the first ~15 lines of the CV and any standalone email addresses.
Values from the LLM win — the regex only fills in `None` slots.

Returns a dict — caller decides which fields to persist. On persist, the
`match_score_cache.mark_stale_for_candidate` hook should be invoked so the
cache recomputes with the fresh skills.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ai import AIError, AIRequest, ai_gateway
from app.core.config import settings
from app.models.ai_feature import AIFeatureKey
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
        "_provenance": {},
        "_needs_human_review": False,
    }
    result = _apply_contact_fallbacks(base, cv_text)
    result["_provenance"] = _build_provenance(result, cv_text, default_source="regex")
    return result


class _CVSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    level: Optional[str] = None
    years: Optional[float] = Field(default=None, ge=0, le=60)

    @field_validator("name")
    @classmethod
    def skill_name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("blank skill")
        return value.strip()


class _CVParseSchema(BaseModel):
    """Strict provider response; operational metadata is added server-side."""

    model_config = ConfigDict(extra="forbid")

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    city: Optional[str] = None
    years_it_experience: Optional[int] = Field(default=None, ge=0, le=60)
    current_position: Optional[str] = None
    skills: list[_CVSkill] = Field(default_factory=list)
    education: list[Any] = Field(default_factory=list)
    languages: list[Any] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    career_summary: Optional[str] = None
    linkedin_url: Optional[str] = None
    confidence: dict[str, float] = Field(default_factory=dict, alias="_confidence")

    @field_validator("email")
    @classmethod
    def plausible_email(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip().lower()
        if not _EMAIL_RE.fullmatch(value):
            raise ValueError("invalid email")
        return value

    @field_validator("phone")
    @classmethod
    def plausible_phone(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if len(re.sub(r"\D", "", value)) not in (9, 11):
            raise ValueError("invalid phone")
        return value.strip()


def _schema_validator(value: object) -> dict[str, Any]:
    parsed = _CVParseSchema.model_validate(value)
    return parsed.model_dump(by_alias=True)


class _CandidateSummarySchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=20, max_length=1200)


def _summary_fallback(parsed: dict[str, Any]) -> Optional[str]:
    """Build a small factual summary without a generative model."""
    parts: list[str] = []
    if parsed.get("current_position"):
        parts.append(str(parsed["current_position"]).strip())
    years = parsed.get("years_it_experience")
    if isinstance(years, int):
        parts.append(f"{years} lat doświadczenia IT")
    skill_names = [
        str(item.get("name", "")).strip()
        for item in parsed.get("skills", [])
        if isinstance(item, dict) and item.get("name")
    ][:6]
    if skill_names:
        parts.append("technologie: " + ", ".join(skill_names))
    return ". ".join(parts) + "." if parts else None


async def _generate_candidate_summary(
    parsed: dict[str, Any],
    *,
    user_id: Optional[int],
    client_id: Optional[int],
    subject_id: Optional[int],
) -> tuple[Optional[str], str]:
    """Generate a factual summary via its own Haiku-first feature route."""
    facts = {
        "years_it_experience": parsed.get("years_it_experience"),
        "current_position": parsed.get("current_position"),
        "skills": parsed.get("skills", []),
        "education": parsed.get("education", []),
        "languages": parsed.get("languages", []),
        "companies": parsed.get("companies", []),
    }

    def validate(value: object) -> str:
        return _CandidateSummarySchema.model_validate(value).summary.strip()

    try:
        result = await ai_gateway.call(
            AIRequest(
                feature=AIFeatureKey.candidate_summary,
                user_id=user_id,
                client_id=client_id,
                subject_type="candidate" if subject_id is not None else "cv_upload",
                subject_id=subject_id,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Napisz zwięzłe polskie podsumowanie profilu kandydata. "
                            "Używaj wyłącznie przekazanych faktów, bez danych kontaktowych, "
                            'ocen i domysłów. Zwróć JSON: {"summary": "..."}.'
                        ),
                    },
                    {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
                ],
                prompt_version="candidate_summary_facts_v1",
                schema_version="candidate_summary_v1",
                structured_validator=validate,
                pii=True,
            )
        )
        summary = (
            result.content
            if isinstance(result.content, str)
            else validate(result.content)
        )
        return summary, f"{result.provider}:{result.model}"
    except Exception as exc:  # noqa: BLE001 - summary must not fail CV extraction
        logger.warning("candidate_summary degraded error_type=%s", type(exc).__name__)
        return _summary_fallback(parsed), "deterministic:summary_v1"


def _evidence_for(value: Any, cv_text: str) -> str:
    """Return a short verbatim evidence line when a value occurs in source text."""
    candidates = value if isinstance(value, list) else [value]
    lowered = cv_text.lower()
    for item in candidates:
        if isinstance(item, dict):
            item = item.get("name")
        text = str(item or "").strip()
        if not text:
            continue
        position = lowered.find(text.lower())
        if position >= 0:
            line_start = cv_text.rfind("\n", 0, position) + 1
            line_end = cv_text.find("\n", position)
            if line_end < 0:
                line_end = len(cv_text)
            return cv_text[line_start:line_end].strip()[:240]
    return ""


def _build_provenance(
    parsed: dict[str, Any], cv_text: str, *, default_source: str
) -> dict[str, dict[str, str]]:
    provenance: dict[str, dict[str, str]] = {}
    for key, value in parsed.items():
        if key.startswith("_") or value in (None, "", [], {}):
            continue
        evidence = _evidence_for(value, cv_text)
        provenance[key] = {
            "source": default_source if evidence else f"{default_source}_inferred",
            "evidence": evidence,
        }
    return provenance


def _merge_deterministic_contacts(
    parsed: dict[str, Any], cv_text: str
) -> dict[str, Any]:
    """Exact source contacts override model output; names only fill blanks."""
    out = dict(parsed)
    deterministic = {
        "email": _extract_email_from_text(cv_text),
        "phone": _extract_phone_from_text(cv_text),
    }
    first, last = _split_name_from_header(cv_text)
    deterministic.update({"first_name": first, "last_name": last})
    confidence = dict(out.get("_confidence") or {})
    for field in ("email", "phone"):
        if deterministic[field]:
            out[field] = deterministic[field]
            confidence[field] = 1.0
    for field in ("first_name", "last_name"):
        if not out.get(field) and deterministic[field]:
            out[field] = deterministic[field]
            confidence[field] = 0.6
    out["_confidence"] = confidence
    return out


def _requires_review(parsed: dict[str, Any]) -> bool:
    has_identity = bool(
        (parsed.get("first_name") and parsed.get("last_name")) or parsed.get("email")
    )
    has_experience = bool(parsed.get("skills") or parsed.get("current_position"))
    return not (has_identity and has_experience)


async def _parse_with_claude(
    cv_text: str,
    *,
    user_id: Optional[int] = None,
    client_id: Optional[int] = None,
    subject_id: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    """Parse via the central gateway; route owns Haiku→Sonnet escalation."""
    if not settings.CV_ENRICHMENT_ENABLED:
        return None
    prompt = CV_ENRICHMENT.render(cv_text=cv_text[:8000])
    try:
        result = await ai_gateway.call(
            AIRequest(
                feature=AIFeatureKey.cv_parser,
                user_id=user_id,
                client_id=client_id,
                subject_type="candidate" if subject_id is not None else "cv_upload",
                subject_id=subject_id,
                messages=[
                    {"role": "system", "content": CV_ENRICHMENT.system_prompt or ""},
                    {"role": "user", "content": prompt},
                ],
                prompt_version=f"{CV_ENRICHMENT.name}_v{CV_ENRICHMENT.version}",
                schema_version="cv_parse_v2",
                structured_validator=_schema_validator,
                pii=True,
            )
        )
        data = dict(result.content)
        data["_source"] = f"{result.provider}:{result.model}"
        return data
    except AIError as exc:
        logger.warning(
            "cv_parser gateway failed code=%s error_type=%s",
            exc.code,
            type(exc).__name__,
        )
        return None


async def _parse_with_ollama(cv_text: str) -> Optional[dict[str, Any]]:
    """Ollama is intentionally unavailable as an implicit production fallback."""
    del cv_text
    return None


async def parse_cv(
    cv_text: str,
    *,
    prefer_llm: bool = True,
    user_id: Optional[int] = None,
    client_id: Optional[int] = None,
    subject_id: Optional[int] = None,
) -> dict[str, Any]:
    """
    Extract structured facts from CV text.

    With `prefer_llm=True` the versioned gateway route runs after deterministic
    extraction. Provider/schema failure yields regex output marked for review;
    there is no silent cross-provider or Ollama production fallback.

    Returns dict with keys: first_name, last_name, email, phone, city,
    years_it_experience, current_position, skills, education, languages,
    companies, career_summary, linkedin_url, _confidence, _source.

    Exact regex email/phone values win over model output. Existing Candidate
    fields remain protected by ``cv_enrichment`` when this result is persisted.
    """
    if not cv_text or not cv_text.strip():
        empty = _regex_fallback("")
        empty["_needs_human_review"] = True
        return empty

    if prefer_llm:
        claude = await _parse_with_claude(
            cv_text,
            user_id=user_id,
            client_id=client_id,
            subject_id=subject_id,
        )
        if claude is not None:
            parsed = _merge_deterministic_contacts(
                _with_linkedin_fallback(claude, cv_text), cv_text
            )
            summary, summary_source = await _generate_candidate_summary(
                parsed,
                user_id=user_id,
                client_id=client_id,
                subject_id=subject_id,
            )
            parsed["career_summary"] = summary
            parsed["_provenance"] = _build_provenance(
                parsed, cv_text, default_source=parsed.get("_source", "model")
            )
            if summary:
                parsed["_provenance"]["career_summary"] = {
                    "source": summary_source,
                    "evidence": "",
                }
            for field in ("email", "phone"):
                if parsed.get(field):
                    parsed["_provenance"][field] = {
                        "source": "deterministic",
                        "evidence": _evidence_for(parsed[field], cv_text),
                    }
            parsed["_needs_human_review"] = _requires_review(parsed)
            parsed["_input_hash"] = hashlib.sha256(cv_text.encode("utf-8")).hexdigest()
            return parsed
    fallback = _regex_fallback(cv_text)
    fallback["_needs_human_review"] = bool(prefer_llm)
    fallback["_input_hash"] = hashlib.sha256(cv_text.encode("utf-8")).hexdigest()
    return fallback


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
