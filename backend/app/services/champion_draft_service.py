"""Champion Profile AI draft service (Phase 14 — AI Intake).

Three input paths produce a `ChampionProfileSuggestion` in `status=pending`:
  1. JD paste             → :func:`generate_from_jd`
  2. Fireflies transcript → :func:`enrich_from_meeting`
  3. CloudTalk transcript → :func:`enrich_from_call`

Two review actions finalise the suggestion:
  :func:`apply_suggestion`  — merges the accepted sections into
                              `jobs.champion_profile` inside a FOR-UPDATE
                              transaction, writes an Activity log entry.
  :func:`reject_suggestion` — marks as rejected, no profile change.

Design notes
------------
* All LLM calls go through :func:`_call_claude_json`, which mirrors the pattern
  in `app/api/ai_writer.py::_generate_with_claude` but is generic (caller
  supplies prompt + system prompt + model).
* LLM output is validated against `ChampionProfile` schema — hallucinated
  fields raise ValidationError and the suggestion is persisted with
  `status=rejected` and `error_message` set so the UI can display the failure.
* `apply_suggestion` uses `SELECT ... FOR UPDATE` to prevent race conditions
  when two DLs (or two tabs) apply different suggestions concurrently.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Iterable, Optional

from fastapi import HTTPException, status as http_status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.champion_suggestion import (
    ChampionProfileSuggestion,
    SuggestionSource,
    SuggestionStatus,
)
from app.models.client import Client
from app.models.job import Job
from app.schemas.champion import (
    ChampionBasics,
    ChampionProfile,
    ChampionProjectContext,
    ScreeningQuestion,
    SourcingStrategy,
)
from app.schemas.champion_suggestion import (
    VALID_SECTIONS,
    payload_from_profile,
)
from app.services.llm_prompts import (
    CHAMPION_PROFILE_ENRICH_FROM_CALL,
    CHAMPION_PROFILE_ENRICH_FROM_MEETING,
    CHAMPION_PROFILE_FROM_JD,
    PromptTemplate,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("CHAMPION_AI_MODEL", "claude-opus-4-5")
MAX_TRANSCRIPT_CHARS = int(
    os.environ.get("CHAMPION_AI_MAX_TRANSCRIPT_CHARS", "40000")
)


# ── LLM plumbing ────────────────────────────────────────────────────────────


def _strip_code_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


async def _call_claude_json(
    *,
    prompt: str,
    system_prompt: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 4000,
) -> dict[str, Any]:
    """Call Claude and parse JSON output. Raises on any failure.

    Logs (without prompt content):  prompt token counts, latency, status.
    """
    import anthropic  # local import: avoid cost of import at module load

    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    client = anthropic.Anthropic(api_key=api_key)

    started = time.time()
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": prompt}],
    )
    latency_ms = int((time.time() - started) * 1000)

    raw = _strip_code_fences(message.content[0].text)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning(
            "champion_draft: LLM returned invalid JSON (model=%s latency=%dms)",
            model,
            latency_ms,
        )
        raise ValueError(f"Invalid JSON from LLM: {exc}") from exc

    usage = getattr(message, "usage", None)
    logger.info(
        "champion_draft: llm_call model=%s latency_ms=%d input_tokens=%s output_tokens=%s",
        model,
        latency_ms,
        getattr(usage, "input_tokens", "?"),
        getattr(usage, "output_tokens", "?"),
    )
    return parsed


def _truncate_transcript(text: str, limit: int = MAX_TRANSCRIPT_CHARS) -> str:
    if len(text) <= limit:
        return text
    # Hard truncate — in the future we can summarise earlier sentences first.
    return text[:limit] + "\n\n[... transkrypt skrócony ...]"


# ── Core: generate / apply / reject ─────────────────────────────────────────


async def _load_job_with_client(db: AsyncSession, job_id: int) -> Job:
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Job not found"
        )
    return job


async def _client_name(db: AsyncSession, client_id: Optional[int]) -> str:
    if not client_id:
        return "nieznany klient"
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    return client.name if client and client.name else "nieznany klient"


async def _supersede_previous_pending(
    db: AsyncSession,
    *,
    job_id: int,
    source_type: SuggestionSource,
) -> None:
    """Mark any still-pending suggestion with the same source_type as superseded."""
    result = await db.execute(
        select(ChampionProfileSuggestion).where(
            ChampionProfileSuggestion.job_id == job_id,
            ChampionProfileSuggestion.source_type == source_type,
            ChampionProfileSuggestion.status == SuggestionStatus.pending,
        )
    )
    for prev in result.scalars().all():
        prev.status = SuggestionStatus.superseded


async def generate_from_jd(
    db: AsyncSession,
    *,
    job_id: int,
    raw_description: str,
    user_id: Optional[int],
) -> ChampionProfileSuggestion:
    """Generate a Champion Profile draft from a raw job description.

    Steps:
      1. Load Job + Client (for placeholders).
      2. Render prompt, call Claude, parse JSON.
      3. Validate via `ChampionProfile.model_validate` — on ValidationError the
         suggestion is saved with `status=rejected` + `error_message`, so the
         DL can see that the parse failed.
      4. Supersede any older pending jd_paste suggestions for the same job.
      5. Persist new suggestion with `status=pending`.
    """
    job = await _load_job_with_client(db, job_id)
    client_name = await _client_name(db, job.client_id)

    prompt = CHAMPION_PROFILE_FROM_JD.render(
        job_title=job.title or "bez tytułu",
        client_name=client_name,
        raw_description=raw_description,
    )

    await _supersede_previous_pending(
        db, job_id=job_id, source_type=SuggestionSource.jd_paste
    )

    # Attempt LLM call — on ANY error, persist a rejected suggestion so the UI
    # can show the failure instead of silently swallowing it.
    error_message: Optional[str] = None
    payload: dict[str, Any] = {}
    status_val: SuggestionStatus = SuggestionStatus.pending

    try:
        raw = await _call_claude_json(
            prompt=prompt,
            system_prompt=CHAMPION_PROFILE_FROM_JD.system_prompt or "",
        )
        confidence = raw.pop("_confidence", {}) or {}
        profile = ChampionProfile.model_validate(raw)
        payload = payload_from_profile(profile, confidence=confidence)
    except ValidationError as exc:
        logger.warning(
            "champion_draft: ChampionProfile validation failed for job %s: %s",
            job_id,
            exc,
        )
        error_message = f"Walidacja schematu nie powiodła się: {exc}"
        status_val = SuggestionStatus.rejected
    except Exception as exc:  # noqa: BLE001 — broad catch is intentional here
        logger.warning("champion_draft: generate_from_jd failed: %s", exc)
        error_message = f"Błąd generowania: {exc}"
        status_val = SuggestionStatus.rejected

    suggestion = ChampionProfileSuggestion(
        job_id=job_id,
        source_type=SuggestionSource.jd_paste,
        source_ref=None,
        payload=payload,
        status=status_val,
        created_by_id=user_id,
        model_name=DEFAULT_MODEL,
        prompt_version=CHAMPION_PROFILE_FROM_JD.version,
        error_message=error_message,
    )
    db.add(suggestion)
    await db.commit()
    await db.refresh(suggestion)
    return suggestion


async def _generate_enrichment_suggestion(
    db: AsyncSession,
    *,
    template: PromptTemplate,
    template_vars: dict[str, Any],
    job_id: int,
    source_type: SuggestionSource,
    source_ref: Optional[str],
    user_id: Optional[int],
) -> ChampionProfileSuggestion:
    """Shared path for Fireflies / CloudTalk enrichment.

    The LLM returns a partial delta keyed by section name. We store it raw
    (after normalisation) so UI diff-viewers can render only the sections
    that the LLM actually touched.
    """
    prompt = template.render(**template_vars)
    status_val: SuggestionStatus = SuggestionStatus.pending
    error_message: Optional[str] = None
    payload: dict[str, Any] = {}

    try:
        raw = await _call_claude_json(
            prompt=prompt,
            system_prompt=template.system_prompt or "",
        )
        payload = {}
        for section in VALID_SECTIONS:
            entry = raw.get(section)
            if not isinstance(entry, dict):
                continue
            value = entry.get("value")
            if value is None:
                continue
            payload[section] = {
                "value": value,
                "confidence": float(entry.get("confidence") or 0.0),
                "rationale": str(entry.get("rationale") or ""),
            }
        if not payload:
            # No recognisable sections = nothing to review. Skip creation.
            logger.info(
                "champion_draft: enrichment produced no patches (job=%s source=%s)",
                job_id,
                source_type.value,
            )
            status_val = SuggestionStatus.rejected
            error_message = "LLM nie zaproponował żadnych zmian."
    except ValidationError as exc:
        logger.warning("champion_draft: enrichment validation failed: %s", exc)
        error_message = f"Walidacja schematu: {exc}"
        status_val = SuggestionStatus.rejected
    except Exception as exc:  # noqa: BLE001
        logger.warning("champion_draft: enrichment call failed: %s", exc)
        error_message = f"Błąd generowania: {exc}"
        status_val = SuggestionStatus.rejected

    suggestion = ChampionProfileSuggestion(
        job_id=job_id,
        source_type=source_type,
        source_ref=source_ref,
        payload=payload,
        status=status_val,
        created_by_id=user_id,
        model_name=DEFAULT_MODEL,
        prompt_version=template.version,
        error_message=error_message,
    )
    db.add(suggestion)
    await db.commit()
    await db.refresh(suggestion)
    return suggestion


async def enrich_from_meeting(
    db: AsyncSession,
    *,
    job_id: int,
    meeting_title: str,
    meeting_summary: str,
    meeting_transcript: str,
    source_ref: Optional[str] = None,
    user_id: Optional[int] = None,
) -> ChampionProfileSuggestion:
    """Generate enrichment suggestion from a Fireflies meeting transcript."""
    job = await _load_job_with_client(db, job_id)
    client_name = await _client_name(db, job.client_id)
    current_profile_json = json.dumps(job.champion_profile or {}, ensure_ascii=False)

    return await _generate_enrichment_suggestion(
        db,
        template=CHAMPION_PROFILE_ENRICH_FROM_MEETING,
        template_vars={
            "current_profile_json": current_profile_json,
            "job_title": job.title or "bez tytułu",
            "client_name": client_name,
            "meeting_title": meeting_title or "brak tytułu",
            "meeting_summary": meeting_summary or "brak podsumowania",
            "meeting_transcript": _truncate_transcript(meeting_transcript or ""),
        },
        job_id=job_id,
        source_type=SuggestionSource.fireflies_meeting,
        source_ref=source_ref,
        user_id=user_id,
    )


async def enrich_from_call(
    db: AsyncSession,
    *,
    job_id: int,
    call_participants: str,
    call_summary: str,
    call_transcript: str,
    source_ref: Optional[str] = None,
    user_id: Optional[int] = None,
) -> ChampionProfileSuggestion:
    """Generate enrichment suggestion from a CloudTalk call transcript."""
    job = await _load_job_with_client(db, job_id)
    client_name = await _client_name(db, job.client_id)
    current_profile_json = json.dumps(job.champion_profile or {}, ensure_ascii=False)

    return await _generate_enrichment_suggestion(
        db,
        template=CHAMPION_PROFILE_ENRICH_FROM_CALL,
        template_vars={
            "current_profile_json": current_profile_json,
            "job_title": job.title or "bez tytułu",
            "client_name": client_name,
            "call_participants": call_participants or "nieznani",
            "call_summary": call_summary or "brak podsumowania",
            "call_transcript": _truncate_transcript(call_transcript or ""),
        },
        job_id=job_id,
        source_type=SuggestionSource.cloudtalk_call,
        source_ref=source_ref,
        user_id=user_id,
    )


# ── Merge logic for apply ───────────────────────────────────────────────────


def _merge_sourcing(current: dict[str, Any], proposed: dict[str, Any]) -> dict[str, Any]:
    """For sourcing: per-field merge. Lists unioned, strings replaced if non-empty."""
    merged = dict(current or {})
    proposed_sources = proposed.get("sources") or []
    if proposed_sources:
        existing = set(merged.get("sources") or [])
        merged["sources"] = sorted(existing.union(proposed_sources))
    for field in ("keywords", "target_companies", "notes"):
        proposed_val = proposed.get(field)
        if proposed_val:
            merged[field] = proposed_val
    return merged


def _merge_basics(current: dict[str, Any], proposed: dict[str, Any]) -> dict[str, Any]:
    """For basics: replace each non-null proposed field."""
    merged = dict(current or {})
    for field in ("onsite_days_per_week", "candidate_location_pref", "language"):
        proposed_val = proposed.get(field)
        if proposed_val is not None and proposed_val != "":
            merged[field] = proposed_val
    return merged


def _merge_screening_questions(
    current: list[dict[str, Any]], proposed: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Append proposed questions, dedup by `id` (current wins on conflict)."""
    existing_ids = {q.get("id") for q in (current or []) if isinstance(q, dict)}
    out = list(current or [])
    for q in proposed or []:
        if not isinstance(q, dict):
            continue
        qid = q.get("id")
        if qid and qid in existing_ids:
            continue
        out.append(q)
        if qid:
            existing_ids.add(qid)
    return out


