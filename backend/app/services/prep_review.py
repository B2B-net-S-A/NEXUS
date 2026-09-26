"""Ocena prepu z transkryptu Teams + notatka z podsumowaniem (0370, F24).

Decyzje Artura 23.09.2026. Każdy prep oceniany osobno według trzech kryteriów:

1. czy omówiono każdy must-have rekrutacji (w pisowni Delivery Leada),
2. czy przećwiczono pytania, które zadaje TEN klient (bank debriefów +
   pytania przypięte do rekrutacji),
3. czy mówił kandydat, a nie prowadzący — udział w rozmowie liczy KOD
   z czasów wypowiedzi, model ocenia tylko, czy kandydat sam opowiedział
   swoje projekty.

Listy punktów buduje kod, model (GPT-6 Luna, zapas Sonnet 5) wskazuje status
i cytat. Cytat nieobecny w transkrypcie = punkt „nie było” z adnotacją
„bez dowodu” — model nie może zaliczyć punktu, którego nie ma w rozmowie.
Poziom oceny (słaby / OK / dobry) liczy kod z progów ``PREP_REVIEW_*``.

W Prepie 2 punkt zaliczony już w Prepie 1 ma status ``covered_in_prep1``
i nie liczy się do mianownika — Prep 2 skupiony na brakach nie może wyjść
„słaby” tylko dlatego, że nie powtarza tematów z Prepu 1.

AI to dodatek, nigdy bramka: awaria modelu daje ``status='unavailable'``
i ``level=NULL`` (nigdy „słaby”), a notatka zawiera same fakty.
Notatka niesie WYŁĄCZNIE podsumowanie — surowy transkrypt zostaje
w ``prep_transcripts`` (nocny ``notes_insights`` czyta notatki kandydata).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.ai_feature import AIFeatureKey
from app.models.interview_question import (
    InterviewQuestion,
    InterviewQuestionSource,
    JobQuestion,
)
from app.models.job import Job
from app.models.note import Note, NoteType
from app.models.prep_meeting import PrepMeeting, PrepReview, PrepTranscript
from app.services.prompt_fencing import fence, json_for_prompt

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.prep_review
PROMPT_VERSION = "prep-review-v1"
NOTE_SOURCE = "teams_prep"
# Runda 8 (R8-N9-9): transkrypt dłuższy niż limit NIE jest ucinany — tematy
# z końca długiego prepu wychodziłyby jako „nie było”. Ponad limitem ocena
# jest niedostępna (``level=NULL``), notatka mówi to wprost. 200 tys. znaków
# to ok. 4 godziny rozmowy (~55 tys. tokenów) — mieści się w kontekście
# modelu i zapasu.
MAX_TRANSCRIPT_CHARS = 200_000
MAX_QUESTIONS = 20
QUOTE_MIN_CHARS = 6
_STATUSES = ("covered", "partial", "missing")
LEVEL_LABELS = {"weak": "słaby", "ok": "OK", "good": "dobry"}

_PROMPT = """Jesteś doświadczonym rekruterem IT. Oceniasz PREP — rozmowę, w której
prowadzący z B2B.NET przygotowuje kandydata do rozmowy z klientem.

Rekrutacja: {title}
Prep nr {prep_no}.

Must-have rekrutacji (każdy oceń osobno):
{must}

Pytania, które zadaje ten klient (czy prowadzący je przećwiczył z kandydatem):
{questions}

Transkrypt prepu (linie „Mówca: wypowiedź”):
{transcript}

Dla KAŻDEGO must-have i KAŻDEGO pytania podaj status:
- "covered" — omówione konkretnie (kandydat opowiedział swoje doświadczenie
  albo odpowiedział na pytanie i prowadzący to dopracował),
- "partial" — wspomniane, ale bez konkretów,
- "missing" — nie było.
Dla "covered" i "partial" podaj "quote": DOSŁOWNY fragment transkryptu
(bez nazwy mówcy, 6–200 znaków), który to pokazuje. Bez cytatu = "missing".
Oceń też, czy kandydat SAM opowiedział o swoich projektach (own_projects).
Napisz krótkie podsumowanie prepu po polsku (3–5 zdań, bez stawek i nazwiska
kandydata): co przygotowano, co zostało do poprawy.

Odpowiedz WYŁĄCZNIE obiektem JSON:
{{"summary": string,
 "must_haves": [{{"key": string, "status": "covered"|"partial"|"missing", "quote": string|null}}],
 "client_questions": [{{"key": string, "status": "covered"|"partial"|"missing", "quote": string|null}}],
 "own_projects": {{"told": boolean, "quote": string|null}}}}
