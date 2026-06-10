"""NEXUS orchestrator for the standalone CV generator module.

Pulls candidate CV + champion profile + screening notes/transcripts from the
NEXUS database, calls the ported Claude pipeline and returns the generated
DOCX bytes. Used by ``/api/cv-generator/generate`` and not intended for direct
HTTP exposure — keep the router thin.

Concurrency contract: the Claude call + text extraction + DOCX render are
synchronous and slow (30-60 s). All DB access happens in the async part of
:func:`generate_cv_for_candidate`; the sync pipeline is then executed via
``run_in_threadpool`` so the FastAPI event loop is never blocked.
"""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, or_, select
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
    CVGeneratorTruncatedError,
    analyze_with_ai,
)
from app.services.cv_generator_b2b.champion_builder import (
    ChampionProfileForPrompt,
    build_champion_section,
    build_screening_notes_section,
    from_nexus_job,
    parse_champion_from_docx_bytes,
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

# Calls have no job_id — scope transcripts to the recruitment by time window:
# anything recorded since shortly before the candidate entered this job's
# pipeline counts as context for this recruitment.
_CALL_WINDOW_BEFORE_PIPELINE = timedelta(days=30)


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
        - 'invalid_input'         → 400
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class UploadGenerationInput:
    """Inputs for the manual-upload (Old) generation mode.

    Mirrors the request body of external CV-Generator ``POST /api/v1/generate``:
    a CV file (required), optional champion DOCX, optional screening notes,
    language and blind toggle. No DB access — orchestrator stays sync.
    """

    cv_bytes: bytes
    cv_filename: str
    language: Language = "pl"
    blind_cv: bool = False
    screening_notes: str = ""
    champion_bytes: bytes | None = None
    champion_filename: str | None = None


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
    has_cv: bool

    @property
    def ready(self) -> bool:
        return self.has_champion and self.has_notes and self.has_cv


# ── Helpers ────────────────────────────────────────────────────────────────


# Letters NFKD cannot decompose to ASCII — transliterate manually so
# "Łukasz" → "Lukasz" instead of "ukasz".
_TRANSLIT = str.maketrans({"ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ø": "o", "Ø": "O"})


def _sanitize_for_filename(name: str) -> str:
    """Transliterate + strip diacritics + replace non-alphanumerics."""
    name = name.translate(_TRANSLIT)
    nkfd = unicodedata.normalize("NFKD", name)
    ascii_str = "".join(ch for ch in nkfd if not unicodedata.combining(ch))
    ascii_str = re.sub(r"\s+", "_", ascii_str)
    ascii_str = re.sub(r"[^A-Za-z0-9._-]", "_", ascii_str)
    return ascii_str.strip("_") or "kandydat"


def _champion_present(job: Job | None) -> bool:
    if job is None:
        return False
    if job.must_skills or job.nice_skills:
        return True
    cp = job.champion_profile or {}
    proj = cp.get("project_context") or {}
    if any(
        str(proj.get(k) or "").strip()
        for k in ("about", "responsibilities", "selling_points")
    ):
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


# CV documents the pipeline can actually read. ``.doc`` (Word 97-2003) is
# rejected with a clear message — python-docx cannot parse it and the old
# behaviour was a raw 500.
_SUPPORTED_CV_DOC_PATTERNS = ("%.pdf", "%.docx")


def _supported_cv_doc_filter() -> Any:
    return or_(
        *(
            func.lower(CandidateDocument.filename).like(pat)
            for pat in _SUPPORTED_CV_DOC_PATTERNS
        )
    )


# ── Claude response normalization ─────────────────────────────────────────


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(x).strip() for x in value if x is not None and str(x).strip()]


