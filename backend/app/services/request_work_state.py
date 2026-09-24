"""Stan pracy nad requestem — „Szukamy / Mamy championa / Klient milczy / Zakończony”.

Decyzja Artura 24.09.2026. W Traffit nikt nie zamyka rekrutacji, więc NEXUS
pokazywał 327 „otwartych” requestów przy realnie ~20 w pracy. Stan prowadzi
Delivery Lead w NEXUSIE (``jobs.work_state``, Traffit go nie nadpisuje):

* ``to_review`` — „Do przejrzenia”: nikt jeszcze nie zdecydował;
* ``searching`` — „Szukamy kandydatów”: jedyny stan, który dostaje ludzi
  z automatu przydziału i jest na pulpicie daily;
* ``client_silent`` — „Klient milczy”: otwarty, ale nikt nad nim nie
  pracuje; wraca sam, gdy klient się odezwie;
* ``finished`` — „Zakończony”: znika z list (status z Traffita zostaje).

„Mamy championa” NIE jest wartością kolumny — to ``champion_found_at``
(przycisk DL, ``api/job_similar.set_champion_found``) przy stanie
``searching``. Jedna reguła ``visible_state`` składa oba pola; front ma jej
lustro w ``lib/request-work-state.ts`` na wspólnym pliku przypadków.

Podpowiedź stanu (``suggest``) liczy się przy odczycie z historii pipeline'u.
Aplikacje z ogłoszeń (etap ``posting``/``new``) NIE są pracą — 235 z 327
rekrutacji zbierało je przy braku jakiegokolwiek ruchu rekrutera.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, Sequence

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User
from app.services.job_similarity import CLIENT_STAGES

WORK_STATES = ("to_review", "searching", "client_silent", "finished")
VISIBLE_STATES = ("to_review", "searching", "champion", "client_silent", "finished")

LABELS = {
    "to_review": "Do przejrzenia",
    "searching": "Szukamy kandydatów",
    "champion": "Mamy championa",
    "client_silent": "Klient milczy",
    "finished": "Zakończony",
}

# Ruch rekrutera = każdy etap poza wejściem z ogłoszenia i zamknięciem osoby.
_NOT_WORK = (
    PipelineStage.posting,
    PipelineStage.new,
    PipelineStage.rejected,
    PipelineStage.withdrawn,
)

FRESH_DAYS = 14
SILENT_AFTER_DAYS = 30
DEAD_AFTER_DAYS = 90


def visible_state_clause(states: Iterable[str]):
    """SQL-owe lustro ``visible_state`` — filtr listy rekrutacji."""
    from sqlalchemy import or_  # noqa: PLC0415

    wanted = set(states)
    clauses = []
    for state in wanted:
        if state == "champion":
            clauses.append(
                and_(Job.work_state == "searching", Job.champion_found_at.is_not(None))
            )
        elif state == "searching":
            clauses.append(
                and_(Job.work_state == "searching", Job.champion_found_at.is_(None))
            )
        else:
            clauses.append(Job.work_state == state)
    return or_(*clauses)


def visible_state(work_state: Optional[str], champion_found_at: object) -> str:
    """Stan pokazywany ludziom. Champion liczy się tylko przy „Szukamy”."""
    state = work_state if work_state in WORK_STATES else "to_review"
    if state == "searching" and champion_found_at is not None:
        return "champion"
    return state


@dataclass(frozen=True)
class WorkSignals:
    job_id: int
    opened_at: Optional[datetime]
    last_work_at: Optional[datetime]
    last_cv_at: Optional[datetime]
    applications_14d: int
    sent_total: int


@dataclass(frozen=True)
class Suggestion:
    state: Optional[str]
    reason: str


def _days(now: datetime, moment: Optional[datetime]) -> Optional[int]:
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max(0, (now - moment).days)


def suggest(signals: WorkSignals, now: datetime) -> Suggestion:
    """Podpowiedź dla DL w „Porządku w requestach” — nigdy nie zapisuje stanu."""
    age = _days(now, signals.opened_at)
    work = _days(now, signals.last_work_at)
    cv = _days(now, signals.last_cv_at)
    if cv is not None and cv <= FRESH_DAYS:
        return Suggestion("searching", f"CV do klienta {cv} dni temu")
    if age is not None and age <= FRESH_DAYS:
        return Suggestion("searching", "Nowy request")
    if work is not None and work <= FRESH_DAYS:
        return Suggestion("searching", f"Rekruter pracował {work} dni temu")
    if (
        cv is not None
        and cv > SILENT_AFTER_DAYS
        and (work is None or work > SILENT_AFTER_DAYS)
    ):
        if cv > DEAD_AFTER_DAYS and (work is None or work > DEAD_AFTER_DAYS):
            return Suggestion("finished", f"Ostatnie CV {cv} dni temu, potem cisza")
        return Suggestion("client_silent", f"CV wysłane {cv} dni temu, potem cisza")
    if cv is None and (work is None or work > DEAD_AFTER_DAYS):
        return Suggestion("finished", "Brak pracy od ponad 90 dni i żadnego CV")
    if cv is None and work is not None and work > SILENT_AFTER_DAYS:
        return Suggestion("client_silent", f"Brak pracy od {work} dni")
    return Suggestion(None, "Brak jednoznacznej podpowiedzi")


async def load_signals(
    db: AsyncSession, jobs: Sequence[Job], *, now: datetime
) -> dict[int, WorkSignals]:
    ids = [job.id for job in jobs]
    if not ids:
        return {}
    since = now - timedelta(days=FRESH_DAYS)
    work = dict(
        (
            await db.execute(
                select(CandidateStage.job_id, func.max(CandidateStage.moved_at))
                .join(User, User.id == CandidateStage.moved_by)
                .where(
                    CandidateStage.job_id.in_(ids),
                    CandidateStage.stage.not_in(_NOT_WORK),
                    User.is_active.is_(True),
                )
                .group_by(CandidateStage.job_id)
            )
        ).all()
    )
    client_rows = (
        await db.execute(
            select(
                CandidateStage.job_id,
                func.max(CandidateStage.moved_at),
                func.count(func.distinct(CandidateStage.candidate_id)),
            )
            .where(
                CandidateStage.job_id.in_(ids),
                CandidateStage.stage.in_(CLIENT_STAGES),
            )
            .group_by(CandidateStage.job_id)
        )
    ).all()
    cv = {job_id: (last, int(n)) for job_id, last, n in client_rows}
    apps = dict(
        (
            await db.execute(
                select(CandidateStage.job_id, func.count(CandidateStage.id))
                .where(
                    CandidateStage.job_id.in_(ids),
                    CandidateStage.stage.in_(
                        (PipelineStage.posting, PipelineStage.new)
                    ),
                    CandidateStage.moved_at >= since,
                )
                .group_by(CandidateStage.job_id)
            )
        ).all()
    )
    return {
        job.id: WorkSignals(
            job_id=job.id,
            opened_at=job.opened_at or job.created_at,
            last_work_at=work.get(job.id),
            last_cv_at=cv.get(job.id, (None, 0))[0],
            applications_14d=int(apps.get(job.id, 0)),
            sent_total=cv.get(job.id, (None, 0))[1],
        )
        for job in jobs
    }


class WorkStateError(ValueError):
    """Niedozwolona zmiana stanu — komunikat po polsku dla UI."""


async def set_work_state(
    db: AsyncSession,
    job: Job,
    state: str,
    *,
    actor_id: Optional[int],
    reason: str = "manual",
) -> bool:
    """Zmień stan requestu. ``False`` = stan już był taki (bez zapisu).

    Wołający trzyma blokadę wiersza rekrutacji i commituje. Przejście na
    „Szukamy” zgłasza rekrutację do nocnego przeglądu bazy — od liczby
    pasujących w bazie zależy, czy automat da rekrutera, czy sourcera.
    """
    if state not in WORK_STATES:
        raise WorkStateError("Nieznany stan requestu.")
    previous = job.work_state
    if previous == state:
        return False
    job.work_state = state
    job.work_state_changed_at = datetime.now(timezone.utc)
    job.work_state_changed_by = actor_id
    db.add(
        Activity(
            entity_type="job",
            entity_id=job.id,
            action="work_state_changed",
            user_id=actor_id,
            details={"from": previous, "to": state, "reason": reason},
        )
    )
    if state == "searching":
        from app.services.auto_match_outbox import enqueue_job  # noqa: PLC0415

        await enqueue_job(db, job_id=job.id, trigger="work_state")
    return True


async def wake_client_silent(
    db: AsyncSession, job_ids: Iterable[int], *, reason: str
) -> list[int]:
    """„Klient milczy” → „Szukamy”, gdy klient się odezwał. Nigdy nie rzuca.

    Wołane z terminów od klienta i z ruchu karty na etap po stronie klienta.
    Blokuje wiersze rekrutacji; zapis idzie w transakcji wołającego.
    """
    ids = sorted({int(i) for i in job_ids if i})
    if not ids:
        return []
    jobs = (
        await db.scalars(
            select(Job)
            .where(and_(Job.id.in_(ids), Job.work_state == "client_silent"))
            .order_by(Job.id)
            .with_for_update()
        )
    ).all()
    woken = []
    for job in jobs:
        if await set_work_state(db, job, "searching", actor_id=None, reason=reason):
            woken.append(job.id)
    return woken


# Klient się odezwał: rozmowa u klienta albo akceptacja kandydata.
CLIENT_RESPONSE_STAGES = (PipelineStage.client_interview, PipelineStage.acceptance)


async def wake_on_client_response(
    db: AsyncSession, *, job_id: int, stage: object, reason: str
) -> None:
    """Hak z ruchu karty i terminów od klienta. Nigdy nie rzuca.

    Savepoint: błąd tutaj nie może cofnąć ruchu w pipeline ani zapisu
    terminów — to wygoda, nie warunek.
    """
    value = getattr(stage, "value", stage)
    if stage is not None and value not in {s.value for s in CLIENT_RESPONSE_STAGES}:
        return
    try:
        async with db.begin_nested():
            await wake_client_silent(db, [job_id], reason=reason)
    except Exception:  # noqa: BLE001
        import logging  # noqa: PLC0415

        logging.getLogger(__name__).exception(
            "[request_work_state] wake job=%s failed", job_id
        )
