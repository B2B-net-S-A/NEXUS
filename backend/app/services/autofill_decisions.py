"""Decyzja o osobie od systemu (silnik „Nowi na 20”, decyzje Artura 23.10.2026).

Osoba dodana przez system (``entry_source = "system"``) leży w „Nowych”, aż
ktoś zdecyduje: „Dzwonię” (blokada 12 h, zapisana na stałe w ``entry_meta``),
przesunięcie dalej albo odrzucenie z powodem. Po ``DECISION_DAYS`` dniach
roboczych bez decyzji karta dostaje plakietkę „N dni bez decyzji”, a osoba
trafia do „Czeka na Ciebie” rekrutera prowadzącego.

Rekrutacja bez rekrutera (decyzja 23.10.2026: „termin od przypisania”):
karty czekają bez terminu, a dni liczą się od przypisania pierwszego
rekrutera, nie od dodania. Jedna reguła dla Tablicy i kolejki decyzji.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.core.scheduling import DEFAULT_TZ, is_business_day
from app.models.job import Job
from app.models.job_work_assignment import JobWorkAssignment

DECISION_DAYS = 2
DECISION_CALL = "call"


def business_days_since(start: datetime, now: datetime) -> int:
    """Pełne dni robocze od dnia ``start`` do dnia ``now`` (bez dnia startu)."""
    zone = ZoneInfo(DEFAULT_TZ)
    first = start.astimezone(zone).date()
    last = now.astimezone(zone).date()
    days = 0
    day: date = first + timedelta(days=1)
    while day <= last:
        if is_business_day(datetime(day.year, day.month, day.day, 12, tzinfo=zone)):
            days += 1
        day += timedelta(days=1)
    return days


def decided(meta: Any) -> bool:
    return isinstance(meta, dict) and bool(meta.get("decided_at"))


def waiting_days(
    *,
    meta: Any,
    entered_at: Optional[datetime],
    recruiter_since: Optional[datetime],
    now: datetime,
) -> Optional[int]:
    """Dni robocze czekania na decyzję; ``None`` = nie czeka (zdecydowano,
    rekrutacja bez rekrutera albo brak daty wejścia)."""
    if decided(meta) or entered_at is None or recruiter_since is None:
        return None
    return business_days_since(max(entered_at, recruiter_since), now)


def decision_due(days: Optional[int]) -> bool:
    return days is not None and days >= DECISION_DAYS


def record_call(process: Any, user_id: int, now: datetime) -> bool:
    """„Dzwonię” na osobie od systemu — decyzja zostaje także po wygaśnięciu
    blokady. Zwraca, czy zapisano (pierwsza decyzja wygrywa)."""
    meta = process.entry_meta
    if not isinstance(meta, dict) or meta.get("kind") != "autofill" or decided(meta):
        return False
    # Nowy słownik: JSONB bez MutableDict nie widzi zmiany w miejscu.
    process.entry_meta = {
        **meta,
        "decided_at": now.isoformat(),
        "decided_by": user_id,
        "decision": DECISION_CALL,
    }
    return True


async def recruiter_since_for_jobs(db, job_ids: list[int]) -> dict[int, datetime]:
    """Od kiedy rekrutacja ma rekrutera. Brak klucza = nie ma rekrutera.

    Najwcześniejsze aktywne przypisanie rekrutera; prowadzący bez wiersza
    przypisania (stare rekrutacje) — od utworzenia rekrutacji.
    """
    if not job_ids:
        return {}
    since: dict[int, datetime] = {
        int(job_id): at
        for job_id, at in (
            await db.execute(
                select(
                    JobWorkAssignment.job_id, func.min(JobWorkAssignment.assigned_at)
                )
                .where(
                    JobWorkAssignment.job_id.in_(job_ids),
                    JobWorkAssignment.state == "active",
                )
                .group_by(JobWorkAssignment.job_id)
            )
        ).all()
    }
    for job_id, created_at, recruiter_id, tac_id in (
        await db.execute(
            select(Job.id, Job.created_at, Job.recruiter_id, Job.tac_id).where(
                Job.id.in_(job_ids)
            )
        )
    ).all():
        if job_id not in since and (recruiter_id or tac_id) and created_at:
            since[int(job_id)] = created_at
    return since


# ── Kto czeka na decyzję (kolejka „Czeka na Ciebie” i poranny dzwonek) ──────


@dataclass(frozen=True)
class DueDecision:
    job_id: int
    candidate_id: int
    score: Optional[int]
    waiting_days: int


async def due_decisions(db, job_ids: list[int], now: datetime) -> list[DueDecision]:
    """Osoby od systemu w „Nowych” tych rekrutacji, o których po
    ``DECISION_DAYS`` dniach roboczych nikt nie zdecydował. Najdłużej
    czekające pierwsze."""
    from app.models.pipeline_template import PipelineStageDef
    from app.models.recruitment_pipeline import CandidateStage
    from app.models.recruitment_process import RecruitmentProcess
    from app.services import candidate_claim
    from app.services.board_stage_badges import board_column_for
    from app.services.pipeline_latest import latest_stage_ids

    if not job_ids:
        return []
    latest = latest_stage_ids(job_ids=job_ids)
    rows = (
        await db.execute(
            select(
                CandidateStage.job_id,
                CandidateStage.candidate_id,
                CandidateStage.stage,
                PipelineStageDef.name,
                PipelineStageDef.category,
                PipelineStageDef.terminal_type,
            )
            .outerjoin(
                PipelineStageDef, PipelineStageDef.id == CandidateStage.stage_def_id
            )
            .where(CandidateStage.id.in_(select(latest.c.latest_id)))
        )
    ).all()
    in_new = {
        (int(job_id), int(candidate_id))
        for job_id, candidate_id, stage, name, category, terminal_type in rows
        if board_column_for(
            name,
            getattr(stage, "value", stage),
            category=getattr(category, "value", category),
            terminal_type=getattr(terminal_type, "value", terminal_type),
        )
        == candidate_claim.NEW_COLUMN
    }
    if not in_new:
        return []
    processes = (
        await db.scalars(
            select(RecruitmentProcess)
            .where(
                RecruitmentProcess.job_id.in_(sorted({j for j, _ in in_new})),
                RecruitmentProcess.entry_source == candidate_claim.ENTRY_SYSTEM,
            )
            .order_by(
                RecruitmentProcess.attempt_no.desc(), RecruitmentProcess.id.desc()
            )
        )
    ).all()
    since = await recruiter_since_for_jobs(db, sorted({j for j, _ in in_new}))
    out: list[DueDecision] = []
    seen: set[tuple[int, int]] = set()
    for process in processes:
        pair = (process.job_id, process.candidate_id)
        if pair in seen or pair not in in_new:
            continue
        seen.add(pair)
        days = waiting_days(
            meta=process.entry_meta,
            entered_at=process.opened_at,
            recruiter_since=since.get(process.job_id),
            now=now,
        )
        if not decision_due(days):
            continue
        meta = process.entry_meta if isinstance(process.entry_meta, dict) else {}
        score = meta.get("score")
        out.append(
            DueDecision(
                job_id=process.job_id,
                candidate_id=process.candidate_id,
                score=int(round(score)) if isinstance(score, (int, float)) else None,
                waiting_days=int(days),
            )
        )
    out.sort(key=lambda d: (-d.waiting_days, d.job_id, d.candidate_id))
    return out
