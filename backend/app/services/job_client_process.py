"""Proces u klienta: etapy po wysłaniu CV i ile to trwa naprawdę (18.11.2026).

Zgłoszenie z zespołu: przy rekrutacji ma się dać zapisać długość procesu
u klienta („jedna rozmowa zdalna” albo „rozmowa + test do wykonania”).
Etapy deklaruje człowiek i leżą w Profilu Championa pod kluczem
``client_process`` (poza sekcjami, poza odciskiem rankingu). Obok nich
pokazujemy czas zmierzony na ruchach kart u tego klienta, bo deklaracja
i rzeczywistość potrafią się rozjechać (np. decyzja po rozmowie 27 dni).

Reguła w ``docs/claude/rekrutacja-tworzenie/proces-u-klienta.md``.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_now
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.schemas.champion import ChampionClientProcess, ClientProcessIn

# Okno historii i próg: mniej niż 5 decyzji to anegdota, nie mediana.
MEASURE_MONTHS = 18
MIN_DECISIONS = 5
_DAY = 86_400.0


@dataclass(frozen=True)
class StagePair:
    """Pierwsze wejścia jednej osoby w jednej rekrutacji do etapów klienta."""

    cv_sent: Optional[datetime]
    client_interview: Optional[datetime]
    decision: Optional[datetime]


def _days(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / _DAY


def summarize(
    pairs: Iterable[StagePair], months: int = MEASURE_MONTHS
) -> Optional[dict]:
    """Mediany w dniach kalendarzowych albo ``None`` poniżej progu decyzji.

    Decyzja = pierwsze wejście w „Akceptacja” albo „Zatrudniony”, ale tylko
    po wysłaniu CV (karta przeniesiona wstecz nie daje ujemnego czasu).
    """
    to_interview: list[float] = []
    to_decision_from_interview: list[float] = []
    to_decision: list[float] = []
    for pair in pairs:
        if pair.cv_sent is None:
            continue
        if pair.client_interview and pair.client_interview > pair.cv_sent:
            to_interview.append(_days(pair.cv_sent, pair.client_interview))
            if pair.decision and pair.decision > pair.client_interview:
                to_decision_from_interview.append(
                    _days(pair.client_interview, pair.decision)
                )
        if pair.decision and pair.decision > pair.cv_sent:
            to_decision.append(_days(pair.cv_sent, pair.decision))
    if len(to_decision) < MIN_DECISIONS:
        return None

    def median(values: list[float]) -> Optional[int]:
        return round(statistics.median(values)) if values else None

    return {
        "cv_to_interview_days": median(to_interview),
        "interview_to_decision_days": median(to_decision_from_interview),
        "cv_to_decision_days": median(to_decision),
        "decisions": len(to_decision),
        "months": months,
    }


async def measured_for_client(db: AsyncSession, client_id: int) -> Optional[dict]:
    since = local_now() - timedelta(days=round(MEASURE_MONTHS * 30.4))
    first = lambda stage: func.min(CandidateStage.moved_at).filter(  # noqa: E731
        CandidateStage.stage == stage
    )
    stmt = (
        select(
            first(PipelineStage.cv_sent),
            first(PipelineStage.client_interview),
            func.min(CandidateStage.moved_at).filter(
                CandidateStage.stage.in_(
                    (PipelineStage.acceptance, PipelineStage.hired)
                )
            ),
        )
        .join(Job, Job.id == CandidateStage.job_id)
        .where(Job.client_id == client_id, CandidateStage.moved_at >= since)
        .group_by(CandidateStage.candidate_id, CandidateStage.job_id)
    )
    rows = (await db.execute(stmt)).all()
    return summarize(StagePair(*row) for row in rows)


def stored_process(profile: Any) -> Optional[dict]:
    """Zapisany proces albo ``None`` (brak, pusty, zepsuty wpis)."""
    raw = (profile or {}).get("client_process") if isinstance(profile, dict) else None
    if not isinstance(raw, dict):
        return None
    try:
        process = ChampionClientProcess.model_validate(raw)
    except ValueError:
        return None
    return process.model_dump(mode="json") if process.steps else None


async def suggested_for_client(
    db: AsyncSession, client_id: int, *, exclude_job_id: Optional[int] = None
) -> Optional[dict]:
    """Proces z najnowszej rekrutacji klienta, która go ma — podpowiedź dla nowej."""
    stmt = (
        select(Job.id, Job.champion_profile)
        .where(
            Job.client_id == client_id,
            Job.champion_profile["client_process"]["steps"].isnot(None),
        )
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(10)
    )
    if exclude_job_id is not None:
        stmt = stmt.where(Job.id != exclude_job_id)
    for job_id, profile in (await db.execute(stmt)).all():
        process = stored_process(profile)
        if process:
            return {**process, "from_job_id": job_id}
    return None


def stamp(payload: ClientProcessIn, user: Any) -> Optional[dict]:
    """Wpis do zapisu ze stemplem autora; pusta lista etapów = usunięcie."""
    if not payload.steps:
        return None
    return ChampionClientProcess(
        **payload.model_dump(),
        set_by_id=getattr(user, "id", None),
        set_by_name=getattr(user, "name", None),
        set_at=local_now(),
    ).model_dump(mode="json")


def with_process(profile: Any, process: Optional[dict]) -> dict:
    """Nowy słownik profilu z procesem (albo bez klucza) — JSONB wymaga nowego obiektu."""
    out = dict(profile or {})
    if process is None:
        out.pop("client_process", None)
    else:
        out["client_process"] = process
    return out
