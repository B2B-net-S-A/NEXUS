"""POST /api/recommendations/cv-upload-preview — ad-hoc CV → matching jobs.

Lives in its own module (no `from __future__ import annotations`) because
FastAPI's `Annotated[UploadFile, File(...)]` resolution misclassifies forward-
ref annotations as Query parameters when the future import is enabled.

Pipeline (no Candidate is persisted):
  1. extract_text  (cv_text_extractor)
  2. parse_cv       (Claude → Ollama → regex)
  3. build query    (skills + summary + position + companies)
  4. semantic search nexus_jobs (Qdrant)
  5. rank with hybrid scoring on an ephemeral SimpleNamespace candidate
  6. apply user filters (location/salary/competence). Industry-blocklist is
     intentionally OFF — no candidate row exists to join against.

TODO: SHA-256 cache of CV text → embedding (Redis) when cost matters. For now
each upload pays one Voyage embed call.
"""

import logging
import os
import tempfile
from types import SimpleNamespace
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import require_candidate_read
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.candidate import AvailabilityStatus, CandidateStatus
from app.models.job import Job, JobStatus
from app.models.user import User
from app.services.cv_parser import parse_cv
from app.services.cv_text_extractor import UnsupportedCvFormat, extract_text
from app.services.embedding_service import (
    _build_job_text,
    SemanticSearchUnavailable,
    search_jobs_semantic,
)
from app.services.recommendation_filters import (
    RecommendationFilters,
    apply_user_filters,
)
from app.services.reranker_service import rerank_or_passthrough
from app.services.scoring_service import rank_jobs_for_candidate

logger = logging.getLogger(__name__)
router = APIRouter()


_MAX_CV_BYTES = 10 * 1024 * 1024  # 10 MB
_ALLOWED_CV_EXT = {".pdf", ".docx", ".doc", ".txt"}


def _build_query_text_from_parsed(parsed: dict) -> str:
    """Compose embedding query string from a parsed-CV dict.

    Mirrors the spirit of `embedding_service._build_candidate_text` but reads
    from the LLM-output dict (no ORM row available).
    """
    parts: list[str] = []
    if parsed.get("current_position"):
        parts.append(parsed["current_position"])
    if parsed.get("career_summary"):
        parts.append(parsed["career_summary"])

    years = parsed.get("years_it_experience")
    if isinstance(years, int):
        if years >= 7:
            parts.append("senior experienced engineer")
        elif years >= 3:
            parts.append("mid-level developer")
        else:
            parts.append("junior entry-level developer")

    for s in parsed.get("skills") or []:
        if isinstance(s, dict) and s.get("name"):
            parts.append(s["name"])
        elif isinstance(s, str):
            parts.append(s)

    for c in parsed.get("companies") or []:
        if isinstance(c, str):
            parts.append(c)

    return " ".join(p for p in parts if p and str(p).strip())


def _ephemeral_candidate_from_parsed(parsed: dict, raw_cv_text: str) -> SimpleNamespace:
    """Build a Candidate-like SimpleNamespace for the scoring engine.

    `id=0` keeps DB joins (`CandidateConflict`, `CandidateStage`) safe — they
    return zero rows and the layers degrade to neutral defaults. Every field
    the scoring engine reads is populated with permissive defaults so a
    missing field never fabricates points.
    """
    return SimpleNamespace(
        id=0,
        name=parsed.get("first_name") or "",
        lastname=parsed.get("last_name") or "",
        email=parsed.get("email"),
        skills=parsed.get("skills") or [],
        verified_tech=[],
        tags=[],
        experience=[],
        location=parsed.get("city"),
        availability_date=None,
        availability_status=AvailabilityStatus.unknown,
        expected_rate_hourly=None,
        years_it_experience=parsed.get("years_it_experience"),
        competence_category=None,
        ai_summary=parsed.get("career_summary"),
        raw_cv_text=raw_cv_text,
        preferences={},
        status=CandidateStatus.active,
        champion=False,
        avatar_url=None,
    )


def _shape_parsed_summary(parsed: dict) -> dict:
    """Trim parser output to the public preview shape."""
    return {
        "first_name": parsed.get("first_name"),
        "last_name": parsed.get("last_name"),
        "email": parsed.get("email"),
        "phone": parsed.get("phone"),
        "city": parsed.get("city"),
        "current_position": parsed.get("current_position"),
        "years_it_experience": parsed.get("years_it_experience"),
        "skills": parsed.get("skills") or [],
        "languages": parsed.get("languages") or [],
        "linkedin_url": parsed.get("linkedin_url"),
        "source": parsed.get("_source"),
    }


