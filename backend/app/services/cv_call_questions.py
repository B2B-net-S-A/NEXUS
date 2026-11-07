"""Pytania pod CV w ściądze do rozmowy (decyzja Artura 05.11.2026, wariant 3).

Luki wychodziły dopiero w QC, po wygenerowaniu CV: 476 z 820 par miało uwagę
„Luka kandydata”, 1505 uwag łącznie. Rekruter wracał wtedy do kandydata drugi
raz albo CV szło z luką. Tu kod porównuje must-have z rolami tą samą metodą co
QC (``dz_review.found_in``), a model układa z luk opcjonalne pytania na rozmowę.
Mapę liczy kod, a model dostaje gotowe stany, więc nie ocenia kandydata.

Wynik jest dodatkiem: nie blokuje zapisu ani przekazania, a awaria modelu kończy
się stanem ``failed`` z „Ponów”. GET nie woła modelu. Rekruter wpisuje odpowiedź
w notatce z nazwą firmy, bo generator przenosi fakt z rozmowy do roli tylko wtedy,
gdy zna firmę (``generator-cv/silnik-cv-bez-wypelniacza.md``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.models.ai_feature import AIFeatureKey
from app.models.candidate import Candidate
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_call_question import CvCallQuestions
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services import cv_qc
from app.services import dz_review as dz
from app.services.ai_models import fallbacks_for, model_for
from app.services.ai_quota import ai_feature
from app.services.cv_generator_b2b.provider import analyze_with_ai
from app.services.llm_prompts import CV_CALL_QUESTIONS
from app.services.money_text import is_rate_text, strip_rates_and_availability
from app.services.prompt_fencing import fence, json_for_prompt

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.cv_call_questions

DESCRIBED = "opisane"
LISTED = "tylko_lista"
UNROLED = "brak_w_rolach"
ABSENT = "brak"
UNVERIFIED = "unverified"

MAX_QUESTIONS = 5
MAX_ROLES = 8
ROLE_DESC_CHARS = 900
ROLE_TECH_MAX = 25
QUESTION_MIN_CHARS = 10
QUESTION_MAX_CHARS = 260
MODEL_TIMEOUT_SECONDS = 60.0

_OPEN_STAGES = (PipelineStage.new, PipelineStage.screening)
# „miałeś/aś”, „używałeś”, „robiłaś”: rekruter czyta pytanie przez telefon osobie,
# której formy nie zna, a końcówki po ukośniku nie da się powiedzieć.
_GENDERED_FORM = re.compile(r"/\s*a(?:ś|s)?\b|\b\w+(?:łeś|łaś)\b", re.IGNORECASE)

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "requirement": {"type": "string"},
                    "company": {"type": "string"},
                    "question": {"type": "string"},
                },
                "required": ["requirement", "company", "question"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class RequirementRow:
    requirement: dz.Requirement
    state: str
    # Stan wymagania w każdej roli z CV, w kolejności ról.
    roles: tuple[str, ...]


def _role_state(role: dz.Role, req: dz.Requirement) -> Optional[str]:
    if not role.detail:
        return UNVERIFIED
    if dz.found_in(role.desc, req):
        return DESCRIBED
    listed = " ".join(v for v in (", ".join(role.technologies), role.title) if v)
    return LISTED if dz.found_in(listed, req) else None


def requirement_map(
    must: list[dz.Requirement], roles: list[dz.Role], cv_text: str
) -> list[RequirementRow]:
    """Must-have × role z CV. Opis roli wygrywa z listą technologii."""

    rows: list[RequirementRow] = []
    for req in must:
        cells = tuple(_role_state(role, req) or ABSENT for role in roles)
        if DESCRIBED in cells:
            state = DESCRIBED
        elif LISTED in cells:
            state = LISTED
        elif dz.found_in(cv_text, req):
            state = UNROLED
        else:
            state = ABSENT
        rows.append(RequirementRow(req, state, cells))
    return rows


def _related(row: RequirementRow, cv_text: str) -> dict[str, list[str]]:
    """Mapa wiedzy IT (07.11.2026): przy braku — zamienniki albo hasła, przy których
    wymaganie jest typowe, wymienione w CV („zna Flask” przy FastAPI)."""
    if row.state != ABSENT or not cv_text:
        return {}
    from app.services.cv_qc import related_hint

    hint = related_hint(row.requirement.label, cv_text)
    if hint is None:
        return {}
    key = "zamienniki_w_cv" if hint["kind"] == "alternative" else "typowe_przy"
    return {key: list(hint["names"])}


def prompt_payload(
    job_title: Optional[str],
    rows: list[RequirementRow],
    roles: list[dz.Role],
    cv_text: str = "",
) -> dict[str, Any]:
    """To, co czyta model: luki i role, bez danych kontaktowych i całego pliku CV."""

    return {
        "rekrutacja": job_title or "",
        "wymagania": [
            {
                "nazwa": row.requirement.label,
                "stan": row.state,
                "role_tylko_lista": [
                    role.company or role.label
                    for role, cell in zip(roles, row.roles)
                    if cell == LISTED
                ],
                **_related(row, cv_text),
            }
            for row in rows
            if row.state != DESCRIBED
        ],
        "stanowiska": [
            {
                "firma": role.company or "",
                "stanowisko": role.title or "",
                "opis": (role.desc or "")[:ROLE_DESC_CHARS],
                "technologie": list(role.technologies)[:ROLE_TECH_MAX],
            }
            for role in roles[:MAX_ROLES]
        ],
    }


def _usable_question(text: str) -> bool:
    return (
        QUESTION_MIN_CHARS <= len(text) <= QUESTION_MAX_CHARS
        and not _GENDERED_FORM.search(text)
        and not is_rate_text(text)
        and strip_rates_and_availability(text).strip() == text
    )


def _known_company(value: Any, roles: list[dz.Role]) -> str:
    wanted = " ".join(str(value or "").split()).casefold()
    if not wanted:
        return ""
    for role in roles:
        company = " ".join((role.company or "").split())
        if company and company.casefold() == wanted:
            return company
    return ""


def parse_questions(
    raw: str, rows: list[RequirementRow], roles: list[dz.Role]
) -> list[dict[str, str]]:
    """Co wolno pokazać: wymaganie z luk, firma z ról, stan z mapy, nie z modelu.

    Kolejność idzie za mapą (najpierw umiejętności krytyczne). Zepsuta odpowiedź
    daje wyjątek, żeby trafiła do stanu ``failed``, a nie do pustej listy.
    """

    parsed = json.loads(raw)
    items = parsed.get("questions") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        raise ValueError("model response without questions")
    by_label: dict[str, dict[str, str]] = {}
    gaps = {
        row.requirement.label.casefold(): row for row in rows if row.state != DESCRIBED
    }
    for item in items:
        if not isinstance(item, dict):
            continue
        row = gaps.get(" ".join(str(item.get("requirement") or "").split()).casefold())
        question = " ".join(str(item.get("question") or "").split())
        if row is None or row.requirement.label in by_label:
            continue
        if not _usable_question(question):
            continue
        by_label[row.requirement.label] = {
            "requirement": row.requirement.label,
            "company": _known_company(item.get("company"), roles),
            "state": row.state,
            "question": question,
        }
    ordered = [
        by_label[row.requirement.label]
        for row in rows
        if row.requirement.label in by_label
    ]
    # Luki są, a pytań nie ma: pusta lista czytałaby się jak „nie ma o co dopytać”.
    if gaps and not ordered:
        raise ValueError("no usable question for the gaps")
    return ordered[:MAX_QUESTIONS]


def _call_model(payload: dict[str, Any], request_id: str) -> str:
    """Jedno wywołanie modelu (w wątku). Osobna funkcja: testy ją podmieniają."""

    return analyze_with_ai(
        CV_CALL_QUESTIONS.render(data=fence("dane", json_for_prompt(payload))),
        request_id,
        system=CV_CALL_QUESTIONS.system_prompt,
        model_override=model_for(FEATURE),
        fallback_models=list(fallbacks_for(FEATURE)),
        response_schema=RESPONSE_SCHEMA,
        total_timeout=MODEL_TIMEOUT_SECONDS,
    )


async def _latest_stage(
    db: AsyncSession, candidate_id: int, job_id: int
) -> Optional[CandidateStage]:
    return await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )


def _ordered_must(job: Job) -> list[dz.Requirement]:
    """Must-have z nazwami z bramki, najpierw umiejętności krytyczne."""

    must, _nice = dz.job_requirements(job)
    critical, _source = cv_qc.critical_requirements(job, must)
    labels = {req.label for req in critical}
    must = cv_qc.with_critical_terms(must, critical)
    return sorted(must, key=lambda req: req.label not in labels)


async def _snapshot_marker(
    db: AsyncSession, candidate_id: int, job_id: int
) -> Optional[str]:
    """Odcisk pliku bez jego czytania: GET nie może pobierać i odczytywać CV."""

    row = (
        await db.execute(
            select(
                CandidateStageCV.original_cv_sha256,
                CandidateStageCV.original_snapshot_at,
                CandidateStageCV.candidate_stage_id,
            )
            .join(
                CandidateStage,
                CandidateStage.id == CandidateStageCV.candidate_stage_id,
            )
            .where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
                or_(
                    CandidateStageCV.original_cv_content.is_not(None),
                    CandidateStageCV.original_cv_storage_key.is_not(None),
                ),
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    return row[0] or f"{row[2]}:{row[1]}"


def _inputs_hash(
    candidate: Candidate, must: list[dz.Requirement], marker: Optional[str]
) -> str:
    extracted = candidate.cv_extracted_data
    payload = {
        "prompt": CV_CALL_QUESTIONS.version,
        "must": [req.label for req in must],
        "file": marker,
        "profile_text": (
            None
            if marker
            else hashlib.sha256((candidate.raw_cv_text or "").encode()).hexdigest()
        ),
        "read": extracted.get("experience") if isinstance(extracted, dict) else None,
        "experience": candidate.experience,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


async def _still_open(
    db: AsyncSession,
    questions: list[dict],
    must: list[dz.Requirement],
    stage: CandidateStage,
    job: Job,
    candidate_id: int,
) -> list[dict]:
    """Bez pytań, na które padła już odpowiedź w screeningu albo potwierdzeniu."""

    if not questions:
        return []
    answers = cv_qc.answers_text(stage, job) or ""
    confirmed = "\n".join(
        row["text"].split(" — ", 1)[0]
        for row in await cv_qc._confirmations(db, candidate_id)
    )
    known = answers + "\n" + confirmed
    by_label = {req.label: req for req in must}
    kept: list[dict] = []
    for item in questions:
        req = by_label.get(item.get("requirement"))
        if req is None or not dz.found_in(known, req):
            kept.append(item)
    return kept


def _response(
    status: str,
    *,
    can_refresh: bool = False,
    stale: bool = False,
    questions: Optional[list[dict]] = None,
    generated_at: Any = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "can_refresh": can_refresh,
        "stale": stale,
        "questions": questions or [],
        "generated_at": generated_at,
    }


async def build_view(
    db: AsyncSession, candidate_id: int, job_id: int, *, can_refresh: bool
) -> dict[str, Any]:
    """Stan sekcji w ściądze. Tylko odczyt: bez modelu i bez pobierania pliku CV.

    ``not_applicable``, ``no_requirements`` i ``no_cv`` to stany, w których sekcji
    nie ma. ``none`` i ``stale`` każą frontowi raz poprosić o odświeżenie.
    """

    candidate = await db.get(Candidate, candidate_id)
    job = await db.get(Job, job_id)
    stage = await _latest_stage(db, candidate_id, job_id)
    if (
        candidate is None
        or job is None
        or stage is None
        or job.status != JobStatus.published
        or stage.stage not in _OPEN_STAGES
    ):
        return _response("not_applicable")
    must = _ordered_must(job)
    if not must:
        return _response("no_requirements")
    marker = await _snapshot_marker(db, candidate_id, job_id)
    if not marker and not (candidate.raw_cv_text or "").strip():
        return _response("no_cv")
    row = await db.get(CvCallQuestions, (candidate_id, job_id))
    if row is None:
        return _response("none", can_refresh=can_refresh)
    stale = row.inputs_hash != _inputs_hash(candidate, must, marker)
    return _response(
        row.status,
        can_refresh=can_refresh,
        stale=stale,
        questions=await _still_open(
            db, list(row.questions or []), must, stage, job, candidate_id
        ),
        generated_at=row.generated_at,
    )


async def _store(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    status: str,
    inputs_hash: str,
    model: Optional[str],
    questions: list[dict],
) -> None:
    values = {
        "status": status,
        "inputs_hash": inputs_hash,
        "model": model,
        "questions": questions,
    }
    statement = pg_insert(CvCallQuestions).values(
        candidate_id=candidate_id, job_id=job_id, **values
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=["candidate_id", "job_id"],
            set_={**values, "generated_at": statement.excluded.generated_at},
        )
    )
    await db.commit()


async def refresh(
    db: AsyncSession, candidate_id: int, job_id: int, *, user_id: int
) -> None:
    """Policz pytania, gdy trzeba. Awaria modelu zostawia ``failed``, nie wyjątek."""

    view = await build_view(db, candidate_id, job_id, can_refresh=True)
    if view["status"] not in ("none", "ready", "failed"):
        return
    if view["status"] == "ready" and not view["stale"]:
        return
    candidate = await db.get(Candidate, candidate_id)
    job = await db.get(Job, job_id)
    stage = await _latest_stage(db, candidate_id, job_id)
    if candidate is None or job is None or stage is None:
        return
    must = _ordered_must(job)
    marker = await _snapshot_marker(db, candidate_id, job_id)
    inputs_hash = _inputs_hash(candidate, must, marker)
    original = await dz._original_cv(db, candidate, stage.id, job_id)
    # `_original_cv` zwraca pusty tekst przy awarii magazynu i przy skanie bez tekstu.
    # Mapa z pustego tekstu uznałaby wszystko za brak, więc model nie dostaje jej wcale.
    text = original.get("text") or (candidate.raw_cv_text or "").strip()
    if not text:
        await _store(
            db,
            candidate_id=candidate_id,
            job_id=job_id,
            status="failed",
            inputs_hash=inputs_hash,
            model=None,
            questions=[],
        )
        return
    roles = dz.original_roles(dz.role_entries(candidate, text))
    rows = requirement_map(must, roles, text)
    if all(row.state == DESCRIBED for row in rows):
        await _store(
            db,
            candidate_id=candidate_id,
            job_id=job_id,
            status="ready",
            inputs_hash=inputs_hash,
            model=None,
            questions=[],
        )
        return
    payload = prompt_payload(job.title, rows, roles, text)
    request_id = f"cvcallq_{uuid.uuid4().hex[:12]}"
    try:
        async with ai_feature(db, FEATURE, user_id=user_id):
            await db.commit()  # połączenie wraca do puli na czas modelu
            raw = await run_in_threadpool(_call_model, payload, request_id)
        questions = parse_questions(raw, rows, roles)
    except Exception as exc:  # noqa: BLE001 — AI to dodatek, nigdy bramka
        await db.rollback()
        logger.warning(
            "[cv_call_questions][%s] failed (%s)", request_id, type(exc).__name__
        )
        await _store(
            db,
            candidate_id=candidate_id,
            job_id=job_id,
            status="failed",
            inputs_hash=inputs_hash,
            model=None,
            questions=[],
        )
        return
    await _store(
        db,
        candidate_id=candidate_id,
        job_id=job_id,
        status="ready",
        inputs_hash=inputs_hash,
        model=model_for(FEATURE),
        questions=questions,
    )
