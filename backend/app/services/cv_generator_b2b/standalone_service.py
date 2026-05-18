"""NEXUS orchestrator for the standalone CV generator module.

Pulls candidate CV + champion profile + screening notes/transcripts from the
NEXUS database, calls the ported Claude pipeline and returns the generated
DOCX bytes. Used by ``/api/cv-generator/generate`` and not intended for direct
HTTP exposure — keep the router thin.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.call import Call
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument
from app.models.job import Job
from app.models.note import Note
from app.models.recruitment_pipeline import CandidateStage
from app.models.screening_note import ScreeningNote
from app.services import object_storage
from app.services.cv_generator_b2b.ai_client import (
    CVGeneratorAIError,
    analyze_with_ai,
)
from app.services.cv_generator_b2b.champion_builder import (
    build_champion_section,
    build_screening_notes_section,
    from_nexus_job,
)
from app.services.cv_generator_b2b.docx_renderer import render_cv_to_bytes
from app.services.cv_generator_b2b.prompts import get_prompt
from app.services.cv_generator_b2b.text_extractor import (
    CVTextExtractionError,
    extract_text_from_file,
)

logger = logging.getLogger(__name__)


TEMPLATE_PATH = str(
    Path(__file__).resolve().parents[2] / "templates" / "cv" / "szablon_firmowy.docx"
)


Language = Literal["pl", "en"]


class StandaloneGenerationError(RuntimeError):
    """Raised on missing inputs or unrecoverable generation failures.

    The ``code`` attribute is used by the API router to map to HTTP statuses:
        - 'candidate_not_found'   → 404
        - 'stage_not_found'       → 404
        - 'no_cv_file'            → 422
        - 'no_champion'           → 422
        - 'no_notes'              → 422
        - 'extraction_failed'     → 502
        - 'ai_failed'             → 502
        - 'render_failed'         → 500
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class GenerationResult:
    candidate_name: str
    filename: str
    docx_bytes: bytes
    warnings: list[str]
    processing_time_ms: int


@dataclass(frozen=True)
class RecruitmentReadiness:
    stage_id: int
    job_id: int
    job_title: str
    stage: str
    has_champion: bool
    has_notes: bool

    @property
    def ready(self) -> bool:
        return self.has_champion and self.has_notes


# ── Helpers ────────────────────────────────────────────────────────────────


def _sanitize_for_filename(name: str) -> str:
    """Strip diacritics + replace non-alphanumerics with underscores."""
    import unicodedata

    nkfd = unicodedata.normalize("NFKD", name)
    ascii_str = "".join(ch for ch in nkfd if not unicodedata.combining(ch))
    ascii_str = re.sub(r"\s+", "_", ascii_str)
    ascii_str = re.sub(r"[^A-Za-z0-9._-]", "_", ascii_str)
    return ascii_str.strip("_") or "kandydat"


def _champion_present(job: Job | None) -> bool:
    if job is None:
        return False
    if (job.must_skills or job.nice_skills):
        return True
    cp = job.champion_profile or {}
    proj = cp.get("project_context") or {}
    if any(str(proj.get(k) or "").strip() for k in ("about", "responsibilities", "selling_points")):
        return True
    if cp.get("screening_questions"):
        return True
    if str(cp.get("internal_consultant_insight") or "").strip():
        return True
    if str(cp.get("historical_client_questions") or "").strip():
        return True
    return False


def _format_screening_note(note: ScreeningNote) -> str:
    parts: list[str] = []
    if note.red_flags:
        parts.append(f"Red flags: {note.red_flags.strip()}")
    if note.personality_notes:
        parts.append(f"Osobowość / soft skills: {note.personality_notes.strip()}")
    if note.closing_strategy:
        parts.append(f"Strategia closingu: {note.closing_strategy.strip()}")
    if note.salary_expectation is not None:
        cur = note.salary_currency or "PLN"
        parts.append(f"Oczekiwana stawka: {note.salary_expectation} {cur}")
    if note.verified_skills:
        try:
            skill_lines: list[str] = []
            for s in note.verified_skills:
                if isinstance(s, dict):
                    name = s.get("skill") or s.get("name") or ""
                    level = s.get("level") or ""
                    extra = s.get("notes") or ""
                    line = name
                    if level:
                        line += f" ({level})"
                    if extra:
                        line += f" — {extra}"
                    skill_lines.append(line.strip())
            if skill_lines:
                parts.append("Zweryfikowane umiejętności: " + ", ".join(skill_lines))
        except Exception:  # noqa: BLE001 — verified_skills shape is JSONB-free
            pass
    if note.overall_impression is not None:
        parts.append(f"Ogólne wrażenie (1-5): {note.overall_impression}")
    return "\n".join(parts)


# ── Query helpers ──────────────────────────────────────────────────────────


