"""„Oceń z AI” na zaznaczonych osobach w oknie „Kandydaci do dodania” (0619).

Zgłoszenie rekrutera z 28.10.2026: zamiast ufać „Propozycjom z bazy” pobierał
CV hurtem (alarm „masowe przeglądanie CV”), wrzucał je do prywatnego czatu,
a ten mówił, kogo dodać i w jakiej kolejności dzwonić. Decyzja Artura
(makieta C, https://claude.ai/artifact/TBHtexa3vvyK76HW2vkSMS): to samo
w NEXUSIE — CV nie wychodzą poza firmę, a ocena zostaje przy rekrutacji.

Reguła (wzór przeglądu zgłoszeń — ``cv_quoted_evidence``):

1. Kod czyta całe CV (``raw_cv_text``), notatki-dowody (rozmowy, spotkania,
   ogólne, rozmowy rekrutacyjne — bez maili, ``EVIDENCE_NOTE_TYPES``; bez
   notatek, których treści oglądający nie widzi) i liczy must-have rekrutacji
   (``must_facts``).
2. Model (``AIFeatureKey.candidate_ai_assessment``) dostaje rolę z Championem
   i krytycznymi, oddaje ``{verdict, strength, reasons: [{text, quote}]}``.
   Powód, którego cytatu nie ma w CV, notatkach ani profilu, znika.
3. Werdykt (``decide``): ``call`` / ``maybe`` / ``no_fit``. „Nie pasuje” bez
   sprawdzonego cytatu i „Dzwoń” bez cytatu albo przy must-have znalezionych
   w mniej niż połowie spadają do „Może”. AI niczego nie odrzuca i nie
   zmienia procentu dopasowania — tylko układa kolejność (``call_order_key``).
4. Brak CV albo awaria modelu = osoba bez werdyktu („AI nie oceniło”),
   którą dalej da się dodać.

Każda osoba to jeden wiersz ``candidate_ai_assessments`` (kto, kiedy, kogo,
werdykt) i jedno zdarzenie ``activities`` (``AUDIT_ACTION``) na paczkę.
Alarm o masowym przeglądaniu CV (``candidate_data_access_alerts``) tego
zdarzenia nie liczy — CV nie opuszcza serwera, rekruter widzi tylko cytaty.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence

import anyio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today, local_day_start_utc
from app.models.activity import Activity
from app.models.ai_feature import AIFeatureKey
from app.models.candidate import Candidate
from app.models.candidate_ai_assessment import CandidateAiAssessment
from app.models.note import Note, NoteType
from app.services.ai_models import fallbacks_for, model_for
from app.services.ai_quota import ai_feature
from app.services.cv_quoted_evidence import (
    job_prompt_block,
    keep_quoted_reasons,
    model_json,
    must_facts,
    normalize,
)
from app.services.llm_prompts import CANDIDATE_AI_ASSESSMENT
from app.services.prompt_fencing import fence

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.candidate_ai_assessment
AUDIT_ACTION = "ai_candidates_assessed"

VERDICT_CALL = "call"
VERDICT_MAYBE = "maybe"
VERDICT_NO_FIT = "no_fit"
VERDICTS = (VERDICT_CALL, VERDICT_MAYBE, VERDICT_NO_FIT)
# Kolejność dzwonienia: Dzwoń, Może, Nie pasuje, a na końcu „AI nie oceniło”.
VERDICT_ORDER = {VERDICT_CALL: 0, VERDICT_MAYBE: 1, VERDICT_NO_FIT: 2}
UNASSESSED_ORDER = 3

# „Dzwoń” tylko, gdy kod widzi co najmniej połowę must-have (jak 0404).
MUST_RATIO_CALL = 0.5

# Zaznaczenie z makiety: „do ok. 30 osób”. Przeglądarka wysyła je paczkami
# (`MAX_PER_REQUEST`), żeby żadne żądanie nie czekało dłużej niż jedna runda
# modelu i żeby panel pokazywał postęp.
MAX_BATCH = 30
MAX_PER_REQUEST = 6
# Limit na osobę i dzień (kalendarz firmy): 150 ocenionych osób = pięć pełnych
# zaznaczeń po 30. Zgłaszający ocenia ~30–40 osób dziennie; limit nie jest
# budżetem AI (tego nie ma — `nexus-bez-limitow-ai.md`), tylko zaporą przed
# przeczesaniem bazy przez AI hurtem. Wynik przepisany z oceny < 24 h limitu
# nie zużywa.
DAILY_PEOPLE_LIMIT = int(os.environ.get("CANDIDATE_AI_ASSESSMENT_DAILY_LIMIT", "150"))
REUSE_WITHIN = timedelta(hours=24)
LATEST_WITHIN = timedelta(days=7)

CV_CHAR_LIMIT = 24_000
NOTES_CHAR_LIMIT = 8_000
NOTE_CHAR_LIMIT = 3_000
REASON_LIMIT = 2
MODEL_TOTAL_TIMEOUT_SECONDS = 45.0
# Wątki na wywołania modelu dla CAŁEGO serwera — własny limiter zamiast
# wspólnej puli (40 wątków): kilka osób klikających naraz zajęłoby ją na
# 45 s i zatrzymało inne trasy z `run_in_threadpool`.
MODEL_THREADS = 8
_limiter: Optional[anyio.CapacityLimiter] = None


def _model_limiter() -> anyio.CapacityLimiter:
    global _limiter
    if _limiter is None:
        _limiter = anyio.CapacityLimiter(MODEL_THREADS)
    return _limiter


SOURCE_CV = "cv"
SOURCE_NOTE = "note"
SOURCE_PROFILE = "profile"

ERROR_NO_CV = "no_cv"


class DailyLimitExceeded(Exception):
    def __init__(self, remaining: int) -> None:
        super().__init__(remaining)
        self.remaining = remaining


# ── Reguła (czyste funkcje) ────────────────────────────────────────────────


def parse_model(raw: Optional[str]) -> tuple[Optional[str], Optional[int], list]:
    """JSON modelu → (werdykt albo ``None``, siła 1–5 albo ``None``, surowe powody)."""
    data = model_json(raw)
    verdict = data.get("verdict")
    verdict = verdict if verdict in VERDICTS else None
    strength = data.get("strength")
    try:
        strength = min(5, max(1, int(strength))) if strength is not None else None
    except (TypeError, ValueError):
        strength = None
    reasons = data.get("reasons")
    return verdict, strength, reasons if isinstance(reasons, list) else []


def decide(
    *,
    model_verdict: Optional[str],
    kept_reasons: Sequence[dict],
    must_found: int,
    must_total: int,
) -> Optional[str]:
    """Werdykt w panelu. ``None`` = „AI nie oceniło”.

    * „Nie pasuje” bez sprawdzonego cytatu → „Może” (bez dowodu nikogo nie
      spychamy na koniec). Z cytatem zostaje także przy must-have znalezionych
      w tekście — słowo bywa użyte w innym znaczeniu (nazwa aplikacji
      z innej dziedziny), a to widzi tylko model.
    * „Dzwoń” bez cytatu albo przy must-have znalezionych w < 50% → „Może”
      (obietnica, której kod nie potwierdza).
    """
    if model_verdict not in VERDICTS:
        return None
    if model_verdict == VERDICT_NO_FIT and not kept_reasons:
        return VERDICT_MAYBE
    if model_verdict == VERDICT_CALL:
        ratio = (must_found / must_total) if must_total > 0 else None
        if not kept_reasons or (ratio is not None and ratio < MUST_RATIO_CALL):
            return VERDICT_MAYBE
    return model_verdict


def call_order_key(row: dict) -> tuple:
    """Kolejność dzwonienia: werdykt, siła, must-have, miejsce w zaznaczeniu.

    To samo liczy panel (``lib/ai-assessment.ts``) — zmiana tu = zmiana tam.
    """
    verdict = row.get("verdict")
    total = row.get("must_total") or 0
    ratio = (row.get("must_found") or 0) / total if total else 0.0
    return (
        VERDICT_ORDER.get(verdict, UNASSESSED_ORDER),
        -(row.get("strength") or 0),
        -ratio,
        row.get("selection_index") or 0,
    )


def tag_sources(
    reasons: Sequence[dict], *, cv: str, notes: str, profile: str
) -> list[dict]:
    """Do każdego powodu dopisz, skąd jest cytat: CV, notatka albo profil."""
    hay = ((SOURCE_CV, normalize(cv)), (SOURCE_NOTE, normalize(notes)))
    out: list[dict] = []
    for reason in reasons:
        needle = normalize(reason.get("quote"))
        source = next((name for name, h in hay if needle and needle in h), None)
        out.append({**reason, "source": source or SOURCE_PROFILE})
    return out


def notes_block(note_texts: Sequence[str]) -> str:
    """Notatki-dowody dla modelu: najnowsze pierwsze, przycięte."""
    parts: list[str] = []
    used = 0
    for content in note_texts:
        chunk = (content or "").strip()[:NOTE_CHAR_LIMIT]
        if not chunk:
            continue
        if used + len(chunk) > NOTES_CHAR_LIMIT:
            break
        parts.append(chunk)
        used += len(chunk)
    return "\n---\n".join(parts)


# ── Dane osoby ─────────────────────────────────────────────────────────────


@dataclass
class Person:
    candidate: Any
    candidate_id: int
    selection_index: int
    cv_text: str = ""
    notes_text: str = ""
    profile: str = ""
    must_found: int = 0
    must_total: int = 0


@dataclass
class Outcome:
    candidate_id: int
    selection_index: int
    verdict: Optional[str] = None
    strength: Optional[int] = None
    must_found: int = 0
    must_total: int = 0
    reasons: list[dict] = field(default_factory=list)
    model: Optional[str] = None
    error: Optional[str] = None
    model_called: bool = False
    reused_from_id: Optional[int] = None


async def load_note_texts(
    db: AsyncSession, user: Any, candidate_ids: Sequence[int]
) -> dict[int, list[str]]:
    """Notatki-dowody osób (bez maili i bez notatek zakrytych przed ``user``)."""
    from app.api.candidate_access import (
        hidden_send_note_ids,
        note_rate_visibility_clause,
    )
    from app.services import note_kinds
    from app.services.must_text_evidence import (
        EVIDENCE_NOTE_TYPES,
        evidence_note_text,
    )

    ids = sorted({int(i) for i in candidate_ids})
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(Note.id, Note.candidate_id, Note.content, Note.kind)
            .where(
                Note.candidate_id.in_(ids),
                Note.source_deleted_at.is_(None),
                Note.note_type.in_([NoteType(t) for t in EVIDENCE_NOTE_TYPES]),
                text(note_kinds.ai_readable_sql("notes")),
                note_rate_visibility_clause(user),
            )
            .order_by(
                func.coalesce(Note.source_created_at, Note.created_at).desc(),
                Note.id.desc(),
            )
        )
    ).all()
    hidden = await hidden_send_note_ids(db, user, [r.id for r in rows])
    out: dict[int, list[str]] = {}
    for row in rows:
        if row.id in hidden:
            continue
        body = evidence_note_text(row.kind, row.content)
        if body.strip():
            out.setdefault(row.candidate_id, []).append(body)
    return out


def prepare(job: Any, candidate: Any, index: int, notes: Sequence[str]) -> Person:
    from app.services.must_text_evidence import cv_text, profile_text

    cv = cv_text(candidate)[:CV_CHAR_LIMIT]
    notes_text = notes_block(notes)
    found, total = must_facts(job, candidate, cv, [notes_text] if notes_text else ())
    return Person(
        candidate=candidate,
        candidate_id=candidate.id,
        selection_index=index,
        cv_text=cv,
        notes_text=notes_text,
        profile=profile_text(candidate),
        must_found=found,
        must_total=total,
    )


def prompt_for(job_block: str, person: Person) -> str:
    return CANDIDATE_AI_ASSESSMENT.render(
        job=job_block,
        cv=fence("cv", person.cv_text),
        notes=fence("notatki", person.notes_text or "(brak notatek)"),
    )


def _call_model(prompt: str) -> str:
    """Jedno wywołanie modelu (w wątku). Osobna funkcja — testy ją podmieniają."""
    from app.services.claude_client import call_claude_text  # noqa: PLC0415

    return call_claude_text(
        total_timeout=MODEL_TOTAL_TIMEOUT_SECONDS,
        model=model_for(FEATURE),
        fallback_models=fallbacks_for(FEATURE),
        max_tokens=700,
        thinking={"type": "disabled"},
        system=CANDIDATE_AI_ASSESSMENT.system_prompt or "",
        messages=[{"role": "user", "content": prompt}],
    )


def outcome_from(person: Person, raw: Any) -> Outcome:
    """Odpowiedź modelu (albo wyjątek) → wynik osoby. Nigdy nie rzuca."""
    base = Outcome(
        candidate_id=person.candidate_id,
        selection_index=person.selection_index,
        must_found=person.must_found,
        must_total=person.must_total,
        model_called=True,
    )
    if isinstance(raw, BaseException):
        base.error = f"model_error:{type(raw).__name__}"[:120]
        return base
    try:
        verdict, strength, raw_reasons = parse_model(raw)
    except Exception as exc:  # noqa: BLE001 — zła odpowiedź = brak werdyktu
        base.error = f"model_error:{type(exc).__name__}"[:120]
        return base
    kept = keep_quoted_reasons(
        raw_reasons,
        (person.cv_text, person.notes_text, person.profile),
        limit=REASON_LIMIT,
    )
    base.verdict = decide(
        model_verdict=verdict,
        kept_reasons=kept,
        must_found=person.must_found,
        must_total=person.must_total,
    )
    base.strength = strength
    base.reasons = tag_sources(
        kept, cv=person.cv_text, notes=person.notes_text, profile=person.profile
    )
    base.model = model_for(FEATURE)
    base.error = None if verdict is not None else "model_no_verdict"
    return base


# ── Limit i ponowne użycie ─────────────────────────────────────────────────


async def used_today(db: AsyncSession, user_id: int) -> int:
    start = local_day_start_utc(business_today())
    return int(
        await db.scalar(
            select(func.count(CandidateAiAssessment.id)).where(
                CandidateAiAssessment.assessed_by == user_id,
                CandidateAiAssessment.model_called.is_(True),
                CandidateAiAssessment.created_at >= start,
            )
        )
        or 0
    )


async def recent_by_candidate(
    db: AsyncSession, *, job_id: int, user_id: int, candidate_ids: Sequence[int]
) -> dict[int, CandidateAiAssessment]:
    """Ocena tej osoby w tej rekrutacji przez tę samą osobę z ostatnich 24 h."""
    since = datetime.now(timezone.utc) - REUSE_WITHIN
    rows = (
        await db.scalars(
            select(CandidateAiAssessment)
            .where(
                CandidateAiAssessment.job_id == job_id,
                CandidateAiAssessment.assessed_by == user_id,
                CandidateAiAssessment.candidate_id.in_(list(candidate_ids)),
                CandidateAiAssessment.verdict.is_not(None),
                CandidateAiAssessment.created_at >= since,
            )
            .order_by(CandidateAiAssessment.created_at.desc())
        )
    ).all()
    out: dict[int, CandidateAiAssessment] = {}
    for row in rows:
        out.setdefault(row.candidate_id, row)
    return out


# ── Ocena ───────────────────────────────────────────────────────────────────


async def assess(
    db: AsyncSession,
    *,
    job: Any,
    user: Any,
    batch_id: str,
    candidate_ids: Sequence[int],
    first_index: int = 0,
    refresh: bool = False,
) -> list[CandidateAiAssessment]:
    """Oceń paczkę osób i zapisz wyniki. Awaria modelu nie rzuca.

    Rzuca ``DailyLimitExceeded``, gdy osób do oceny modelem jest więcej, niż
    zostało z dziennego limitu — wtedy nic nie jest wywoływane ani zapisane.
    """
    # Same id, nie obiekty ORM: `rollback()` po awarii wygasza wszystko, co sesja
    # wczytała, a leniwe odświeżenie w AsyncSession kończy się MissingGreenlet.
    job_id, user_id = job.id, user.id
    ids = list(dict.fromkeys(int(i) for i in candidate_ids))
    candidates = {
        c.id: c
        for c in (
            await db.scalars(select(Candidate).where(Candidate.id.in_(ids)))
        ).all()
    }
    ids = [i for i in ids if i in candidates]
    reused = (
        {}
        if refresh
        else await recent_by_candidate(
            db, job_id=job_id, user_id=user_id, candidate_ids=ids
        )
    )
    notes = await load_note_texts(db, user, [i for i in ids if i not in reused])

    outcomes: list[Outcome] = []
    to_call: list[Person] = []
    for offset, cid in enumerate(ids):
        index = first_index + offset
        previous = reused.get(cid)
        if previous is not None:
            outcomes.append(
                Outcome(
                    candidate_id=cid,
                    selection_index=index,
                    verdict=previous.verdict,
                    strength=previous.strength,
                    must_found=previous.must_found,
                    must_total=previous.must_total,
                    reasons=list(previous.reasons or []),
                    model=previous.model,
                    reused_from_id=previous.reused_from_id or previous.id,
                )
            )
            continue
        person = prepare(job, candidates[cid], index, notes.get(cid, ()))
        if not person.cv_text.strip():
            outcomes.append(
                Outcome(
                    candidate_id=cid,
                    selection_index=index,
                    must_found=person.must_found,
                    must_total=person.must_total,
                    error=ERROR_NO_CV,
                )
            )
            continue
        to_call.append(person)

    if to_call:
        remaining = DAILY_PEOPLE_LIMIT - await used_today(db, user_id)
        if len(to_call) > remaining:
            raise DailyLimitExceeded(max(0, remaining))
        job_block = job_prompt_block(job, with_critical=True)
        prompts = [prompt_for(job_block, p) for p in to_call]
        try:
            async with ai_feature(db, FEATURE, user_id=user_id, units=len(to_call)):
                await db.commit()  # zwolnij połączenie na czas modelu
                answers = await asyncio.gather(
                    *(
                        anyio.to_thread.run_sync(
                            _call_model, p, limiter=_model_limiter()
                        )
                        for p in prompts
                    ),
                    return_exceptions=True,
                )
        except Exception as exc:  # noqa: BLE001 — AI układa kolejność, nie blokuje
            logger.warning(
                "candidate_ai_assessment: model call failed (%s)", type(exc).__name__
            )
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                logger.warning("candidate_ai_assessment: rollback after model failure")
            answers = [exc] * len(to_call)
        for person, raw in zip(to_call, answers):
            if isinstance(raw, BaseException):
                logger.warning(
                    "candidate_ai_assessment: model failed (%s)", type(raw).__name__
                )
            outcomes.append(outcome_from(person, raw))

    outcomes.sort(key=lambda o: o.selection_index)
    rows = [
        CandidateAiAssessment(
            batch_id=batch_id,
            job_id=job_id,
            candidate_id=o.candidate_id,
            assessed_by=user_id,
            selection_index=o.selection_index,
            verdict=o.verdict,
            strength=o.strength,
            must_found=o.must_found,
            must_total=o.must_total,
            reasons=o.reasons,
            model=o.model,
            error=o.error,
            model_called=o.model_called,
            reused_from_id=o.reused_from_id,
        )
        for o in outcomes
    ]
    db.add_all(rows)
    verdicts = Counter(o.verdict or "none" for o in outcomes)
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action=AUDIT_ACTION,
            user_id=user_id,
            # Same id i liczby — bez nazwisk, cytatów i treści CV.
            details={
                "batch_id": batch_id,
                "candidate_ids": [o.candidate_id for o in outcomes],
                "model_called": sum(1 for o in outcomes if o.model_called),
                "reused": sum(1 for o in outcomes if o.reused_from_id),
                "verdicts": dict(verdicts),
            },
        )
    )
    await db.commit()
    return rows


async def batch_rows(
    db: AsyncSession, *, job_id: int, user_id: int, batch_id: Optional[str] = None
) -> list[CandidateAiAssessment]:
    """Wiersze paczki (albo ostatniej paczki tej osoby w rekrutacji, ≤ 7 dni)."""
    if batch_id is None:
        since = datetime.now(timezone.utc) - LATEST_WITHIN
        batch_id = await db.scalar(
            select(CandidateAiAssessment.batch_id)
            .where(
                CandidateAiAssessment.job_id == job_id,
                CandidateAiAssessment.assessed_by == user_id,
                CandidateAiAssessment.created_at >= since,
            )
            .order_by(
                CandidateAiAssessment.created_at.desc(),
                CandidateAiAssessment.id.desc(),
            )
            .limit(1)
        )
        if batch_id is None:
            return []
    return list(
        (
            await db.scalars(
                select(CandidateAiAssessment)
                .where(
                    CandidateAiAssessment.job_id == job_id,
                    CandidateAiAssessment.assessed_by == user_id,
                    CandidateAiAssessment.batch_id == batch_id,
                )
                .order_by(CandidateAiAssessment.selection_index)
            )
        ).all()
    )
