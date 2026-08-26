"""Security-first AI candidate activity-summary service.

The summary is deliberately a *derived, scoped cache*, never a candidate-global
fact.  A cache row is reusable only for the exact visibility scope and content
policy that produced it.  Candidate/job history is filtered before rendering,
all financial facts are excluded, and untrusted free text passes input and
output DLP.

Generation uses a short, committed database lease.  The external LLM call runs
without an open transaction; publishing is fenced by a compare-and-swap token
so an expired or superseded worker cannot overwrite the winner.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import time
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import false, func, or_, select, union, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.recruitment_access import job_scope_clause
from app.models.ai_feature import AIFeatureKey
from app.models.call import Call
from app.models.candidate import Candidate
from app.models.candidate_activity_summary import CandidateActivitySummary
from app.models.client import Client
from app.models.contract import Contract
from app.models.interview_feedback import InterviewFeedback
from app.models.job import Job
from app.models.note import Note
from app.models.recruitment_pipeline import CandidateStage
from app.models.screening_note import ScreeningNote
from app.models.user import User
from app.services.ai_quota import (
    AIQuotaExceeded,
    ai_feature,
    get_feature_config,
    get_master_enabled,
)
from app.services.candidate_identity_quarantine import source_is_eligible_clause
from app.services.client_identity import client_display_name_expression
from app.services.llm_prompts import CANDIDATE_ACTIVITY_SUMMARY

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("CANDIDATE_SUMMARY_MODEL", "claude-sonnet-5")
MAX_TOKENS = 1200

# Changing this value invalidates every previously generated row even when the
# prompt happens to retain the same version.
CONTENT_POLICY_VERSION = "candidate-summary-no-finance-v3"
VISIBILITY_SCOPE_VERSION = "candidate-summary-scope-v1"

# Input caps so a hyperactive candidate cannot create an unbounded prompt.
_MAX_NOTES = 30
_MAX_NOTE_CHARS = 350
_MAX_STAGE_ROWS = 80
_MAX_JOBS_RENDERED = 15
_MAX_FEEDBACK = 15
_MAX_SCREENINGS = 3
_MAX_CONTRACTS = 12
_MAX_CALLS = 6
_MAX_CALL_CHARS = 250
_MAX_SUMMARY_CHARS = 4000
_DEFAULT_LEASE_SECONDS = 180

_EMPTY = "(brak danych)"

# Amount-oriented DLP.  Dates, ratings and technology versions are allowed;
# numbers become sensitive when they carry a currency/unit or sit next to a
# finance keyword.  The same detector guards prompt inputs and LLM output.
_NUMBER_TOKEN = r"(?:\d{1,3}(?:[ .]\d{3})*(?:[,.]\d{1,3})?|\d+(?:[,.]\d+)?)"
_AMOUNT_TOKEN = rf"(?:{_NUMBER_TOKEN}\s*(?:k\b|tys(?:\.|ięcy)?\b)?)"
_CURRENCY_TOKEN = (
    r"(?:(?<![\w])(?:"
    r"PLN|EUR|USD|GBP|CHF|SEK|NOK|DKK|CZK|HUF|RON|UAH|RUB|JPY|CNY|"
    r"CAD|AUD|AED|zł(?:ot(?:y|e|ych))?|euro|"
    r"dolar(?:a|y|ów)?|dollar(?:s)?|funt(?:a|y|ów)?|pound(?:s)?|"
    r"frank(?:a|i|ów)?|koron(?:a|y|ę|ach)?|dirham(?:s|y|ów)?"
    r")(?![\w])|[$€£¥])"
)
_MONEY_UNIT = (
    r"(?:/\s*(?:h|hour|godz\.?|d|dzień|dzien|day|mies\.?|miesiąc)|"
    r"per\s+(?:hour|day|month)|netto|brutto)"
)
_FINANCE_KEYWORD = (
    r"(?:staw(?:ka|ki|kę)|wynagrodzeni(?:e|a|u)|pensj(?:a|i|ę)|salary|rate|"
    r"budżet|budzet|marż(?:a|y|ę)|koszt(?:y|u)?|płac(?:a|y|ę)|zarob(?:ki|ków)|"
    r"kwot(?:a|y|ę)|pieniądz(?:e|y)?|finansow(?:y|a|e|ych)|compensation|"
    r"netto|brutto|b2b|uop|vat|currency|walut(?:a|y|ę))"
)
_FINANCIAL_AMOUNT_RE = re.compile(
    rf"(?:{_AMOUNT_TOKEN}\s*(?:{_CURRENCY_TOKEN}|{_MONEY_UNIT}))|"
    rf"(?:(?:{_CURRENCY_TOKEN})\s*{_AMOUNT_TOKEN})|"
    rf"(?:{_FINANCE_KEYWORD}.{{0,48}}?{_AMOUNT_TOKEN})|"
    rf"(?:{_AMOUNT_TOKEN}.{{0,48}}?{_FINANCE_KEYWORD})|"
    rf"(?:\b\d{{2,}}\s*(?:k\b|tys(?:\.|ięcy)?\b))",
    re.IGNORECASE,
)
_FINANCIAL_TOPIC_RE = re.compile(
    rf"(?:{_CURRENCY_TOKEN})|"
    rf"(?<![\w]){_FINANCE_KEYWORD}(?![\w])|"
    rf"(?:{_MONEY_UNIT})",
    re.IGNORECASE,
)

_PROMPT_INJECTION_RE = re.compile(
    r"(?:"
    r"(?:zignoruj|pomiń|pomin|zapomnij|nadpisz|obejdź|obejdz)\b.{0,80}\b"
    r"(?:poprzedn|wcześniejsz|wczesniejsz|powyższ|powyzsz|"
    r"instrukcj|polecen|zasad|prompt|system)|"
    r"(?:ignore|disregard|forget|override|bypass)\b.{0,80}\b"
    r"(?:previous|prior|above|instruction|rules|prompt|system)|"
    r"(?:ujawnij|pokaż|pokaz|wypisz|zwróć|zwroc)\b.{0,80}\b"
    r"(?:prompt|instrukcj|wiadomość system|wiadomosc system)|"
    r"(?:reveal|expose|print|return)\b.{0,80}\b"
    r"(?:system prompt|hidden prompt|instructions)|"
    r"(?:napisz|wpisz|dodaj)\s+(?:w\s+podsumowaniu\s+)?(?:że|ze)\b|"
    r"(?:write|state|claim)\s+(?:in\s+the\s+summary\s+)?that\b|"
    r"(?:nie\s+wspominaj|do\s+not\s+mention|don't\s+mention)\b|"
    r"(?:system|developer)\s*(?:prompt|message|instruction)|"
    r"jesteś\s+(?:chatgpt|claude|asystentem)|"
    r"you\s+are\s+(?:chatgpt|claude|an?\s+assistant)|"
    r"(?:act|behave)\s+as\s+(?:chatgpt|claude|an?\s+assistant)|"
    r"od\s+teraz\s+(?:jesteś|jestes|działaj|dzialaj)|"
    r"<\s*/?\s*(?:system|assistant|developer)\b|"
    r"###\s*(?:system|instruction|developer)"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_FRAGMENT_SPLIT_RE = re.compile(r"(?:\r?\n)+|(?<=[.!?])\s+")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_HTML_SCRIPT_STYLE_RE = re.compile(
    r"<\s*(script|style)\b[^>]*>.*?<\s*/\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
_UNTRUSTED_ROLE_BLOCK_RE = re.compile(
    r"<\s*(system|assistant|developer)\b[^>]*>.*?<\s*/\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
_HTML_BLOCK_TAG_RE = re.compile(
    r"<\s*/?\s*(?:p|div|br|li|ul|ol|table|tr|td|th|h[1-6])\b[^>]*>",
    re.IGNORECASE,
)
_HTML_TAG_RE = re.compile(r"<[^>]*>")
_SOURCE_NAMES = (
    "profile",
    "submissions",
    "feedback",
    "screening",
    "notes",
    "contracts",
    "calls",
)
_MANIFEST_COUNTER_KEYS = (
    "included_items",
    "truncated_items",
    "redacted_financial_fragments",
    "redacted_instruction_fragments",
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")

_FINANCIAL_PREFERENCE_KEYS = frozenset(
    {
        "salary",
        "salary_expectation",
        "salary_currency",
        "salary_min",
        "salary_max",
        "rate",
        "rate_min",
        "rate_max",
        "rate_currency",
        "expected_rate",
        "expected_rate_hourly",
        "expected_rate_currency",
        "budget",
        "compensation",
        "pay",
        "currency",
        "tax_basis",
        "contract_type",
        "net",
        "gross",
        "vat",
        "billing_rate",
        "client_rate",
        "sell_rate",
        "margin",
    }
)
_DROP_PREFERENCE_VALUE = object()

# PL labels for pipeline stages (prompt readability).
_STAGE_LABELS = {
    "new": "Nowy / analiza CV",
    "prep_call": "Preparation call",
    "screening": "Screening",
    "verified": "Zweryfikowany",
    "interview": "Interview wewnętrzny",
    "cv_sent": "CV wysłane do klienta",
    "client_interview": "Rozmowa u klienta",
    "acceptance": "Akceptacja klienta",
    "negotiation": "Negocjacje",
    "onboarding": "Onboarding",
    "hired": "Zatrudniony",
    "rejected": "Odrzucony",
    "withdrawn": "Wycofał się",
}

_DECISION_LABELS = {
    "advance": "dalej w procesie",
    "reject": "odrzucenie",
    "on_hold": "wstrzymane",
}


class CandidateActivitySummaryNotFound(Exception):
    """Candidate does not exist."""


class CandidateActivitySummaryLLMError(Exception):
    """The LLM call failed or returned content rejected by policy."""


class CandidateActivitySummaryBusy(Exception):
    """Another worker owns the live generation lease for this scoped row."""


@dataclass
class _RedactionStats:
    financial_fragments: int = 0
    instruction_fragments: int = 0
    truncated_fragments: int = 0


@dataclass(frozen=True)
class SourceSection:
    name: str
    text: str
    included_items: int
    truncated_items: int = 0
    redacted_financial_fragments: int = 0
    redacted_instruction_fragments: int = 0

    def manifest_entry(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "included_items": self.included_items,
            "truncated_items": self.truncated_items,
            "redacted_financial_fragments": self.redacted_financial_fragments,
            "redacted_instruction_fragments": self.redacted_instruction_fragments,
        }


@dataclass(frozen=True)
class SummaryContext:
    sections: dict[str, str]
    visibility_scope_hash: str
    source_version: str
    source_manifest: dict[str, Any]


@dataclass(frozen=True)
class CandidateActivitySummaryState:
    row: Optional[CandidateActivitySummary]
    current_source_version: str
    visibility_scope_hash: str
    current_source_manifest: dict[str, Any]

    @property
    def is_stale(self) -> bool:
        return bool(
            self.row is not None
            and self.row.source_version != self.current_source_version
        )


# ── Small render and DLP helpers ─────────────────────────────────────────────


def _truncate(text: Optional[str], limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + " […]"


def _enum_val(value: Any) -> str:
    if value is None:
        return ""
    return str(getattr(value, "value", value))


def _fmt_date(value: Optional[datetime | date]) -> str:
    if value is None:
        return "?"
    return value.strftime("%Y-%m-%d")


def _skills_to_text(raw: Any, limit: int = 25) -> str:
    if not raw:
        return ""
    if isinstance(raw, list):
        names: list[str] = []
        for skill in raw:
            name = (
                (skill.get("name") or skill.get("skill") or "")
                if isinstance(skill, dict)
                else str(skill)
            ).strip()
            if name:
                names.append(name)
        return ", ".join(names[:limit])
    if isinstance(raw, str):
        return _truncate(raw, 400)
    return ""


def _normalize_security_text(raw: Optional[str]) -> str:
    """Expose hidden Unicode and markup before scanning or prompting."""

    text = html.unescape(raw or "")
    text = unicodedata.normalize("NFKC", text)
    text = "".join(char for char in text if unicodedata.category(char) != "Cf")
    text = _HTML_SCRIPT_STYLE_RE.sub("", text)
    text = _HTML_COMMENT_RE.sub("", text)
    text = _UNTRUSTED_ROLE_BLOCK_RE.sub("\nSYSTEM PROMPT\n", text)
    text = _HTML_BLOCK_TAG_RE.sub("\n", text)
    # Inline tags join their surrounding text, making evasions such as
    # ``1<span>80</span> PLN`` visible to the amount detector.
    text = _HTML_TAG_RE.sub("", text)
    return _CONTROL_RE.sub(" ", text)


def _normalize_for_detection(raw: Optional[str]) -> str:
    """Expose evasions without discarding potentially unsafe tag bodies.

    Input sanitization may safely drop a script or comment.  Detection cannot:
    output DLP must still see an amount or instruction hidden inside markup
    before anything is allowed into the cache.
    """

    text = html.unescape(raw or "")
    text = unicodedata.normalize("NFKC", text)
    text = "".join(char for char in text if unicodedata.category(char) != "Cf")
    # Keep HTML comment bodies visible to the scanners.
    text = _HTML_COMMENT_RE.sub(lambda match: f" {match.group(0)[4:-3]} ", text)
    # Removing tags, rather than tag blocks, joins split-token evasions such as
    # ``1<span>80</span>`` and retains script/style/role-block bodies.
    text = _HTML_TAG_RE.sub("", text)
    return _CONTROL_RE.sub(" ", text)


def _contains_financial_amount(text: str) -> bool:
    detection_text = _normalize_for_detection(text)
    # Fail closed on the financial topic itself, not just Arabic numerals.
    # This also catches word-written amounts ("sto osiemdziesiąt zł") and
    # output such as "stawka do ustalenia", which must not enter this cache.
    return bool(
        _FINANCIAL_AMOUNT_RE.search(detection_text)
        or _FINANCIAL_TOPIC_RE.search(detection_text)
    )


def _contains_prompt_injection(text: str) -> bool:
    detection_text = _normalize_for_detection(text)
    markup_visible = html.unescape(text or "")
    markup_visible = unicodedata.normalize("NFKC", markup_visible)
    markup_visible = "".join(
        char for char in markup_visible if unicodedata.category(char) != "Cf"
    )
    return bool(
        _PROMPT_INJECTION_RE.search(detection_text)
        or _PROMPT_INJECTION_RE.search(markup_visible)
    )


def _scope_log_ref(visibility_scope_hash: str | None) -> str:
    """Return a non-PII correlation key suitable for production logs."""

    value = str(visibility_scope_hash or "")
    return value[:12] if _SHA256_RE.fullmatch(value) else "invalid"


def _log_policy_event(
    *,
    reason: str,
    candidate_id: int | None,
    visibility_scope_hash: str | None,
    source: str,
    count: int = 1,
) -> None:
    """Emit an aggregate, source-free event for DLP/lease monitoring."""

    logger.warning(
        "candidate_activity_summary: policy_event reason=%s candidate_id=%s "
        "scope=%s source=%s count=%d",
        reason,
        candidate_id if candidate_id is not None else "unknown",
        _scope_log_ref(visibility_scope_hash),
        source,
        count,
    )


def _safe_preferences(value: Any, stats: _RedactionStats) -> Any:
    """Recursively remove financial keys while keeping safe preferences."""

    if isinstance(value, dict):
        normalized_keys = {
            re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_") for key in value
        }
        amount_keys = {"amount", "value", "min", "max", "minimum", "maximum"}
        financial_dimension_keys = {
            "currency",
            "unit",
            "tax_basis",
            "contract_type",
            "net",
            "gross",
            "vat",
        }
        if normalized_keys & amount_keys and normalized_keys & financial_dimension_keys:
            stats.financial_fragments += 1
            return _DROP_PREFERENCE_VALUE

        safe: dict[str, Any] = {}
        for raw_key, child in value.items():
            key = str(raw_key)
            normalized_key = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
            if normalized_key in _FINANCIAL_PREFERENCE_KEYS or any(
                token in normalized_key
                for token in (
                    "salary",
                    "stawka",
                    "wynagrod",
                    "rate",
                    "budget",
                    "currency",
                    "margin",
                    "compensation",
                    "billing",
                    "sell",
                    "finance",
                )
            ):
                stats.financial_fragments += 1
                continue
            safe_child = _safe_preferences(child, stats)
            if safe_child is not _DROP_PREFERENCE_VALUE:
                safe[key] = safe_child
        return safe
    if isinstance(value, list):
        safe_items = [_safe_preferences(item, stats) for item in value]
        return [item for item in safe_items if item is not _DROP_PREFERENCE_VALUE]
    return value


def _sanitize_untrusted(
    raw: Optional[str],
    *,
    limit: int,
    stats: _RedactionStats,
) -> str:
    """Drop whole sensitive/instruction-like fragments from untrusted text."""
    text = _normalize_security_text(raw).strip()
    if not text:
        return ""

    safe_fragments: list[str] = []
    for fragment in _FRAGMENT_SPLIT_RE.split(text):
        fragment = " ".join(fragment.split()).strip()
        if not fragment or not any(char.isalnum() for char in fragment):
            continue
        if _contains_financial_amount(fragment):
            stats.financial_fragments += 1
            continue
        if _contains_prompt_injection(fragment):
            stats.instruction_fragments += 1
            continue
        # Prevent source text from closing the fixed XML-like prompt boundary.
        safe_fragments.append(fragment.replace("<", "‹").replace(">", "›"))

    safe = " ".join(safe_fragments)
    if len(safe) > limit:
        stats.truncated_fragments += 1
        safe = _truncate(safe, limit)
    return safe


def _source_section(
    name: str,
    lines: list[str],
    *,
    query_truncated: int = 0,
    stats: Optional[_RedactionStats] = None,
) -> SourceSection:
    stats = stats or _RedactionStats()
    return SourceSection(
        name=name,
        text="\n".join(lines) or _EMPTY,
        included_items=len(lines),
        truncated_items=query_truncated + stats.truncated_fragments,
        redacted_financial_fragments=stats.financial_fragments,
        redacted_instruction_fragments=stats.instruction_fragments,
    )


def _scope_filter(column: Any, visible_job_ids: tuple[int, ...], *, null_ok: bool):
    member_clause = column.in_(visible_job_ids) if visible_job_ids else false()
    return or_(column.is_(None), member_clause) if null_ok else member_clause


def _visibility_scope_hash(
    user: User, visible_job_ids: list[int] | tuple[int, ...]
) -> str:
    roles = sorted(role.value for role in user.get_all_roles())
    payload = json.dumps(
        {
            "version": VISIBILITY_SCOPE_VERSION,
            # Per-user fencing is intentional.  Even two users with currently
            # identical memberships cannot accidentally share prose.
            "user_id": user.id,
            "roles": roles,
            "visible_job_ids": sorted({int(job_id) for job_id in visible_job_ids}),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ── Visibility scope and deterministic source builders ──────────────────────


async def _visible_candidate_job_ids(
    db: AsyncSession, candidate_id: int, user: User
) -> tuple[int, ...]:
    """Return every candidate-linked job that is inside the caller's scope."""
    candidate_jobs = union(
        select(CandidateStage.job_id.label("job_id")).where(
            CandidateStage.candidate_id == candidate_id
        ),
        select(InterviewFeedback.job_id.label("job_id")).where(
            InterviewFeedback.candidate_id == candidate_id,
            InterviewFeedback.job_id.is_not(None),
        ),
        select(ScreeningNote.job_id.label("job_id")).where(
            ScreeningNote.candidate_id == candidate_id,
            ScreeningNote.job_id.is_not(None),
        ),
        select(Note.job_id.label("job_id")).where(
            Note.candidate_id == candidate_id,
            Note.job_id.is_not(None),
            Note.source_deleted_at.is_(None),
            source_is_eligible_clause(
                candidate_id_column=Note.candidate_id,
                source_id_column=Note.id,
                source_kind="note",
            ),
        ),
        select(Contract.job_id.label("job_id")).where(
            Contract.candidate_id == candidate_id,
            Contract.job_id.is_not(None),
        ),
    ).subquery()
    rows = await db.execute(
        select(candidate_jobs.c.job_id)
        .where(job_scope_clause(user, candidate_jobs.c.job_id))
        .distinct()
    )
    return tuple(sorted(int(job_id) for job_id in rows.scalars() if job_id is not None))


