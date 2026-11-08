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
* Przed porcją dnia (decyzja Artura 08.11.2026): ``plan_batch_reset`` i
  ``scripts/autofill_withdraw_batch_reset.py`` — karty starsze niż 7 dni albo
  poniżej 65%, tylko w rekrutacjach w pracy.
* Miejsce dla świeżych (decyzja Artura 08.11.2026): ``plan_fresh_seats`` wskazuje
  nietknięte karty od systemu starsze niż ``FRESH_SEAT_AGE_DAYS``, od najniższego
  wyniku. To jedyny powód, przy którym osoba może wrócić do tej rekrutacji:
  ``ranked_picks`` i pula nocnego przeglądu pomijają ten wpis archiwum.
* Dalej niż ``OFFICE_FAR_KM`` od biura (decyzja Artura 29.10.2026): ta sama
  droga, ``plan_far`` i ``scripts/autofill_withdraw_far_from_office.py`` —
  66 nietkniętych kart w 38 rekrutacjach z biurem w Warszawie.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
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
# Odrzucenie na cały klient (27.10.2026): „Pracuje u tego klienta” / „Nie chce
# do tego klienta” zdejmuje nietknięte karty tej osoby z innych rekrutacji.
CLIENT_REMOVAL_REASON = "autofill_withdrawn_client"
# „Nie szuka pracy” z datą (28.10.2026) zdejmuje nietknięte karty tej osoby
# ze wszystkich innych rekrutacji.
NOT_LOOKING_REMOVAL_REASON = "autofill_withdrawn_not_looking"
# Miasto dalej niż ``OFFICE_FAR_KM`` od każdego biura rekrutacji (29.10.2026).
FAR_REMOVAL_REASON = "autofill_withdrawn_far_from_office"
# Przed włączeniem porcji dnia (decyzja Artura 08.11.2026): nietknięte karty
# od systemu starsze niż ``review_batch.MAX_AGE_DAYS`` albo poniżej
# ``review_batch.MIN_SCORE`` — na kopii z 06.11 ok. 850 starszych niż 7 dni
# i 147 poniżej 65% z 1 440 kart w rekrutacjach z rekruterem.
BATCH_RESET_REASON = "autofill_withdrawn_batch_reset"
# Miejsce dla świeżych (08.11.2026): z 2 993 kart nieruszonych 7 dni do klienta
# poszły 3 (0,1%), a osoba do 14 dni w bazie to 5,5% wysyłek wobec 1,5% starszych.
FRESH_SEAT_REASON = "autofill_withdrawn_fresh_seat"
FRESH_SEAT_AGE_DAYS = 7
# „Praca w tle” mówi, dlaczego system wycofał osoby (`details.why`).
_WHY = {
    REMOVAL_REASON: "budget",
    CLIENT_REMOVAL_REASON: "client",
    NOT_LOOKING_REMOVAL_REASON: "not_looking",
    FAR_REMOVAL_REASON: "far",
    BATCH_RESET_REASON: "batch_reset",
    FRESH_SEAT_REASON: "fresh_seat",
}
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


