"""Deterministic match justification built only from ``ScoreBreakdown``.

Pipeline for one (candidate, job) pair:
  1. Compute the deterministic hybrid score (``scoring_service`` via the shared
     ``match_score_cache``) — the same 0-100 number the kanban ring shows.
  2. Fingerprint the inputs (CV + requirements + champion + score). If a cached
     ``CandidateMatchJustification`` row matches that fingerprint, serve it — no
     LLM call.
  3. On a miss (or ``force``), render summary/pros/watch-outs directly from the
     scored layers, matched skills, gaps and penalties. No LLM is involved.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.job import Job
from app.models.match_justification import CandidateMatchJustification
from app.services.match_score_cache import get_cached_or_compute
from app.services.scoring_service import ScoreBreakdown

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "deterministic:score_breakdown_v1"
MAX_CV_CHARS = 6000
MAX_REQ_CHARS = 3000
MAX_CHAMPION_CHARS = 2000
JUSTIFICATION_VERSION = "score_breakdown_v1"

# Output caps keep the stored explanation compact and UI-safe.
_MAX_SUMMARY_CHARS = 1200
_MAX_BULLET_CHARS = 320
_MAX_BULLETS = 8


class MatchJustificationNotFound(Exception):
    """Candidate or job does not exist."""


class MatchJustificationLLMError(Exception):
    """Deprecated compatibility error; deterministic generation does not raise it."""


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
            "prompt_version": JUSTIFICATION_VERSION,
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


def _sanitize_output(parsed: dict) -> dict:
    summary = (str(parsed.get("summary") or "")).strip()[:_MAX_SUMMARY_CHARS]
    pros = _clean_bullets(parsed.get("pros"))
    watchouts = _clean_bullets(parsed.get("watchouts"))
    if not summary and not pros:
        raise MatchJustificationLLMError("Explanation output empty (no summary / pros)")
    return {"summary": summary, "pros": pros, "watchouts": watchouts}


# Backward-compatible name for callers/tests from the previous implementation.
_sanitize_llm_output = _sanitize_output


# ── Score computation ──────────────────────────────────────────────────────


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
        logger.warning(
            "match_justification: similarity lookup failed error_type=%s",
            type(exc).__name__,
        )

    return await get_cached_or_compute(
        candidate, job, db, semantic_similarity=similarity
    )


# ── Orchestration ───────────────────────────────────────────────────────────


async def generate_prose(
    candidate: Candidate, job: Job, breakdown: dict, *, model: str = DEFAULT_MODEL
) -> dict:
    """Render an explanation exclusively from ``ScoreBreakdown`` fields.

    ``candidate``, ``job`` and ``model`` remain in the signature for one-release
    API compatibility. They are deliberately not read: unscored CV/JD facts
    must never leak into or alter the explanation.
    """
    del candidate, job, model
    total = int(round(min(max(float(breakdown.get("total") or 0), 0), 100)))
    layer_labels = {
        "semantic": "Dopasowanie semantyczne",
        "skills": "Umiejętności",
        "salary": "Stawka",
        "location": "Lokalizacja",
        "availability": "Dostępność",
        "champion_fit": "Profil Champion",
    }
    pros: list[str] = []
    watchouts: list[str] = []

    matching_must = [str(v) for v in breakdown.get("matching_must") or []]
    matching_nice = [str(v) for v in breakdown.get("matching_nice") or []]
    gap_must = [str(v) for v in breakdown.get("gap_must") or []]
    gap_nice = [str(v) for v in breakdown.get("gap_nice") or []]
    penalties = [str(v) for v in breakdown.get("penalties") or []]
    if matching_must:
        pros.append("Spełnione wymagania MUST: " + ", ".join(matching_must))
    if matching_nice:
        pros.append("Spełnione wymagania NICE: " + ", ".join(matching_nice))
    if gap_must:
        watchouts.append("Braki w wymaganiach MUST: " + ", ".join(gap_must))
    if gap_nice:
        watchouts.append("Braki w wymaganiach NICE: " + ", ".join(gap_nice))
    if penalties:
        watchouts.append("Aktywne kary scoringu: " + ", ".join(penalties))

    layer_parts: list[str] = []
    for key, label in layer_labels.items():
        layer = breakdown.get(key)
        if not isinstance(layer, dict):
            continue
        points = float(layer.get("points") or 0)
        maximum = float(layer.get("max") or 0)
        reason = str(layer.get("reason") or "").strip()
        detail = f"{label}: {points:g}/{maximum:g}"
        if reason:
            detail += f" — {reason}"
        layer_parts.append(detail)
        target = pros if maximum > 0 and points / maximum >= 0.6 else watchouts
        target.append(detail)

    summary = f"Wynik dopasowania: {total}/100. " + "; ".join(layer_parts) + "."
    return _sanitize_output({"summary": summary, "pros": pros, "watchouts": watchouts})


async def get_or_generate(
    candidate_id: int,
    job_id: int,
    db: AsyncSession,
    *,
    user_id: Optional[int] = None,
    force: bool = False,
) -> CandidateMatchJustification:
    """Return the (cached or freshly generated) justification row.

    Raises ``MatchJustificationNotFound`` for an unknown candidate/job.
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

    # Cache miss / forced refresh / stale inputs → local deterministic render.
    del user_id
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
        # the duplicate render is harmless and the request still succeeds.
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
