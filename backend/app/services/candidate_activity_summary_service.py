"""AI candidate-activity-summary service — the "Podsumowanie aktywności" note.

Pipeline for one candidate:
  1. Gather the whole activity history from the DB (pipeline stages per job,
     interview feedback, screenings, notes, contracts, rate history, call
     summaries) plus the profile facts (rates, availability, preferences).
  2. Render it into deterministic plain-text sections and fingerprint them
     (``input_hash``). If the cached ``CandidateActivitySummary`` row matches
     that fingerprint, serve it — no LLM call.
  3. On a miss (or ``force``), gate the paid LLM call behind the reserved
     ``AIFeatureKey.candidate_summary`` toggle/quota and ask Claude to write
     the short Polish note.

The "Aktualizuj notatkę" button calls step 1-3 again: it only pays for a new
generation when the underlying history actually changed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_feature import AIFeatureKey, AIUsageLog
from app.models.call import Call
from app.models.candidate import Candidate
from app.models.candidate_activity_summary import CandidateActivitySummary
from app.models.client import Client
from app.models.contract import Contract
from app.models.interview_feedback import InterviewFeedback
from app.models.job import Job
from app.models.note import Note
from app.models.rate_history import RateHistory
from app.models.recruitment_pipeline import CandidateStage
from app.models.screening_note import ScreeningNote
from app.services.ai_quota import (
    AIQuotaExceeded,
    get_feature_config,
    get_master_enabled,
    get_total_usage_for_period,
)
from app.services.llm_prompts import CANDIDATE_ACTIVITY_SUMMARY

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("CANDIDATE_SUMMARY_MODEL", "claude-sonnet-5")
MAX_TOKENS = 1200

# Input caps so a hyperactive candidate can't blow up the prompt.
_MAX_NOTES = 30
_MAX_NOTE_CHARS = 350
_MAX_STAGE_ROWS = 80
_MAX_JOBS_RENDERED = 15
_MAX_FEEDBACK = 15
_MAX_SCREENINGS = 3
_MAX_CONTRACTS = 12
_MAX_RATE_ROWS = 20
_MAX_CALLS = 6
_MAX_CALL_CHARS = 250
# Output cap so a runaway model can't bloat the row / the card.
_MAX_SUMMARY_CHARS = 4000

_EMPTY = "(brak danych)"

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
    """The LLM call failed or returned unusable output."""


# ── Small render helpers ─────────────────────────────────────────────────────


def _truncate(text: Optional[str], limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + " […]"


def _enum_val(value: Any) -> str:
    """`.value` for enums, `str()` otherwise, '' for None."""
    if value is None:
        return ""
    return str(getattr(value, "value", value))


def _fmt_date(value: Optional[datetime | date]) -> str:
    if value is None:
        return "?"
    return value.strftime("%Y-%m-%d")


def _fmt_rate(
    value: Optional[Decimal | int | float],
    currency: Optional[str],
    unit: Any = None,
) -> str:
    if value is None:
        return ""
    num = f"{Decimal(str(value)).normalize():f}"
    unit_sfx = {"hourly": "/h", "daily": "/dzień", "monthly": "/mies."}.get(
        _enum_val(unit), ""
    )
    return f"{num} {(currency or 'PLN').upper()}{unit_sfx}"


def _skills_to_text(raw: Any, limit: int = 25) -> str:
    if not raw:
        return ""
    if isinstance(raw, list):
        names = []
        for s in raw:
            name = (
                (s.get("name") or s.get("skill") or "")
                if isinstance(s, dict)
                else str(s)
            ).strip()
            if name:
                names.append(name)
        return ", ".join(names[:limit])
    if isinstance(raw, str):
        return _truncate(raw, 400)
    return ""


# ── Section builders (deterministic text → both prompt and hash input) ──────


def _profile_section(candidate: Candidate) -> str:
    lines: list[str] = []
    status = _enum_val(candidate.status)
    if status:
        lines.append(f"Status w ATS: {status}")
    if candidate.competence_category:
        lines.append(f"Kategoria kompetencji: {candidate.competence_category}")
    skills = _skills_to_text(candidate.skills)
    if skills:
        lines.append(f"Umiejętności: {skills}")
    expected = _fmt_rate(
        candidate.expected_rate_hourly, candidate.expected_rate_currency, "hourly"
    )
    if expected:
        lines.append(f"Oczekiwana stawka (profil): {expected}")
    if candidate.salary_expectation:
        lines.append(
            "Oczekiwania finansowe (salary): "
            f"{candidate.salary_expectation} {(candidate.salary_currency or 'PLN').upper()}"
        )
    availability = _enum_val(candidate.availability_status)
    if availability and availability != "unknown":
        lines.append(f"Status dostępności: {availability}")
    if candidate.availability_date:
        lines.append(f"Dostępny od: {_fmt_date(candidate.availability_date)}")
    if candidate.notice_period:
        unit = _enum_val(candidate.notice_period_unit) or "dni"
        lines.append(f"Okres wypowiedzenia: {candidate.notice_period} {unit}")
    if isinstance(candidate.preferences, dict) and candidate.preferences:
        lines.append(
            "Preferencje (surowe): "
            + _truncate(
                json.dumps(candidate.preferences, ensure_ascii=False, sort_keys=True),
                600,
            )
        )
    if candidate.engagement_notes:
        lines.append(
            f"Notatki o zaangażowaniu: {_truncate(candidate.engagement_notes, 500)}"
        )
    return "\n".join(lines) or _EMPTY


async def _submissions_section(db: AsyncSession, candidate_id: int) -> str:
    rows = (
        await db.execute(
            select(CandidateStage, Job.title, Client.name)
            .join(Job, Job.id == CandidateStage.job_id)
            .outerjoin(Client, Client.id == Job.client_id)
            .where(CandidateStage.candidate_id == candidate_id)
            .order_by(CandidateStage.moved_at.desc())
            .limit(_MAX_STAGE_ROWS)
        )
    ).all()
    if not rows:
        return _EMPTY

    # Group stage moves per job — newest job first (rows already sorted desc).
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
                "expected_rate": None,
                "client_rate": None,
                "offer_response": None,
            },
        )
        entry["stages"].append(_enum_val(stage.stage))
        if stage.rejection_note:
            entry["rejection_notes"].append(_truncate(stage.rejection_note, 250))
        if entry["expected_rate"] is None and stage.expected_rate_value is not None:
            entry["expected_rate"] = _fmt_rate(
                stage.expected_rate_value,
                stage.expected_rate_currency,
                stage.expected_rate_unit,
            )
        if entry["client_rate"] is None and stage.client_rate_value is not None:
            entry["client_rate"] = _fmt_rate(
                stage.client_rate_value,
                stage.client_rate_currency,
                stage.client_rate_unit,
            )
        if entry["offer_response"] is None and stage.candidate_offer_response:
            entry["offer_response"] = _enum_val(stage.candidate_offer_response)

    lines: list[str] = []
    for entry in list(jobs.values())[:_MAX_JOBS_RENDERED]:
        latest_stage = entry["stages"][0]
        label = _STAGE_LABELS.get(latest_stage, latest_stage)
        client = f" — klient: {entry['client']}" if entry["client"] else ""
        lines.append(
            f"- {entry['title']}{client}: ostatni etap „{label}” "
            f"({_fmt_date(entry['last_moved'])})"
        )
        reached = {s for s in entry["stages"]}
        if "client_interview" in reached:
            lines.append("  Doszło do rozmowy u klienta.")
        elif "interview" in reached:
            lines.append("  Doszło do interview wewnętrznego.")
        if entry["expected_rate"]:
            lines.append(f"  Stawka kandydata w procesie: {entry['expected_rate']}")
        if entry["client_rate"]:
            lines.append(f"  Stawka do klienta: {entry['client_rate']}")
        if entry["offer_response"]:
            lines.append(f"  Odpowiedź na ofertę: {entry['offer_response']}")
        for note in entry["rejection_notes"][:2]:
            lines.append(f"  Powód odrzucenia: {note}")
    return "\n".join(lines)


async def _feedback_section(db: AsyncSession, candidate_id: int) -> str:
    rows = (
        await db.execute(
            select(InterviewFeedback, Job.title)
            .outerjoin(Job, Job.id == InterviewFeedback.job_id)
            .where(InterviewFeedback.candidate_id == candidate_id)
            .order_by(InterviewFeedback.id.desc())
            .limit(_MAX_FEEDBACK)
        )
    ).all()
    if not rows:
        return _EMPTY
    lines: list[str] = []
    for fb, job_title in rows:
        bits: list[str] = []
        source = _enum_val(fb.feedback_source)
        side = "od klienta" if source == "client_side" else "od kandydata"
        decision = _DECISION_LABELS.get(_enum_val(fb.decision), "")
        if decision:
            bits.append(f"decyzja: {decision}")
        if fb.overall_fit:
            bits.append(f"dopasowanie {fb.overall_fit}/5")
        if fb.overall_impression:
            bits.append(f"wrażenie {fb.overall_impression}/5")
        interest = _enum_val(fb.interest_level)
        if interest:
            bits.append(f"zainteresowanie kandydata: {interest}")
        header = f"- {job_title or 'Rekrutacja'} ({side})"
        if bits:
            header += ": " + ", ".join(bits)
        lines.append(header)
        if fb.feedback_summary:
            lines.append(f"  Feedback: {_truncate(fb.feedback_summary, 400)}")
        if fb.concerns:
            lines.append(f"  Obawy: {_truncate(fb.concerns, 250)}")
    return "\n".join(lines)


async def _screening_section(db: AsyncSession, candidate_id: int) -> str:
    rows = (
        (
            await db.execute(
                select(ScreeningNote)
                .where(ScreeningNote.candidate_id == candidate_id)
                .order_by(ScreeningNote.created_at.desc())
                .limit(_MAX_SCREENINGS)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return _EMPTY
    lines: list[str] = []
    for sn in rows:
        bits: list[str] = []
        if sn.salary_expectation:
            neg = " (do negocjacji)" if sn.salary_negotiable else ""
            bits.append(
                f"oczekiwania: {sn.salary_expectation} "
                f"{(sn.salary_currency or 'PLN').upper()}{neg}"
            )
        motivation = _enum_val(sn.motivation_primary)
        if motivation:
            bits.append(f"motywacja: {motivation}")
        if sn.readiness_to_change:
            bits.append(f"gotowość do zmiany {sn.readiness_to_change}/5")
        lines.append(f"- Screening {_fmt_date(sn.created_at)}: " + ", ".join(bits))
        if sn.red_flags:
            lines.append(f"  Red flags: {_truncate(sn.red_flags, 250)}")
        if sn.personality_notes:
            lines.append(f"  Notatki: {_truncate(sn.personality_notes, 300)}")
    return "\n".join(lines)


async def _notes_section(db: AsyncSession, candidate_id: int) -> str:
    rows = (
        (
            await db.execute(
                select(Note)
                .where(
                    Note.candidate_id == candidate_id,
                    Note.source_deleted_at.is_(None),
                )
                .order_by(Note.created_at.desc())
                .limit(_MAX_NOTES)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return _EMPTY
    lines = [
        f"- [{_fmt_date(n.source_created_at or n.created_at)}] "
        f"{_truncate(n.content, _MAX_NOTE_CHARS)}"
        for n in rows
        if (n.content or "").strip()
    ]
    return "\n".join(lines) or _EMPTY


async def _contracts_section(db: AsyncSession, candidate_id: int) -> str:
    rows = (
        await db.execute(
            select(Contract, Client.name)
            .outerjoin(Client, Client.id == Contract.client_id)
            .where(Contract.candidate_id == candidate_id)
            .order_by(Contract.start_date.desc().nulls_last())
            .limit(_MAX_CONTRACTS)
        )
    ).all()
    if not rows:
        return _EMPTY
    lines: list[str] = []
    for contract, client_name in rows:
        period = f"{_fmt_date(contract.start_date)} → " + (
            _fmt_date(contract.end_date) if contract.end_date else "czas nieokreślony"
        )
        bits = [f"- Umowa z klientem {client_name or '?'} ({period})"]
        rate = _fmt_rate(contract.rate_candidate, contract.currency, contract.rate_unit)
        if rate:
            bits.append(f"stawka kandydata: {rate}")
        work_mode = _enum_val(contract.work_mode)
        if work_mode:
            bits.append(f"tryb pracy: {work_mode}")
        status = _enum_val(contract.status)
        if status:
            bits.append(f"status: {status}")
        if contract.project_name:
            bits.append(f"projekt: {contract.project_name}")
        lines.append(", ".join(bits))
        termination = _enum_val(contract.termination_reason)
        if termination:
            lines.append(f"  Powód zakończenia: {termination}")
    return "\n".join(lines)


async def _rates_section(db: AsyncSession, candidate_id: int) -> str:
    rows = (
        await db.execute(
            select(RateHistory, Client.name)
            .outerjoin(Client, Client.id == RateHistory.client_id)
            .where(RateHistory.candidate_id == candidate_id)
            .order_by(RateHistory.start_date.desc())
            .limit(_MAX_RATE_ROWS)
        )
    ).all()
    if not rows:
        return _EMPTY
    lines: list[str] = []
    for rh, client_name in rows:
        target = f" u klienta {client_name}" if client_name else ""
        note = f" — {_truncate(rh.notes, 150)}" if rh.notes else ""
        lines.append(
            f"- {_fmt_rate(rh.rate, rh.currency)} ({_enum_val(rh.contract_type)}) "
            f"od {_fmt_date(rh.start_date)}{target}{note}"
        )
    return "\n".join(lines)


async def _calls_section(db: AsyncSession, candidate_id: int) -> str:
    rows = (
        (
            await db.execute(
                select(Call)
                .where(Call.candidate_id == candidate_id, Call.summary.isnot(None))
                .order_by(Call.started_at.desc().nulls_last())
                .limit(_MAX_CALLS)
            )
        )
        .scalars()
        .all()
    )
    lines = [
        f"- [{_fmt_date(c.started_at)}] {_truncate(c.summary, _MAX_CALL_CHARS)}"
        for c in rows
        if (c.summary or "").strip()
    ]
    return "\n".join(lines) or _EMPTY


async def build_context(db: AsyncSession, candidate: Candidate) -> dict[str, str]:
    """All prompt sections as deterministic plain text (also the hash input)."""
    return {
        "profile": _profile_section(candidate),
        "submissions": await _submissions_section(db, candidate.id),
        "feedback": await _feedback_section(db, candidate.id),
        "screening": await _screening_section(db, candidate.id),
        "notes": await _notes_section(db, candidate.id),
        "contracts": await _contracts_section(db, candidate.id),
        "rates": await _rates_section(db, candidate.id),
        "calls": await _calls_section(db, candidate.id),
    }


def _input_hash(sections: dict[str, str]) -> str:
    """Fingerprint of the gathered history + prompt version + model.

    Includes the prompt version so a prompt bump invalidates every cached row.
    """
    payload = json.dumps(
        {
            "prompt_version": CANDIDATE_ACTIVITY_SUMMARY.version,
            "model": DEFAULT_MODEL,
            "sections": sections,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ── LLM plumbing ─────────────────────────────────────────────────────────────


async def _call_claude_text(
    *, prompt: str, system_prompt: str, model: str, max_tokens: int
) -> str:
    """Call Claude and return the plain-text answer."""
    from app.services.claude_client import call_claude  # local: avoid load-time cost

    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if not api_key:
        raise CandidateActivitySummaryLLMError("ANTHROPIC_API_KEY not configured")

    started = time.time()
    try:
        message = await run_in_threadpool(
            call_claude,
            model=model,
            max_tokens=max_tokens,
            # Sonnet 5 does adaptive thinking by default; those tokens count
            # toward max_tokens and would truncate the note. Disable it.
            thinking={"type": "disabled"},
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            api_key=api_key,
        )
    except Exception as exc:  # noqa: BLE001 - surface as a clean domain error
        raise CandidateActivitySummaryLLMError(f"LLM request failed: {exc}") from exc

    latency_ms = int((time.time() - started) * 1000)
    # Claude 5 can lead with a non-text (thinking) block → collect every text
    # block rather than trusting content[0].text.
    raw = "".join(
        getattr(b, "text", "") or "" for b in message.content if hasattr(b, "text")
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


def _sanitize_llm_output(raw: str) -> str:
    text = (raw or "").strip()
    # Strip accidental code fences (with or without a language tag).
    if text.startswith("```"):
        text = re.sub(r"^```[^\n]*\n?", "", text)
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        text = text.strip()
    if not text:
        raise CandidateActivitySummaryLLMError("LLM output empty")
    return text[:_MAX_SUMMARY_CHARS].rstrip()


async def generate_summary(
    sections: dict[str, str], *, model: str = DEFAULT_MODEL
) -> str:
    """Ask Claude to write the note. Returns sanitized plain text."""
    prompt = CANDIDATE_ACTIVITY_SUMMARY.render(**sections)
    raw = await _call_claude_text(
        prompt=prompt,
        system_prompt=CANDIDATE_ACTIVITY_SUMMARY.system_prompt or "",
        model=model,
        max_tokens=MAX_TOKENS,
    )
    return _sanitize_llm_output(raw)


# ── Quota gate ───────────────────────────────────────────────────────────────


async def _gate_and_count(db: AsyncSession, user_id: Optional[int]) -> None:
    """Respect the AI kill-switch + `candidate_summary` toggle/limit, then
    record 1 use. Raises ``AIQuotaExceeded`` if blocked."""
    feature = AIFeatureKey.candidate_summary
    if not await get_master_enabled(db):
        raise AIQuotaExceeded(feature, "Funkcje AI są wyłączone globalnie")

    config = await get_feature_config(db, feature)
    if config is not None and not config.enabled:
        raise AIQuotaExceeded(feature, "Funkcja AI wyłączona w ustawieniach")

    limit = config.monthly_limit if config else 0
    period = datetime.now(timezone.utc).date().replace(day=1)
    used = await get_total_usage_for_period(db, feature, period)
    if limit > 0 and used >= limit:
        raise AIQuotaExceeded(
            feature, "Miesięczny limit wyczerpany", used=used, limit=limit
        )

    now = datetime.now(timezone.utc)
    await db.execute(
        pg_insert(AIUsageLog)
        .values(
            feature=feature,
            user_id=user_id,
            period_start=period,
            count=1,
            last_call_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_ai_usage_feature_user_period",
            set_={"count": AIUsageLog.count + 1, "last_call_at": now},
        )
    )


# ── Orchestration ────────────────────────────────────────────────────────────


async def get_or_generate(
    candidate_id: int,
    db: AsyncSession,
    *,
    user_id: Optional[int] = None,
    force: bool = False,
) -> tuple[CandidateActivitySummary, bool]:
    """Return ``(row, generated)`` — the cached or freshly generated note.

    ``generated`` is False when the history hash matched and the cached note
    was served for free. Raises ``CandidateActivitySummaryNotFound`` (unknown
    candidate), ``AIQuotaExceeded`` (AI disabled / over limit) or
    ``CandidateActivitySummaryLLMError`` (generation failed).
    """
    candidate = await db.scalar(select(Candidate).where(Candidate.id == candidate_id))
    if candidate is None:
        raise CandidateActivitySummaryNotFound("Kandydat nie istnieje")

    sections = await build_context(db, candidate)
    input_hash = _input_hash(sections)

    row = await get_cached(candidate_id, db)
    if row is not None and not force and row.input_hash == input_hash:
        return row, False

    # Serialize concurrent refreshes of the same candidate BEFORE the paid
    # call: without this, two simultaneous clicks both see a stale/missing row
    # and both pay Anthropic (the loser's work is discarded on the unique
    # constraint). The xact-scoped advisory lock is released by commit/rollback.
    await db.execute(
        sa_text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"candidate_activity_summary:{candidate_id}"},
    )
    # Re-check after acquiring the lock — the winner may have just written a
    # row for exactly this history; serve it for free instead of regenerating.
    row = await get_cached(candidate_id, db)
    if row is not None and not force and row.input_hash == input_hash:
        return row, False

    # Cache miss / forced refresh / stale inputs → paid LLM call (gated).
    await _gate_and_count(db, user_id)
    summary = await generate_summary(sections)

    now = datetime.now(timezone.utc)
    if row is None:
        row = CandidateActivitySummary(candidate_id=candidate_id)
        db.add(row)
    row.summary = summary
    row.model = DEFAULT_MODEL
    row.input_hash = input_hash
    row.generated_by = user_id
    row.generated_at = now

    try:
        await db.commit()
    except IntegrityError:
        # Concurrent first refresh of the same candidate inserted the row first
        # (unique constraint). Roll back and serve the winner's row.
        await db.rollback()
        existing = await get_cached(candidate_id, db)
        if existing is not None:
            return existing, False
        raise
    await db.refresh(row)
    return row, True


async def get_cached(
    candidate_id: int, db: AsyncSession
) -> Optional[CandidateActivitySummary]:
    """Fetch the stored note without generating (used by the GET endpoint)."""
    return await db.scalar(
        select(CandidateActivitySummary).where(
            CandidateActivitySummary.candidate_id == candidate_id
        )
    )
