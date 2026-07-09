"""AI match-justification service — the prose behind the "Dopasowanie" tab.

Pipeline for one (candidate, job) pair:
  1. Compute the deterministic hybrid score (``scoring_service`` via the shared
     ``match_score_cache``) — the same 0-100 number the kanban ring shows.
  2. Fingerprint the inputs (CV + requirements + champion + score). If a cached
     ``CandidateMatchJustification`` row matches that fingerprint, serve it — no
     LLM call.
  3. On a miss (or ``force``), gate the paid LLM call behind the reserved
     ``AIFeatureKey.scoring`` toggle/quota, ask Claude to *explain* the score
     (never to change it), and upsert the prose.

The LLM only produces prose (summary / pros / watch-outs). The number always
comes from the deterministic engine, so the ring stays consistent with the rest
of the app and the model can't inflate a match.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_feature import AIFeatureKey, AIUsageLog
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.match_justification import CandidateMatchJustification
from app.services.ai_quota import (
    AIQuotaExceeded,
    get_feature_config,
    get_master_enabled,
    get_total_usage_for_period,
)
from app.services.llm_prompts import MATCH_JUSTIFICATION
from app.services.match_score_cache import get_cached_or_compute
from app.services.scoring_service import ScoreBreakdown

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("MATCH_SCORING_MODEL", "claude-sonnet-5")
MAX_CV_CHARS = int(os.environ.get("MATCH_SCORING_MAX_CV_CHARS", "6000"))
MAX_REQ_CHARS = 3000
MAX_CHAMPION_CHARS = 2000
MAX_TOKENS = 1500

# Output caps so a runaway model can't bloat the row / the tab.
_MAX_SUMMARY_CHARS = 1200
_MAX_BULLET_CHARS = 320
_MAX_BULLETS = 8


class MatchJustificationNotFound(Exception):
    """Candidate or job does not exist."""


class MatchJustificationLLMError(Exception):
    """The LLM call failed or returned unusable output."""


# ── LLM plumbing (mirrors champion_draft_service._call_claude_json) ──────────


def _strip_code_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


async def _call_claude_json(
    *, prompt: str, system_prompt: str, model: str, max_tokens: int
) -> dict[str, Any]:
    """Call Claude and parse JSON. Raises MatchJustificationLLMError on failure."""
    import anthropic  # local import: avoid import cost at module load

    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if not api_key:
        raise MatchJustificationLLMError("ANTHROPIC_API_KEY not configured")

    client = anthropic.Anthropic(api_key=api_key)
    started = time.time()
    try:
        message = await run_in_threadpool(
            client.messages.create,
            model=model,
            max_tokens=max_tokens,
            # Sonnet 5 does adaptive thinking by default; those tokens count
            # toward max_tokens and would truncate this JSON. Disable it.
            thinking={"type": "disabled"},
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:  # noqa: BLE001 - surface as a clean domain error
        raise MatchJustificationLLMError(f"LLM request failed: {exc}") from exc

    latency_ms = int((time.time() - started) * 1000)
    # Claude 5 can lead with a non-text (thinking) block → collect every text
    # block rather than trusting content[0].text.
    raw = _strip_code_fences(
        "".join(
            getattr(b, "text", "") or "" for b in message.content if hasattr(b, "text")
        )
    )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning(
            "match_justification: invalid JSON (model=%s latency=%dms)",
            model,
            latency_ms,
        )
        raise MatchJustificationLLMError(f"Invalid JSON from LLM: {exc}") from exc

    usage = getattr(message, "usage", None)
    logger.info(
        "match_justification: llm_call model=%s latency_ms=%d in=%s out=%s",
        model,
        latency_ms,
        getattr(usage, "input_tokens", "?"),
        getattr(usage, "output_tokens", "?"),
    )
    if not isinstance(parsed, dict):
        raise MatchJustificationLLMError("LLM returned non-object JSON")
    return parsed


# ── Prompt context builders ─────────────────────────────────────────────────


def _truncate(text: Optional[str], limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + " […]"


def _candidate_cv_text(candidate: Candidate) -> str:
    """Best CV text available: raw CV, else the AI summary as a fallback."""
    cv = (candidate.raw_cv_text or "").strip()
    if not cv:
        cv = (candidate.ai_summary or "").strip()
    return _truncate(cv, MAX_CV_CHARS) or "(brak treści CV w systemie)"


def _skills_to_text(raw: Any) -> str:
    """Flatten a skills JSONB (list of str / list of dict / str) to a CSV line."""
    if not raw:
        return "(brak)"
    if isinstance(raw, list):
        names = []
        for s in raw:
            if isinstance(s, dict):
                name = s.get("name") or s.get("skill") or ""
            else:
                name = str(s)
            name = name.strip()
            if name:
                names.append(name)
        return ", ".join(names[:40]) or "(brak)"
    if isinstance(raw, str):
        return _truncate(raw, 600) or "(brak)"
    return "(brak)"


def _job_requirements_text(job: Job) -> str:
    parts: list[str] = []
    must = _skills_to_text(job.must_skills)
    nice = _skills_to_text(job.nice_skills)
    if must and must != "(brak)":
        parts.append(f"MUST: {must}")
    if nice and nice != "(brak)":
        parts.append(f"NICE: {nice}")
    if job.requirements:
        parts.append(job.requirements)
    if job.description:
        parts.append(f"Opis: {job.description}")
    return _truncate("\n".join(parts), MAX_REQ_CHARS) or "(brak wymagań w systemie)"


def _champion_context_text(job: Job) -> str:
    """Readable slice of the Champion profile JSONB (defensive on shape)."""
    cp = job.champion_profile
    if not isinstance(cp, dict) or not cp:
        return "(brak profilu Championa)"
    bits: list[str] = []
    ctx = cp.get("project_context")
    if isinstance(ctx, dict):
        for key, label in (
            ("about", "Projekt"),
            ("responsibilities", "Obowiązki"),
            ("selling_points", "Atuty"),
        ):
            val = (ctx.get(key) or "").strip() if isinstance(ctx.get(key), str) else ""
            if val:
                bits.append(f"{label}: {val}")
    basics = cp.get("basics")
    if isinstance(basics, dict):
        loc = basics.get("candidate_location_pref")
        onsite = basics.get("onsite_days_per_week")
        if loc:
            bits.append(f"Preferowana lokalizacja: {loc}")
        if onsite is not None:
            bits.append(f"Dni w biurze/tydz.: {onsite}")
    return _truncate("\n".join(bits), MAX_CHAMPION_CHARS) or "(brak profilu Championa)"


def _format_score_breakdown(bd: dict) -> str:
    """Render the ScoreBreakdown dict as compact, human-readable lines."""
    lines: list[str] = [f"Wynik łączny: {bd.get('total')}/100"]
    layer_labels = {
        "semantic": "Semantyczne dopasowanie",
        "skills": "Umiejętności",
        "salary": "Stawka/widełki",
        "location": "Lokalizacja",
        "availability": "Dostępność",
        "champion_fit": "Dopasowanie do Championa",
    }
    for key, label in layer_labels.items():
        layer = bd.get(key)
        if isinstance(layer, dict):
            reason = layer.get("reason") or ""
            lines.append(
                f"- {label}: {layer.get('points')}/{layer.get('max')}"
                + (f" ({reason})" if reason else "")
            )
    matching = bd.get("matching_must") or []
    gaps = bd.get("gap_must") or []
    matching_nice = bd.get("matching_nice") or []
    if matching:
        lines.append("Spełnione MUST: " + ", ".join(map(str, matching)))
    if gaps:
        lines.append("Braki MUST: " + ", ".join(map(str, gaps)))
    if matching_nice:
        lines.append("Spełnione NICE: " + ", ".join(map(str, matching_nice)))
    penalties = bd.get("penalties") or []
    if penalties:
        lines.append("Kary: " + ", ".join(map(str, penalties)))
    return "\n".join(lines)


def _input_hash(candidate: Candidate, job: Job, breakdown: dict) -> str:
    """Fingerprint the inputs so the prose regenerates only when they change.

    Includes the prompt version so a prompt bump invalidates every cached row.
    """
    payload = json.dumps(
        {
            "prompt_version": MATCH_JUSTIFICATION.version,
            "model": DEFAULT_MODEL,
            "score": int(round(breakdown.get("total") or 0)),
            "cv": _candidate_cv_text(candidate),
            "cand_summary": candidate.ai_summary or "",
            "cand_skills": _skills_to_text(candidate.skills),
            "cand_cc": candidate.competence_category or "",
            "job_title": job.title or "",
            "job_req": _job_requirements_text(job),
            "champion": _champion_context_text(job),
            "matching_must": sorted(map(str, breakdown.get("matching_must") or [])),
            "gap_must": sorted(map(str, breakdown.get("gap_must") or [])),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ── Output sanitisation ─────────────────────────────────────────────────────


def _clean_bullets(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        text = (str(item) if item is not None else "").strip()
        if text:
            out.append(text[:_MAX_BULLET_CHARS])
        if len(out) >= _MAX_BULLETS:
            break
    return out


def _sanitize_llm_output(parsed: dict) -> dict:
    summary = (str(parsed.get("summary") or "")).strip()[:_MAX_SUMMARY_CHARS]
    pros = _clean_bullets(parsed.get("pros"))
    watchouts = _clean_bullets(parsed.get("watchouts"))
    if not summary and not pros:
        raise MatchJustificationLLMError("LLM output empty (no summary / pros)")
    return {"summary": summary, "pros": pros, "watchouts": watchouts}


# ── Score + quota ───────────────────────────────────────────────────────────


async def _compute_breakdown(
    candidate: Candidate, job: Job, db: AsyncSession
) -> ScoreBreakdown:
    """Same calibrated score the kanban ring uses (cache-first + Qdrant cosine)."""
    similarity: Optional[float] = None
    try:
        from app.services.embedding_service import (  # noqa: PLC0415
            _build_job_text,
            similarity_for_candidate_ids,
        )

        sims = await similarity_for_candidate_ids(_build_job_text(job), [candidate.id])
        similarity = sims.get(candidate.id)
    except Exception as exc:  # pragma: no cover - semantic layer is best-effort
        logger.warning("match_justification: similarity lookup failed: %s", exc)

    return await get_cached_or_compute(
        candidate, job, db, semantic_similarity=similarity
    )


async def _gate_and_count(db: AsyncSession, user_id: Optional[int]) -> None:
    """Respect the AI kill-switch + `scoring` toggle/limit, then record 1 use.

    Tolerant of a missing `ai_features` row: `AIFeatureConfig.enabled` defaults
    to True, so an unseeded feature is treated as enabled (only an explicit
    disable or the master toggle blocks). Raises ``AIQuotaExceeded`` if blocked.
    """
    if not await get_master_enabled(db):
        raise AIQuotaExceeded(AIFeatureKey.scoring, "Funkcje AI są wyłączone globalnie")

    config = await get_feature_config(db, AIFeatureKey.scoring)
    if config is not None and not config.enabled:
        raise AIQuotaExceeded(
            AIFeatureKey.scoring, "Funkcja AI wyłączona w ustawieniach"
        )

    limit = config.monthly_limit if config else 0
    period = datetime.now(timezone.utc).date().replace(day=1)
    used = await get_total_usage_for_period(db, AIFeatureKey.scoring, period)
    if limit > 0 and used >= limit:
        raise AIQuotaExceeded(
            AIFeatureKey.scoring, "Miesięczny limit wyczerpany", used=used, limit=limit
        )

    now = datetime.now(timezone.utc)
    await db.execute(
        pg_insert(AIUsageLog)
        .values(
            feature=AIFeatureKey.scoring,
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


# ── Orchestration ───────────────────────────────────────────────────────────


async def generate_prose(
    candidate: Candidate, job: Job, breakdown: dict, *, model: str = DEFAULT_MODEL
) -> dict:
    """Ask Claude to explain the score. Returns {summary, pros, watchouts}."""
    prompt = MATCH_JUSTIFICATION.render(
        job_title=job.title or "(brak tytułu)",
        job_requirements=_job_requirements_text(job),
        champion_context=_champion_context_text(job),
        competence_category=candidate.competence_category or "(brak)",
        candidate_summary=_truncate(candidate.ai_summary, 1500) or "(brak)",
        candidate_skills=_skills_to_text(candidate.skills),
        candidate_cv=_candidate_cv_text(candidate),
        score=int(round(breakdown.get("total") or 0)),
        score_breakdown=_format_score_breakdown(breakdown),
    )
    parsed = await _call_claude_json(
        prompt=prompt,
        system_prompt=MATCH_JUSTIFICATION.system_prompt or "",
        model=model,
        max_tokens=MAX_TOKENS,
    )
    return _sanitize_llm_output(parsed)


async def get_or_generate(
    candidate_id: int,
    job_id: int,
    db: AsyncSession,
    *,
    user_id: Optional[int] = None,
    force: bool = False,
) -> CandidateMatchJustification:
    """Return the (cached or freshly generated) justification row.

    Raises ``MatchJustificationNotFound`` (unknown candidate/job),
    ``AIQuotaExceeded`` (AI disabled / over limit) or
    ``MatchJustificationLLMError`` (generation failed).
    """
    candidate = await db.scalar(select(Candidate).where(Candidate.id == candidate_id))
    if candidate is None:
        raise MatchJustificationNotFound("Kandydat nie istnieje")
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if job is None:
        raise MatchJustificationNotFound("Oferta nie istnieje")

    breakdown_obj = await _compute_breakdown(candidate, job, db)
    breakdown = breakdown_obj.as_dict()
    score = int(round(min(max(breakdown.get("total") or 0.0, 0.0), 100.0)))
    input_hash = _input_hash(candidate, job, breakdown)

    row = await db.scalar(
        select(CandidateMatchJustification).where(
            CandidateMatchJustification.candidate_id == candidate_id,
            CandidateMatchJustification.job_id == job_id,
        )
    )
    if row is not None and not force and row.input_hash == input_hash:
        return row

    # Cache miss / forced refresh / stale inputs → paid LLM call (gated).
    await _gate_and_count(db, user_id)
    prose = await generate_prose(candidate, job, breakdown)

    if row is None:
        row = CandidateMatchJustification(candidate_id=candidate_id, job_id=job_id)
        db.add(row)
    # A regenerated justification is a new verdict → drop the stale rating.
    if row.input_hash != input_hash:
        row.rating = None
        row.rating_comment = None
        row.rated_by = None
        row.rated_at = None
    row.score = score
    row.summary = prose["summary"]
    row.pros = prose["pros"]
    row.watchouts = prose["watchouts"]
    row.model = DEFAULT_MODEL
    row.input_hash = input_hash

    try:
        await db.commit()
    except IntegrityError:
        # Concurrent first-view of the same (candidate, job) inserted the row
        # first (unique constraint). Roll back and serve the winner's row —
        # the LLM work is wasted but the request still succeeds.
        await db.rollback()
        existing = await get_cached(candidate_id, job_id, db)
        if existing is not None:
            return existing
        raise
    await db.refresh(row)
    return row


async def get_cached(
    candidate_id: int, job_id: int, db: AsyncSession
) -> Optional[CandidateMatchJustification]:
    """Fetch the stored justification without generating (used by feedback)."""
    return await db.scalar(
        select(CandidateMatchJustification).where(
            CandidateMatchJustification.candidate_id == candidate_id,
            CandidateMatchJustification.job_id == job_id,
        )
    )