def _shape_job(j: Job) -> dict:
    return {
        "id": j.id,
        "title": j.title,
        "client_id": j.client_id,
        "location": j.location,
        "salary_min": j.salary_min,
        "salary_max": j.salary_max,
        "remote_policy": j.remote_policy.value if j.remote_policy else None,
        "status": j.status.value if j.status else None,
        "priority": j.priority.value if j.priority else None,
        "seniority": j.seniority.value if j.seniority else None,
        "industry": j.industry,
        "deadline": j.deadline.isoformat() if j.deadline else None,
    }


@router.post("/recommendations/cv-upload-preview")
@limiter.limit("10/minute")
async def cv_upload_preview(
    request: Request,
    file: Annotated[UploadFile, File(description="CV file (PDF/DOCX/TXT)")],
    top_k: Annotated[int, Query(ge=1, le=50)] = 10,
    threshold: Annotated[float, Query(ge=0.0, le=100.0)] = 0.0,
    location: Annotated[Optional[str], Form()] = None,
    salary_min: Annotated[Optional[int], Form()] = None,
    salary_max: Annotated[Optional[int], Form()] = None,
    competence_category: Annotated[Optional[str], Form()] = None,
    current_user: User = Depends(require_candidate_read),
    db: AsyncSession = Depends(get_db),
):
    """Preview top jobs for a freshly uploaded CV — no Candidate is created."""
    filename = file.filename or "cv"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in _ALLOWED_CV_EXT:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Nieobsługiwany format pliku: {ext or '(brak rozszerzenia)'}. "
                "Akceptowane: PDF, DOCX, DOC, TXT."
            ),
        )

    payload = await file.read(_MAX_CV_BYTES + 1)
    if len(payload) > _MAX_CV_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Plik CV przekracza limit {_MAX_CV_BYTES // (1024 * 1024)} MB.",
        )
    if not payload:
        raise HTTPException(status_code=400, detail="Pusty plik CV.")

    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=ext, delete=False, prefix="nexus_cv_preview_"
        ) as tmp:
            tmp.write(payload)
            tmp_path = tmp.name

        try:
            # PDF/DOCX extraction (incl. OCR) is CPU/IO heavy and synchronous —
            # offload so it does not block the single-worker event loop.
            cv_text = await run_in_threadpool(extract_text, tmp_path, filename)
        except UnsupportedCvFormat as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        if not cv_text.strip():
            raise HTTPException(
                status_code=400,
                detail=(
                    "Nie udało się odczytać tekstu z CV "
                    "(plik uszkodzony lub zaszyfrowany?)."
                ),
            )

        # Settings → AI quota gate (Traffit gap #5).
        # Charge cv_parser only when we'll actually invoke parse_cv() with
        # extracted text. Counted before commit so a quota-blocked upload
        # gets 503 without burning a Claude call.
        #
        # `ai_feature(...)`, nie gołe `check_and_increment`: obciążenie i
        # DEKLARACJA to jeden krok. Samo obciążenie nie ustawia kontekstu
        # wywołania, więc `parse_cv` (wołany bez `db`) docierał do
        # `claude_client._assert_declared` jako niezadeklarowany i logował się
        # jako „UNGATED" mimo poprawnie naliczonej kwoty — zatruwało to detektor
        # nieobjętych bramką wywołań i pod `AI_QUOTA_STRICT` wywaliłoby tę
        # ścieżkę do cichego fallbacku regex/Ollama.
        from app.models.ai_feature import AIFeatureKey
        from app.services.ai_quota import AIQuotaExceeded, ai_feature

        try:
            async with ai_feature(db, AIFeatureKey.cv_parser, user_id=current_user.id):
                await db.commit()
                parsed = await parse_cv(cv_text)
        except AIQuotaExceeded as exc:
            await db.rollback()
            raise HTTPException(
                status_code=503,
                detail={
                    "feature": exc.feature.value,
                    "reason": exc.reason,
                    "used": exc.used,
                    "limit": exc.limit,
                },
            ) from exc
        query_text = _build_query_text_from_parsed(parsed) or cv_text[:2000]

        # Wider Qdrant pool when reranker is on so the cross-encoder has room
        # to reorder; otherwise keep the historical 4x multiplier behaviour.
        rerank_enabled = bool(getattr(settings, "RERANKER_ENABLED", False))
        retrieval_k = 50 if rerank_enabled else top_k * 4
        # `search_jobs_semantic` already embeds `query_text` as a query and
        # returns [] on embedding failure, so it is the single source of truth
        # here — the previous standalone `generate_embedding` probe wasted a
        # Voyage call and (worse) embedded the query as a document.
        # `raise_on_error=True` — bez tego awaria providera dawała `[]`, czyli
        # to samo co zdrowe zapytanie bez trafień, a fallback niżej dolewał
        # 50 ARBITRALNYCH opublikowanych ofert (bez ORDER BY, z ~2857). Warstwa
        # semantyczna w ich scoringu wynosi 0 z 60 punktów, a rekruter dostawał
        # HTTP 200 z listą podpisaną „dopasowania".
        semantic_unavailable = False
        try:
            hits = await search_jobs_semantic(
                query_text, top_k=retrieval_k, raise_on_error=True
            )
        except SemanticSearchUnavailable:
            logger.warning("[cv-match] wyszukiwanie semantyczne niedostępne")
            semantic_unavailable = True
            hits = []
        emb_ok = bool(hits)
        similarity_map: dict[int, float] = {h["job_id"]: h["score"] for h in hits}
        job_ids: list[int] = list(similarity_map.keys())

        # Fallback tylko po ODPOWIEDZI wyszukiwania. Przy awarii losowa lista
        # ofert podpisana „dopasowania" jest gorsza niż jej brak.
        if not job_ids and not semantic_unavailable:
            fallback_rows = await db.execute(
                select(Job.id)
                .where(Job.status == JobStatus.published)
                .order_by(Job.id.desc())
                .limit(50)
            )
            job_ids = [j for (j,) in fallback_rows.all()]

        if not job_ids:
            return {
                "parsed_summary": _shape_parsed_summary(parsed),
                "matches": [],
                "search_type": (
                    "unavailable"
                    if semantic_unavailable
                    else ("semantic" if emb_ok else "fallback")
                ),
                # `meta` w kształcie z `matching.py` — `CVDropzoneMatch.tsx`
                # przekazuje już `recommendationMeta={result.meta ?? null}`,
                # więc slot na baner istnieje i był na stałe pusty.
                "meta": {
                    "mode": "unavailable" if semantic_unavailable else "semantic",
                    "degraded": semantic_unavailable,
                    "reason": (
                        "semantic_unavailable" if semantic_unavailable else None
                    ),
                },
            }

        jobs_res = await db.execute(
            select(Job).where(Job.id.in_(job_ids), Job.status == JobStatus.published)
        )
        jobs = jobs_res.scalars().all()

        # Voyage Rerank 2.5 — re-order semantic candidates with a cross-encoder
        # when enabled. Replaces Qdrant cosine in similarity_map; downstream
        # scoring still applies (semantic 40 / skills 30 / salary 15 / loc 10 / avail 5).
        if rerank_enabled and jobs:
            ordered_jobs = [
                j for j in sorted(jobs, key=lambda j: -similarity_map.get(j.id, 0.0))
            ]
            docs = [_build_job_text(j)[:4000] for j in ordered_jobs]
            pairs = await rerank_or_passthrough(
                query_text, docs, top_k=len(ordered_jobs)
            )
            if pairs and any(score != 1.0 for _, score in pairs):
                similarity_map = {
                    ordered_jobs[idx].id: float(score) for idx, score in pairs
                }

        candidate = _ephemeral_candidate_from_parsed(parsed, cv_text)
        filters = RecommendationFilters(
            location=location,
            salary_min=salary_min,
            salary_max=salary_max,
            competence_category=[competence_category] if competence_category else None,
            # Ephemeral candidate (no DB row) → no conflicts to annotate;
            # hard exclusions are candidate-bound and enforced in the filter
            # service itself for persisted candidates (M2 PR1 fail-closed).
            industry_blocklist=False,
        )
        filtered, _stats = await apply_user_filters(candidate, jobs, filters, db)

        breakdowns = await rank_jobs_for_candidate(
            candidate,
            [fj.job for fj in filtered],
            db,
            similarity_map=similarity_map,
        )

        warning_by_job = {fj.job.id: fj.warning for fj in filtered}

        matches = []
        for b in breakdowns:
            if b.total < threshold:
                continue
            j = next((x.job for x in filtered if x.job.id == b.job_id), None)
            if not j:
                continue
            matches.append(
                {
                    "job": _shape_job(j),
                    "total_score": round(b.total, 1),
                    "breakdown": b.as_dict(),
                    "warning": warning_by_job.get(j.id),
                }
            )
            if len(matches) >= top_k:
                break

        return {
            "parsed_summary": _shape_parsed_summary(parsed),
            "matches": matches,
            "search_type": (
                "unavailable"
                if semantic_unavailable
                else ("semantic" if emb_ok else "fallback")
            ),
            "meta": {
                "mode": "unavailable" if semantic_unavailable else "semantic",
                "degraded": semantic_unavailable,
                "reason": "semantic_unavailable" if semantic_unavailable else None,
            },
        }
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                logger.warning("[cv-upload-preview] failed to unlink %s", tmp_path)