def _merge_section(
    section: str, current: Any, proposed: Any
) -> Any:
    """Apply the section-specific merge rule. Raw dicts, no Pydantic objects."""
    if section == "basics":
        return _merge_basics(current or {}, proposed or {})
    if section == "sourcing":
        return _merge_sourcing(current or {}, proposed or {})
    if section == "screening_questions":
        return _merge_screening_questions(current or [], proposed or [])
    # project_context: replace per-field (object-like, but treat as replace-on-non-empty)
    if section == "project_context":
        merged = dict(current or {})
        for field in ("about", "responsibilities", "selling_points"):
            proposed_val = (proposed or {}).get(field)
            if proposed_val:
                merged[field] = proposed_val
        return merged
    # scalar / string sections: replace on non-empty
    if proposed not in (None, "", [], {}):
        return proposed
    return current


async def apply_suggestion(
    db: AsyncSession,
    *,
    suggestion_id: int,
    accepted_sections: Iterable[str],
    user_id: int,
) -> ChampionProfileSuggestion:
    """Merge the accepted sections of a pending suggestion into the Job's profile.

    Uses `SELECT ... FOR UPDATE` on the Job row to avoid racing with a
    parallel apply. Raises 409 if the suggestion is no longer pending.
    """
    accepted_list = [s for s in accepted_sections if s in VALID_SECTIONS]

    # Load suggestion (without lock) to know which job to lock.
    res = await db.execute(
        select(ChampionProfileSuggestion).where(
            ChampionProfileSuggestion.id == suggestion_id
        )
    )
    suggestion = res.scalar_one_or_none()
    if not suggestion:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Suggestion not found"
        )
    if suggestion.status != SuggestionStatus.pending:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"Suggestion already {suggestion.status.value}",
        )

    # Lock the Job row for the merge.
    job_res = await db.execute(
        select(Job).where(Job.id == suggestion.job_id).with_for_update()
    )
    job = job_res.scalar_one_or_none()
    if not job:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Job not found"
        )

    current_profile: dict[str, Any] = dict(job.champion_profile or {})
    # Ensure all sections exist as defaults before merging.
    defaults = ChampionProfile().model_dump(mode="json")
    for k, v in defaults.items():
        current_profile.setdefault(k, v)

    merged_sections: list[str] = []
    for section in accepted_list:
        entry = suggestion.payload.get(section) or {}
        if not isinstance(entry, dict):
            continue
        proposed_value = entry.get("value")
        if proposed_value is None:
            continue
        current_profile[section] = _merge_section(
            section, current_profile.get(section), proposed_value
        )
        merged_sections.append(section)

    # Final validation — guarantees we never write a bad profile to DB.
    validated = ChampionProfile.model_validate(current_profile)
    job.champion_profile = validated.model_dump(mode="json")

    # Status: full accept iff all sections with value=non-null were accepted,
    # otherwise partially_accepted.
    all_sections_with_value = {
        s
        for s in VALID_SECTIONS
        if isinstance(suggestion.payload.get(s), dict)
        and suggestion.payload[s].get("value") is not None
    }
    accepted_set = set(merged_sections)
    if accepted_set and accepted_set == all_sections_with_value:
        suggestion.status = SuggestionStatus.accepted
    elif accepted_set:
        suggestion.status = SuggestionStatus.partially_accepted
    else:
        suggestion.status = SuggestionStatus.rejected

    suggestion.reviewed_by_id = user_id
    from datetime import datetime, timezone

    suggestion.reviewed_at = datetime.now(timezone.utc)

    db.add(
        Activity(
            entity_type="job",
            entity_id=job.id,
            action="champion_profile_applied_from_suggestion",
            user_id=user_id,
            details={
                "suggestion_id": suggestion.id,
                "source_type": suggestion.source_type.value,
                "accepted_sections": merged_sections,
            },
        )
    )
    await db.commit()
    await db.refresh(suggestion)
    return suggestion