def _profile_section(candidate: Candidate) -> SourceSection:
    lines: list[str] = []
    stats = _RedactionStats()

    status = _enum_val(candidate.status)
    if status:
        lines.append(f"Status w ATS: {status}")
    if candidate.competence_category:
        category = _sanitize_untrusted(
            str(candidate.competence_category), limit=160, stats=stats
        )
        if category:
            lines.append(f"Kategoria kompetencji: {category}")
    skills = _sanitize_untrusted(
        _skills_to_text(candidate.skills), limit=500, stats=stats
    )
    if skills:
        lines.append(f"Umiejętności: {skills}")

    availability = _enum_val(candidate.availability_status)
    if availability and availability != "unknown":
        lines.append(f"Status dostępności: {availability}")
    if candidate.availability_date:
        lines.append(f"Dostępny od: {_fmt_date(candidate.availability_date)}")
    if candidate.notice_period:
        unit = _enum_val(candidate.notice_period_unit) or "dni"
        lines.append(f"Okres wypowiedzenia: {candidate.notice_period} {unit}")

    if isinstance(candidate.preferences, dict) and candidate.preferences:
        safe_preference_data = _safe_preferences(candidate.preferences, stats)
        if safe_preference_data is not _DROP_PREFERENCE_VALUE and safe_preference_data:
            safe_preferences = _sanitize_untrusted(
                json.dumps(
                    safe_preference_data,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                limit=600,
                stats=stats,
            )
            if safe_preferences:
                lines.append(f"Preferencje: {safe_preferences}")
    safe_engagement = _sanitize_untrusted(
        candidate.engagement_notes, limit=500, stats=stats
    )
    if safe_engagement:
        lines.append(f"Notatki o zaangażowaniu: {safe_engagement}")
    return _source_section("profile", lines, stats=stats)


async def _submissions_section(
    db: AsyncSession, candidate_id: int, visible_job_ids: tuple[int, ...]
) -> SourceSection:
    if not visible_job_ids:
        return _source_section("submissions", [])
    rows = (
        await db.execute(
            select(
                CandidateStage,
                Job.title,
                client_display_name_expression().label("client_name"),
            )
            .join(Job, Job.id == CandidateStage.job_id)
            .outerjoin(Client, Client.id == Job.client_id)
            .where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id.in_(visible_job_ids),
            )
            .order_by(CandidateStage.moved_at.desc())
            .limit(_MAX_STAGE_ROWS + 1)
        )
    ).all()
    query_truncated = max(0, len(rows) - _MAX_STAGE_ROWS)
    rows = rows[:_MAX_STAGE_ROWS]
    if not rows:
        return _source_section("submissions", [])

    jobs: dict[int, dict[str, Any]] = {}
    for stage, job_title, client_name in rows:
        entry = jobs.setdefault(
            stage.job_id,
            {
                "title": job_title,
                "client": client_name,
                "last_moved": stage.moved_at,
                "stages": [],
                "rejection_notes": [],
                "offer_response": None,
            },
        )
        entry["stages"].append(_enum_val(stage.stage))
        if stage.rejection_note:
            entry["rejection_notes"].append(stage.rejection_note)
        if entry["offer_response"] is None and stage.candidate_offer_response:
            entry["offer_response"] = _enum_val(stage.candidate_offer_response)

    stats = _RedactionStats()
    lines: list[str] = []
    rendered_jobs = list(jobs.values())[:_MAX_JOBS_RENDERED]
    query_truncated += max(0, len(jobs) - len(rendered_jobs))
    for entry in rendered_jobs:
        title = _sanitize_untrusted(entry["title"], limit=180, stats=stats)
        client_name = _sanitize_untrusted(entry["client"], limit=120, stats=stats)
        latest_stage = entry["stages"][0]
        label = _STAGE_LABELS.get(latest_stage, latest_stage)
        client = f" — klient: {client_name}" if client_name else ""
        lines.append(
            f"- {title or 'Rekrutacja'}{client}: ostatni etap „{label}” "
            f"({_fmt_date(entry['last_moved'])})"
        )
        reached = set(entry["stages"])
        if "client_interview" in reached:
            lines.append("  Doszło do rozmowy u klienta.")
        elif "interview" in reached:
            lines.append("  Doszło do interview wewnętrznego.")
        if entry["offer_response"]:
            lines.append(f"  Odpowiedź na ofertę: {entry['offer_response']}")
        for raw_note in entry["rejection_notes"][:2]:
            note = _sanitize_untrusted(raw_note, limit=250, stats=stats)
            if note:
                lines.append(f"  Powód odrzucenia: {note}")
    return _source_section(
        "submissions", lines, query_truncated=query_truncated, stats=stats
    )


