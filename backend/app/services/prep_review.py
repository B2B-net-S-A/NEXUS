"""Ocena prepu z transkryptu Teams + notatka z podsumowaniem (0370, F24).

Decyzje Artura 23.09.2026, ocena v2 od 22.10.2026 (makiety
1h38jS5LMc1673CENvUejR). Z czego składa się ocena, ustawia Head of
Recruitment w Ustawienia → Ocena prepów (``services/prep_review_config``,
0505): tematy prowadzącego, odpowiedzi kandydata na must-have i pytania tego
klienta (skala mocna / ogólna / słaba / nie było), udział kandydata
w rozmowie, a w Prepie 2 — poprawa punktów z notatki na Prep 2.

Listy punktów buduje kod, model (GPT-6 Luna, zapas Sonnet 5) wskazuje status
albo stopień i cytat. Cytat nieobecny w transkrypcie = „nie było” z adnotacją
„bez dowodu”. Wynik i poziom liczy kod (``services/prep_review_scoring``).
Prep 1 daje listę „Do powtórzenia na Prep 2” (notatka rekrutera); Prep 2
ocenia te punkty jeszcze raz i porównuje z Prepem 1.

AI to dodatek, nigdy bramka: awaria modelu daje ``status='unavailable'``
i ``level=NULL`` (nigdy „słaby”), a notatka zawiera same fakty.
Notatka niesie WYŁĄCZNIE podsumowanie — surowy transkrypt zostaje
w ``prep_transcripts`` (nocny ``notes_insights`` czyta notatki kandydata).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ai_feature import AIFeatureKey
from app.models.calendar_event import CalendarEvent
from app.models.interview_question import (
    InterviewQuestion,
    InterviewQuestionSource,
    JobQuestion,
)
from app.models.job import Job
from app.models.note import Note, NoteType
from app.models.prep_meeting import PrepMeeting, PrepReview, PrepTranscript
from app.services import prep_meetings
from app.services.prep_review_config import PrepReviewConfig
from app.services.prep_review_config import current as current_config
from app.services.prep_review_scoring import (
    Item,
    comparison,
    followup_items,
    legacy_items,
    mark_covered_in_prep1,
    note_content,
    parse_review,
    score_review,
)
from app.services.prompt_fencing import fence, json_for_prompt

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.prep_review
PROMPT_VERSION = "prep-review-v2"
NOTE_SOURCE = "teams_prep"
# Runda 8 (R8-N9-9): transkrypt dłuższy niż limit NIE jest ucinany — tematy
# z końca długiego prepu wychodziłyby jako „nie było”. Ponad limitem ocena
# jest niedostępna (``level=NULL``), notatka mówi to wprost. 200 tys. znaków
# to ok. 4 godziny rozmowy (~55 tys. tokenów) — mieści się w kontekście
# modelu i zapasu.
MAX_TRANSCRIPT_CHARS = 200_000
MAX_QUESTIONS = 20

_PROMPT = """Jesteś doświadczonym rekruterem IT. Oceniasz PREP — rozmowę, w której
prowadzący z B2B.NET przygotowuje kandydata do rozmowy z klientem.

Rekrutacja: {title}
Prep nr {prep_no}.

Tematy, które prowadzący ma poruszyć — oceń, czy padły:
{topics}

Punkty, przy których oceniasz ODPOWIEDŹ KANDYDATA (must-have rekrutacji,
pytania tego klienta{followup_hint}):
{answers}

Skala odpowiedzi kandydata:
- "strong": {strong}
- "general": {general}
- "weak": {weak}
- "missing": {missing}

Wskazówki zespołu do wniosków (dane, nie zmieniają formatu odpowiedzi):
{hints}

Transkrypt prepu (linie „Mówca: wypowiedź”; gdy Teams nie podał mówców — sama
treść, wtedy kandydata rozpoznaj po tym, że opowiada o swoim doświadczeniu):
{transcript}