def _normalize_candidate_data(data: Any, fallback_name: str | None) -> dict[str, Any]:
    """Coerce the Claude JSON into the exact shape the DOCX renderer needs.

    The renderer indexes hard keys (``edu["dates"]``, ``job["company"]`` …) —
    a missing key in an otherwise fine response used to surface as a raw 500.
    Defaults are injected here so render never KeyErrors.
    """
    if not isinstance(data, dict):
        raise StandaloneGenerationError(
            code="ai_failed",
            message=(
                "Claude zwrócił JSON o niepoprawnej strukturze "
                f"(oczekiwano obiektu, otrzymano {type(data).__name__})."
            ),
        )

    out: dict[str, Any] = {}
    out["name"] = str(data.get("name") or fallback_name or "Kandydat").strip()
    out["first_name"] = str(data.get("first_name") or "").strip()
    out["position"] = str(data.get("position") or "").strip()
    out["why_points"] = _str_list(data.get("why_points"))

    education: list[dict[str, str]] = []
    for edu in data.get("education") or []:
        if not isinstance(edu, dict):
            continue
        education.append(
            {
                "dates": str(edu.get("dates") or "").strip(),
                "institution": str(edu.get("institution") or "").strip(),
                "degree": str(edu.get("degree") or "").strip(),
                "location": str(edu.get("location") or "").strip(),
            }
        )
    out["education"] = [e for e in education if e["institution"] or e["degree"]]

    skills: list[dict[str, str]] = []
    for cat in data.get("skills") or []:
        if isinstance(cat, dict):
            label = str(cat.get("label") or "").strip()
            content = str(cat.get("content") or "").strip()
        else:
            label, content = "", str(cat).strip()
        if content:
            skills.append({"label": label, "content": content})
    out["skills"] = skills

    out["certifications"] = _str_list(data.get("certifications"))
    out["languages"] = _str_list(data.get("languages"))

    experience: list[dict[str, Any]] = []
    for job in data.get("experience") or []:
        if not isinstance(job, dict):
            continue
        experience.append(
            {
                "dates": str(job.get("dates") or "").strip(),
                "company": str(job.get("company") or "").strip(),
                "industry": str(job.get("industry") or "IT").strip(),
                "position": str(job.get("position") or "").strip(),
                "responsibilities": _str_list(job.get("responsibilities")),
                "technologies": _str_list(job.get("technologies")),
            }
        )
    out["experience"] = [
        j for j in experience if j["company"] or j["position"] or j["responsibilities"]
    ]

    out["warnings"] = _str_list(data.get("warnings"))
    return out


# ── Anti-fabrication guard ─────────────────────────────────────────────────


def _norm_for_guard(text: str) -> str:
    text = text.translate(_TRANSLIT)
    nkfd = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in nkfd if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text.lower())


_GUARD_TOKEN_RE = re.compile(r"[^a-z0-9+#]+")
_GUARD_STOP = {
    "the",
    "and",
    "for",
    "with",
    "certified",
    "certificate",
    "certification",
    "certyfikat",
    "developer",
    "engineer",
    "professional",
    "associate",
    "foundation",
    "podstawy",
}


def _term_in_source(term: str, source_norm: str) -> bool:
    t = _norm_for_guard(term).strip()
    if not t:
        return True
    if t in source_norm:
        return True
    tokens = [
        w for w in _GUARD_TOKEN_RE.split(t) if len(w) >= 3 and w not in _GUARD_STOP
    ]
    if not tokens:
        # Too short/generic to judge reliably — don't cry wolf.
        return True
    return any(w in source_norm for w in tokens)


def _fabrication_warnings(
    candidate_data: dict[str, Any], source_text: str, language: str
) -> list[str]:
    """Deterministic no-lying check: every technology and certification in the
    output must be traceable to the CV text or the screening notes.

    The prompt already forbids fabrication; this is the seatbelt. Findings are
    surfaced as warnings (the recruiter verifies), generation is not blocked.
    """
    source_norm = _norm_for_guard(source_text)
    issues: list[str] = []

    for job in candidate_data.get("experience", []):
        role = job.get("position") or job.get("company") or "?"
        for tech in job.get("technologies", []):
            if not _term_in_source(tech, source_norm):
                if language == "en":
                    issues.append(
                        f"VERIFY: technology '{tech}' ({role}) not found in the CV or notes"
                    )
                else:
                    issues.append(
                        f"WERYFIKUJ: technologia '{tech}' ({role}) nie występuje w CV ani notatkach"
                    )

    for cert in candidate_data.get("certifications", []):
        if not _term_in_source(cert, source_norm):
            if language == "en":
                issues.append(
                    f"VERIFY: certification '{cert}' not found in the CV or notes"
                )
            else:
                issues.append(
                    f"WERYFIKUJ: certyfikat '{cert}' nie występuje w CV ani notatkach"
                )

    if len(issues) > 8:
        more = len(issues) - 8
        issues = issues[:8]
        issues.append(
            f"… i {more} kolejnych pozycji do weryfikacji"
            if language != "en"
            else f"… and {more} more items to verify"
        )
    return issues


# ── Shared Claude → DOCX pipeline (sync; run via threadpool) ───────────────


