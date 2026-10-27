"""Jednorazowe wycofanie kart od systemu ponad budżetem (decyzja Artura 25.10.2026).

Analiza odrzuceń po pierwszym dniu silnika „Nowi na 20”: 16 z 34 odrzuceń to
„za droga” przy stawce, którą system znał, a 218 nietkniętych kart od systemu
miało znaną „Stawkę od” ponad 25% nad budżetem. Od tej zmiany silnik takich
osób nie dodaje (``new_column_autofill.budget_tier``); ta naprawa zdejmuje te,
które dodał wcześniej, zanim minie im termin decyzji i każdą trzeba będzie
odrzucić ręcznie z powodem.

Reguły, które łatwo cofnąć „przy okazji”:

* Tylko karta, której nikt nie dotknął: proces ``entry_source = "system"``,
  otwarty, bez „Dzwonię” i bez decyzji (``entry_meta.decided_at``), dokładnie
  jeden wiersz etapu pary i bez osoby (``moved_by`` puste), bez arkusza
  screeningu, scorecardu, oceny i notatki etapu (zapisują się na tym samym
  wierszu bez ruchu karty, a archiwum ich nie przechowuje), żadnej notatki
  pary. Wszystko sprawdzane drugi raz pod blokadą kandydata przy wykonaniu.
* Zdjęcie tą samą drogą co ręczne „Usuń z rekrutacji”: archiwum
  ``candidate_stage_removals`` (bez autora — zdejmuje system), proces
  ``voided``, skasowane wiersze etapu. Silnik nie przywraca osoby, bo czyta to
  archiwum (``ranked_picks``).
* Bez powodu w ``autofill_feedback`` — to nie decyzja człowieka, raport jakości
  liczy tylko odrzucenia zespołu.
* Uruchamia ``scripts/autofill_withdraw_over_budget.py`` (domyślnie podgląd).
* Próg czyta z ``BUDGET_HARD_OVER``: 27.10.2026 zdjęto 197 kart ponad 25%,
  a po obniżce progu do 15% ten sam skrypt zdejmuje karty 15–25%.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Iterable, Optional

from sqlalchemy import and_, exists, func, or_, select

from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_stage_removal import CandidateStageRemoval
from app.models.job import Job
from app.models.note import Note
from app.models.recruitment_pipeline import CandidateStage
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.services import candidate_claim

logger = logging.getLogger(__name__)

REMOVAL_REASON = "autofill_withdrawn_over_budget"
ACTIVITY_ENTITY = "job_automation"
ACTION = "autofill_withdrawn"


def _empty_json(column):
    """SQL NULL albo JSONB ``null`` — oba znaczą „nikt nic nie zapisał”."""
    return or_(column.is_(None), func.jsonb_typeof(column) == "null")


def _untouched_pairs(job_ids: Optional[list[int]] = None):
    """Zapytanie o pary ``(candidate_id, job_id)`` nietkniętych kart od systemu."""
    single = (
        select(CandidateStage.candidate_id, CandidateStage.job_id)
        .group_by(CandidateStage.candidate_id, CandidateStage.job_id)
        .having(
            func.count() == 1,
            func.bool_and(
                and_(
                    CandidateStage.moved_by.is_(None),
                    _empty_json(CandidateStage.screening_answers),
                    _empty_json(CandidateStage.scorecard_answers),
                    CandidateStage.rating.is_(None),
                    or_(
                        CandidateStage.notes.is_(None),
                        func.btrim(CandidateStage.notes) == "",
                    ),
                )
            ),
        )
    )
    if job_ids is not None:
        single = single.where(CandidateStage.job_id.in_(job_ids))
    single = single.subquery()
    noted = exists().where(
        Note.candidate_id == RecruitmentProcess.candidate_id,
        Note.job_id == RecruitmentProcess.job_id,
    )
    query = (
        select(RecruitmentProcess.candidate_id, RecruitmentProcess.job_id)
        .join(
            single,
            (single.c.candidate_id == RecruitmentProcess.candidate_id)
            & (single.c.job_id == RecruitmentProcess.job_id),
        )
        .where(
            RecruitmentProcess.entry_source == candidate_claim.ENTRY_SYSTEM,
            RecruitmentProcess.status == ProcessStatus.open,
            RecruitmentProcess.claimed_by_user_id.is_(None),
            RecruitmentProcess.entry_meta["decided_at"].astext.is_(None),
            ~noted,
        )
        .order_by(RecruitmentProcess.job_id, RecruitmentProcess.candidate_id)
    )
    if job_ids is not None:
        query = query.where(RecruitmentProcess.job_id.in_(job_ids))
    return query


async def _over_budget(db, pairs: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """Pary, w których znana stawka jest ponad ``BUDGET_HARD_OVER`` nad budżetem."""
    from app.services.dealbreaker_filters import resolve_job_budget_hourly
    from app.services.new_column_autofill import budget_tier

    pairs = list(pairs)
    if not pairs:
        return []
    jobs = {
        j.id: j
        for j in (
            await db.scalars(
                select(Job)
                .where(Job.id.in_({j for _, j in pairs}))
                .execution_options(populate_existing=True)
            )
        ).all()
    }
    candidates = {
        c.id: c
        for c in (
            await db.scalars(
                select(Candidate)
                .where(Candidate.id.in_({c for c, _ in pairs}))
                .execution_options(populate_existing=True)
            )
        ).all()
    }
    budgets = {job_id: resolve_job_budget_hourly(job) for job_id, job in jobs.items()}
    return [
        (cid, job_id)
        for cid, job_id in pairs
        if cid in candidates
        and job_id in jobs
        and budget_tier(candidates[cid], budgets[job_id]) is None
    ]


async def plan(db, *, job_ids: Optional[list[int]] = None) -> list[tuple[int, int]]:
    """Pary do wycofania — bez zapisu."""
    rows = (await db.execute(_untouched_pairs(job_ids))).all()
    return await _over_budget(db, [(int(c), int(j)) for c, j in rows])


async def _withdraw_pair(db, candidate_id: int, job_id: int) -> bool:
    from app.services.candidate_contact_hooks import (
        has_active_contact_trigger,
        maybe_close_contact_opportunity,
    )
    from app.services.candidate_stage_removal_snapshot import (
        ordered_stage_rows,
        stage_removal_snapshot,
    )
    from app.services.recruitment_process_commands import (
        delete_voided_stage_history,
        void_process,
    )

    locked = await db.scalar(
        select(Candidate.id).where(Candidate.id == candidate_id).with_for_update()
    )
    if locked is None:
        return False
    # Ponowne sprawdzenie pod blokadą: od podglądu ktoś mógł ruszyć kartę,
    # dopisać notatkę albo kliknąć „Dzwonię”.
    still = (await db.execute(_untouched_pairs([job_id]))).all()
    if (candidate_id, job_id) not in {(int(c), int(j)) for c, j in still}:
        return False
    if not await _over_budget(db, [(candidate_id, job_id)]):
        return False
    stage_rows = (
        await db.scalars(
            select(CandidateStage)
            .where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
            )
            .with_for_update()
        )
    ).all()
    ordered = ordered_stage_rows(stage_rows)
    db.add(
        CandidateStageRemoval(
            candidate_id=candidate_id,
            job_id=job_id,
            removed_by=None,
            reason=REMOVAL_REASON,
            last_stage=ordered[-1].stage.value,
            stage_count=len(stage_rows),
            stages_snapshot=stage_removal_snapshot(ordered),
        )
    )
    await db.flush()
    await void_process(db, candidate_id=candidate_id, job_id=job_id, actor_user=None)
    await delete_voided_stage_history(db, candidate_id=candidate_id, job_id=job_id)
    if not await has_active_contact_trigger(
        db, candidate_id=candidate_id, job_id=job_id
    ):
        await maybe_close_contact_opportunity(
            db,
            candidate_id=candidate_id,
            job_id=job_id,
            reason="removed_from_recruitment",
        )
    return True


async def apply(db, pairs: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """Wycofaj pary z podglądu; każda w savepoincie. Bez commitu."""
    withdrawn: list[tuple[int, int]] = []
    for candidate_id, job_id in pairs:
        try:
            async with db.begin_nested():
                done = await _withdraw_pair(db, candidate_id, job_id)
        except Exception as exc:  # noqa: BLE001 — jedna karta nie wywraca reszty
            logger.warning(
                "[autofill_withdraw] job=%s candidate=%s: %s",
                job_id,
                candidate_id,
                type(exc).__name__,
            )
            continue
        if done:
            withdrawn.append((candidate_id, job_id))
    by_job: dict[int, list[int]] = defaultdict(list)
    for candidate_id, job_id in withdrawn:
        by_job[job_id].append(candidate_id)
    for job_id, candidate_ids in by_job.items():
        db.add(
            Activity(
                entity_type=ACTIVITY_ENTITY,
                entity_id=job_id,
                action=ACTION,
                user_id=None,
                # `count` czyta „Praca w tle” (`_DETAIL_KEYS`).
                details={"count": len(candidate_ids), "candidate_ids": candidate_ids},
            )
        )
    await db.flush()
    return withdrawn