async def _feedback_section(
    db: AsyncSession, candidate_id: int, visible_job_ids: tuple[int, ...]
) -> SourceSection:
    rows = (
        await db.execute(
            select(InterviewFeedback, Job.title)
            .outerjoin(Job, Job.id == InterviewFeedback.job_id)
            .where(
                InterviewFeedback.candidate_id == candidate_id,
                _scope_filter(InterviewFeedback.job_id, visible_job_ids, null_ok=False),
            )
            .order_by(InterviewFeedback.id.desc())
            .limit(_MAX_FEEDBACK + 1)
        )
    ).all()
    query_truncated = max(0, len(rows) - _MAX_FEEDBACK)
    rows = rows[:_MAX_FEEDBACK]
    stats = _RedactionStats()
    lines: list[str] = []
    for feedback, raw_job_title in rows:
        bits: list[str] = []
        source = _enum_val(feedback.feedback_source)
        side = "od klienta" if source == "client_side" else "od kandydata"
        decision = _DECISION_LABELS.get(_enum_val(feedback.decision), "")
        if decision:
            bits.append(f"decyzja: {decision}")
        if feedback.overall_fit:
            bits.append(f"dopasowanie {feedback.overall_fit}/5")
        if feedback.overall_impression:
            bits.append(f"wrażenie {feedback.overall_impression}/5")
        interest = _enum_val(feedback.interest_level)
        if interest:
            bits.append(f"zainteresowanie kandydata: {interest}")
        job_title = _sanitize_untrusted(raw_job_title, limit=180, stats=stats)
        header = f"- {job_title or 'Rekrutacja'} ({side})"
        if bits:
            header += ": " + ", ".join(bits)
        lines.append(header)
        summary = _sanitize_untrusted(feedback.feedback_summary, limit=400, stats=stats)
        if summary:
            lines.append(f"  Feedback: {summary}")
        concerns = _sanitize_untrusted(feedback.concerns, limit=250, stats=stats)
        if concerns:
            lines.append(f"  Obawy: {concerns}")
    return _source_section(
        "feedback", lines, query_truncated=query_truncated, stats=stats
    )


