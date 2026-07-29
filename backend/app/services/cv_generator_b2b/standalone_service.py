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

import copy
import json
import logging
import re
import time
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.call import Call
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument
from app.models.client import Client
from app.models.job import Job
from app.models.note import Note
from app.models.recruitment_pipeline import CandidateStage
from app.models.screening_note import ScreeningNote
from app.services import object_storage
from app.services.cv_generator_b2b.ai_client import (
    CVGeneratorAIError,
    CVGeneratorOverloadedError,
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
from app.services.cv_generator_b2b.docx_renderer import (
    compile_keyword_patterns,
    highlight_spans,
    render_cv_to_bytes,
)
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

# How much presentation work the generator is allowed to do. The axis is
# PRESENTATION, never truth: the anti-fabrication ceiling (prompt rules +
# ``_fabrication_warnings``) is identical in all three modes — a higher mode
# never licenses adding a fact the source does not carry.
#
#   * "basic"    — Przepisanie: facts only, source wording kept, no champion.
#   * "polished" — Redakcja: same facts, cleaner language and terminology,
#                  screening notes may enrich why_points, still no champion.
#   * "tailored" — Pod ofertę: the client's Champion Profile drives ordering,
#                  emphasis and bolding. This is the mode that made CVs read
#                  as "written by AI against the job ad", so it is never the
#                  default and can be capped per client (``Client.cv_content_mode_cap``).
ContentMode = Literal["basic", "polished", "tailored"]

CONTENT_MODES: tuple[str, ...] = ("basic", "polished", "tailored")

#: Deliberately NOT "tailored" — the most-positioned variant must be an
#: explicit choice, never what a recruiter gets by clicking through.
DEFAULT_CONTENT_MODE: ContentMode = "polished"

#: Ordered weakest → strongest positioning; used to apply the per-client cap.
_CONTENT_MODE_RANK: dict[str, int] = {"basic": 0, "polished": 1, "tailored": 2}


def normalize_content_mode(value: Any) -> ContentMode:
    """Coerce free-form input to a known mode, defaulting to the safe middle.

    Unknown values fall back to :data:`DEFAULT_CONTENT_MODE` rather than to
    "tailored": a typo or a stale client must never silently upgrade a CV to
    the most-positioned variant.
    """
    text = str(value or "").strip().lower()
    return text if text in _CONTENT_MODE_RANK else DEFAULT_CONTENT_MODE  # type: ignore[return-value]


def apply_content_mode_cap(requested: Any, cap: Any = None) -> tuple[ContentMode, bool]:
    """Clamp ``requested`` to the client's ceiling.

    Returns ``(effective_mode, was_capped)``. A ``cap`` of ``None`` (the
    default for every client) means "no ceiling" — existing recruitments keep
    working untouched. Setting a cap is what turns a promise made to a client
    ("we stopped positioning CVs against your job ad") into something the
    generator actually enforces, instead of a checkbox a recruiter can undo.
    """
    mode = normalize_content_mode(requested)
    if cap is None:
        return mode, False
    ceiling = normalize_content_mode(cap)
    if _CONTENT_MODE_RANK[mode] <= _CONTENT_MODE_RANK[ceiling]:
        return mode, False
    return ceiling, True


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
        - 'ai_overloaded'         → 503  (transient — Claude pool saturated)
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
    content_mode: ContentMode = DEFAULT_CONTENT_MODE


@dataclass(frozen=True)
class GenerationResult:
    candidate_name: str
    filename: str
    docx_bytes: bytes
    warnings: list[str]
    processing_time_ms: int
    # ``candidate_data`` captured BEFORE render mutates it (blind anonymization),
    # so the DOCX can be re-rendered later from the saved log without re-calling
    # Claude. ``job_id`` is set in New mode (None for manual upload).
    render_payload: dict[str, Any]
    job_id: int | None = None


def rerender_docx_from_payload(render_payload: dict[str, Any]) -> bytes:
    """Re-render a previously generated CV from its saved ``render_payload``.

    Deterministic — no Claude call. Deep-copies because ``render_cv_to_bytes``
    mutates the dict in place for blind anonymization, and the stored payload
    must stay reusable for the next download.
    """
    return render_cv_to_bytes(copy.deepcopy(render_payload), TEMPLATE_PATH)


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


# Letters NFKD cannot decompose to ASCII — transliterate manually so the ASCII
# fallback renders "Łukasz" → "Lukasz" instead of dropping it to "ukasz".
_TRANSLIT = str.maketrans({"ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ø": "o", "Ø": "O"})


def _sanitize_for_filename(name: str) -> str:
    """Sanitize ``name`` into a filename component while **preserving** Polish
    diacritics (ł, ą, ż, ó, …) and other Unicode letters.

    Whitespace collapses to underscores; characters that are neither Unicode
    word characters nor ``.``/``-`` become underscores. The latin-1 constraint
    of HTTP headers is handled separately at the ``Content-Disposition`` layer
    (see :func:`ascii_filename_fallback`), so the file saved on disk keeps the
    candidate's real spelling.
    """
    cleaned = re.sub(r"\s+", "_", name)
    # ``\w`` matches Unicode letters/digits/underscore for ``str`` patterns, so
    # Polish letters survive while punctuation/brackets become underscores.
    cleaned = re.sub(r"[^\w.-]", "_", cleaned)
    return cleaned.strip("_") or "kandydat"


def ascii_filename_fallback(filename: str) -> str:
    """ASCII-fold ``filename`` for the legacy ``filename="…"`` parameter of
    ``Content-Disposition`` — HTTP header values must be latin-1 encodable.

    Modern clients receive the real (possibly Polish) name via the RFC 5987
    ``filename*`` parameter; this is only the fallback for clients that ignore
    it. Transliterates Polish letters, strips diacritics, then replaces anything
    left outside ``[A-Za-z0-9._-]`` with an underscore.
    """
    folded = filename.translate(_TRANSLIT)
    nkfd = unicodedata.normalize("NFKD", folded)
    ascii_str = "".join(ch for ch in nkfd if not unicodedata.combining(ch))
    ascii_str = re.sub(r"[^A-Za-z0-9._-]", "_", ascii_str)
    return ascii_str.strip("_") or "kandydat"


# Characters reserved by common filesystems (path separators, wildcards,
# quotes, angle brackets, pipe, control chars). Everything else — including
# spaces, ``+``/``#`` (e.g. "C++ Developer") and Polish diacritics — survives.
_FILENAME_RESERVED = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _sanitize_filename_part(text: str) -> str:
    """Clean one component of the download filename while **preserving** spaces
    and Polish diacritics.

    Runs of whitespace collapse to a single space; only filesystem-reserved
    characters are dropped. HTTP-header encoding is handled separately at the
    ``Content-Disposition`` layer (:func:`ascii_filename_fallback` + the RFC 5987
    ``filename*`` parameter), so the file saved on disk keeps the real spelling.
    """
    without_reserved = _FILENAME_RESERVED.sub("", text)
    collapsed = re.sub(r"\s+", " ", without_reserved)
    return collapsed.strip(" .")


def _build_download_filename(role_title: str | None, candidate_name: str) -> str:
    """Compose the CV download filename.

    With a recruitment role (Champion Profile → ``Job.title``) the name is
    ``"{role}_{name}.docx"`` (e.g. ``"IT Analyst_Jan Kowalski.docx"``). Without
    one — manual-upload mode or a blank title — it falls back to the legacy
    ``"CV_B2B_{name}.docx"`` shape.
    """
    role_part = _sanitize_filename_part(role_title or "")
    if role_part:
        name_part = _sanitize_filename_part(candidate_name) or "Kandydat"
        return f"{role_part}_{name_part}.docx"
    return f"CV_B2B_{_sanitize_for_filename(candidate_name)}.docx"


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


def _has_candidate_answers(screening_answers: Any) -> bool:
    """True if the stage holds at least one non-empty candidate answer.

    ``screening_answers`` is the JSONB payload of
    ``CandidateStage.screening_answers`` (shape: :class:`ScreeningAnswers`).
    Used for the readiness badge so a candidate screened purely through the
    Q&A sheet is not reported as "no notes".
    """
    if not isinstance(screening_answers, dict):
        return False
    answers = screening_answers.get("answers")
    if not isinstance(answers, list):
        return False
    return any(
        isinstance(a, dict) and str(a.get("response") or "").strip() for a in answers
    )


def _format_candidate_answers(screening_answers: Any, screening_questions: Any) -> str:
    """Render the recruiter-recorded candidate answers as a Q&A block.

    The screening sheet stores what the candidate said to each Champion
    screening question in ``CandidateStage.screening_answers`` (each item pairs
    a ``question_id`` with the candidate's ``response``). The question text
    lives on the job's Champion Profile (``screening_questions``), so we join by
    id to give Claude the full question -> answer pair.

    Only the candidate's own answers are emitted. The recruiter's ``overall_fit``
    rating, deal-breaker flags and free-text ``notes`` are deliberately left out
    — the prompt's confidentiality rules bar recruiter judgment from the CV.
    """
    if not _has_candidate_answers(screening_answers):
        return ""

    q_by_id: dict[str, str] = {}
    if isinstance(screening_questions, list):
        for q in screening_questions:
            if not isinstance(q, dict):
                continue
            qid = str(q.get("id") or "").strip()
            if qid:
                q_by_id[qid] = str(q.get("question") or "").strip()

    lines: list[str] = []
    for a in screening_answers.get("answers") or []:
        if not isinstance(a, dict):
            continue
        response = str(a.get("response") or "").strip()
        if not response:
            continue
        question = q_by_id.get(str(a.get("question_id") or "").strip(), "")
        lines.append(f"P: {question}\nO: {response}" if question else f"O: {response}")
    return "\n\n".join(lines)


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


# Claude picks up the prompt's typographic en-dashes (date examples like
# "MM.YYYY – MM.YYYY") and sprinkles em/en dashes across the generated CV.
# Recruiters want plain ASCII hyphens, so fold every dash variant down to "-".
_DASH_TRANS = {
    ord("‐"): "-",  # hyphen
    ord("‑"): "-",  # non-breaking hyphen
    ord("‒"): "-",  # figure dash
    ord("–"): "-",  # en dash
    ord("—"): "-",  # em dash
    ord("―"): "-",  # horizontal bar
    ord("−"): "-",  # minus sign
}


def _normalize_dashes(value: Any) -> Any:
    """Recursively replace typographic dashes with plain hyphens in strings."""
    if isinstance(value, str):
        return value.translate(_DASH_TRANS)
    if isinstance(value, list):
        return [_normalize_dashes(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalize_dashes(v) for k, v in value.items()}
    return value


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(x).strip() for x in value if x is not None and str(x).strip()]


def _drop_empty_commas(text: str) -> str:
    """Remove commas that don't sit between two values — a common LLM defect.

    Strips trailing (``,]`` / ``,}``), leading (``[,`` / ``{,``) and doubled
    (``,,``) commas, each of which makes ``json.loads`` fail with the exact
    "Expecting value" error we see in production. String-aware: a comma inside
    a string literal is never touched, so this is a *no-op on well-formed JSON*
    (valid JSON can't contain an empty-value comma) — the fast path above is
    never perturbed.
    """
    out: list[str] = []
    in_string = False
    escaped = False
    prev_significant = ""  # last non-whitespace char emitted outside a string
    n = len(text)
    for i, ch in enumerate(text):
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            prev_significant = '"'
            continue
        if ch in " \t\r\n":
            out.append(ch)
            continue
        if ch == ",":
            if prev_significant in ("", "[", "{", ","):
                continue  # leading or doubled comma → drop
            nxt = i + 1
            while nxt < n and text[nxt] in " \t\r\n":
                nxt += 1
            if nxt < n and text[nxt] in "}],":
                continue  # trailing (or pre-comma) comma → drop
            out.append(ch)
            prev_significant = ","
            continue
        out.append(ch)
        prev_significant = ch
    return "".join(out)


def _escape_stray_quotes(text: str) -> str:
    """Escape unescaped double-quotes that appear INSIDE a string value.

    Claude sometimes writes prose containing a literal quote — an inch mark
    (``15"``), a quoted project name (``system "Alpha"``), a cited job title —
    without escaping it, which makes ``json.loads`` fail with the exact
    "Expecting ',' delimiter" error we see in production. A ``"`` encountered
    while inside a string is a genuine close only when the next significant
    char is structural (``:`` ``,`` ``}`` ``]``) or the input ends; anything
    else means the quote is stray content, so it is rewritten to ``\\"``.

    Closing on ``,`` is deliberate: array-of-string elements (``why_points``)
    are separated by ``",`` and must still terminate — the price is that a
    quoted term sitting immediately before a prose comma can't be recovered,
    but the strict-first caller only *uses* this output if it re-parses, so the
    worst case is the same hard failure as before. No-op on valid JSON, where
    every in-string quote is already escaped.
    """
    out: list[str] = []
    in_string = False
    escaped = False
    n = len(text)
    for i, ch in enumerate(text):
        if not in_string:
            out.append(ch)
            if ch == '"':
                in_string = True
            continue
        if escaped:
            out.append(ch)
            escaped = False
            continue
        if ch == "\\":
            out.append(ch)
            escaped = True
            continue
        if ch == '"':
            nxt = i + 1
            while nxt < n and text[nxt] in " \t\r\n":
                nxt += 1
            if nxt >= n or text[nxt] in ":,}]":
                out.append(ch)  # legitimate close
                in_string = False
            else:
                out.append('\\"')  # stray content quote → escape
            continue
        out.append(ch)
    return "".join(out)


def _close_truncated_json(text: str) -> str:
    """Best-effort close of an unterminated JSON string / array / object.

    Walks the text tracking string state and the bracket stack, then appends a
    closing quote (if a string is still open) and the missing ``]``/``}`` in
    reverse order. Only a safety net for a response cut mid-structure — it can't
    invent a missing value, so a dangling ``"key":`` stays unparseable. A no-op
    on balanced input.
    """
    stack: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
    repaired = text
    if in_string:
        repaired += '"'
    for opener in reversed(stack):
        repaired += "}" if opener == "{" else "]"
    return repaired


def _json_error_context(text: str, err: json.JSONDecodeError, radius: int = 180) -> str:
    """One-line diagnostic around a JSON parse failure.

    The defect is often deep in the document (e.g. char 8416), so logging just
    the head is useless. Surface length, position and a window around the
    failing offset so the actual malformation is visible in Grafana/Loki.
    """
    pos = getattr(err, "pos", 0) or 0
    lo = max(0, pos - radius)
    hi = min(len(text), pos + radius)
    return (
        f"len={len(text)} pos={pos} line={err.lineno} col={err.colno} "
        f"head={text[:100]!r} tail={text[-100:]!r} window={text[lo:hi]!r}"
    )


def _loads_cv_json(text: str) -> Any:
    """Parse Claude's JSON, tolerating a prose wrapper and common LLM defects.

    Strict-first, so a well-formed response is never altered:
      1. ``json.loads(text)`` — fast path.
      2. Slice to the outermost ``{...}`` — drops "Oto dane: {...}" prose.
      3. Conservative repair on that slice, re-parsing after each step:
         - drop empty-value commas (the usual "Expecting value" culprit),
         - escape stray in-string quotes (the "Expecting ',' delimiter"
           culprit — an unescaped ``"`` inside prose),
         - close a truncated tail.
         Each repair is a no-op on well-formed JSON and they compose, so a
         response with several defects at once still parses.

    Re-raises the ORIGINAL ``json.JSONDecodeError`` when nothing parses, so the
    caller logs the real defect rather than a repair artefact.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    candidate = text[start : end + 1] if start != -1 and end > start else text

    decomma = _drop_empty_commas(candidate)
    requote = _escape_stray_quotes(candidate)
    requote_decomma = _drop_empty_commas(requote)
    first_err: json.JSONDecodeError | None = None
    for attempt in (
        candidate,
        decomma,
        requote,
        requote_decomma,
        _close_truncated_json(requote_decomma),
    ):
        try:
            return json.loads(attempt)
        except json.JSONDecodeError as err:
            if first_err is None:
                first_err = err
    # first_err is always set here (every attempt failed), but guard for mypy.
    raise first_err if first_err is not None else json.JSONDecodeError("", text, 0)


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
    return _normalize_dashes(out)


# ── Per-role technology cap ────────────────────────────────────────────────

# Readability: the "Technologie:" line for a long role can balloon to 20+
# entries. Keep the most relevant 12 — champion must/nice-to-have first.
_MAX_TECHNOLOGIES_PER_ROLE = 12


def _cap_role_technologies(
    candidate_data: dict[str, Any], highlight_keywords: list[str] | None
) -> None:
    patterns = compile_keyword_patterns(highlight_keywords or [])
    for job in candidate_data.get("experience", []):
        techs = job.get("technologies") or []
        if len(techs) <= _MAX_TECHNOLOGIES_PER_ROLE:
            continue
        prioritized = [t for t in techs if patterns and highlight_spans(t, patterns)]
        rest = [t for t in techs if t not in prioritized]
        kept = set((prioritized + rest)[:_MAX_TECHNOLOGIES_PER_ROLE])
        # Preserve the model's original ordering within the kept subset.
        job["technologies"] = [t for t in techs if t in kept]


# ── Overlapping employment dates check ─────────────────────────────────────

_ONGOING_RE = re.compile(r"obecnie|currently|present|now", re.IGNORECASE)
_DATE_TOKEN_RE = re.compile(r"(?:(\d{1,2})\.)?(\d{4})")

# A 1-month "overlap" is usually just a handover month — don't cry wolf.
_MIN_OVERLAP_MONTHS = 2


def _parse_date_range(dates: str) -> tuple[int, int] | None:
    """Parse "MM.YYYY – MM.YYYY" / "YYYY" / "MM.YYYY – obecnie" into a
    (start, end) pair of absolute month indexes. Returns None when the
    string doesn't carry parseable dates."""
    if not dates or not dates.strip():
        return None
    tokens = [
        (int(m.group(2)), int(m.group(1)) if m.group(1) else None)
        for m in _DATE_TOKEN_RE.finditer(dates)
    ]
    if not tokens:
        return None
    start_year, start_month = tokens[0]
    start = start_year * 12 + ((start_month or 1) - 1)
    if _ONGOING_RE.search(dates):
        end = 9999 * 12
    else:
        end_year, end_month = tokens[-1]
        end = end_year * 12 + ((end_month or 12) - 1)
    if end < start:
        return None
    return (start, end)


def _total_experience_years(experience: list[dict[str, Any]]) -> int | None:
    """Sum the candidate's actual time employed across all roles, in whole
    years. Intervals are merged so overlapping/parallel contracts (common in
    B2B) are counted once, and an ongoing role ("obecnie") is capped at the
    current month. Returns ``None`` when no role carries parseable dates.

    Claude is reliable at EXTRACTING dates but not at the arithmetic of summing
    them — it tends to round down ("ponad 4" for a 5-year candidate). Computing
    the figure here makes the why_points headline exact.
    """
    now = datetime.now()
    now_idx = now.year * 12 + (now.month - 1)
    intervals: list[tuple[int, int]] = []
    for job in experience or []:
        rng = _parse_date_range(job.get("dates") or "")
        if rng is None:
            continue
        start, end = rng
        end = min(end, now_idx)  # cap the "obecnie" sentinel at the current month
        if end >= start:
            intervals.append((start, end))
    if not intervals:
        return None

    intervals.sort()
    total_months = 0
    cur_start, cur_end = intervals[0]
    for start, end in intervals[1:]:
        if start <= cur_end + 1:  # overlapping or back-to-back → one stretch
            cur_end = max(cur_end, end)
        else:
            total_months += cur_end - cur_start + 1
            cur_start, cur_end = start, end
    total_months += cur_end - cur_start + 1

    years = round(total_months / 12)
    return years if years >= 1 else None


# A years-of-experience figure in a why_point ("Ponad 4 lata doświadczenia…").
# The optional approximate prefix is swallowed so it gets replaced by the exact
# figure (recruiter: "5 years must read 5, not 'over 4'").
_YEARS_PHRASE_RE = re.compile(
    r"(?:ponad|powyżej|przeszło|niemal|prawie|blisko|około|ok\.?|~|"
    r"over|nearly|almost|about|more than)?\s*"
    r"\d+(?:\s*[-–/]\s*\d+)?\s*"
    r"(?:lata|lat|roku|rok|years|year|yrs|yr)\b",
    re.IGNORECASE,
)


def _polish_year_unit(years: int) -> str:
    if years == 1:
        return "rok"
    if 2 <= years % 10 <= 4 and not 12 <= years % 100 <= 14:
        return "lata"
    return "lat"


# Connectors that bind a duration to a specific technology, tool or company
# ("5 lat z Kubernetes", "3 years with Docker", "8 years at Gigaset", "5 lat
# w Gigaset"). Role connectors ("jako" / "as") are deliberately excluded — a
# duration tied to a ROLE is the total-career headline we DO want to correct.
_BOUND_CONNECTOR_RE = re.compile(r"\b(?:z|ze|w|we|u|with|in|at)\b", re.IGNORECASE)

# Markers introducing the "w tym Y lat w [firmie]" sub-figure of a why_point.
# That figure is scoped to one company/chapter of the career, so the recompute
# must never land on it — only the clause BEFORE a marker is searched.
_SUBFIGURE_SPLIT_RE = re.compile(r"\sw tym\s|\sincluding\s|\sincl\.?\s", re.IGNORECASE)


def _experience_bound_terms(candidate_data: dict[str, Any]) -> set[str]:
    """Collect the vocabulary a duration must never be inflated against: the
    champion highlight list, every role's ``technologies`` and every role's
    company name — lowercased. Used to tell a scoped duration ("2 lata z
    Intune", "5 years at Gigaset") apart from the total-career headline so the
    recompute never inflates the former. Sub-4-char tokens are dropped to
    avoid spurious substring hits (e.g. "AI", "Go", "MDM")."""
    raw: list[str] = list(candidate_data.get("highlight_keywords") or [])
    for job in candidate_data.get("experience") or []:
        raw.extend(job.get("technologies") or [])
        company = str(job.get("company") or "")
        raw.append(company)
        raw.extend(company.split())
    return {s for t in raw if len(s := str(t).strip().lower()) >= 4}


def _years_bound_to_tech_or_company(
    point: str, years_end: int, bound_terms: set[str]
) -> bool:
    """True when the years figure is tied to a specific technology or company
    rather than a role — e.g. "6 lat doświadczenia z Microsoft Intune" or
    "5 years at Gigaset". Only the clause the figure introduces is inspected
    (up to the next comma / "w tym" / "including") so a trailing tech mention
    or the "w tym Y lat w [firma]" sub-figure can't trigger a false positive."""
    if not bound_terms:
        return False
    tail = point[years_end:]
    clause = re.split(r"[,;]| w tym | including | incl\.? ", tail, maxsplit=1)[0]
    conn = _BOUND_CONNECTOR_RE.search(clause)
    if not conn:
        return False
    after = clause[conn.end() :].lower()
    return any(term in after for term in bound_terms)


def _fix_experience_years(candidate_data: dict[str, Any], language: str) -> None:
    """Overwrite the (often under-counted) total-years figure in the experience
    why_point with the exact value computed from the candidate's dates. Only
    the headline total is touched — the "w tym Y lat w …" sub-figure and any
    other point are left as Claude wrote them.

    A technology- or company-specific duration ("2 lata z Microsoft Intune",
    "5 years at Gigaset") is left alone: overwriting it with the total career
    figure would falsely inflate experience with that one technology or tenure
    at that one company, so such points are skipped in favour of a generic
    role/seniority headline.

    Only the clause before "w tym" / "including" is searched. When the headline
    figure itself is unparseable (e.g. "5+ years"), the search must not drift
    into the sub-figure — that once turned "including 5 years at Gigaset" into
    "including 8 years at Gigaset" by stamping the career total there.
    """
    years = _total_experience_years(candidate_data.get("experience") or [])
    if not years:
        return
    if language == "en":
        replacement = f"{years} {'year' if years == 1 else 'years'}"
    else:
        replacement = f"{years} {_polish_year_unit(years)}"

    bound_terms = _experience_bound_terms(candidate_data)

    points = candidate_data.get("why_points") or []
    for i, point in enumerate(points):
        if not isinstance(point, str):
            continue
        low = point.lower()
        if "doświadcz" not in low and "experience" not in low:
            continue
        head = _SUBFIGURE_SPLIT_RE.split(point, maxsplit=1)[0]
        match = _YEARS_PHRASE_RE.search(head)
        if not match:
            continue
        if _years_bound_to_tech_or_company(point, match.end(), bound_terms):
            continue
        points[i] = point[: match.start()] + replacement + point[match.end() :]
        break


def _date_overlap_warnings(candidate_data: dict[str, Any], language: str) -> list[str]:
    """Informational check: overlapping employment periods are common in B2B
    (parallel contracts), but the recruiter should verify them consciously
    before the client spots them at the interview. Never blocks generation
    and never alters the CV itself."""
    roles: list[tuple[str, str, tuple[int, int]]] = []
    for job in candidate_data.get("experience", []):
        rng = _parse_date_range(job.get("dates") or "")
        if rng is not None:
            label = job.get("company") or job.get("position") or "?"
            roles.append((label, job.get("dates") or "", rng))

    issues: list[str] = []
    for i in range(len(roles)):
        for j in range(i + 1, len(roles)):
            name_a, dates_a, (start_a, end_a) = roles[i]
            name_b, dates_b, (start_b, end_b) = roles[j]
            overlap = min(end_a, end_b) - max(start_a, start_b) + 1
            if overlap >= _MIN_OVERLAP_MONTHS:
                if language == "en":
                    issues.append(
                        f"VERIFY: overlapping employment periods: "
                        f"'{name_a}' ({dates_a}) and '{name_b}' ({dates_b})"
                    )
                else:
                    issues.append(
                        f"WERYFIKUJ: nakładające się okresy zatrudnienia: "
                        f"'{name_a}' ({dates_a}) i '{name_b}' ({dates_b})"
                    )
    if len(issues) > 3:
        more = len(issues) - 3
        issues = issues[:3]
        issues.append(
            f"… i {more} kolejnych nakładających się par"
            if language != "en"
            else f"… and {more} more overlapping pairs"
        )
    return issues


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


def _champion_parse_warnings(
    champion_dto: ChampionProfileForPrompt | None,
) -> list[str]:
    """Surface an implausible Champion DOCX parse to the recruiter.

    The parser cannot fail loudly — a heading spelled differently than expected
    is indistinguishable from a section that simply isn't there — so the only
    honest signal is the *shape* of what came out. Both warnings are gated on
    ``from_docx``: the New-mode path builds its profile from structured JSONB
    (:func:`from_nexus_job`) and can never hit a heading-recognition failure.
    """
    if champion_dto is None:
        return []
    diag = champion_dto.diagnostics
    if not diag.from_docx:
        return []
    if diag.nothing_recognised:
        return [
            "Profil Championa: nie rozpoznano żadnej sekcji z treścią — "
            "profil został zignorowany przy generowaniu. Upewnij się, że plik "
            "zawiera nagłówki MUST-HAVE / NICE-TO-HAVE w osobnych wierszach."
        ]
    if diag.wiped_out:
        return [
            "Profil Championa: żadna pozycja z MUST-HAVE / NICE-TO-HAVE nie "
            f"wyglądała na technologię (odrzucono wszystkie {diag.raw_entry_count}) "
            "— CV powstało bez wytłuszczeń i bez listy brakujących wymagań. "
            "Najczęstsza przyczyna: wymagania opisane zdaniami zamiast listą "
            "technologii."
        ]
    if diag.implausible:
        return [
            "Profil Championa: nietypowy układ dokumentu — pominięto "
            f"{diag.dropped_total} pozycji, które wyglądały na opis wymagań, "
            "a nie na technologie. Sprawdź nagłówki sekcji w pliku championa; "
            "wytłuszczenia technologii w CV mogą być niepełne."
        ]
    return []


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
    job_id: int | None = None,
    job_title: str | None = None,
    content_mode: ContentMode = DEFAULT_CONTENT_MODE,
) -> GenerationResult:
    """Extract CV text, call Claude and render the DOCX.

    Fully synchronous — wrap in ``run_in_threadpool`` from async callers.
    Used by both the DB-backed (New) and the manual-upload (Old) modes; the
    modes differ only in how the inputs are sourced.

    ``content_mode`` gates every channel through which the client's job ad can
    shape the document. Below "tailored" the Champion Profile is not sent to
    the model at all, so the prompt's whole positioning section has nothing to
    act on, and the client's requirement list stops driving what gets bolded.
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
    mode = normalize_content_mode(content_mode)
    system_prompt = get_prompt(language, blind_cv, mode)

    user_parts = [f"<cv>\n{cv_text.strip()}\n</cv>"]
    screening_section = build_screening_notes_section(screening_notes_text, language)
    if screening_section.strip():
        user_parts.append(
            f"<screening_notes>\n{screening_section.strip()}\n</screening_notes>"
        )
    # Only "tailored" gets the client's requirements in front of the model.
    # Withholding the section (rather than relying on the prompt to ignore it)
    # is what makes the lower modes trustworthy: there is nothing to position
    # against, so no instruction can leak the job ad into the document.
    champion_section = (
        build_champion_section(champion_dto, language)
        if champion_dto and mode == "tailored"
        else ""
    )
    if champion_section.strip():
        user_parts.append(
            f"<champion_profile>\n{champion_section.strip()}\n</champion_profile>"
        )
    user_content = "\n\n".join(user_parts)

    logger.info(
        "[cv_b2b][%s] Built prompt: cv_chars=%d, notes_chars=%d, champion_chars=%d, "
        "lang=%s, blind=%s, content_mode=%s",
        request_id,
        len(cv_text),
        len(screening_notes_text),
        len(champion_section),
        language,
        blind_cv,
        mode,
    )

    # ── 3. Claude call ───────────────────────────────────────────────────
    try:
        response_text = analyze_with_ai(user_content, request_id, system=system_prompt)
    except CVGeneratorTruncatedError as err:
        raise StandaloneGenerationError(code="ai_failed", message=str(err)) from err
    except CVGeneratorOverloadedError as err:
        # Transient — Claude pool saturated even after fallback. Surface the
        # clean retry-actionable message as-is (no raw API dict).
        raise StandaloneGenerationError(code="ai_overloaded", message=str(err)) from err
    except CVGeneratorAIError as err:
        raise StandaloneGenerationError(
            code="ai_failed",
            message=f"Claude wywołanie nieudane: {err}",
        ) from err

    cleaned = response_text.strip()
    cleaned = re.sub(r"```json\n?", "", cleaned)
    cleaned = re.sub(r"```\n?", "", cleaned).strip()

    try:
        raw_data = _loads_cv_json(cleaned)
    except json.JSONDecodeError as err:
        # The defect is often deep in the document (e.g. char 8416), so a
        # head-only log hides it — dump length/position and a window around the
        # failing offset instead. See _json_error_context.
        logger.error(
            "[cv_b2b][%s] Claude returned unparseable JSON: %s",
            request_id,
            _json_error_context(cleaned, err),
        )
        raise StandaloneGenerationError(
            code="ai_failed",
            message=f"Claude zwrócił niepoprawny JSON: {err}",
        ) from err

    candidate_data = _normalize_candidate_data(raw_data, fallback_name)
    candidate_data["language"] = language
    candidate_data["blind_cv"] = blind_cv
    # Stamped BEFORE the render_payload snapshot so the saved row records which
    # mode produced the document that actually reached the client.
    candidate_data["content_mode"] = mode

    # Bold only the TECHNOLOGIES the client listed — must-have AND nice-to-have
    # (compile_keyword_patterns drops methodologies/concepts/requirement prose).
    # Only in "tailored": bolding the client's requirement list is precisely
    # what makes a CV read as a mirror of the job ad.
    if champion_dto and mode == "tailored":
        highlight = [
            kw.strip()
            for kw in (champion_dto.must_have + champion_dto.nice_to_have)
            if kw and kw.strip()
        ]
        if highlight:
            candidate_data["highlight_keywords"] = highlight

    # Readability: hard-cap the "Technologie:" line per role (champion first).
    _cap_role_technologies(candidate_data, candidate_data.get("highlight_keywords"))

    # Exact years of experience — Claude tends to under-count ("ponad 4" for a
    # 5-year candidate); recompute the headline from the extracted dates.
    _fix_experience_years(candidate_data, language)

    # The recruitment role (Champion Profile → Job.title) names the vacancy, not
    # the candidate — so it no longer overwrites ``position``. Putting the job
    # ad's title in the CV header states something the source never said, which
    # is the same class of defect clients report as "written against our advert".
    # It stays the download filename (useful to the recruiter) and is rendered
    # as a separate, clearly-labelled line. Set BEFORE the render_payload
    # snapshot so re-downloads reproduce an identical header.
    role_title = (job_title or "").strip()
    if role_title:
        candidate_data["considered_for"] = role_title

    # ── 4. Anti-fabrication seatbelt + date sanity ───────────────────────
    source_text = f"{cv_text}\n{screening_notes_text}"
    guard_warnings = _fabrication_warnings(candidate_data, source_text, language)
    guard_warnings.extend(_date_overlap_warnings(candidate_data, language))
    guard_warnings.extend(_champion_parse_warnings(champion_dto))

    # Snapshot for the saved-CV log BEFORE render mutates candidate_data
    # (blind mode rewrites name/company in place). Re-rendering this payload
    # reproduces an identical DOCX without another Claude call.
    render_payload = copy.deepcopy(candidate_data)

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
    filename = _build_download_filename(role_title, candidate_name)

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
        render_payload=render_payload,
        job_id=job_id,
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
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
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
            or _has_candidate_answers(stage.screening_answers)
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
    content_mode: ContentMode = DEFAULT_CONTENT_MODE,
) -> GenerationResult:
    """Generate the B2B-formatted CV for ``candidate_id`` using the champion
    + notes context tied to the given ``stage_id``.

    Validates the readiness contract documented in
    :class:`StandaloneGenerationError`. Raises with a specific ``code`` so
    the API layer can map to the right HTTP status.

    ``content_mode`` is clamped to the recruiting client's ceiling
    (``Client.cv_content_mode_cap``) before it reaches the pipeline, so a
    commitment made to a client holds regardless of what the recruiter picks
    in the UI.
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

    # Per-client ceiling. NULL cap (the default everywhere) = no ceiling, so
    # nothing changes for clients we have made no promise to.
    client = await db.get(Client, job.client_id) if job.client_id else None
    effective_mode, was_capped = apply_content_mode_cap(
        content_mode, getattr(client, "cv_content_mode_cap", None)
    )
    if was_capped:
        logger.info(
            "[cv_b2b][%s] content_mode capped %s→%s by client %s",
            request_id,
            normalize_content_mode(content_mode),
            effective_mode,
            job.client_id,
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

    # Candidate's own answers to the Champion screening questions, recorded by
    # the recruiter in the screening sheet (CandidateStage.screening_answers).
    # These are candidate-provided facts — the generator must weave them into
    # the CV just like any other screening note.
    answers_text = _format_candidate_answers(
        stage.screening_answers,
        (job.champion_profile or {}).get("screening_questions"),
    )
    if answers_text:
        screening_parts.append(
            f"[Odpowiedzi kandydata na pytania screeningowe]\n{answers_text}"
        )

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
            job_id=job.id,
            job_title=job.title,
            content_mode=effective_mode,
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
        content_mode=payload.content_mode,
    )


__all__ = [
    "CONTENT_MODES",
    "DEFAULT_CONTENT_MODE",
    "ContentMode",
    "StandaloneGenerationError",
    "GenerationResult",
    "RecruitmentReadiness",
    "UploadGenerationInput",
    "apply_content_mode_cap",
    "generate_cv_for_candidate",
    "generate_cv_from_uploads",
    "list_recruitments_with_readiness",
    "normalize_content_mode",
]
