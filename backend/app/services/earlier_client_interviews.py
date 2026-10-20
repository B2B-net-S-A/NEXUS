"""Wcześniejsze rozmowy osoby u tego samego klienta (20.10.2026).

Delivery Lead odrzucał osobę, bo była już na rozmowie u managera tej
rekrutacji w innym procesie, i nie miał jak tego wskazać. Przegląd DL
(``GET /api/dl-review/context``) dostaje listę takich rozmów:

* okno odrzucenia z powodem „Już po rozmowie u tego hiring managera” daje ją
  do wyboru — opis powodu wskazuje konkretny proces;
* gdy któraś rozmowa była u TEGO SAMEGO hiring managera
  (``Job.hiring_manager_contact_id``), panel ostrzega, zanim ktoś wyśle CV.

„Rozmowa” = wiersz etapu w kolumnie Tablicy „Rozmowa u klienta” albo dalej
przed zatrudnieniem („Umowa”). Kolumnę liczy ``board_column_for`` — etapy
Nordei rozpoznawane po nazwie mają kod ``interview``, więc sam kod etapu by
ich nie złapał. Zatrudnienie się nie liczy: to współpraca, nie rozmowa.

Tylko odczyt; tytuły innych rekrutacji klienta widzi każdy z dostępem do
przeglądu (jak „Poprzednie wysyłki”).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage
from app.services.board_stage_badges import board_column_for

MET_COLUMNS: frozenset[str] = frozenset({"client_interview", "contract"})
LIMIT = 10


@dataclass(frozen=True)
class EarlierInterview:
    job_id: int
    job_title: str
    interview_at: datetime
    latest_stage: Optional[str]
    same_hiring_manager: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "job_title": self.job_title,
            "interview_at": self.interview_at.isoformat(),
            "latest_stage": self.latest_stage,
            "same_hiring_manager": self.same_hiring_manager,
        }


def _value(raw: object) -> Optional[str]:
    if raw is None:
        return None
    return str(getattr(raw, "value", raw))


async def load(
    db: AsyncSession,
    *,
    job: Job,
    candidate_id: int,
    client_ids: Iterable[int],
    stage_labels: dict[str, str],
) -> list[EarlierInterview]:
    """Rozmowy osoby w innych rekrutacjach klienta, najnowsze pierwsze.

    ``client_ids`` = rodzina klienta rekrutacji (spółki powiązane), jak
    w „Poprzednich wysyłkach”. ``stage_labels`` tłumaczy kod etapu, gdy wiersz
    nie ma definicji etapu z nazwą.
    """
    family = sorted({int(c) for c in client_ids if c is not None})
    if not family:
        return []
    rows = (
        await db.execute(
            select(
                CandidateStage.job_id,
                CandidateStage.stage,
                CandidateStage.moved_at,
                PipelineStageDef.name.label("def_name"),
                PipelineStageDef.category,
                PipelineStageDef.terminal_type,
                func.coalesce(func.nullif(Job.working_title, ""), Job.title).label(
                    "job_title"
                ),
                Job.hiring_manager_contact_id,
            )
            .join(Job, Job.id == CandidateStage.job_id)
            .outerjoin(
                PipelineStageDef, PipelineStageDef.id == CandidateStage.stage_def_id
            )
            .where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id != job.id,
                Job.client_id.in_(family),
            )
            .order_by(CandidateStage.moved_at, CandidateStage.id)
        )
    ).all()

    met_at: dict[int, datetime] = {}
    latest: dict[int, Optional[str]] = {}
    meta: dict[int, tuple[str, Optional[int]]] = {}
    for row in rows:
        stage = _value(row.stage)
        column = board_column_for(
            row.def_name,
            stage,
            category=_value(row.category),
            terminal_type=_value(row.terminal_type),
        )
        if column in MET_COLUMNS and row.job_id not in met_at:
            met_at[row.job_id] = row.moved_at
        latest[row.job_id] = row.def_name or stage_labels.get(stage or "", stage)
        meta[row.job_id] = (
            row.job_title or "Rekrutacja",
            row.hiring_manager_contact_id,
        )

    manager = job.hiring_manager_contact_id
    found = [
        EarlierInterview(
            job_id=job_id,
            job_title=meta[job_id][0],
            interview_at=at,
            latest_stage=latest.get(job_id),
            same_hiring_manager=manager is not None and meta[job_id][1] == manager,
        )
        for job_id, at in met_at.items()
    ]
    found.sort(key=lambda item: item.interview_at, reverse=True)
    return found[:LIMIT]