async def _screening_section(
    db: AsyncSession, candidate_id: int, visible_job_ids: tuple[int, ...]
) -> SourceSection:
    rows = (
        (
            await db.execute(
                select(ScreeningNote)
                .where(
                    ScreeningNote.candidate_id == candidate_id,
                    _scope_filter(ScreeningNote.job_id, visible_job_ids, null_ok=False),
                )
                .order_by(ScreeningNote.created_at.desc())
                .limit(_MAX_SCREENINGS + 1)
            )
        )
        .scalars()
        .all()
    )
    query_truncated = max(0, len(rows) - _MAX_SCREENINGS)
    rows = rows[:_MAX_SCREENINGS]
    stats = _RedactionStats()
    lines: list[str] = []
    for screening in rows:
        bits: list[str] = []
        motivation = _enum_val(screening.motivation_primary)
        if motivation == "money":
            stats.financial_fragments += 1
        elif motivation:
            bits.append(f"motywacja: {motivation}")
        if screening.readiness_to_change:
            bits.append(f"gotowość do zmiany {screening.readiness_to_change}/5")
        header = f"- Screening {_fmt_date(screening.created_at)}"
        if bits:
            header += ": " + ", ".join(bits)
        lines.append(header)
        red_flags = _sanitize_untrusted(screening.red_flags, limit=250, stats=stats)
        if red_flags:
            lines.append(f"  Red flags: {red_flags}")
        notes = _sanitize_untrusted(screening.personality_notes, limit=300, stats=stats)
        if notes:
            lines.append(f"  Notatki: {notes}")
    return _source_section(
        "screening", lines, query_truncated=query_truncated, stats=stats
    )