async def _far_from_office(
    db, pairs: Iterable[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Pary, w których miasto osoby jest dalej niż ``OFFICE_FAR_KM`` od
    każdego biura rekrutacji z biurem — ta sama reguła co silnik."""
    from app.services.dealbreaker_filters import dealbreaker_inputs_for_job
    from app.services.new_column_autofill import OFFICE_FAR_KM, office_km

    pairs = list(pairs)
    if not pairs:
        return []
    jobs = {
        j.id: dealbreaker_inputs_for_job(j)
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
    far = []
    for cid, job_id in pairs:
        inputs = jobs.get(job_id)
        if cid not in candidates or inputs is None or not inputs.wants_office:
            continue
        km = office_km(candidates[cid], inputs.office_tokens)
        if km is not None and km > OFFICE_FAR_KM:
            far.append((cid, job_id))
    return far


async def plan_far(db, *, job_ids: Optional[list[int]] = None) -> list[tuple[int, int]]:
    """Pary do wycofania, bo osoba mieszka daleko od biura — bez zapisu."""
    rows = (await db.execute(_untouched_pairs(job_ids))).all()
    return await _far_from_office(db, [(int(c), int(j)) for c, j in rows])


async def _stale_for_batch(
    db, pairs: Iterable[tuple[int, int]], *, now: datetime
) -> list[tuple[int, int]]:
    """Pary w rekrutacjach w pracy, których karta nie należy do porcji dnia
    (``review_batch.in_batch``): za stara albo poniżej progu."""
    from app.models.job import JobStatus
    from app.services import review_batch
    from app.services.request_work_state import IN_WORK_STATES

    pairs = list(pairs)
    if not pairs:
        return []
    working = set(
        (
            await db.scalars(
                select(Job.id).where(
                    Job.id.in_({j for _, j in pairs}),
                    Job.status == JobStatus.published,
                    Job.work_state.in_(IN_WORK_STATES),
                )
            )
        ).all()
    )
    cards = {
        (card.candidate_id, card.job_id): card
        for card in await review_batch.pending_cards(db, job_ids=working)
    }
    return [
        pair
        for pair in pairs
        if pair[1] in working
        and pair in cards
        and not review_batch.in_batch(cards[pair], now)
    ]


async def plan_batch_reset(
    db, *, now: datetime, job_ids: Optional[list[int]] = None
) -> list[tuple[int, int]]:
    """Pary do wycofania przed porcją dnia — bez zapisu."""
    rows = (await db.execute(_untouched_pairs(job_ids))).all()
    return await _stale_for_batch(db, [(int(c), int(j)) for c, j in rows], now=now)


async def plan_fresh_seats(db, job_id: int, *, now: datetime) -> list[tuple[int, int]]:
    """Karty, które mogą ustąpić osobie nowej w bazie, od najniższego wyniku.
    Nietknięte i starsze niż ``FRESH_SEAT_AGE_DAYS`` — bez zapisu."""
    from app.services import review_batch

    untouched = {
        (int(c), int(j))
        for c, j in (await db.execute(_untouched_pairs([job_id]))).all()
    }
    oldest = now - timedelta(days=FRESH_SEAT_AGE_DAYS)
    cards = [
        card
        for card in await review_batch.pending_cards(db, job_ids=[job_id])
        if (card.candidate_id, card.job_id) in untouched
        and card.opened_at is not None
        and card.opened_at <= oldest
    ]
    cards.sort(key=lambda c: (c.score, c.opened_at, c.candidate_id))
    return [(card.candidate_id, card.job_id) for card in cards]


async def plan(db, *, job_ids: Optional[list[int]] = None) -> list[tuple[int, int]]:
    """Pary do wycofania — bez zapisu."""
    rows = (await db.execute(_untouched_pairs(job_ids))).all()
    return await _over_budget(db, [(int(c), int(j)) for c, j in rows])


async def _withdraw_pair(
    db,
    candidate_id: int,
    job_id: int,
    *,
    reason: str = REMOVAL_REASON,
    check_budget: bool = True,
    check_far: bool = False,
    check_batch_reset: bool = False,
) -> bool:
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
    if check_batch_reset:
        stale = await _stale_for_batch(
            db, [(candidate_id, job_id)], now=datetime.now(timezone.utc)
        )
        if not stale:
            return False
    elif check_far:
        if not await _far_from_office(db, [(candidate_id, job_id)]):
            return False
    elif check_budget and not await _over_budget(db, [(candidate_id, job_id)]):
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
            reason=reason,
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


async def apply(
    db,
    pairs: Iterable[tuple[int, int]],
    *,
    reason: str = REMOVAL_REASON,
    check_budget: bool = True,
    check_far: bool = False,
    check_batch_reset: bool = False,
) -> list[tuple[int, int]]:
    """Wycofaj pary z podglądu; każda w savepoincie. Bez commitu.
    ``check_far`` sprawdza pod blokadą odległość zamiast budżetu."""
    withdrawn: list[tuple[int, int]] = []
    for candidate_id, job_id in pairs:
        try:
            async with db.begin_nested():
                done = await _withdraw_pair(
                    db,
                    candidate_id,
                    job_id,
                    reason=reason,
                    check_budget=check_budget,
                    check_far=check_far,
                    check_batch_reset=check_batch_reset,
                )
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
                details={
                    "count": len(candidate_ids),
                    "candidate_ids": candidate_ids,
                    "why": _WHY.get(reason, "budget"),
                },
            )
        )
    await db.flush()
    return withdrawn


async def withdraw_at_client(
    db, *, candidate_id: int, client_id: int, except_job_id: int
) -> list[tuple[int, int]]:
    """Nietknięte karty tej osoby od systemu w innych rekrutacjach klienta
    (odrzucenie „na cały klient”, 27.10.2026). Bez commitu — w transakcji ruchu."""
    job_ids = list(
        (
            await db.scalars(
                select(Job.id).where(
                    Job.client_id == client_id, Job.id != except_job_id
                )
            )
        ).all()
    )
    if not job_ids:
        return []
    pairs = [
        (int(c), int(j))
        for c, j in (await db.execute(_untouched_pairs(job_ids))).all()
        if int(c) == candidate_id
    ]
    return await apply(db, pairs, reason=CLIENT_REMOVAL_REASON, check_budget=False)


async def withdraw_elsewhere(
    db, *, candidate_id: int, except_job_id: int
) -> list[tuple[int, int]]:
    """Nietknięte karty tej osoby od systemu we wszystkich innych rekrutacjach
    („Nie szuka pracy” z datą, 28.10.2026). Bez commitu — w transakcji ruchu."""
    job_ids = list(
        (
            await db.scalars(
                select(CandidateStage.job_id).where(
                    CandidateStage.candidate_id == candidate_id,
                    CandidateStage.job_id != except_job_id,
                )
            )
        ).all()
    )
    if not job_ids:
        return []
    pairs = [
        (int(c), int(j))
        for c, j in (await db.execute(_untouched_pairs(sorted(set(job_ids))))).all()
        if int(c) == candidate_id
    ]
    return await apply(db, pairs, reason=NOT_LOOKING_REMOVAL_REASON, check_budget=False)
