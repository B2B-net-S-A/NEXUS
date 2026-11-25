"""„Pytania z rozmów”: proponowana odpowiedź pod każdym pytaniem (F55, 25.11.2026).

Decyzja Artura z 25.11.2026: pod każdym pytaniem z banku klienta ekran
Rekrutacje → „Pytania z rozmów” pokazuje odpowiedź, z której rekruter
przygotowuje kandydata. Źródła odpowiedzi (``ideal_answer_source``):

* ``excel`` — odpowiedź z archiwum Excela (``legacy_import``),
* ``manual`` — wpisana przez człowieka (Baza pytań),
* ``ai`` — z nocnego biegu tego modułu; interfejs oznacza ją „do sprawdzenia”,
* ``none`` — model uznał wiersz za etykietę działu, która zapowiada kolejne
  pytania tej samej notatki („Kolejki i komunikacja asynchroniczna”), albo
  za tekst, który nie jest pytaniem. Taki wiersz nie ma odpowiedzi, ekran
  rysuje go jako nagłówek, a do modelu nie wraca co noc.

Kod nie zgaduje nagłówków z tekstu (liczba słów, brak „?”): na kopii
produkcji z 25.11 z 32 krótkich wierszy bez „?” nagłówkami były 4, reszta
to krótkie pytania („Playwright”, „Czy zna RLS”), które potrzebują odpowiedzi.
Decyduje model, a w partii pytania jednego stanowiska stoją w kolejności
zapisu (``id``), więc widzi etykietę razem z pytaniami pod nią.

NULL = jeszcze nie rozstrzygnięte; tylko takie pytania (``client_debrief``
i ``legacy_import`` bez odpowiedzi) idą do modelu, najstarsze pierwsze, do
``INTERVIEW_ANSWER_PROPOSALS_PER_NIGHT`` na noc, w partiach po 20 w obrębie
klienta. Przy pytaniu idzie stanowisko z rekrutacji, w której padło (tytuł
i do 5 must-have), bez nazwy klienta, kandydatów, managerów i stawek.

Podział pracy: model pisze odpowiedź albo ``null``; KOD przyjmuje tylko id
z partii, przycina długość i zapisuje warunkowym ``UPDATE`` (odpowiedź, która
w międzyczasie stanęła w bazie, zostaje). Model jest dodatkiem: nieudana
partia = log i następna partia, pytanie wraca następnej nocy.

Reguła dla ludzi: ``docs/claude/integracje/pytania-z-rozmow-jak-excel.md``.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ai_feature import AIFeatureKey
from app.models.interview_feedback import FeedbackSource, InterviewFeedback
from app.models.interview_question import (
    InterviewQuestion,
    InterviewQuestionSource,
    JobQuestion,
)
from app.models.job import Job
from app.services.ai_models import fallbacks_for, model_for
from app.services.client_questions_asked import question_hash
from app.services.job_working_title import job_display_title_expr
from app.services.llm_prompts import INTERVIEW_ANSWER_PROPOSAL
from app.services.llm_providers import api_key_configured
from app.services.prompt_fencing import fence, json_for_prompt

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.interview_answer_proposal

SOURCE_EXCEL = "excel"
SOURCE_MANUAL = "manual"
SOURCE_AI = "ai"
SOURCE_NONE = "none"
ANSWER_SOURCES = (SOURCE_EXCEL, SOURCE_AI, SOURCE_MANUAL)

BANK_SOURCES = (
    InterviewQuestionSource.client_debrief,
    InterviewQuestionSource.legacy_import,
)
BATCH_SIZE = 20
ANSWER_MAX = 1200
QUESTION_MAX = 500
ROLE_SKILLS = 5
# Tyle nieudanych partii z rzędu = dostawca leży; reszta nocy nic nie da.
MAX_FAILED_IN_A_ROW = 3


# ── Odczyt dla ekranu ───────────────────────────────────────────────────────


def bank_answer(question: Any) -> tuple[Optional[str], Optional[str]]:
    """``(answer, answer_source)`` pytania dla „Pytań z rozmów”.

    ``(None, "none")`` = nocny bieg uznał wiersz za nagłówek działu (ekran
    rysuje go jako nagłówek); ``(None, None)`` = jeszcze nie przeliczone.
    Wiersz z odpowiedzią bez źródła (zapisany przed 0778 albo starym kodem)
    dostaje źródło jak w backfillu: ``excel`` przy archiwum, ``manual`` przy
    reszcie.
    """
    answer = (getattr(question, "ideal_answer", None) or "").strip() or None
    stored = getattr(question, "ideal_answer_source", None)
    if answer is None:
        return None, (SOURCE_NONE if stored == SOURCE_NONE else None)
    if stored in ANSWER_SOURCES:
        return answer, stored
    if question.source == InterviewQuestionSource.legacy_import:
        return answer, SOURCE_EXCEL
    return answer, SOURCE_MANUAL


def source_after_human_edit(ideal_answer: Optional[str]) -> Optional[str]:
    """Źródło po zmianie odpowiedzi w Bazie pytań: wpisana = ``manual``.

    Wyczyszczona = NULL („jeszcze nie przeliczone”), a nie ``none``: ``none``
    ekran rysuje jako nagłówek działu, a wyczyszczona odpowiedź nie robi
    z pytania nagłówka. Nocny bieg może potem zaproponować nową.
    """
    return SOURCE_MANUAL if (ideal_answer or "").strip() else None


# ── Co idzie do modelu ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class PendingQuestion:
    id: int
    text: str
    client_id: int
    role: Optional[str]


def _skill_names(raw: object) -> list[str]:
    names: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        name = item.get("name") if isinstance(item, dict) else item
        if isinstance(name, str) and name.strip() and name.strip() not in names:
            names.append(name.strip())
    return names


def role_label(title: Optional[str], must_skills: object) -> Optional[str]:
    """„Programista Integracji · IBM MQ, Java” — tytuł i do 5 must-have."""
    title = re.sub(r"\s+", " ", title or "").strip()
    skills = _skill_names(must_skills)[:ROLE_SKILLS]
    if not title:
        return ", ".join(skills) or None
    return f"{title} · {', '.join(skills)}" if skills else title


def _unanswered():
    return (
        InterviewQuestion.source.in_(BANK_SOURCES),
        InterviewQuestion.client_id.is_not(None),
        InterviewQuestion.ideal_answer_source.is_(None),
        or_(
            InterviewQuestion.ideal_answer.is_(None),
            func.btrim(InterviewQuestion.ideal_answer) == "",
        ),
    )


async def _newest_job_per_question(
    db: AsyncSession, rows: Sequence[Any]
) -> dict[int, int]:
    """Najnowsza rekrutacja, w której pytanie padło (jak ``questions_asked_in_job``:
    linia debriefu albo przypięcie importu Excela)."""
    ids = [r.id for r in rows]
    newest: dict[int, int] = {}
    pins = await db.execute(
        select(JobQuestion.question_id, func.max(JobQuestion.job_id))
        .where(
            JobQuestion.question_id.in_(ids),
            JobQuestion.added_by_user_id.is_(None),
        )
        .group_by(JobQuestion.question_id)
    )
    for question_id, job_id in pins:
        newest[question_id] = job_id
    debrief_job: dict[tuple[int, str], int] = {}
    debriefs = await db.execute(
        select(Job.id, Job.client_id, InterviewFeedback.client_questions)
        .join(InterviewFeedback, InterviewFeedback.job_id == Job.id)
        .where(
            Job.client_id.in_({r.client_id for r in rows}),
            InterviewFeedback.feedback_source == FeedbackSource.candidate_side,
            InterviewFeedback.client_questions.is_not(None),
        )
    )
    for job_id, client_id, text in debriefs:
        for line in (text or "").splitlines():
            if line.strip():
                key = (client_id, question_hash(line))
                debrief_job[key] = max(job_id, debrief_job.get(key, 0))
    for r in rows:
        job_id = debrief_job.get((r.client_id, r.normalized_text_hash))
        if job_id is not None and job_id > newest.get(r.id, 0):
            newest[r.id] = job_id
    return newest


async def pending_questions(db: AsyncSession, *, limit: int) -> list[PendingQuestion]:
    """Pytania bez odpowiedzi i bez rozstrzygnięcia, najstarsze pierwsze."""
    if limit <= 0:
        return []
    rows = list(
        (
            await db.execute(
                select(
                    InterviewQuestion.id,
                    InterviewQuestion.text,
                    InterviewQuestion.client_id,
                    InterviewQuestion.normalized_text_hash,
                )
                .where(*_unanswered())
                .order_by(InterviewQuestion.created_at, InterviewQuestion.id)
                .limit(limit)
            )
        ).all()
    )
    if not rows:
        return []
    job_of = await _newest_job_per_question(db, rows)
    labels: dict[int, Optional[str]] = {}
    if job_of:
        jobs = await db.execute(
            select(Job.id, job_display_title_expr(), Job.must_skills).where(
                Job.id.in_(set(job_of.values()))
            )
        )
        labels = {job_id: role_label(title, skills) for job_id, title, skills in jobs}
    return [
        PendingQuestion(
            id=r.id,
            text=r.text,
            client_id=r.client_id,
            role=labels.get(job_of.get(r.id, -1)),
        )
        for r in rows
    ]


def make_batches(
    pending: Iterable[PendingQuestion], size: int = BATCH_SIZE
) -> list[list[PendingQuestion]]:
    """Partie po ``size`` w obrębie klienta, pytania jednego stanowiska obok siebie."""
    by_client: dict[int, list[PendingQuestion]] = {}
    for q in pending:
        by_client.setdefault(q.client_id, []).append(q)
    batches: list[list[PendingQuestion]] = []
    for questions in by_client.values():
        ordered = sorted(questions, key=lambda q: (q.role is None, q.role or "", q.id))
        batches += [ordered[i : i + size] for i in range(0, len(ordered), size)]
    return batches


def build_prompt(batch: Sequence[PendingQuestion]) -> str:
    items = [
        {"id": q.id, "pytanie": q.text.strip()[:QUESTION_MAX], "stanowisko": q.role}
        for q in batch
    ]
    return INTERVIEW_ANSWER_PROPOSAL.render(
        questions=fence("pytania", json_for_prompt(items))
    )


# ── Co wraca od modelu ──────────────────────────────────────────────────────


def _json_items(raw: str) -> list:
    body = (raw or "").strip()
    if body.startswith("```"):
        body = body.strip("`")
        if body.lower().startswith("json"):
            body = body[4:]
    starts = [i for i in (body.find("["), body.find("{")) if i >= 0]
    if not starts:
        raise ValueError("odpowiedź bez JSON")
    start = min(starts)
    end = body.rfind("]" if body[start] == "[" else "}")
    if end <= start:
        raise ValueError("odpowiedź bez JSON")
    parsed = json.loads(body[start : end + 1])
    if isinstance(parsed, dict):
        parsed = parsed.get("answers") or parsed.get("items") or []
    if not isinstance(parsed, list):
        raise ValueError("odpowiedź bez listy")
    return parsed


def clip_answer(text: str, limit: int = ANSWER_MAX) -> Optional[str]:
    """Odpowiedź bez pustych linii na końcach; za długa urwana na końcu zdania."""
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    value = "\n".join(line for line in lines if line).strip()
    if not value:
        return None
    if len(value) <= limit:
        return value
    cut = value[:limit]
    end = max(cut.rfind(". "), cut.rfind(".\n"))
    return cut[: end + 1] if end >= limit // 2 else cut.rstrip() + "…"


def check_reply(raw: str, batch_ids: Iterable[int]) -> dict[int, Optional[str]]:
    """``{id: odpowiedź albo None}`` — None = nagłówek, nie pytanie.

    Id spoza partii i wpisy bez ``answer`` (ani tekstu, ani ``null``) odpadają;
    pierwszy wpis danego id wygrywa. Pusty tekst to nie decyzja — pytanie wraca
    następnej nocy.
    """
    allowed = set(batch_ids)
    out: dict[int, Optional[str]] = {}
    for item in _json_items(raw):
        if not isinstance(item, dict) or "answer" not in item:
            continue
        try:
            qid = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        if qid not in allowed or qid in out:
            continue
        answer = item["answer"]
        if answer is None:
            out[qid] = None
        elif isinstance(answer, str):
            clipped = clip_answer(answer)
            if clipped is not None:
                out[qid] = clipped
    return out


async def store(db: AsyncSession, answers: dict[int, Optional[str]]) -> tuple[int, int]:
    """Zapis tylko tam, gdzie nadal nie ma odpowiedzi ani rozstrzygnięcia.

    Zwraca (odpowiedzi, nagłówki). Wołający nie musi commitować.
    """
    answered = headings = 0
    for qid, answer in answers.items():
        result = await db.execute(
            update(InterviewQuestion)
            .where(InterviewQuestion.id == qid, *_unanswered())
            .values(
                ideal_answer=answer,
                ideal_answer_source=SOURCE_AI if answer is not None else SOURCE_NONE,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount:
            if answer is None:
                headings += 1
            else:
                answered += 1
    await db.commit()
    return answered, headings


# ── Nocny bieg ──────────────────────────────────────────────────────────────


def _call_model(prompt: str) -> str:
    """Jedno wywołanie modelu (w wątku). Osobna funkcja: testy ją podmieniają."""
    from app.services.claude_client import call_claude, text_of  # noqa: PLC0415

    message = call_claude(
        model=model_for(FEATURE),
        fallback_models=list(fallbacks_for(FEATURE)),
        max_tokens=8000,
        timeout=180,
        max_retries=1,
        total_timeout=300,
        system=INTERVIEW_ANSWER_PROPOSAL.system_prompt or "",
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": prompt}],
    )
    return text_of(message)


async def run(db: AsyncSession, *, limit: Optional[int] = None) -> dict:
    """Jeden bieg: propozycje dla najstarszych pytań bez odpowiedzi.

    Zwraca same liczby (do ``app_settings`` i logu), nigdy treść pytań.
    """
    from app.services.ai_quota import ai_feature  # noqa: PLC0415

    if limit is None:
        limit = settings.INTERVIEW_ANSWER_PROPOSALS_PER_NIGHT
    summary: dict[str, Any] = {
        "status": "ok",
        "pending": 0,
        "batches": 0,
        "failed_batches": 0,
        "answered": 0,
        "headings": 0,
        "left_for_next_run": 0,
    }
    if limit <= 0:
        return {**summary, "status": "disabled"}
    if not api_key_configured(model_for(FEATURE)):
        return {**summary, "status": "unconfigured"}
    pending = await pending_questions(db, limit=limit)
    batches = make_batches(pending)
    summary["pending"] = len(pending)
    failed_in_a_row = 0
    for batch in batches:
        summary["batches"] += 1
        try:
            async with ai_feature(db, FEATURE):
                # Licznik AI zapisuje wiersz w tej sesji — commit PRZED modelem.
                await db.commit()
                raw = await run_in_threadpool(_call_model, build_prompt(batch))
            answers = check_reply(raw, (q.id for q in batch))
            answered, headings = await store(db, answers)
        except Exception as exc:  # noqa: BLE001 — wynik modelu to dodatek
            logger.warning(
                "[interview_answer_proposals] partia nieudana size=%s (%s)",
                len(batch),
                type(exc).__name__,
            )
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                logger.warning("[interview_answer_proposals] rollback failed")
            summary["failed_batches"] += 1
            failed_in_a_row += 1
            if failed_in_a_row >= MAX_FAILED_IN_A_ROW:
                summary["status"] = "provider_unavailable"
                break
            continue
        failed_in_a_row = 0
        summary["answered"] += answered
        summary["headings"] += headings
    summary["left_for_next_run"] = int(
        await db.scalar(
            select(func.count()).select_from(InterviewQuestion).where(*_unanswered())
        )
        or 0
    )
    logger.info("[interview_answer_proposals] %s", summary)
    return summary