async def _notes_section(
    db: AsyncSession, candidate_id: int, visible_job_ids: tuple[int, ...]
) -> SourceSection:
    rows = (
        (
            await db.execute(
                select(Note)
                .where(
                    Note.candidate_id == candidate_id,
                    Note.source_deleted_at.is_(None),
                    # A candidate-global note has no job membership proof. The
                    # summary is scope-bound, so NULL job_id is deliberately
                    # rejected instead of being shared across disjoint teams.
                    _scope_filter(Note.job_id, visible_job_ids, null_ok=False),
                    source_is_eligible_clause(
                        candidate_id_column=Note.candidate_id,
                        source_id_column=Note.id,
                        source_kind="note",
                    ),
                )
                .order_by(Note.created_at.desc())
                .limit(_MAX_NOTES + 1)
            )
        )
        .scalars()
        .all()
    )
    query_truncated = max(0, len(rows) - _MAX_NOTES)
    rows = rows[:_MAX_NOTES]
    stats = _RedactionStats()
    lines: list[str] = []
    for note in rows:
        safe = _sanitize_untrusted(note.content, limit=_MAX_NOTE_CHARS, stats=stats)
        if safe:
            lines.append(
                f"- [{_fmt_date(note.source_created_at or note.created_at)}] {safe}"
            )
    return _source_section("notes", lines, query_truncated=query_truncated, stats=stats)


async def _contracts_section(
    db: AsyncSession, candidate_id: int, visible_job_ids: tuple[int, ...]
) -> SourceSection:
    """Scoped non-financial cooperation facts only."""
    if not visible_job_ids:
        return _source_section("contracts", [])
    rows = (
        await db.execute(
            select(
                Contract,
                client_display_name_expression().label("client_name"),
            )
            .outerjoin(Client, Client.id == Contract.client_id)
            .where(
                Contract.candidate_id == candidate_id,
                Contract.job_id.in_(visible_job_ids),
            )
            .order_by(Contract.start_date.desc().nulls_last())
            .limit(_MAX_CONTRACTS + 1)
        )
    ).all()
    query_truncated = max(0, len(rows) - _MAX_CONTRACTS)
    rows = rows[:_MAX_CONTRACTS]
    stats = _RedactionStats()
    lines: list[str] = []
    for contract, raw_client_name in rows:
        client_name = _sanitize_untrusted(raw_client_name, limit=120, stats=stats)
        period = f"{_fmt_date(contract.start_date)} → " + (
            _fmt_date(contract.end_date) if contract.end_date else "czas nieokreślony"
        )
        bits = [f"- Współpraca z klientem {client_name or '?'} ({period})"]
        work_mode = _enum_val(contract.work_mode)
        if work_mode:
            bits.append(f"tryb pracy: {work_mode}")
        status = _enum_val(contract.status)
        if status:
            bits.append(f"status: {status}")
        project = _sanitize_untrusted(contract.project_name, limit=180, stats=stats)
        if project:
            bits.append(f"projekt: {project}")
        lines.append(", ".join(bits))
        termination = _enum_val(contract.termination_reason)
        if termination:
            lines.append(f"  Powód zakończenia: {termination}")
    return _source_section(
        "contracts", lines, query_truncated=query_truncated, stats=stats
    )


async def _calls_section(
    db: AsyncSession, candidate_id: int, visible_job_ids: tuple[int, ...]
) -> SourceSection:
    """Only calls whose contract resolves to a job inside the caller's scope."""
    if not visible_job_ids:
        return _source_section("calls", [])
    rows = (
        (
            await db.execute(
                select(Call)
                .join(Contract, Contract.id == Call.contract_id)
                .where(
                    Call.candidate_id == candidate_id,
                    Call.summary.is_not(None),
                    Contract.job_id.in_(visible_job_ids),
                )
                .order_by(Call.started_at.desc().nulls_last())
                .limit(_MAX_CALLS + 1)
            )
        )
        .scalars()
        .all()
    )
    query_truncated = max(0, len(rows) - _MAX_CALLS)
    rows = rows[:_MAX_CALLS]
    stats = _RedactionStats()
    lines: list[str] = []
    for call in rows:
        safe = _sanitize_untrusted(call.summary, limit=_MAX_CALL_CHARS, stats=stats)
        if safe:
            lines.append(f"- [{_fmt_date(call.started_at)}] {safe}")
    return _source_section("calls", lines, query_truncated=query_truncated, stats=stats)