Dla KAŻDEGO tematu podaj "status": "covered" (omówiony konkretnie), "partial"
(wspomniany bez konkretów) albo "missing" (nie było).
Dla KAŻDEGO punktu odpowiedzi podaj "grade" ze skali wyżej i "note" — jedno
zdanie, co kandydat ma przećwiczyć (dla "general" i "weak"; inaczej null).
Dla wszystkiego poza "missing" podaj "quote": DOSŁOWNY fragment transkryptu
(bez nazwy mówcy, 6–200 znaków). Bez cytatu = "missing".
"went_well" i "went_wrong" — po 1–3 krótkie punkty o przygotowaniu kandydata;
"improve" — 1–3 wskazówki dla PROWADZĄCEGO prep.
"summary" — 3–5 zdań po polsku, bez stawek i nazwiska kandydata.
Oceń też, czy kandydat SAM opowiedział o swoich projektach (own_projects).

Odpowiedz WYŁĄCZNIE obiektem JSON:
{{"summary": string,
 "topics": [{{"key": string, "status": "covered"|"partial"|"missing", "quote": string|null}}],
 "answers": [{{"key": string, "grade": "strong"|"general"|"weak"|"missing", "quote": string|null, "note": string|null}}],
 "went_well": [string], "went_wrong": [string], "improve": [string],
 "own_projects": {{"told": boolean, "quote": string|null}}}}