async def reject_suggestion(
    db: AsyncSession,
    *,
    suggestion_id: int,
    user_id: int,
) -> ChampionProfileSuggestion:
    res = await db.execute(
        select(ChampionProfileSuggestion).where(
            ChampionProfileSuggestion.id == suggestion_id
        )
    )
    suggestion = res.scalar_one_or_none()
    if not suggestion:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Suggestion not found"
        )
    if suggestion.status != SuggestionStatus.pending:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"Suggestion already {suggestion.status.value}",
        )

    from datetime import datetime, timezone

    suggestion.status = SuggestionStatus.rejected
    suggestion.reviewed_by_id = user_id
    suggestion.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(suggestion)
    return suggestion


# ── Explicit re-exports for tests / callers ─────────────────────────────────

__all__ = [
    "DEFAULT_MODEL",
    "MAX_TRANSCRIPT_CHARS",
    "generate_from_jd",
    "enrich_from_meeting",
    "enrich_from_call",
    "apply_suggestion",
    "reject_suggestion",
    "_call_claude_json",
    "_merge_section",
    "_merge_screening_questions",
    "_merge_basics",
    "_merge_sourcing",
]


# Compatibility shim for `ChampionBasics` / other schemas in tests (no-op).
_ = (ChampionBasics, ChampionProjectContext, ScreeningQuestion, SourcingStrategy)