Klucze ("key") przepisz dokładnie z list powyżej."""


# ── Materiał dla modelu ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class Item:
    key: str
    label: str
    kind: str  # "must" | "question"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().casefold()


async def build_items(db: AsyncSession, job: Job) -> list[Item]:
    """Punkty oceny: must-have (pisownia DL-a) + pytania tego klienta."""
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
        for qid, text in entries[:MAX_QUESTIONS]
        if text.strip()
    )
    return items


def input_hash(material: dict, model: str) -> str:
    payload = json.dumps(
        {"v": PROMPT_VERSION, "model": model, **material},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ── Odpowiedź modelu → punkty z dowodem ──────────────────────────────────────


def _json_object(raw: str) -> dict:
    body = (raw or "").strip()
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in model output")
    data = json.loads(body[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("model output is not an object")
    return data


def _verified(quote: Any, haystack: str) -> Optional[str]:
    if not isinstance(quote, str):
        return None
    q = quote.strip().strip("„”\"'")
    if len(q) < QUOTE_MIN_CHARS or _norm(q) not in haystack:
        return None
    return q[:300]


def _status(value: Any) -> Optional[str]:
    """Status modelu bez wielkości liter („Covered” = „covered”)."""
    if not isinstance(value, str):
        return None
    status = value.strip().casefold()
    return status if status in _STATUSES else None


def _check_protocol(items: list[Item], given: dict[str, dict]) -> None:
    """Odpowiedź, która nie trzyma się kluczy albo statusów, to awaria modelu.

    Runda 8 (R8-N9-2): klucz „Java” zamiast „must:Java” albo pominięta grupa
    zerowały wszystkie punkty i dawały „słaby” z dzwonkiem do organizatora
    i HoR — a awaria modelu ma dawać ``unavailable`` (``level=NULL``). Model,
    który pominie pojedynczy punkt, dalej dostaje za niego „nie było”; odmowa
    dopiero, gdy nie pasuje co najmniej połowa kluczy albo statusów.
    """
    if not items:
        return
    matched = [given[i.key] for i in items if i.key in given]
    if len(matched) * 2 < len(items):
        raise ValueError("model output keys do not match the items")
    valid = sum(1 for entry in matched if _status(entry.get("status")) is not None)
    if valid * 2 < len(matched):
        raise ValueError("model output statuses are not recognised")


def parse_review(raw: str, *, items: list[Item], transcript: str) -> dict:
    """JSON modelu → ``{summary, items, own_projects}``; cytaty sprawdzone.

    Punkt, o którym model milczy, jest „nie było”. Status ``covered``/
    ``partial`` bez cytatu obecnego w transkrypcie też — z ``unverified``.
    Odpowiedź niezgodna z protokołem (brak grupy, obce klucze albo statusy
    dla większości punktów) rzuca ``ValueError`` — wołający zapisuje wtedy
    ocenę jako niedostępną.
    """
    data = _json_object(raw)
    haystack = _norm(transcript)
    given: dict[str, dict] = {}
    for group, kind in (("must_haves", "must"), ("client_questions", "question")):
        entries = data.get(group)
        if any(i.kind == kind for i in items) and not isinstance(entries, list):
            raise ValueError(f"model output without {group}")
        for entry in entries or []:
            if isinstance(entry, dict) and entry.get("key"):
                given.setdefault(str(entry["key"]).strip(), entry)
    _check_protocol(items, given)
    out: list[dict] = []
    for item in items:
        entry = given.get(item.key) or {}
        status = _status(entry.get("status")) or "missing"
        quote = _verified(entry.get("quote"), haystack) if status != "missing" else None
        unverified = status != "missing" and quote is None
        out.append(
            {
                "key": item.key,
                "label": item.label,
                "kind": item.kind,
                "status": "missing" if unverified else status,
                "quote": quote,
                "unverified": unverified,
            }
        )
    own = data.get("own_projects") if isinstance(data.get("own_projects"), dict) else {}
    own_quote = _verified(own.get("quote"), haystack)
    summary = data.get("summary")
    return {
        "summary": summary.strip()[:2000] if isinstance(summary, str) else None,
        "items": out,
        "own_projects": {
            "told": bool(own.get("told")) and own_quote is not None,
            "quote": own_quote,
        },
    }


# ── Poziom oceny (kod, nie model) ────────────────────────────────────────────


_POINTS = {"covered": 1.0, "partial": 0.5, "missing": 0.0}


def apply_prep1_coverage(items: list[dict], prep1_covered: set[str]) -> list[dict]:
    """Prep 2: punkt zaliczony w Prepie 1 nie obniża oceny."""
    out = []
    for item in items:
        if item["status"] != "covered" and item["key"] in prep1_covered:
            out.append({**item, "status": "covered_in_prep1"})
        else:
            out.append(item)
    return out


@dataclass(frozen=True)
class Grade:
    level: str
    coverage: Optional[float]
    remaining: list[str]


def grade(
    items: list[dict],
    *,
    talk_share: Optional[float],
    duration_seconds: int,
    own_projects_told: bool,
) -> Grade:
    scored = [i for i in items if i["status"] in _POINTS]
    coverage = (
        round(sum(_POINTS[i["status"]] for i in scored) / len(scored), 3)
        if scored
        else None
    )
    remaining = [i["label"] for i in scored if i["status"] != "covered"]
    too_short = duration_seconds < settings.PREP_REVIEW_MIN_MINUTES * 60
    weak = (
        too_short
        or (coverage is not None and coverage < settings.PREP_REVIEW_WEAK_COVERAGE)
        or (
            talk_share is not None and talk_share < settings.PREP_REVIEW_WEAK_TALK_SHARE
        )
    )
    if weak:
        return Grade("weak", coverage, remaining)
    good = (
        (coverage is None or coverage >= settings.PREP_REVIEW_GOOD_COVERAGE)
        and (talk_share is None or talk_share >= settings.PREP_REVIEW_GOOD_TALK_SHARE)
        and own_projects_told
    )
    return Grade("good" if good else "ok", coverage, remaining)


# ── Notatka ──────────────────────────────────────────────────────────────────


def _count(items: list[dict], kind: str) -> str:
    rel = [i for i in items if i["kind"] == kind]
    done = sum(1 for i in rel if i["status"] in ("covered", "covered_in_prep1"))
    return f"{done}/{len(rel)}"


def note_content(
    *,
    prep_no: int,
    level: Optional[str],
    items: list[dict],
    talk_share: Optional[float],
    duration_seconds: int,
    summary: Optional[str],
    remaining: list[str],
) -> str:
    facts = [f"Czas: {max(1, round(duration_seconds / 60))} min"]
    if talk_share is not None:
        facts.append(f"kandydat mówił {round(talk_share * 100)}% czasu")
    lines = [f"# Prep {prep_no} — podsumowanie z Teams"]
    if level:
        facts.insert(0, f"Ocena: {LEVEL_LABELS[level]}")
        facts.append(f"must-have {_count(items, 'must')}")
        if any(i["kind"] == "question" for i in items):
            facts.append(f"pytania klienta {_count(items, 'question')}")
    lines.append(" · ".join(facts))
    lines.append(
        summary
        or "Podsumowanie AI jest niedostępne — pełny transkrypt "
        "jest w kalendarzu „Rozmowy u klienta”."
    )
    if level and remaining:
        head = "Na Prep 2 zostało" if prep_no == 1 else "Nie omówiono"
        lines.append(f"{head}: " + "; ".join(remaining[:12]))
    return "\n\n".join(lines)


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


async def _prep1_covered(db: AsyncSession, prep: PrepMeeting) -> set[str]:
    if prep.prep_no != 2:
        return set()
    earlier = await db.scalar(
        select(PrepReview)
        .join(PrepMeeting, PrepMeeting.id == PrepReview.prep_meeting_id)
        .where(
            PrepMeeting.candidate_id == prep.candidate_id,
            PrepMeeting.job_id == prep.job_id,
            PrepMeeting.prep_no == 1,
            PrepReview.status == "ok",
        )
        .order_by(PrepReview.id.desc())
        .limit(1)
    )
    if earlier is None:
        return set()
    return {
        i["key"]
        for i in (earlier.criteria or {}).get("items", [])
        if i.get("status") == "covered"
    }


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

    items = await build_items(db, job)
    text = transcript.plain_text
    too_long = len(text) > MAX_TRANSCRIPT_CHARS
    chain = model_chain_for(FEATURE)
    material = {
        "title": job.title or "",
        "prep_no": prep.prep_no,
        "items": [[i.key, i.label] for i in items],
        "transcript": text,
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
        prompt = _PROMPT.format(
            title=job.title or "rekrutacja",
            prep_no=prep.prep_no,
            must=fence(
                "must_haves",
                json_for_prompt(
                    [{"key": i.key, "name": i.label} for i in items if i.kind == "must"]
                ),
            ),
            questions=fence(
                "client_questions",
                json_for_prompt(
                    [
                        {"key": i.key, "question": i.label}
                        for i in items
                        if i.kind == "question"
                    ]
                ),
            ),
            transcript=fence("transcript", text),
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

    if parsed is None:
        review.status = "unavailable"
        review.level = None
        review.coverage = None
        review.criteria = {}
        review.summary = None
        review.remaining = []
        review.input_hash = None
        level = None
        items_out: list[dict] = []
        remaining: list[str] = []
        summary = None
    else:
        items_out = apply_prep1_coverage(
            parsed["items"], await _prep1_covered(db, prep)
        )
        g = grade(
            items_out,
            talk_share=talk_share,
            duration_seconds=transcript.duration_seconds,
            own_projects_told=parsed["own_projects"]["told"],
        )
        level, remaining, summary = g.level, g.remaining, parsed["summary"]
        review.status = "ok"
        review.level = g.level
        review.coverage = Decimal(str(g.coverage)) if g.coverage is not None else None
        review.criteria = {"items": items_out, "own_projects": parsed["own_projects"]}
        review.summary = summary
        review.remaining = remaining
        review.input_hash = digest
    review.model = model_used
    review.prompt_version = PROMPT_VERSION

    await _upsert_note(
        db,
        prep,
        transcript,
        note_content(
            prep_no=prep.prep_no,
            level=level,
            items=items_out,
            talk_share=talk_share,
            duration_seconds=transcript.duration_seconds,
            summary=summary,
            remaining=remaining,
        ),
    )
    await db.commit()
    return review