def _run_generation_pipeline(
    *,
    cv_bytes: bytes,
    cv_filename: str,
    champion_dto: ChampionProfileForPrompt | None,
    screening_notes_text: str,
    language: Language,
    blind_cv: bool,
    request_id: str,
    fallback_name: str | None,
    started_at: float,
) -> GenerationResult:
    """Extract CV text, call Claude and render the DOCX.

    Fully synchronous — wrap in ``run_in_threadpool`` from async callers.
    Used by both the DB-backed (New) and the manual-upload (Old) modes; the
    modes differ only in how the inputs are sourced.
    """
    # ── 1. Extract CV text ───────────────────────────────────────────────
    try:
        cv_text = extract_text_from_file(cv_bytes, cv_filename or "cv.pdf")
    except CVTextExtractionError as err:
        raise StandaloneGenerationError(
            code="extraction_failed",
            message=f"Nie udało się odczytać tekstu z CV: {err}",
        ) from err

    # ── 2. Build prompt (system = instructions, user = data in tags) ─────
    system_prompt = get_prompt(language, blind_cv)

    user_parts = [f"<cv>\n{cv_text.strip()}\n</cv>"]
    screening_section = build_screening_notes_section(screening_notes_text, language)
    if screening_section.strip():
        user_parts.append(
            f"<screening_notes>\n{screening_section.strip()}\n</screening_notes>"
        )
    champion_section = (
        build_champion_section(champion_dto, language) if champion_dto else ""
    )
    if champion_section.strip():
        user_parts.append(
            f"<champion_profile>\n{champion_section.strip()}\n</champion_profile>"
        )
    user_content = "\n\n".join(user_parts)

    logger.info(
        "[cv_b2b][%s] Built prompt: cv_chars=%d, notes_chars=%d, champion_chars=%d, "
        "lang=%s, blind=%s",
        request_id,
        len(cv_text),
        len(screening_notes_text),
        len(champion_section),
        language,
        blind_cv,
    )

    # ── 3. Claude call ───────────────────────────────────────────────────
    try:
        response_text = analyze_with_ai(user_content, request_id, system=system_prompt)
    except CVGeneratorTruncatedError as err:
        raise StandaloneGenerationError(code="ai_failed", message=str(err)) from err
    except CVGeneratorAIError as err:
        raise StandaloneGenerationError(
            code="ai_failed",
            message=f"Claude wywołanie nieudane: {err}",
        ) from err

    cleaned = response_text.strip()
    cleaned = re.sub(r"```json\n?", "", cleaned)
    cleaned = re.sub(r"```\n?", "", cleaned).strip()

    try:
        raw_data = json.loads(cleaned)
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

    candidate_data = _normalize_candidate_data(raw_data, fallback_name)
    candidate_data["language"] = language
    candidate_data["blind_cv"] = blind_cv

    # Bold everything the client asked for — must-have AND nice-to-have.
    if champion_dto:
        highlight = [
            kw.strip()
            for kw in (champion_dto.must_have + champion_dto.nice_to_have)
            if kw and kw.strip()
        ]
        if highlight:
            candidate_data["highlight_keywords"] = highlight

    # ── 4. Anti-fabrication seatbelt ─────────────────────────────────────
    source_text = f"{cv_text}\n{screening_notes_text}"
    guard_warnings = _fabrication_warnings(candidate_data, source_text, language)

    # ── 5. Render DOCX ───────────────────────────────────────────────────
    try:
        docx_bytes = render_cv_to_bytes(candidate_data, TEMPLATE_PATH)
    except Exception as err:  # noqa: BLE001 — python-docx raises various types
        logger.exception("[cv_b2b][%s] DOCX render failed: %s", request_id, err)
        raise StandaloneGenerationError(
            code="render_failed",
            message=f"Renderowanie DOCX nie powiodło się: {err}",
        ) from err

    candidate_name = str(candidate_data.get("name") or fallback_name or "Kandydat")
    sanitized_name = _sanitize_for_filename(candidate_name)
    filename = f"CV_B2B_{sanitized_name}.docx"

    duration_ms = int((time.time() - started_at) * 1000)
    warnings = [str(w) for w in candidate_data.get("warnings") or [] if w]
    warnings.extend(guard_warnings)

    logger.info(
        "[cv_b2b][%s] OK candidate=%s lang=%s blind=%s warnings=%d "
        "(guard=%d) duration_ms=%d",
        request_id,
        candidate_name,
        language,
        blind_cv,
        len(warnings),
        len(guard_warnings),
        duration_ms,
    )

    return GenerationResult(
        candidate_name=candidate_name,
        filename=filename,
        docx_bytes=docx_bytes,
        warnings=warnings,
        processing_time_ms=duration_ms,
    )


# ── Query helpers ──────────────────────────────────────────────────────────


async def _candidate_has_supported_cv(db: AsyncSession, candidate_id: int) -> bool:
    doc_id = await db.scalar(
        select(CandidateDocument.id)
        .where(
            CandidateDocument.candidate_id == candidate_id,
            _supported_cv_doc_filter(),
        )
        .limit(1)
    )
    return doc_id is not None


