"""Akademia — warstwa bazy: nabór z ogłoszeń, sortowanie Luną, akcje, terminy.

Czyste reguły są w ``academy_rules`` (sortowanie) i ``academy_flow``
(przejścia). Tu tylko zapytania i zapis.

Nabór z ogłoszeń: każdy kandydat, który ma jakikolwiek wiersz etapu
(``candidate_stages``) w rekrutacji-źródle programu (od ``since``), dostaje
wiersz ``academy_applications``. Jedna osoba = jeden wiersz w programie:

* wiersza nie ma → nowy (``new``), sortuje go Luna;
* osoba odrzucona (``rejected``) aplikuje znowu → tylko stempel
  ``reapplied_at``; nie wraca do telefonów i Luna nie czyta jej CV
  (decyzja Artura: wykluczenie na zawsze);
* osoba, która sama zrezygnowała (``withdrew``), aplikuje znowu → wraca na
  początek jako nowe zgłoszenie.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.academy import (
    AcademyApplication,
    AcademyProgram,
    AcademyProgramSource,
    AcademySession,
)
from app.models.activity import Activity
from app.models.ai_feature import AIFeatureKey
from app.models.candidate import Candidate
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services import academy_rules
from app.services.academy_flow import (
    STATUS_LABELS,
    AcademyActionError,
    ActionInput,
    apply_action,
)
from app.services.ai_models import fallbacks_for, model_for
from app.services.ai_quota import ai_feature
from app.services.llm_prompts import ACADEMY_SCREENING
from app.services.prompt_fencing import fence
from app.core.scheduling import business_today

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.academy_screening
SCREENING_VERSION = 1
CV_CHAR_LIMIT = 12000
SCREEN_BATCH = 25
APPLICATIONS_LIST_LIMIT = 2000
_CLOSED_STATUSES = ("rejected", "withdrew")
# Etapy, którymi osoba WCHODZI do rekrutacji z ogłoszenia. Tylko nowy wiersz
# na tych etapach jest ponownym zgłoszeniem — przesunięcie karty w Traffit
# (np. na „Odrzucony”) po decyzji w akademii nie może udawać, że ktoś wrócił.
ENTRY_STAGES = (PipelineStage.posting, PipelineStage.new)

# Jeden bieg sortowania na program naraz (backend = jeden proces uvicorna):
# pętla tła i przycisk „Pobierz zgłoszenia” nie czytają tego samego CV dwa razy.
_program_locks: dict[int, asyncio.Lock] = {}


def _lock_for(program_id: int) -> asyncio.Lock:
    lock = _program_locks.get(program_id)
    if lock is None:
        lock = asyncio.Lock()
        _program_locks[program_id] = lock
    return lock


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── nabór z ogłoszeń ───────────────────────────────────────────────────────


async def intake_program(db: AsyncSession, program_id: int) -> dict[str, int]:
    """Dociąga zgłoszenia z ogłoszeń-źródeł programu. Commit robi wołający."""
    sources = (
        (
            await db.execute(
                select(AcademyProgramSource).where(
                    AcademyProgramSource.program_id == program_id
                )
            )
        )
        .scalars()
        .all()
    )
    stats = {"new": 0, "reapplied": 0, "returned": 0}
    if not sources:
        return stats

    # Kandydat → (pierwszy wiersz etapu, ostatnie WEJŚCIE z ogłoszenia albo
    # None, rekrutacja ostatniego wejścia).
    applied: dict[int, tuple[datetime, Optional[datetime], int]] = {}
    for source in sources:
        conditions = [CandidateStage.job_id == source.job_id]
        if source.since is not None:
            conditions.append(
                CandidateStage.moved_at
                >= datetime(
                    source.since.year,
                    source.since.month,
                    source.since.day,
                    tzinfo=timezone.utc,
                )
            )
        rows = (
            await db.execute(
                select(
                    CandidateStage.candidate_id,
                    func.min(CandidateStage.moved_at),
                    func.max(CandidateStage.moved_at).filter(
                        CandidateStage.stage.in_(ENTRY_STAGES)
                    ),
                )
                .where(*conditions)
                .group_by(CandidateStage.candidate_id)
            )
        ).all()
        for candidate_id, first_at, last_at in rows:
            if first_at is None:
                continue
            prev = applied.get(candidate_id)
            if prev is None:
                applied[candidate_id] = (first_at, last_at, source.job_id)
                continue
            first = min(prev[0], first_at)
            if last_at is not None and (prev[1] is None or last_at > prev[1]):
                applied[candidate_id] = (first, last_at, source.job_id)
            else:
                applied[candidate_id] = (first, prev[1], prev[2])
    if not applied:
        return stats

    existing = {
        row.candidate_id: row
        for row in (
            await db.execute(
                select(AcademyApplication)
                .where(
                    AcademyApplication.program_id == program_id,
                    AcademyApplication.candidate_id.in_(list(applied)),
                )
                # Wiersz, na którym człowiek właśnie klika akcję, pomijamy w tym
                # biegu — inaczej reset „zrezygnował → nowy” nadpisałby „Przywróć”.
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    }

    now = _now()
    to_insert = []
    for candidate_id, (first_at, last_at, job_id) in applied.items():
        row = existing.get(candidate_id)
        if row is None:
            to_insert.append(
                {
                    "program_id": program_id,
                    "candidate_id": candidate_id,
                    "source_job_id": job_id,
                    "applied_at": first_at,
                    "status": "new",
                }
            )
            continue
        closed_at = row.closed_at
        if closed_at is None or last_at is None or last_at <= closed_at:
            continue
        if row.status == "rejected":
            if row.reapplied_at is None or last_at > row.reapplied_at:
                row.reapplied_at = last_at
                stats["reapplied"] += 1
        elif row.status == "withdrew":
            _reset_to_new(row, applied_at=last_at, source_job_id=job_id, now=now)
            stats["returned"] += 1

    if to_insert:
        result = await db.execute(
            pg_insert(AcademyApplication)
            .values(to_insert)
            .on_conflict_do_nothing(
                constraint="uq_academy_applications_program_candidate"
            )
            .returning(AcademyApplication.id)
        )
        stats["new"] = len(result.all())
    return stats


def _reset_to_new(
    row: AcademyApplication, *, applied_at: datetime, source_job_id: int, now: datetime
) -> None:
    row.status = "new"
    row.applied_at = applied_at
    row.source_job_id = source_job_id
    for attr in (
        "screening_verdict",
        "screening",
        "screened_at",
        "experience_years",
        "session_id",
        "attended",
        "task_due",
        "task_result",
        "contract_sent_at",
        "signed_at",
        "cohort_month",
        "closed_stage",
        "closed_reason",
        "closed_at",
        "closed_by",
        "reapplied_at",
    ):
        setattr(row, attr, None)
    row.call_attempts = 0
    row.last_call_at = None
    row.updated_at = now


# ── sortowanie Luną ────────────────────────────────────────────────────────


def _call_model(prompt: str) -> str:
    """Jedno wywołanie modelu (w wątku). Osobna funkcja — testy ją podmieniają."""
    from app.services.claude_client import call_claude_text  # noqa: PLC0415

    return call_claude_text(
        model=model_for(FEATURE),
        fallback_models=fallbacks_for(FEATURE),
        max_tokens=1500,
        thinking={"type": "disabled"},
        system=ACADEMY_SCREENING.system_prompt or "",
        messages=[{"role": "user", "content": prompt}],
    )


def _parse_json(raw: str) -> Any:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("brak JSON-a w odpowiedzi")
    return json.loads(text[start : end + 1])


async def _screen_one(application_id: int, program: AcademyProgram) -> Optional[str]:
    """Posortuj jedno zgłoszenie. Zwraca werdykt albo ``None`` (pominięte)."""
    async with AsyncSessionLocal() as db:
        row = await db.get(AcademyApplication, application_id)
        if row is None or row.status != "new" or row.screening_verdict is not None:
            return None
        candidate = await db.get(Candidate, row.candidate_id)
        if candidate is None:
            return None
        education = candidate.education
        experience = candidate.experience
        languages = candidate.languages
        cv_text = (candidate.raw_cv_text or "")[:CV_CHAR_LIMIT]

        parsed: Any = None
        model_error: Optional[str] = None
        if program.luna_enabled and cv_text.strip():
            try:
                async with ai_feature(db, FEATURE, user_id=None):
                    await db.commit()  # zwolnij połączenie na czas modelu
                    raw = await run_in_threadpool(
                        _call_model, ACADEMY_SCREENING.render(cv=fence("cv", cv_text))
                    )
                parsed = _parse_json(raw)
            except Exception as exc:  # noqa: BLE001 — Luna sortuje, nigdy nie blokuje
                model_error = type(exc).__name__
                logger.warning(
                    "academy: screening failed application=%s (%s)",
                    application_id,
                    model_error,
                )
                try:
                    await db.rollback()
                except Exception:  # noqa: BLE001
                    logger.warning("academy: rollback after screening failure failed")

        result = academy_rules.evaluate(
            education=education,
            experience=experience,
            languages=languages,
            model_parsed=parsed,
            cv_text=cv_text,
            max_experience_years=program.max_experience_years,
            require_polish=program.require_polish,
            today=business_today(),
            model_error=model_error,
        )
        payload = {
            "version": SCREENING_VERSION,
            "facts": result.facts,
            "reasons": result.reasons,
            "model": model_for(FEATURE) if parsed is not None else None,
            "error": model_error,
        }
        new_status = (
            "new" if result.verdict == academy_rules.VERDICT_SKIP else "to_call"
        )
        # Warunkowy zapis: równoległy bieg albo decyzja człowieka w międzyczasie wygrywa.
        updated = await db.execute(
            update(AcademyApplication)
            .where(
                AcademyApplication.id == application_id,
                AcademyApplication.status == "new",
                AcademyApplication.screening_verdict.is_(None),
            )
            .values(
                screening_verdict=result.verdict,
                screening=payload,
                screened_at=_now(),
                experience_years=result.experience_years,
                status=new_status,
            )
        )
        await db.commit()
        return result.verdict if updated.rowcount else None


async def screen_pending(program_id: int, limit: int = SCREEN_BATCH) -> dict[str, int]:
    """Posortuj do ``limit`` nowych zgłoszeń programu (własne sesje)."""
    stats = {"call": 0, "review": 0, "skip": 0}
    async with AsyncSessionLocal() as db:
        program = await db.get(AcademyProgram, program_id)
        if program is None:
            return stats
        ids = (
            (
                await db.execute(
                    select(AcademyApplication.id)
                    .where(
                        AcademyApplication.program_id == program_id,
                        AcademyApplication.status == "new",
                        AcademyApplication.screening_verdict.is_(None),
                    )
                    .order_by(AcademyApplication.applied_at)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        db.expunge(program)
    for application_id in ids:
        verdict = await _screen_one(application_id, program)
        if verdict:
            stats[verdict] += 1
    return stats


async def sync_program(program_id: int) -> dict[str, int]:
    """Nabór + sortowanie jednego programu. Jeden bieg na program naraz."""
    lock = _lock_for(program_id)
    if lock.locked():
        return {"busy": 1}
    async with lock:
        async with AsyncSessionLocal() as db:
            intake = await intake_program(db, program_id)
            await db.commit()
        screened = await screen_pending(program_id)
    return {**intake, **screened}


_background: set[asyncio.Task] = set()


async def intake_now(program_id: int) -> Optional[dict[str, int]]:
    """Sam nabór (szybki, w żądaniu). ``None`` = inny bieg trzyma program."""
    lock = _lock_for(program_id)
    if lock.locked():
        return None
    async with lock:
        async with AsyncSessionLocal() as db:
            stats = await intake_program(db, program_id)
            await db.commit()
    return stats


async def _screen_in_background(program_id: int) -> None:
    lock = _lock_for(program_id)
    if lock.locked():
        return  # trwa bieg pętli — posortuje te same zgłoszenia
    async with lock:
        try:
            await screen_pending(program_id)
        except Exception:  # noqa: BLE001 — sortowanie w tle nigdy nie wywraca żądania
            logger.exception(
                "academy: background screening program=%s failed", program_id
            )


def start_screening(program_id: int) -> None:
    """Sortowanie Luną w tle — przycisk na ekranie nie czeka na model.

    Referencja w ``_background``: zadanie bez niej może zostać zebrane przez
    GC w trakcie działania.
    """
    task = asyncio.create_task(_screen_in_background(program_id))
    _background.add(task)
    task.add_done_callback(_background.discard)


async def wait_for_background() -> None:
    """Czeka na sortowanie w tle (testy, łagodne zamknięcie)."""
    while _background:
        await asyncio.gather(*list(_background), return_exceptions=True)


async def sync_all_active() -> dict[int, dict[str, int]]:
    async with AsyncSessionLocal() as db:
        ids = (
            (
                await db.execute(
                    select(AcademyProgram.id).where(AcademyProgram.is_active.is_(True))
                )
            )
            .scalars()
            .all()
        )
    results: dict[int, dict[str, int]] = {}
    for program_id in ids:
        try:
            results[program_id] = await sync_program(program_id)
        except Exception:  # noqa: BLE001 — jeden program nie blokuje drugiego
            logger.exception("academy: sync program=%s failed", program_id)
    return results


# ── akcje na zgłoszeniu ────────────────────────────────────────────────────


async def session_taken(db: AsyncSession, session_id: int) -> int:
    return int(
        await db.scalar(
            select(func.count(AcademyApplication.id)).where(
                AcademyApplication.session_id == session_id,
                AcademyApplication.status.in_(("scheduled", "task_given")),
                or_(
                    AcademyApplication.attended.is_(None),
                    AcademyApplication.attended.is_(True),
                ),
            )
        )
        or 0
    )


async def perform_action(
    db: AsyncSession,
    *,
    row: AcademyApplication,
    program: AcademyProgram,
    action: ActionInput,
    user_id: Optional[int],
) -> AcademyApplication:
    """Wykonaj akcję na wierszu zablokowanym przez wołającego (``FOR UPDATE``)."""
    if action.action == "schedule" and action.session_id is not None:
        session = await db.get(AcademySession, action.session_id, with_for_update=True)
        if session is None or session.program_id != program.id:
            raise AcademyActionError(
                "session_missing", "Nie ma takiego terminu.", status_code=404
            )
        if session.cancelled_at is not None:
            raise AcademyActionError("session_cancelled", "Ten termin jest odwołany.")
        # Osoba już liczona w tym terminie nie zajmuje drugiego miejsca; ta,
        # która „nie przyszła”, już się nie liczy — przy ponownym zapisie
        # na ten sam termin MUSI przejść przez limit.
        counted_here = row.session_id == session.id and row.attended is not False
        if not counted_here:
            taken = await session_taken(db, session.id)
            if taken >= session.capacity:
                raise AcademyActionError(
                    "session_full", "Ten termin jest już pełny — wybierz inny."
                )

    before = row.status
    changes = apply_action(
        status=row.status,
        call_attempts=row.call_attempts,
        contract_sent_at=row.contract_sent_at,
        action=action,
        now=_now(),
        today=business_today(),
        task_due_days=program.task_due_days,
        user_id=user_id,
    )
    for key, value in changes.items():
        setattr(row, key, value)
    if row.status != before:
        db.add(
            Activity(
                entity_type="candidate",
                entity_id=row.candidate_id,
                action="academy_status",
                user_id=user_id,
                details={
                    "program_id": program.id,
                    "program": program.name,
                    "from": before,
                    "to": row.status,
                    "label": STATUS_LABELS.get(row.status, row.status),
                    "reason": row.closed_reason
                    if row.status in ("rejected", "withdrew")
                    else None,
                },
            )
        )
    return row


# ── odczyt ─────────────────────────────────────────────────────────────────


def application_dict(
    row: AcademyApplication,
    candidate: Candidate,
    session: Optional[AcademySession],
    source_title: Optional[str],
) -> dict[str, Any]:
    screening = row.screening or {}
    return {
        "id": row.id,
        "candidate_id": row.candidate_id,
        "full_name": f"{candidate.name or ''} {candidate.lastname or ''}".strip()
        or "(bez nazwiska)",
        "email": candidate.email,
        "phone": candidate.phone,
        "city": getattr(candidate, "city", None) or candidate.location,
        "has_cv": bool((candidate.raw_cv_text or "").strip()),
        "source_job_id": row.source_job_id,
        "source_job_title": source_title,
        "applied_at": row.applied_at,
        "status": row.status,
        "screening_verdict": row.screening_verdict,
        "screening_reasons": screening.get("reasons") or [],
        "screening_facts": screening.get("facts") or {},
        "screened_at": row.screened_at,
        "experience_years": float(row.experience_years)
        if row.experience_years is not None
        else None,
        "call_attempts": row.call_attempts,
        "last_call_at": row.last_call_at,
        "session_id": row.session_id,
        "session_starts_at": session.starts_at if session else None,
        "attended": row.attended,
        "task_due": row.task_due,
        "task_result": row.task_result,
        "contract_sent_at": row.contract_sent_at,
        "signed_at": row.signed_at,
        "cohort_month": row.cohort_month,
        "closed_stage": row.closed_stage,
        "closed_reason": row.closed_reason,
        "closed_at": row.closed_at,
        "reapplied_at": row.reapplied_at,
        "note": row.note,
        "updated_at": row.updated_at,
    }


async def list_applications(
    db: AsyncSession,
    program_id: int,
    *,
    statuses: Optional[list[str]] = None,
    q: Optional[str] = None,
    limit: int = APPLICATIONS_LIST_LIMIT,
) -> tuple[list[dict[str, Any]], int]:
    """Zgłoszenia programu i łączna liczba pasujących (przed ``limit``).

    Odrzuceni zostają w programie na zawsze, więc wierszy przybywa. Lista NIE
    może po cichu ucinać najnowszych: najpierw idą osoby w toku (kolejki
    telefonów, terminy, edycja), potem zamknięte — w obu grupach najnowsze
    zgłoszenia pierwsze. Gdy ``limit`` coś utnie, są to najstarsze zamknięte,
    a front pokazuje „pokazano N z M” (liczniki kolejek liczy serwer).
    """
    from app.models.job import Job  # noqa: PLC0415

    filters = [AcademyApplication.program_id == program_id]
    joined_candidate = False
    if statuses:
        filters.append(AcademyApplication.status.in_(statuses))
    if q:
        escaped = (
            q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        needle = f"%{escaped}%"
        joined_candidate = True
        filters.append(
            or_(
                func.concat(Candidate.name, " ", Candidate.lastname).ilike(needle),
                Candidate.email.ilike(needle),
                Candidate.phone.ilike(needle),
            )
        )
    stmt = (
        select(AcademyApplication, Candidate, AcademySession, Job.title)
        .join(Candidate, Candidate.id == AcademyApplication.candidate_id)
        .outerjoin(AcademySession, AcademySession.id == AcademyApplication.session_id)
        .outerjoin(Job, Job.id == AcademyApplication.source_job_id)
        .where(*filters)
    )
    closed_last = case((AcademyApplication.status.in_(_CLOSED_STATUSES), 1), else_=0)
    stmt = stmt.order_by(
        closed_last,
        AcademyApplication.applied_at.desc(),
        AcademyApplication.id.desc(),
    ).limit(limit)
    rows = (await db.execute(stmt)).all()
    items = [
        application_dict(app, cand, sess, title) for app, cand, sess, title in rows
    ]
    if len(items) < limit:
        return items, len(items)
    total_stmt = select(func.count()).select_from(AcademyApplication).where(*filters)
    if joined_candidate:
        total_stmt = total_stmt.join(
            Candidate, Candidate.id == AcademyApplication.candidate_id
        )
    total = int(await db.scalar(total_stmt) or 0)
    return items, total


async def list_applications_by_ids(
    db: AsyncSession, ids: list[int]
) -> list[dict[str, Any]]:
    from app.models.job import Job  # noqa: PLC0415

    if not ids:
        return []
    rows = (
        await db.execute(
            select(AcademyApplication, Candidate, AcademySession, Job.title)
            .join(Candidate, Candidate.id == AcademyApplication.candidate_id)
            .outerjoin(
                AcademySession, AcademySession.id == AcademyApplication.session_id
            )
            .outerjoin(Job, Job.id == AcademyApplication.source_job_id)
            .where(AcademyApplication.id.in_(ids))
        )
    ).all()
    return [application_dict(app, cand, sess, title) for app, cand, sess, title in rows]


async def status_counts(db: AsyncSession, program_id: int) -> dict[str, int]:
    rows = (
        await db.execute(
            select(AcademyApplication.status, func.count())
            .where(AcademyApplication.program_id == program_id)
            .group_by(AcademyApplication.status)
        )
    ).all()
    counts = {status: int(n) for status, n in rows}
    counts["luna_skipped"] = int(
        await db.scalar(
            select(func.count()).where(
                AcademyApplication.program_id == program_id,
                AcademyApplication.status == "new",
                AcademyApplication.screening_verdict == "skip",
            )
        )
        or 0
    )
    counts["unscreened"] = int(
        await db.scalar(
            select(func.count()).where(
                AcademyApplication.program_id == program_id,
                AcademyApplication.status == "new",
                AcademyApplication.screening_verdict.is_(None),
            )
        )
        or 0
    )
    counts["reapplied_excluded"] = int(
        await db.scalar(
            select(func.count()).where(
                AcademyApplication.program_id == program_id,
                AcademyApplication.status == "rejected",
                AcademyApplication.reapplied_at.is_not(None),
            )
        )
        or 0
    )
    return counts


async def sessions_with_counts(
    db: AsyncSession, program_id: int, *, since: Optional[datetime] = None
) -> list[dict[str, Any]]:
    taken = (
        select(
            AcademyApplication.session_id.label("sid"),
            func.count(AcademyApplication.id)
            .filter(
                AcademyApplication.status.in_(("scheduled", "task_given")),
                or_(
                    AcademyApplication.attended.is_(None),
                    AcademyApplication.attended.is_(True),
                ),
            )
            .label("taken"),
            func.count(AcademyApplication.id).label("all_people"),
        )
        .where(AcademyApplication.session_id.is_not(None))
        .group_by(AcademyApplication.session_id)
        .subquery()
    )
    stmt = (
        select(AcademySession, taken.c.taken, taken.c.all_people)
        .outerjoin(taken, taken.c.sid == AcademySession.id)
        .where(AcademySession.program_id == program_id)
        .order_by(AcademySession.starts_at)
    )
    if since is not None:
        stmt = stmt.where(AcademySession.starts_at >= since)
    rows = (await db.execute(stmt)).all()
    return [
        {
            "id": s.id,
            "starts_at": s.starts_at,
            "location": s.location,
            "capacity": s.capacity,
            "taken": int(t or 0),
            "people": int(a or 0),
            "cancelled": s.cancelled_at is not None,
        }
        for s, t, a in rows
    ]


__all__ = [
    "AcademyActionError",
    "ActionInput",
    "application_dict",
    "intake_program",
    "list_applications",
    "perform_action",
    "screen_pending",
    "sessions_with_counts",
    "status_counts",
    "sync_all_active",
    "sync_program",
]
