"""Jednorazowe uzupełnienie osoby na kartach „System” w „Screeningu”
(decyzja Artura 28.10.2026, razem z wariantem A).

Od tej zmiany ruch człowieka z „Nowych” do „Screeningu” bierze kartę bez
osoby jak „Biorę” (``candidate_claim.take_unowned_on_screening``). Karty
przeniesione wcześniej dalej pokazują „System” i nie trafiają do filtra
„Ty”. Ta naprawa daje im osobę, która przeniosła je do „Screeningu”.

* Tylko otwarty proces ``entry_source = "system"`` bez osoby z „Biorę”
  (``claimed_by_user_id`` puste) i bez „Prowadzi”, którego bieżący wiersz
  etapu stoi w „Screeningu” i ma autora, a ten autor ma aktywne konto.
* Blokada 12 h liczy się od tamtego ruchu, nie od uruchomienia, więc
  zwykle już wygasła: karta i filtr pokazują osobę, a nikt nie dostaje
  świeżej blokady.
* Uruchamia ``scripts/system_card_screening_backfill.py`` (domyślnie podgląd).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import exists, select

from app.models.candidate_job_owner import CandidateJobOwner
from app.models.recruitment_pipeline import CandidateStage
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.user import User
from app.services import candidate_claim


@dataclass(frozen=True)
class Take:
    process_id: int
    candidate_id: int
    job_id: int
    user_id: int
    moved_at: datetime


def _candidates_stmt():
    owned = exists().where(
        CandidateJobOwner.candidate_id == RecruitmentProcess.candidate_id,
        CandidateJobOwner.job_id == RecruitmentProcess.job_id,
    )
    return select(RecruitmentProcess).where(
        RecruitmentProcess.entry_source == candidate_claim.ENTRY_SYSTEM,
        RecruitmentProcess.status == ProcessStatus.open,
        RecruitmentProcess.claimed_by_user_id.is_(None),
        ~owned,
    )


async def _latest_stage(db, process: RecruitmentProcess):
    return await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == process.candidate_id,
            CandidateStage.job_id == process.job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )


async def plan(db) -> list[Take]:
    takes: list[Take] = []
    for process in (await db.scalars(_candidates_stmt())).all():
        stage = await _latest_stage(db, process)
        if stage is None or stage.moved_by is None:
            continue
        if (
            await candidate_claim.stage_column(db, stage)
            != candidate_claim.SCREENING_COLUMN
        ):
            continue
        active = await db.scalar(
            select(User.is_active).where(User.id == stage.moved_by)
        )
        if not active:
            continue
        takes.append(
            Take(
                process_id=process.id,
                candidate_id=process.candidate_id,
                job_id=process.job_id,
                user_id=stage.moved_by,
                moved_at=stage.moved_at,
            )
        )
    return takes


async def apply(db, takes: list[Take]) -> list[Take]:
    """Zapis planu; każdy proces sprawdzany drugi raz pod blokadą wiersza."""
    done: list[Take] = []
    for take in takes:
        process = await db.scalar(
            _candidates_stmt()
            .where(RecruitmentProcess.id == take.process_id)
            .with_for_update()
        )
        if process is None:
            continue
        stage = await _latest_stage(db, process)
        if stage is None or stage.moved_by != take.user_id:
            continue
        candidate_claim.set_claim(process, take.user_id, now=take.moved_at)
        done.append(take)
    await db.flush()
    return done