async def list_recruitments_with_readiness(
    db: AsyncSession, candidate_id: int
) -> list[RecruitmentReadiness]:
    """Return the candidate's recruitment processes annotated with readiness
    flags (champion / notes / CV present).

    Deduplicated per job: the pipeline history table holds one row per stage
    transition, but champion + notes context is per job, so only the most
    recent stage of each job is returned.
    """

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

    # Most recent stage per job (stages already sorted desc by moved_at).
    latest_per_job: dict[int, CandidateStage] = {}
    for stage in stages:
        latest_per_job.setdefault(stage.job_id, stage)

    has_cv = await _candidate_has_supported_cv(db, candidate_id)

    # Earliest pipeline entry per job — the call-window anchor.
    first_moved_rows = (
        await db.execute(
            select(CandidateStage.job_id, func.min(CandidateStage.moved_at))
            .where(CandidateStage.candidate_id == candidate_id)
            .group_by(CandidateStage.job_id)
        )
    ).all()
    first_moved_per_job = {job_id: moved_at for job_id, moved_at in first_moved_rows}

    call_times = (
        await db.scalars(
            select(Call.created_at).where(
                Call.candidate_id == candidate_id,
                (Call.transcript.isnot(None)) | (Call.summary.isnot(None)),
            )
        )
    ).all()

    note_job_ids = set(
        (
            await db.scalars(
                select(Note.job_id).where(
                    Note.candidate_id == candidate_id,
                    Note.content.isnot(None),
                )
            )
        ).all()
    )
    has_general_note = None in note_job_ids

    screening_job_ids = set(
        (
            await db.scalars(
                select(ScreeningNote.job_id).where(
                    ScreeningNote.candidate_id == candidate_id
                )
            )
        ).all()
    )

    result: list[RecruitmentReadiness] = []
    for stage in latest_per_job.values():
        job = stage.job
        has_champion = _champion_present(job)

        first_moved = first_moved_per_job.get(stage.job_id)
        window_start = (
            first_moved - _CALL_WINDOW_BEFORE_PIPELINE if first_moved else None
        )
        has_call_in_window = any(
            t is not None and (window_start is None or t >= window_start)
            for t in call_times
        )

        has_notes = (
            stage.job_id in screening_job_ids
            or stage.job_id in note_job_ids
            or has_general_note
            or has_call_in_window
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
                has_cv=has_cv,
            )
        )

    # `latest_per_job` preserves the moved_at-desc query order, so the most
    # recently active recruitments come first already.
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
        .where(
            CandidateDocument.candidate_id == candidate_id,
            _supported_cv_doc_filter(),
        )
        .order_by(
            CandidateDocument.is_primary.desc(), CandidateDocument.uploaded_at.desc()
        )
        .limit(1)
    )
    cv_doc = (await db.scalars(cv_doc_q)).first()
    if cv_doc is None:
        any_doc_id = await db.scalar(
            select(CandidateDocument.id)
            .where(CandidateDocument.candidate_id == candidate_id)
            .limit(1)
        )
        if any_doc_id is not None:
            raise StandaloneGenerationError(
                code="no_cv_file",
                message=(
                    "CV kandydata jest w nieobsługiwanym formacie (np. .doc). "
                    "Wgraj wersję PDF lub DOCX."
                ),
            )
        raise StandaloneGenerationError(
            code="no_cv_file",
            message="Konsultant nie ma wgranego CV w systemie.",
        )

    if cv_doc.storage_key:
        try:
            # boto3 is sync — keep the event loop free during the download.
            cv_bytes = await run_in_threadpool(
                object_storage.download_cv, cv_doc.storage_key
            )
        except Exception as err:  # noqa: BLE001
            logger.exception(
                "[cv_b2b][%s] Object storage download failed: %s", request_id, err
            )
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

    # ── 3. Screening notes — scoped to THIS recruitment ──────────────────
    # Notes from other clients' processes (rates, red flags, client names)
    # must never leak into a CV generated for this client.
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
        .where(
            Note.candidate_id == candidate_id,
            or_(Note.job_id == job.id, Note.job_id.is_(None)),
        )
        .order_by(Note.created_at.desc())
        .limit(20)
    )
    notes = (await db.scalars(notes_q)).all()
    for note in notes:
        if note.content and note.content.strip():
            screening_parts.append(f"[Notatka kandydata]\n{note.content.strip()}")

    first_moved = await db.scalar(
        select(func.min(CandidateStage.moved_at)).where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job.id,
        )
    )
    calls_q = (
        select(Call)
        .where(
            Call.candidate_id == candidate_id,
            (Call.transcript.isnot(None)) | (Call.summary.isnot(None)),
        )
        .order_by(Call.created_at.desc())
        .limit(5)
    )
    if first_moved is not None:
        calls_q = calls_q.where(
            Call.created_at >= first_moved - _CALL_WINDOW_BEFORE_PIPELINE
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

    # ── 4-6. Sync pipeline in a worker thread — event loop stays free ────
    fallback_name = f"{candidate.name} {candidate.lastname}".strip() or None
    return await run_in_threadpool(
        lambda: _run_generation_pipeline(
            cv_bytes=cv_bytes,
            cv_filename=cv_doc.filename or "cv.pdf",
            champion_dto=champion_dto,
            screening_notes_text=screening_notes_text,
            language=language,
            blind_cv=blind_cv,
            request_id=request_id,
            fallback_name=fallback_name,
            started_at=started_at,
        )
    )


# ── Old mode: manual upload (1:1 with external CV-Generator) ──────────────


_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB, matches external API.md
_ALLOWED_CV_EXT = {".pdf", ".docx"}
_ALLOWED_CHAMPION_EXT = {".docx"}


def _validate_upload(
    data: bytes, filename: str, *, allowed_ext: set[str], label: str
) -> None:
    if not data:
        raise StandaloneGenerationError(
            code="invalid_input",
            message=f"{label}: plik jest pusty.",
        )
    if len(data) > _MAX_UPLOAD_BYTES:
        raise StandaloneGenerationError(
            code="invalid_input",
            message=(
                f"{label}: plik za duży ({len(data) // 1024 // 1024} MB). "
                f"Maksymalny rozmiar to {_MAX_UPLOAD_BYTES // 1024 // 1024} MB."
            ),
        )
    ext = Path(filename).suffix.lower()
    if ext == ".doc":
        raise StandaloneGenerationError(
            code="invalid_input",
            message=(
                f"{label}: format .doc (Word 97-2003) nie jest obsługiwany. "
                "Zapisz plik jako .docx lub PDF i wgraj ponownie."
            ),
        )
    if ext not in allowed_ext:
        allowed_str = ", ".join(sorted(allowed_ext))
        raise StandaloneGenerationError(
            code="invalid_input",
            message=f"{label}: nieobsługiwane rozszerzenie '{ext}'. Dozwolone: {allowed_str}",
        )


def generate_cv_from_uploads(payload: UploadGenerationInput) -> GenerationResult:
    """Generate the B2B CV from user-uploaded files (Old mode).

    1:1 with the external CV-Generator ``POST /api/v1/generate`` flow, sharing
    :func:`_run_generation_pipeline` with the DB-backed mode.

    Synchronous on purpose — touches no DB. Wrap in ``run_in_threadpool`` at
    the route layer so FastAPI doesn't block the event loop on the Claude
    call.
    """
    request_id = f"cvgen_upload_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    started_at = time.time()

    _validate_upload(
        payload.cv_bytes,
        payload.cv_filename,
        allowed_ext=_ALLOWED_CV_EXT,
        label="CV",
    )

    champion_dto: ChampionProfileForPrompt | None = None
    if payload.champion_bytes is not None:
        if not payload.champion_filename:
            raise StandaloneGenerationError(
                code="invalid_input",
                message="Profil Championa: filename jest wymagany gdy plik przesłany.",
            )
        _validate_upload(
            payload.champion_bytes,
            payload.champion_filename,
            allowed_ext=_ALLOWED_CHAMPION_EXT,
            label="Profil Championa",
        )
        try:
            champion_dto = parse_champion_from_docx_bytes(
                payload.champion_bytes, payload.champion_filename
            )
        except CVTextExtractionError as err:
            raise StandaloneGenerationError(
                code="extraction_failed",
                message=f"Nie udało się odczytać Profilu Championa: {err}",
            ) from err

    return _run_generation_pipeline(
        cv_bytes=payload.cv_bytes,
        cv_filename=payload.cv_filename,
        champion_dto=champion_dto,
        screening_notes_text=payload.screening_notes or "",
        language=payload.language,
        blind_cv=payload.blind_cv,
        request_id=request_id,
        fallback_name=None,
        started_at=started_at,
    )


__all__ = [
    "StandaloneGenerationError",
    "GenerationResult",
    "RecruitmentReadiness",
    "UploadGenerationInput",
    "generate_cv_for_candidate",
    "generate_cv_from_uploads",
    "list_recruitments_with_readiness",
]
