"""Dzwonek przy przekazaniu karty między ludźmi na Tablicy (0408, 02.10.2026).

Zgłoszenie testerów: „Przekaż Delivery Leadowi" przesuwało kartę do „QC CV"
bez powiadomienia — Delivery Lead nie wiedział, że ma kogoś do sprawdzenia,
a osoba, która przekazała kartę, nie dowiadywała się, że DL wysłał CV do
klienta. Jedynym śladem była Tablica rekrutacji i poranny skrót.

Reguły powiadomień etapów (0066) tego nie załatwiają: wiszą na etapach
szablonu (etap „QC CV" nie ma żadnej), a ich odbiorcą jest prowadzący
rekrutację, nie osoba, która pracuje z kandydatem. Tu odbiorcę wyznacza
przepływ, tą samą regułą co kolejka „Czeka na Ciebie" (`board_tasks`):

* karta wchodzi do przeglądu DL (poza Nordeą: etap „QC CV") → Delivery Lead
  rekrutacji;
* karta wchodzi do kolejki Cpro (Nordea) → osoba od Cpro;
* karta wraca z kolejki Cpro do „QC CV" → osoba, która ją tam przekazała;
* karta wychodzi z kolumn sprzed wysłania na „CV wysłane" albo z „QC CV" do
  zamkniętych → osoba, która ją przekazała, i rekruter kandydata.

Wynik przeglądu idzie typem ``stage_rule`` z tą samą encją co reguły etapów,
więc prowadzący rekrutację, który jest też rekruterem kandydata, dostaje jeden
dzwonek (`ix_notif_dedup_daily`), nie dwa — dlatego ten moduł biegnie PRZED
regułami. Osoba wykonująca ruch nigdy nie powiadamia samej siebie.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.job import Job
from app.models.notification import NotificationType
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.services import board_tasks
from app.services.board_stage_badges import (
    CV_QC_COLUMN,
    board_column_for,
    cpro_enabled_for_client,
    is_cpro_stage,
)
from app.services.interview_slots import default_recruiter_id
from app.services.job_working_title import display_title
from app.services.notification_triggers import emit

# Kolumny, z których ruch na „CV wysłane" jest wysłaniem (nie cofnięciem karty
# z rozmowy u klienta ani przywróceniem z zamkniętych).
_BEFORE_SEND_COLUMNS = frozenset({"new", "screening", "verified", CV_QC_COLUMN})


@dataclass(frozen=True)
class _Place:
    column: str
    is_cpro: bool


async def _places(db: AsyncSession, rows: list[CandidateStage]) -> dict[int, _Place]:
    def_ids = {r.stage_def_id for r in rows if r.stage_def_id is not None}
    defs = {}
    if def_ids:
        defs = {
            d.id: d
            for d in (
                await db.scalars(
                    select(PipelineStageDef).where(PipelineStageDef.id.in_(def_ids))
                )
            ).all()
        }
    out: dict[int, _Place] = {}
    for row in rows:
        d = defs.get(row.stage_def_id)
        column = board_column_for(
            d.name if d else None,
            getattr(row.stage, "value", row.stage),
            category=d.category.value if d and d.category else None,
            terminal_type=d.terminal_type.value if d and d.terminal_type else None,
        )
        out[row.id] = _Place(
            column=column,
            is_cpro=column == CV_QC_COLUMN and is_cpro_stage(d.name if d else None),
        )
    return out


def _full_name(candidate: Candidate) -> str:
    return (
        " ".join(p for p in (candidate.name, candidate.lastname) if p)
        or f"#{candidate.id}"
    )


async def notify_handoff(
    db: AsyncSession,
    *,
    stage: CandidateStage,
    previous_stage: Optional[CandidateStage],
    job: Job,
    candidate: Candidate,
    mover: User,
    stage_display_name: str,
) -> int:
    """Powiadom osobę, do której właśnie trafiła karta. Zwraca liczbę dzwonków."""

    places = await _places(db, [r for r in (stage, previous_stage) if r is not None])
    new = places[stage.id]
    prev = (
        places[previous_stage.id]
        if previous_stage is not None
        else _Place("new", False)
    )
    nordea = cpro_enabled_for_client(job.client_id)

    who = mover.name or "Ktoś z zespołu"
    person = _full_name(candidate)
    where = f"w rekrutacji „{display_title(job)}”"
    card_link = f"/jobs/{job.id}?candidate={candidate.id}"

    ntype = NotificationType.board_task_waiting
    link = card_link
    recipients: list[Optional[int]] = []
    title = message = ""

    if new.column == CV_QC_COLUMN and not nordea and not new.is_cpro:
        recipients = await board_tasks.dl_reviewer_ids(
            db, delivery_lead_id=job.delivery_lead_id, client_id=job.client_id
        )
        title = f"Do przeglądu: {person}"
        message = (
            f"{who} przekazał(a) Ci kandydata {person} {where}. Sprawdź CV "
            "i wyślij je do klienta albo odrzuć."
        )
    elif new.column == CV_QC_COLUMN and nordea and new.is_cpro:
        recipients = [
            await board_tasks.cpro_queue_owner_id(
                db,
                job_sender_id=job.cpro_sender_id,
                task_assignee_id=stage.task_assignee_id,
            )
        ]
        link = "/dashboard#czeka-na-ciebie"
        title = f"Do wrzucenia do Cpro: {person}"
        message = f"{who} przekazał(a) kandydata {person} do kolejki Cpro {where}."
    elif new.column == CV_QC_COLUMN and nordea and prev.is_cpro:
        recipients = [previous_stage.moved_by if previous_stage is not None else None]
        title = f"Wrócił z kolejki Cpro: {person}"
        message = (
            f"{who} zwrócił(a) kandydata {person} z kolejki Cpro {where}. "
            "Popraw CV i przekaż ponownie."
        )
    elif (new.column == "cv_sent" and prev.column in _BEFORE_SEND_COLUMNS) or (
        new.column == "closed" and prev.column == CV_QC_COLUMN
    ):
        ntype = NotificationType.stage_rule
        recipients = [
            previous_stage.moved_by if previous_stage is not None else None,
            await default_recruiter_id(
                db, candidate_id=stage.candidate_id, job_id=stage.job_id
            ),
        ]
        if new.column == "closed":
            title = f"Po przeglądzie: {person} → {stage_display_name}"
            message = (
                f"{who} przeniósł(a) kandydata {person} z przeglądu na etap "
                f"„{stage_display_name}” {where}."
            )
        elif nordea:
            title = f"Wysłane do Cpro: {person}"
            message = f"{who} wrzucił(a) kandydata {person} do Cpro {where}."
        else:
            title = f"CV wysłane do klienta: {person}"
            message = f"{who} wysłał(a) CV kandydata {person} do klienta {where}."
    else:
        return 0

    emitted = 0
    for user_id in dict.fromkeys(recipients):
        if user_id is None or user_id == mover.id:
            continue
        created = await emit(
            db,
            user_id=user_id,
            title=title,
            message=message,
            ntype=ntype,
            related_entity_type="candidate_stage",
            related_entity_id=stage.id,
            link=link,
        )
        emitted += int(created is not None)
    return emitted


__all__ = ["notify_handoff"]