async def list_recruitments_with_readiness(
    db: AsyncSession, candidate_id: int
) -> list[RecruitmentReadiness]:
    """Return all of the candidate's recruitment processes annotated with
    champion / notes readiness flags."""

    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        raise StandaloneGenerationError(
            code="candidate_not_found",
            message=f"Candidate {candidate_id} does not exist",
        )

    stages_q = (
        select(CandidateStage)
        .options(selectinload(CandidateStage.job))
        .where(CandidateStage.candidate_id == candidate_id)
        .order_by(CandidateStage.moved_at.desc())
    )
    stages = (await db.scalars(stages_q)).all()

    if not stages:
        return []

    candidate_has_transcript_q = select(Call.id).where(
        Call.candidate_id == candidate_id,
        (Call.transcript.isnot(None)) | (Call.summary.isnot(None)),
    ).limit(1)
    candidate_has_transcript = (await db.scalar(candidate_has_transcript_q)) is not None

    candidate_has_note_q = select(Note.id).where(Note.candidate_id == candidate_id).limit(1)
    candidate_has_note = (await db.scalar(candidate_has_note_q)) is not None

    result: list[RecruitmentReadiness] = []
    for stage in stages:
        job = stage.job
        has_champion = _champion_present(job)

        sn_q = (
            select(ScreeningNote.id)
            .where(
                ScreeningNote.candidate_id == candidate_id,
                ScreeningNote.job_id == stage.job_id,
            )
            .limit(1)
        )
        has_screening_for_job = (await db.scalar(sn_q)) is not None

        has_notes = (
            has_screening_for_job
            or candidate_has_transcript
            or candidate_has_note
            or bool(stage.notes and stage.notes.strip())
        )

        result.append(
            RecruitmentReadiness(
                stage_id=stage.id,
                job_id=stage.job_id,
                job_title=job.title if job else f"Job #{stage.job_id}",
                stage=stage.stage.value if stage.stage else "",
                has_champion=has_champion,
                has_notes=has_notes,
            )
        )

    return result


# ── Main entrypoint ────────────────────────────────────────────────────────