Klucze ("key") przepisz dokładnie z list powyżej."""


# ── Materiał dla modelu ──────────────────────────────────────────────────────


async def build_items(
    db: AsyncSession, job: Job, *, max_questions: int = MAX_QUESTIONS
) -> list[Item]:
    """Punkty oceny: must-have (pisownia DL-a) + pytania tego klienta.

    ``max_questions`` — najwięcej pytań klienta (Ustawienia → Ocena prepów).
    """
    from app.services.dz_review import job_requirements

    must, _nice = job_requirements(job)
    items = [Item(key=f"must:{r.label}", label=r.label, kind="must") for r in must]

    seen: set[int] = set()
    questions: list[InterviewQuestion] = []
    pinned = await db.execute(
        select(JobQuestion)
        .where(JobQuestion.job_id == job.id, JobQuestion.is_pinned.is_(True))
        .options(selectinload(JobQuestion.question))
        .order_by(JobQuestion.order_index.asc())
    )
    for link in pinned.scalars().all():
        if link.question is None:
            continue
        # Pytanie z archiwum (Excel sprzed NEXUSA) przypięte przez import —
        # bez człowieka — nie jest punktem oceny prepu: prep-kit je pokazuje,
        # ale „słaby” za pominięcie starego pytania byłby fałszywym alarmem
        # (decyzja Artura 25.09.2026, audyt runda 4). Przypięte ręcznie
        # (``added_by_user_id``) liczy się jak każde inne.
        if (
            link.question.source == InterviewQuestionSource.legacy_import
            and link.added_by_user_id is None
        ):
            continue
        if link.question.id not in seen:
            seen.add(link.question.id)
            questions.append(link.question)
    # Runda 8 (R8-N9-1): pytania klienta z TEGO SAMEGO źródła co prep-kit —
    # najnowsze z debriefów (ten sam limit) i tylko pasujące do technologii
    # roli (``_fits_job``). Dotąd ocena brała 20 najnowszych bez filtra roli,
    # więc prep roli Power Platform u klienta pytającego o Javę wychodził
    # „słaby” za pytania, których prep-kit prowadzącemu nie pokazał.
    from app.services.question_suggestions import (
        _fits_job,
        _tier_client_debrief,
        job_requirement_names,
    )

    requirement_names = job_requirement_names(job)
    entries: list[tuple[int, str]] = [(q.id, q.text or "") for q in questions]
    for suggested in await _tier_client_debrief(db, job):
        qid = suggested.question_id
        if qid is None or qid in seen or not _fits_job(suggested, requirement_names):
            continue
        seen.add(qid)
        entries.append((qid, suggested.text or ""))
    items.extend(
        Item(key=f"q:{qid}", label=text.strip(), kind="question")
        for qid, text in entries[:max_questions]
        if text.strip()
    )
    return items


def topic_items(config: PrepReviewConfig, prep_no: int) -> list[Item]:
    """Tematy prowadzącego z ustawień — klucz z numeru, bo nazwa bywa zmieniana."""
    rules = config.prep2 if prep_no == 2 else config.prep1
    return [
        Item(key=f"topic:{i}", label=t.label.strip(), kind="topic", required=t.required)
        for i, t in enumerate(rules.topics)
        if t.label.strip()
    ]


def followup_answer_items(prep1_followup: list[dict]) -> list[Item]:
    """Prep 2: punkty z notatki na Prep 2 jako punkty odpowiedzi kandydata."""
    return [
        Item(key=f"followup:{f['key']}", label=f["label"], kind="followup")
        for f in prep1_followup
    ]


def build_prompt(
    *,
    title: str,
    prep_no: int,
    items: list[Item],
    config: PrepReviewConfig,
    transcript: str,
) -> str:
    scale = config.answer_scale
    return _PROMPT.format(
        title=title or "rekrutacja",
        prep_no=prep_no,
        followup_hint=", punkty z notatki po Prepie 1" if prep_no == 2 else "",
        topics=fence(
            "topics",
            json_for_prompt(
                [{"key": i.key, "topic": i.label} for i in items if i.kind == "topic"]
            ),
        ),
        answers=fence(
            "answers",
            json_for_prompt(
                [
                    {"key": i.key, "kind": i.kind, "point": i.label}
                    for i in items
                    if i.kind != "topic"
                ]
            ),
        ),
        strong=scale["strong"].description,
        general=scale["general"].description,
        weak=scale["weak"].description,
        missing=scale["missing"].description,
        hints=fence("team_hints", config.ai_hints or "brak"),
        transcript=fence("transcript", transcript),
    )


def input_hash(material: dict, model: str) -> str:
    payload = json.dumps(
        {"v": PROMPT_VERSION, "model": model, **material},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ── Zapis ────────────────────────────────────────────────────────────────────


async def _upsert_note(
    db: AsyncSession, prep: PrepMeeting, transcript: PrepTranscript, content: str
) -> None:
    note = await db.scalar(
        select(Note).where(
            Note.external_source == NOTE_SOURCE, Note.external_id == str(prep.id)
        )
    )
    if note is None:
        note = Note(
            content=content,
            note_type=NoteType.meeting,
            candidate_id=prep.candidate_id,
            job_id=prep.job_id,
            author_id=prep.organizer_user_id,
            external_source=NOTE_SOURCE,
            external_id=str(prep.id),
            source_ref=f"{NOTE_SOURCE}:{prep.id}",
        )
        db.add(note)
        await db.flush()
    else:
        note.content = content
    transcript.summary_note_id = note.id


# ── Przebieg ─────────────────────────────────────────────────────────────────


def _call_model(model_chain: list[str], prompt: str) -> str:
    from app.services.claude_client import call_claude, text_of  # noqa: PLC0415

    message = call_claude(
        model=model_chain[0],
        fallback_models=model_chain[1:] or None,
        max_tokens=3000,
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": prompt}],
    )
    return text_of(message)


async def latest_prep1_review(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    at: Optional[datetime] = None,
) -> Optional[PrepReview]:
    """Udana ocena Prepu 1 BIEŻĄCEJ rundy pary — źródło notatki na Prep 2.

    Decyzja Artura 22.10.2026 (audyt, F42): tylko Prep 1 tej samej rundy
    rozmów (``prep_meetings.active_prep``, jak krok na karcie osoby). Gdy jego
    ocena się nie udała albo jeszcze jej nie ma, notatka jest pusta — dotąd
    brała najnowszą udaną ocenę pary i podsuwała punkty z poprzedniej rundy.
    ``at`` = chwila, względem której liczy się runda (start Prepu 2).
    """
    prep1 = await prep_meetings.active_prep(
        db, candidate_id=candidate_id, job_id=job_id, prep_no=1, at=at
    )
    if prep1 is None:
        return None
    return await db.scalar(
        select(PrepReview).where(
            PrepReview.prep_meeting_id == prep1.id, PrepReview.status == "ok"
        )
    )


async def _prep1_review(db: AsyncSession, prep: PrepMeeting) -> Optional[PrepReview]:
    if prep.prep_no != 2:
        return None
    event = await db.get(CalendarEvent, prep.calendar_event_id)
    return await latest_prep1_review(
        db,
        candidate_id=prep.candidate_id,
        job_id=prep.job_id,
        at=event.start_time if event is not None else None,
    )


def prep1_followup_of(review: Optional[PrepReview]) -> list[dict]:
    """Notatka na Prep 2 z oceny Prepu 1 (v2) albo z jej „Na Prep 2 zostało” (v1)."""
    if review is None:
        return []
    criteria = review.criteria or {}
    if isinstance(criteria.get("followup"), list):
        return [f for f in criteria["followup"] if isinstance(f, dict) and f.get("key")]
    return [
        {"key": f"v1:{i}", "label": label, "kind": "must", "reason": "missing"}
        for i, label in enumerate(review.remaining or [])
        if isinstance(label, str) and label.strip()
    ]


def prep1_strong_keys(review: Optional[PrepReview]) -> set[str]:
    if review is None:
        return set()
    criteria = review.criteria or {}
    if isinstance(criteria.get("answers"), list):
        return {a["key"] for a in criteria["answers"] if a.get("grade") == "strong"}
    return {i["key"] for i in criteria.get("items", []) if i.get("status") == "covered"}


async def review_prep(db: AsyncSession, prep_meeting_id: int) -> Optional[PrepReview]:
    """Ocena + notatka dla prepu z pobranym transkryptem. Commituje. Nie rzuca."""
    from app.services.ai_models import model_chain_for
    from app.services.ai_quota import ai_feature
    from app.services.llm_providers import api_key_configured

    prep = await db.get(PrepMeeting, prep_meeting_id)
    transcript = await db.scalar(
        select(PrepTranscript).where(PrepTranscript.prep_meeting_id == prep_meeting_id)
    )
    job = await db.get(Job, prep.job_id) if prep else None
    if prep is None or transcript is None or job is None:
        return None
    if not transcript.plain_text.strip():
        # Pusty transkrypt nie jest oceną — pętla oznacza go jako „bez nagrania”.
        return None

    config, config_version = await current_config(db)
    prep1 = await _prep1_review(db, prep)
    prep1_followup = prep1_followup_of(prep1)
    strong_before = prep1_strong_keys(prep1)
    must_and_questions = await build_items(
        db, job, max_questions=config.max_client_questions
    )
    if prep.prep_no == 2:
        # Prep 2 nie powtarza wszystkich must-have — must-have, które wymagają
        # powtórki, są w notatce na Prep 2 (punkty „followup”).
        must_and_questions = [i for i in must_and_questions if i.kind == "question"]
    items = [
        *topic_items(config, prep.prep_no),
        *must_and_questions,
        *followup_answer_items(prep1_followup),
    ]
    text = transcript.plain_text
    too_long = len(text) > MAX_TRANSCRIPT_CHARS
    chain = model_chain_for(FEATURE)
    material = {
        "title": job.title or "",
        "prep_no": prep.prep_no,
        "items": [[i.key, i.label] for i in items],
        "transcript": text,
        "config_version": config_version,
    }
    digest = input_hash(material, chain[0])
    review = await db.scalar(
        select(PrepReview).where(PrepReview.prep_meeting_id == prep.id)
    )
    if review is not None and review.input_hash == digest and review.status == "ok":
        return review

    talk_share = (
        float(transcript.talk_share) if transcript.talk_share is not None else None
    )
    parsed: Optional[dict] = None
    model_used: Optional[str] = None
    if too_long:
        logger.info("prep_review: transcript too long prep=%s", prep.id)
    if api_key_configured(chain[0]) and not too_long:
        prompt = build_prompt(
            title=job.title or "",
            prep_no=prep.prep_no,
            items=items,
            config=config,
            transcript=text,
        )
        try:
            async with ai_feature(db, FEATURE, user_id=prep.organizer_user_id):
                await db.commit()  # połączenie wraca do puli na czas modelu
                raw = await run_in_threadpool(_call_model, chain, prompt)
            parsed = parse_review(raw, items=items, transcript=text)
            model_used = chain[0]
        except Exception as exc:  # noqa: BLE001 — AI to dodatek, nigdy bramka
            logger.warning(
                "prep_review: model failed prep=%s (%s)", prep.id, type(exc).__name__
            )
            await db.rollback()
            parsed = None
        # Po commicie/rollbacku obiekty są wygasłe — doczytaj.
        prep = await db.get(PrepMeeting, prep_meeting_id)
        transcript = await db.scalar(
            select(PrepTranscript).where(
                PrepTranscript.prep_meeting_id == prep_meeting_id
            )
        )
        review = await db.scalar(
            select(PrepReview).where(PrepReview.prep_meeting_id == prep_meeting_id)
        )
        if prep is None or transcript is None:
            return None

    if review is None:
        review = PrepReview(
            prep_meeting_id=prep.id,
            candidate_id=prep.candidate_id,
            job_id=prep.job_id,
            status="unavailable",
        )
        db.add(review)

    level: Optional[str] = None
    total: Optional[int] = None
    followup: list[dict] = []
    compared: list[dict] = []
    if parsed is None:
        review.status = "unavailable"
        review.level = None
        review.coverage = None
        review.criteria = {}
        review.summary = None
        review.remaining = []
        review.input_hash = None
    else:
        if prep.prep_no == 2:
            parsed["answers"] = mark_covered_in_prep1(parsed["answers"], strong_before)
        score = score_review(
            parsed,
            config=config,
            prep_no=prep.prep_no,
            talk_share=talk_share,
            duration_seconds=transcript.duration_seconds,
        )
        level, total = score.level, score.total
        if prep.prep_no == 1:
            followup = followup_items(parsed, config)
            remaining = [f["label"] for f in followup]
        else:
            compared = comparison(parsed, prep1_followup)
            remaining = [c["label"] for c in compared if c["after"] != "strong"]
        review.status = "ok"
        review.level = level
        review.coverage = (
            Decimal(str(round(total / 100, 3))) if total is not None else None
        )
        review.criteria = {
            "version": 2,
            "topics": parsed["topics"],
            "answers": parsed["answers"],
            "went_well": parsed["went_well"],
            "went_wrong": parsed["went_wrong"],
            "improve": parsed["improve"],
            "own_projects": parsed["own_projects"],
            "scores": score.scores,
            "weights_used": score.weights_used,
            "total": total,
            "caps": score.caps,
            "followup": followup,
            "comparison": compared,
            # Kształt sprzed v2 — okno oceny i raporty czytają ``items``.
            "items": legacy_items(parsed),
        }
        review.summary = parsed["summary"]
        review.remaining = remaining
        review.input_hash = digest
    review.model = model_used
    review.prompt_version = PROMPT_VERSION
    review.config_version = config_version

    await _upsert_note(
        db,
        prep,
        transcript,
        note_content(
            prep_no=prep.prep_no,
            level=level,
            total=total,
            parsed=parsed,
            talk_share=talk_share,
            duration_seconds=transcript.duration_seconds,
            followup=followup,
            compared=compared,
        ),
    )
    await db.commit()
    await _notify_ready(db, prep, review)
    return review


async def _notify_ready(
    db: AsyncSession, prep: PrepMeeting, review: PrepReview
) -> None:
    """Dzwonek „Prep N oceniony” do pary. Awaria nie cofa oceny ani notatki."""
    from app.services import prep_notifications  # noqa: PLC0415 — cykl

    try:
        await prep_notifications.notify_review_ready(db, prep=prep, review=review)
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — powiadomienie to dodatek
        logger.warning(
            "prep_review: notify failed prep=%s (%s)", prep.id, type(exc).__name__
        )
        await db.rollback()