def _input_hash(sections: dict[str, str], visibility_scope_hash: str = "") -> str:
    """Fingerprint safe source content, scope, prompt, model and policy."""
    payload = json.dumps(
        {
            "content_policy_version": CONTENT_POLICY_VERSION,
            "prompt_version": CANDIDATE_ACTIVITY_SUMMARY.version,
            "model": DEFAULT_MODEL,
            "visibility_scope_hash": visibility_scope_hash,
            "sections": sections,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def build_context(
    db: AsyncSession, candidate: Candidate, user: User
) -> SummaryContext:
    visible_job_ids = await _visible_candidate_job_ids(db, candidate.id, user)
    source_sections = [
        _profile_section(candidate),
        await _submissions_section(db, candidate.id, visible_job_ids),
        await _feedback_section(db, candidate.id, visible_job_ids),
        await _screening_section(db, candidate.id, visible_job_ids),
        await _notes_section(db, candidate.id, visible_job_ids),
        await _contracts_section(db, candidate.id, visible_job_ids),
        await _calls_section(db, candidate.id, visible_job_ids),
    ]
    sections = {section.name: section.text for section in source_sections}
    scope_hash = _visibility_scope_hash(user, visible_job_ids)
    source_version = _input_hash(sections, scope_hash)
    manifest = {
        "content_policy_version": CONTENT_POLICY_VERSION,
        "sources": [section.manifest_entry() for section in source_sections],
    }
    financial_redactions = sum(
        section.redacted_financial_fragments for section in source_sections
    )
    instruction_redactions = sum(
        section.redacted_instruction_fragments for section in source_sections
    )
    if financial_redactions:
        _log_policy_event(
            reason="source_finance_redacted",
            candidate_id=candidate.id,
            visibility_scope_hash=scope_hash,
            source="prompt_context",
            count=financial_redactions,
        )
    if instruction_redactions:
        _log_policy_event(
            reason="source_injection_redacted",
            candidate_id=candidate.id,
            visibility_scope_hash=scope_hash,
            source="prompt_context",
            count=instruction_redactions,
        )
    return SummaryContext(
        sections=sections,
        visibility_scope_hash=scope_hash,
        source_version=source_version,
        source_manifest=manifest,
    )


# ── LLM plumbing ─────────────────────────────────────────────────────────────


async def _call_claude_text(
    *, prompt: str, system_prompt: str, model: str, max_tokens: int
) -> str:
    from app.services.claude_client import call_claude  # local: load only on use

    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if not api_key:
        raise CandidateActivitySummaryLLMError("ANTHROPIC_API_KEY not configured")

    started = time.time()
    try:
        message = await run_in_threadpool(
            call_claude,
            model=model,
            max_tokens=max_tokens,
            thinking={"type": "disabled"},
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            api_key=api_key,
        )
    except Exception as exc:  # noqa: BLE001 - map provider details to domain error
        raise CandidateActivitySummaryLLMError(f"LLM request failed: {exc}") from exc

    latency_ms = int((time.time() - started) * 1000)
    raw = "".join(
        getattr(block, "text", "") or ""
        for block in message.content
        if hasattr(block, "text")
    ).strip()
    usage = getattr(message, "usage", None)
    logger.info(
        "candidate_activity_summary: llm_call model=%s latency_ms=%d in=%s out=%s",
        model,
        latency_ms,
        getattr(usage, "input_tokens", "?"),
        getattr(usage, "output_tokens", "?"),
    )
    return raw


def _sanitize_llm_output(
    raw: str,
    *,
    candidate_id: int | None = None,
    visibility_scope_hash: str | None = None,
    source: str = "llm_output",
) -> str:
    # Scan the untrusted response before presentation cleanup.  Otherwise an
    # amount/instruction hidden in a script, comment or role tag could be
    # silently removed here but still bypass the explicit fail-closed policy.
    if _contains_financial_amount(raw):
        _log_policy_event(
            reason="output_finance_rejected",
            candidate_id=candidate_id,
            visibility_scope_hash=visibility_scope_hash,
            source=source,
        )
        raise CandidateActivitySummaryLLMError(
            "LLM output rejected by financial-data policy"
        )
    if _contains_prompt_injection(raw):
        _log_policy_event(
            reason="output_injection_rejected",
            candidate_id=candidate_id,
            visibility_scope_hash=visibility_scope_hash,
            source=source,
        )
        raise CandidateActivitySummaryLLMError(
            "LLM output rejected by instruction-injection policy"
        )
    text = _normalize_security_text(raw).strip()
    if text.startswith("```"):
        text = re.sub(r"^```[^\n]*\n?", "", text)
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        text = text.strip()
    if not text:
        raise CandidateActivitySummaryLLMError("LLM output empty")
    return text[:_MAX_SUMMARY_CHARS].rstrip()


async def generate_summary(
    sections: dict[str, str],
    *,
    model: str = DEFAULT_MODEL,
    candidate_id: int | None = None,
    visibility_scope_hash: str | None = None,
) -> str:
    """Generate prose only after a defense-in-depth scan of safe sections."""
    for section_name, section_text in sections.items():
        if _contains_financial_amount(section_text):
            _log_policy_event(
                reason="input_finance_rejected",
                candidate_id=candidate_id,
                visibility_scope_hash=visibility_scope_hash,
                source=section_name,
            )
            raise CandidateActivitySummaryLLMError(
                f"Prompt input rejected by financial-data policy: {section_name}"
            )
        if _contains_prompt_injection(section_text):
            _log_policy_event(
                reason="input_injection_rejected",
                candidate_id=candidate_id,
                visibility_scope_hash=visibility_scope_hash,
                source=section_name,
            )
            raise CandidateActivitySummaryLLMError(
                f"Prompt input rejected by instruction policy: {section_name}"
            )
    prompt = CANDIDATE_ACTIVITY_SUMMARY.render(**sections)
    raw = await _call_claude_text(
        prompt=prompt,
        system_prompt=CANDIDATE_ACTIVITY_SUMMARY.system_prompt or "",
        model=model,
        max_tokens=MAX_TOKENS,
    )
    return _sanitize_llm_output(
        raw,
        candidate_id=candidate_id,
        visibility_scope_hash=visibility_scope_hash,
    )


# ── Feature gate and quota ───────────────────────────────────────────────────


async def _ensure_feature_enabled(db: AsyncSession) -> None:
    feature = AIFeatureKey.candidate_summary
    if not await get_master_enabled(db):
        raise AIQuotaExceeded(feature, "Funkcje AI są wyłączone globalnie")
    config = await get_feature_config(db, feature)
    if config is not None and not config.enabled:
        raise AIQuotaExceeded(feature, "Funkcja AI wyłączona w ustawieniach")


# ── Scope-aware cache and lease/CAS orchestration ────────────────────────────


def _lease_seconds() -> int:
    try:
        configured = int(
            os.environ.get(
                "CANDIDATE_SUMMARY_LEASE_SECONDS", str(_DEFAULT_LEASE_SECONDS)
            )
        )
    except ValueError:
        configured = _DEFAULT_LEASE_SECONDS
    return min(max(configured, 30), 900)


def _source_manifest_is_safe(manifest: Any) -> bool:
    """Allow only aggregate counters; raw source data never belongs here."""
    if not isinstance(manifest, dict):
        return False
    if set(manifest) != {"content_policy_version", "sources"}:
        return False
    if manifest.get("content_policy_version") != CONTENT_POLICY_VERSION:
        return False
    sources = manifest.get("sources")
    if not isinstance(sources, list) or len(sources) != len(_SOURCE_NAMES):
        return False

    seen: set[str] = set()
    expected_keys = {"name", *_MANIFEST_COUNTER_KEYS}
    for source in sources:
        if not isinstance(source, dict) or set(source) != expected_keys:
            return False
        name = source.get("name")
        if name not in _SOURCE_NAMES or name in seen:
            return False
        seen.add(name)
        for key in _MANIFEST_COUNTER_KEYS:
            value = source.get(key)
            # ``bool`` is an ``int`` subclass; reject it to keep the wire shape
            # unambiguous and prevent arbitrary truthy metadata.
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                return False
    return seen == set(_SOURCE_NAMES)


def _cached_row_is_safe(row: CandidateActivitySummary) -> bool:
    """Defense in depth for data inserted outside the application writer."""
    if (
        not isinstance(row.summary, str)
        or row.generated_at is None
        or not isinstance(row.model, str)
        or not row.model
        or not isinstance(row.source_version, str)
        or _SHA256_RE.fullmatch(row.source_version) is None
        or row.input_hash != row.source_version
        or row.content_policy_version != CONTENT_POLICY_VERSION
        or not _source_manifest_is_safe(row.source_manifest)
    ):
        return False
    try:
        normalized = _sanitize_llm_output(
            row.summary,
            candidate_id=row.candidate_id,
            visibility_scope_hash=row.visibility_scope_hash,
            source="cache",
        )
    except CandidateActivitySummaryLLMError:
        return False
    # The publisher stores canonical plaintext.  A manually inserted row that
    # needs HTML/Unicode cleanup is not trusted for direct serving.
    return normalized == row.summary


async def get_cached(
    candidate_id: int,
    db: AsyncSession,
    *,
    visibility_scope_hash: str,
    content_policy_version: str = CONTENT_POLICY_VERSION,
) -> Optional[CandidateActivitySummary]:
    """Fetch only a complete row for the exact safe scope/policy.

    Legacy rows carry ``legacy-unscoped`` and therefore never match.
    """
    row = await db.scalar(
        select(CandidateActivitySummary).where(
            CandidateActivitySummary.candidate_id == candidate_id,
            CandidateActivitySummary.visibility_scope_hash == visibility_scope_hash,
            CandidateActivitySummary.content_policy_version == content_policy_version,
            CandidateActivitySummary.summary.is_not(None),
        )
    )
    if row is not None and not _cached_row_is_safe(row):
        _log_policy_event(
            reason="cache_policy_rejected",
            candidate_id=candidate_id,
            visibility_scope_hash=visibility_scope_hash,
            source="cache",
        )
        return None
    return row


async def _acquire_generation_lease(
    candidate_id: int,
    db: AsyncSession,
    context: SummaryContext,
) -> Optional[str]:
    token = str(uuid.uuid4())
    # Use the database clock for both acquisition and expiry comparisons.
    # Multiple app instances may have small wall-clock skew; that must not let
    # two workers believe they own the same generation lease.
    expires_at = func.now() + timedelta(seconds=_lease_seconds())
    insert_stmt = pg_insert(CandidateActivitySummary).values(
        candidate_id=candidate_id,
        summary=None,
        model=None,
        input_hash=context.source_version,
        source_version=context.source_version,
        visibility_scope_hash=context.visibility_scope_hash,
        content_policy_version=CONTENT_POLICY_VERSION,
        source_manifest={},
        generated_by=None,
        generated_at=None,
        generation_lease_token=token,
        generation_lease_expires_at=expires_at,
    )
    stmt = insert_stmt.on_conflict_do_update(
        constraint="uq_candidate_activity_summary_scope_policy",
        set_={
            "generation_lease_token": token,
            "generation_lease_expires_at": expires_at,
            "updated_at": func.now(),
        },
        where=or_(
            CandidateActivitySummary.generation_lease_token.is_(None),
            CandidateActivitySummary.generation_lease_expires_at.is_(None),
            CandidateActivitySummary.generation_lease_expires_at <= func.now(),
        ),
    ).returning(CandidateActivitySummary.id)
    acquired_id = await db.scalar(stmt)
    # The lease must be visible to competitors, and the transaction/connection
    # must be released, before any external provider call begins.
    await db.commit()
    return token if acquired_id is not None else None


async def _release_generation_lease(
    candidate_id: int,
    db: AsyncSession,
    context: SummaryContext,
    token: str,
) -> None:
    try:
        await db.execute(
            update(CandidateActivitySummary)
            .where(
                CandidateActivitySummary.candidate_id == candidate_id,
                CandidateActivitySummary.visibility_scope_hash
                == context.visibility_scope_hash,
                CandidateActivitySummary.content_policy_version
                == CONTENT_POLICY_VERSION,
                CandidateActivitySummary.generation_lease_token == token,
            )
            .values(
                generation_lease_token=None,
                generation_lease_expires_at=None,
            )
        )
        await db.commit()
    except Exception:  # noqa: BLE001 - cleanup must not mask the original failure
        await db.rollback()
        logger.exception(
            "candidate_activity_summary: failed to release generation lease"
        )


async def _publish_generation(
    candidate_id: int,
    db: AsyncSession,
    context: SummaryContext,
    *,
    token: str,
    summary: str,
    user_id: Optional[int],
) -> Optional[CandidateActivitySummary]:
    generated_at = datetime.now(timezone.utc)
    # Defense in depth: callers cannot bypass output DLP by invoking the
    # persistence seam directly.
    summary = _sanitize_llm_output(
        summary,
        candidate_id=candidate_id,
        visibility_scope_hash=context.visibility_scope_hash,
        source="publish",
    )
    if _SHA256_RE.fullmatch(
        context.source_version
    ) is None or not _source_manifest_is_safe(context.source_manifest):
        _log_policy_event(
            reason="source_metadata_rejected",
            candidate_id=candidate_id,
            visibility_scope_hash=context.visibility_scope_hash,
            source="publish",
        )
        raise CandidateActivitySummaryLLMError(
            "Source metadata rejected by candidate-summary policy"
        )
    published_id = await db.scalar(
        update(CandidateActivitySummary)
        .where(
            CandidateActivitySummary.candidate_id == candidate_id,
            CandidateActivitySummary.visibility_scope_hash
            == context.visibility_scope_hash,
            CandidateActivitySummary.content_policy_version == CONTENT_POLICY_VERSION,
            CandidateActivitySummary.generation_lease_token == token,
            CandidateActivitySummary.generation_lease_expires_at.is_not(None),
            CandidateActivitySummary.generation_lease_expires_at > func.now(),
        )
        .values(
            summary=summary,
            model=DEFAULT_MODEL,
            input_hash=context.source_version,
            source_version=context.source_version,
            source_manifest=context.source_manifest,
            generated_by=user_id,
            generated_at=generated_at,
            generation_lease_token=None,
            generation_lease_expires_at=None,
        )
        .returning(CandidateActivitySummary.id)
    )
    await db.commit()
    if published_id is None:
        return None
    return await get_cached(
        candidate_id,
        db,
        visibility_scope_hash=context.visibility_scope_hash,
    )


def _state(
    row: Optional[CandidateActivitySummary], context: SummaryContext
) -> CandidateActivitySummaryState:
    return CandidateActivitySummaryState(
        row=row,
        current_source_version=context.source_version,
        visibility_scope_hash=context.visibility_scope_hash,
        current_source_manifest=context.source_manifest,
    )


async def _refresh_generation_principals(
    db: AsyncSession,
    *,
    candidate_id: int,
    user_id: int,
) -> tuple[Candidate, User]:
    """Reload candidate and caller state after every external wait boundary."""

    candidate = await db.scalar(
        select(Candidate)
        .where(Candidate.id == candidate_id)
        .execution_options(populate_existing=True)
    )
    fresh_user = await db.scalar(
        select(User).where(User.id == user_id).execution_options(populate_existing=True)
    )
    if candidate is None:
        raise CandidateActivitySummaryNotFound("Kandydat nie istnieje")
    if fresh_user is None or not fresh_user.is_active:
        raise CandidateActivitySummaryBusy(
            "Uprawnienia użytkownika zmieniły się podczas generowania"
        )
    return candidate, fresh_user


async def get_summary_state(
    candidate_id: int,
    db: AsyncSession,
    *,
    user: User,
) -> CandidateActivitySummaryState:
    """Read current safe cache state; never generates or serves while disabled."""
    await _ensure_feature_enabled(db)
    candidate = await db.scalar(select(Candidate).where(Candidate.id == candidate_id))
    if candidate is None:
        raise CandidateActivitySummaryNotFound("Kandydat nie istnieje")
    context = await build_context(db, candidate, user)
    row = await get_cached(
        candidate_id,
        db,
        visibility_scope_hash=context.visibility_scope_hash,
    )
    return _state(row, context)


async def get_or_generate(
    candidate_id: int,
    db: AsyncSession,
    *,
    user: User,
    user_id: Optional[int] = None,
    force: bool = False,
) -> tuple[CandidateActivitySummaryState, bool]:
    """Return scoped state and whether this request published new prose."""
    await _ensure_feature_enabled(db)
    candidate = await db.scalar(select(Candidate).where(Candidate.id == candidate_id))
    if candidate is None:
        raise CandidateActivitySummaryNotFound("Kandydat nie istnieje")

    context = await build_context(db, candidate, user)
    row = await get_cached(
        candidate_id,
        db,
        visibility_scope_hash=context.visibility_scope_hash,
    )
    # ``force`` is the explicit refresh contract: callers may regenerate even
    # when the deterministic source version has not changed (for example after
    # an operator judges the prose stale). Normal GETs still use the cache.
    if row is not None and not force and row.source_version == context.source_version:
        return _state(row, context), False

    # The first context is useful for a cache hit, but it cannot be trusted for
    # generation until a committed lease fences quarantine/cache invalidation.
    # A mismatch decision can land between that read and lease acquisition.
    # Re-read the candidate and all scoped sources after acquiring the lease;
    # if anything changed, release and reacquire for the new source snapshot.
    token: str | None = None
    for attempt in range(2):
        token = await _acquire_generation_lease(candidate_id, db, context)
        if token is None:
            _log_policy_event(
                reason="lease_busy",
                candidate_id=candidate_id,
                visibility_scope_hash=context.visibility_scope_hash,
                source="generation",
            )
            raise CandidateActivitySummaryBusy("Podsumowanie jest już generowane")

        fresh_candidate, fresh_user = await _refresh_generation_principals(
            db,
            candidate_id=candidate_id,
            user_id=user.id,
        )
        fresh_context = await build_context(db, fresh_candidate, fresh_user)
        if (
            fresh_context.visibility_scope_hash == context.visibility_scope_hash
            and fresh_context.source_version == context.source_version
        ):
            context = fresh_context
            break

        await _release_generation_lease(candidate_id, db, context, token)
        _log_policy_event(
            reason="context_changed_after_lease",
            candidate_id=candidate_id,
            visibility_scope_hash=fresh_context.visibility_scope_hash,
            source="generation",
        )
        context = fresh_context
        token = None
        if attempt == 1:
            raise CandidateActivitySummaryBusy(
                "Źródła zmieniły się podczas generowania; spróbuj ponownie"
            )

    if token is None:  # defensive; every loop exit above assigns a live token
        raise CandidateActivitySummaryBusy("Nie udało się uzyskać lease")

    try:
        # Jedna bramka kwot w całym repo (`ai_quota.ai_feature`), nie druga kopia
        # tej samej logiki. Poprzednie `_gate_and_count` reimplementowało główny
        # przełącznik, limit i upsert `ON CONFLICT`, ale NIE ustawiało kontekstu
        # wywołania AI — więc poprawnie obciążona karta „Podsumowanie aktywności"
        # logowała się na granicy providera jako „UNGATED", a pod
        # `AI_QUOTA_STRICT` rzuciłaby wyjątkiem, mimo że kwota była naliczona.
        #
        # Commit the usage record before leaving for the provider.  No database
        # transaction remains open during the network call.
        async with ai_feature(db, AIFeatureKey.candidate_summary, user_id=user_id):
            await db.commit()
            summary = await generate_summary(
                context.sections,
                candidate_id=candidate_id,
                visibility_scope_hash=context.visibility_scope_hash,
            )
        final_candidate, final_user = await _refresh_generation_principals(
            db,
            candidate_id=candidate_id,
            user_id=user.id,
        )
        final_context = await build_context(db, final_candidate, final_user)
        if (
            final_context.visibility_scope_hash != context.visibility_scope_hash
            or final_context.source_version != context.source_version
        ):
            _log_policy_event(
                reason="context_changed_after_provider",
                candidate_id=candidate_id,
                visibility_scope_hash=final_context.visibility_scope_hash,
                source="generation",
            )
            raise CandidateActivitySummaryBusy(
                "Źródła lub uprawnienia zmieniły się podczas generowania"
            )
        row = await _publish_generation(
            candidate_id,
            db,
            context,
            token=token,
            summary=summary,
            user_id=user_id,
        )
        if row is None:
            # The lease expired or was superseded.  CAS intentionally rejects
            # our late result.  Return a winner only when it published the exact
            # same source version; otherwise make the race explicit.
            winner = await get_cached(
                candidate_id,
                db,
                visibility_scope_hash=context.visibility_scope_hash,
            )
            if winner is not None and winner.source_version == context.source_version:
                return _state(winner, context), False
            _log_policy_event(
                reason="lease_expired_cas",
                candidate_id=candidate_id,
                visibility_scope_hash=context.visibility_scope_hash,
                source="generation",
            )
            raise CandidateActivitySummaryBusy(
                "Lease wygasł przed publikacją podsumowania"
            )
        return _state(row, context), True
    except Exception:
        await db.rollback()
        await _release_generation_lease(candidate_id, db, context, token)
        raise