async def generate_cv_for_candidate(
    db: AsyncSession,
    *,
    candidate_id: int,
    stage_id: int,
    language: Language = "pl",
    blind_cv: bool = False,
) -> GenerationResult:
    """Generate the B2B-formatted CV for ``candidate_id`` using the champion
    + notes context tied to the given ``stage_id``.

    Validates the readiness contract documented in
    :class:`StandaloneGenerationError`. Raises with a specific ``code`` so
    the API layer can map to the right HTTP status.
    """
    request_id = f"cvgen_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    started_at = time.time()

    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        raise StandaloneGenerationError(
            code="candidate_not_found",
            message=f"Candidate {candidate_id} does not exist",
        )

    stage_q = (
        select(CandidateStage)
        .options(selectinload(CandidateStage.job))
        .where(CandidateStage.id == stage_id)
    )
    stage = (await db.scalars(stage_q)).first()
    if stage is None or stage.candidate_id != candidate_id:
        raise StandaloneGenerationError(
            code="stage_not_found",
            message=f"Stage {stage_id} not found for candidate {candidate_id}",
        )

    job = stage.job
    if job is None:
        raise StandaloneGenerationError(
            code="stage_not_found",
            message=f"Stage {stage_id} has no linked job",
        )

    # ── 1. CV file ────────────────────────────────────────────────────────
    cv_doc_q = (
        select(CandidateDocument)
        .where(CandidateDocument.candidate_id == candidate_id)
        .order_by(CandidateDocument.is_primary.desc(), CandidateDocument.uploaded_at.desc())
        .limit(1)
    )
    cv_doc = (await db.scalars(cv_doc_q)).first()
    if cv_doc is None:
        raise StandaloneGenerationError(
            code="no_cv_file",
            message="Konsultant nie ma wgranego CV w systemie.",
        )

    if cv_doc.storage_key:
        try:
            cv_bytes = object_storage.download_cv(cv_doc.storage_key)
        except Exception as err:  # noqa: BLE001
            logger.exception("[cv_b2b][%s] Object storage download failed: %s", request_id, err)
            raise StandaloneGenerationError(
                code="extraction_failed",
                message=f"Nie udało się pobrać CV z Object Storage: {err}",
            ) from err
    elif cv_doc.file_content:
        cv_bytes = bytes(cv_doc.file_content)
    else:
        raise StandaloneGenerationError(
            code="no_cv_file",
            message="CV kandydata jest puste (brak storage_key i file_content).",
        )

    # ── 2. Champion ───────────────────────────────────────────────────────
    if not _champion_present(job):
        raise StandaloneGenerationError(
            code="no_champion",
            message=(
                "Profil Championa dla tej rekrutacji jest pusty. Uzupełnij "
                "must-have / nice-to-have / kontekst projektu przed generacją CV."
            ),
        )

    champion_dto = from_nexus_job(
        must_skills=job.must_skills,
        nice_skills=job.nice_skills,
        champion_profile=job.champion_profile,
        requirements=job.requirements,
    )

    # ── 3. Screening notes ────────────────────────────────────────────────
    screening_parts: list[str] = []

    sn_q = (
        select(ScreeningNote)
        .where(
            ScreeningNote.candidate_id == candidate_id,
            ScreeningNote.job_id == job.id,
        )
        .order_by(ScreeningNote.created_at.desc())
    )
    screening_notes = (await db.scalars(sn_q)).all()
    for sn in screening_notes:
        text = _format_screening_note(sn)
        if text:
            screening_parts.append(f"[Notatka ze screeningu]\n{text}")

    if stage.notes and stage.notes.strip():
        screening_parts.append(f"[Notatka z procesu]\n{stage.notes.strip()}")

    notes_q = (
        select(Note)
        .where(Note.candidate_id == candidate_id)
        .order_by(Note.created_at.desc())
        .limit(20)
    )
    notes = (await db.scalars(notes_q)).all()
    for note in notes:
        if note.content and note.content.strip():
            screening_parts.append(f"[Notatka kandydata]\n{note.content.strip()}")

    calls_q = (
        select(Call)
        .where(
            Call.candidate_id == candidate_id,
            (Call.transcript.isnot(None)) | (Call.summary.isnot(None)),
        )
        .order_by(Call.created_at.desc())
        .limit(5)
    )
    calls = (await db.scalars(calls_q)).all()
    for call in calls:
        # Prefer transcript; fall back to AI-generated summary.
        body = (call.transcript or call.summary or "").strip()
        if body:
            screening_parts.append(f"[Transkrypt rozmowy]\n{body}")

    if not screening_parts:
        raise StandaloneGenerationError(
            code="no_notes",
            message=(
                "Brak notatek z rozmowy dla tej rekrutacji. Wymagana jest "
                "co najmniej jedna: notatka ze screeningu, transkrypt rozmowy "
                "albo notatka procesu."
            ),
        )

    screening_notes_text = "\n\n".join(screening_parts)

    # ── 4. Build prompt ──────────────────────────────────────────────────
    try:
        cv_text = extract_text_from_file(cv_bytes, cv_doc.filename or "cv.pdf")
    except CVTextExtractionError as err:
        raise StandaloneGenerationError(
            code="extraction_failed",
            message=f"Nie udało się odczytać tekstu z CV: {err}",
        ) from err

    base_prompt = get_prompt(language)
    screening_section = build_screening_notes_section(screening_notes_text, language)
    champion_section = build_champion_section(champion_dto, language)

    full_content = (
        f"{base_prompt}\n\nCV do analizy:\n\n{cv_text}{screening_section}{champion_section}"
    )

    logger.info(
        "[cv_b2b][%s] Built prompt: cv_chars=%d, notes_chars=%d, champion_chars=%d, lang=%s, blind=%s",
        request_id,
        len(cv_text),
        len(screening_notes_text),
        len(champion_section),
        language,
        blind_cv,
    )

    # ── 5. Claude call ───────────────────────────────────────────────────
    try:
        response_text = analyze_with_ai(full_content, request_id)
    except CVGeneratorAIError as err:
        raise StandaloneGenerationError(
            code="ai_failed",
            message=f"Claude wywołanie nieudane: {err}",
        ) from err

    cleaned = response_text.strip()
    cleaned = re.sub(r"```json\n?", "", cleaned)
    cleaned = re.sub(r"```\n?", "", cleaned).strip()

    try:
        candidate_data = json.loads(cleaned)
    except json.JSONDecodeError as err:
        logger.error(
            "[cv_b2b][%s] Claude returned non-JSON (first 200 chars): %r",
            request_id,
            cleaned[:200],
        )
        raise StandaloneGenerationError(
            code="ai_failed",
            message=f"Claude zwrócił niepoprawny JSON: {err}",
        ) from err

    candidate_data["language"] = language
    candidate_data["blind_cv"] = blind_cv

    if champion_dto.must_have:
        candidate_data["highlight_keywords"] = [
            kw for kw in champion_dto.must_have if kw and kw.strip()
        ]

    # ── 6. Render DOCX ───────────────────────────────────────────────────
    try:
        docx_bytes = render_cv_to_bytes(candidate_data, TEMPLATE_PATH)
    except Exception as err:  # noqa: BLE001 — python-docx raises various types
        logger.exception("[cv_b2b][%s] DOCX render failed: %s", request_id, err)
        raise StandaloneGenerationError(
            code="render_failed",
            message=f"Renderowanie DOCX nie powiodło się: {err}",
        ) from err

    candidate_name = str(candidate_data.get("name") or candidate.name or "Kandydat")
    sanitized_name = _sanitize_for_filename(candidate_name)
    filename = f"CV_B2B_{sanitized_name}.docx"

    duration_ms = int((time.time() - started_at) * 1000)
    warnings_raw = candidate_data.get("warnings") or []
    warnings = [str(w) for w in warnings_raw if w]

    logger.info(
        "[cv_b2b][%s] OK candidate=%s lang=%s blind=%s warnings=%d duration_ms=%d",
        request_id,
        candidate_name,
        language,
        blind_cv,
        len(warnings),
        duration_ms,
    )

    return GenerationResult(
        candidate_name=candidate_name,
        filename=filename,
        docx_bytes=docx_bytes,
        warnings=warnings,
        processing_time_ms=duration_ms,
    )


__all__ = [
    "StandaloneGenerationError",
    "GenerationResult",
    "RecruitmentReadiness",
    "generate_cv_for_candidate",
    "list_recruitments_with_readiness",
]
