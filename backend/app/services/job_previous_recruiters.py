"""„Poprzedni rekruter” — uśpienie i powrót zespołu rekrutacji (14.10.2026).

Prośba Head of Recruitment, decyzje Artura tego samego dnia
(``docs/claude/rekrutacja-tablica/role-przy-rekrutacji-delivery-lead-rekruter.md``,
sekcja „Poprzedni rekruter”):

* zamknięcie rekrutacji albo zejście z P1 (na „Bez priorytetu” albo
  „Przyjmujemy kandydatów”) przenosi wszystkich, którzy pracowali jako
  „Rekruter”, do „Poprzedni rekruter” (``park_team``);
* powrót na P1 albo ponowne otwarcie przy P1 przywraca ich samo
  (``restore_team``) — poza kontami nieaktywnymi i bez roli rekrutera;
* reguła działa na zdarzeniach: osoba dodana ręcznie przy „Bez priorytetu”
  jest zwykłym rekruterem (``clear_parked`` przy każdym ponownym dodaniu).

Nic nie jest kasowane: ``jobs.recruiter_id`` i ręcznie dopisani zostają, bo
wisi na nich dostęp, kreator metryk i dzwonki o własnych kandydatach. Reguła
zespołu (``job_team``) pomija osoby z otwartym wierszem
``job_previous_recruiters``. Wyjątek: przy zejściu z P1 żywe przypisania
dostają powód ``parked``, żeby automat nie liczył ich w obłożeniu.

Wołający trzyma ``allocation_lock`` i blokadę wiersza rekrutacji (w tej
kolejności), gdy funkcja zwalnia albo zakłada przypisania (zejście z P1,
powrót). Bez commitu.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import exists, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.activity import Activity
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_previous_recruiter import JobPreviousRecruiter
from app.models.job_work_assignment import WORK_ROLE, JobWorkAssignment
from app.models.notification import NotificationType
from app.models.user import User
from app.services.job_priority import level_of

logger = logging.getLogger(__name__)

PARKED_RELEASE_REASON = "parked"


@dataclass(frozen=True)
class PreviousRecruiter:
    user_id: int
    name: str
    via: str
    reason: str
    parked_at: datetime
    parked_by_name: Optional[str]
    # Wróci przy P1: konto aktywne i rola rekrutera (lustro ``restore_team``).
    will_return: bool


# ── Klauzule i odczyty ───────────────────────────────────────────────────────


def _open():
    return JobPreviousRecruiter.cleared_at.is_(None)


def parked_exists(job_col, user_col):
    """SQL: osoba jest uśpiona przy rekrutacji (otwarty wiersz)."""
    return exists(
        select(JobPreviousRecruiter.id).where(
            JobPreviousRecruiter.job_id == job_col,
            JobPreviousRecruiter.user_id == user_col,
            _open(),
        )
    )


def parked_job_ids(user_ids: list[int]):
    """Podzapytanie: rekrutacje, przy których któraś z osób jest uśpiona."""
    return select(JobPreviousRecruiter.job_id).where(
        JobPreviousRecruiter.user_id.in_(user_ids), _open()
    )


async def load_parked(db: AsyncSession, job_ids: Iterable[int]) -> dict[int, set[int]]:
    """Uśpione osoby per rekrutacja — jedno zapytanie."""
    ids = sorted({int(job_id) for job_id in job_ids})
    out: dict[int, set[int]] = {}
    if not ids:
        return out
    rows = (
        await db.execute(
            select(JobPreviousRecruiter.job_id, JobPreviousRecruiter.user_id).where(
                JobPreviousRecruiter.job_id.in_(ids), _open()
            )
        )
    ).all()
    for job_id, user_id in rows:
        out.setdefault(job_id, set()).add(user_id)
    return out


async def previous_recruiters_for_jobs(
    db: AsyncSession, job_ids: Iterable[int]
) -> dict[int, list[PreviousRecruiter]]:
    """Wiersz „Poprzedni rekruter” dla wielu rekrutacji (stała liczba zapytań)."""
    from app.services.job_team import WORK_ROLES  # noqa: PLC0415

    ids = sorted({int(job_id) for job_id in job_ids})
    out: dict[int, list[PreviousRecruiter]] = {job_id: [] for job_id in ids}
    if not ids:
        return out
    parker = aliased(User)
    rows = (
        await db.execute(
            select(JobPreviousRecruiter, User, parker.name)
            .join(User, User.id == JobPreviousRecruiter.user_id)
            .outerjoin(parker, parker.id == JobPreviousRecruiter.parked_by_id)
            .where(JobPreviousRecruiter.job_id.in_(ids), _open())
            .order_by(JobPreviousRecruiter.parked_at, JobPreviousRecruiter.id)
        )
    ).all()
    for row, user, parked_by_name in rows:
        out[row.job_id].append(
            PreviousRecruiter(
                user_id=user.id,
                name=user.name,
                via=row.via,
                reason=row.reason,
                parked_at=row.parked_at,
                parked_by_name=parked_by_name,
                will_return=bool(user.is_active and user.has_any_role(*WORK_ROLES)),
            )
        )
    return out


async def working_owner_id(db: AsyncSession, job: Job) -> Optional[int]:
    """Prowadzący, który PRACUJE — ``None``, gdy jest wśród poprzednich.

    Dzwonki „do prowadzącego rekrutacji” (nowe zgłoszenie, termin, karta
    utknęła) nie budzą osoby, która przy rekrutacji już nie pracuje; wołający
    spada wtedy na swoją dotychczasową ścieżkę zapasową (zwykle DL).
    """
    owner_id = job.recruiter_id
    if owner_id is None:
        return None
    parked = await db.scalar(
        select(JobPreviousRecruiter.id)
        .where(
            JobPreviousRecruiter.job_id == job.id,
            JobPreviousRecruiter.user_id == owner_id,
            _open(),
        )
        .limit(1)
    )
    return None if parked is not None else owner_id


# ── Zapis ────────────────────────────────────────────────────────────────────


async def clear_parked(
    db: AsyncSession,
    *,
    job_id: int,
    user_id: int,
    reason: str,
    actor_id: Optional[int],
) -> bool:
    """Zdejmuje znacznik „poprzedni” z osoby. ``True``, gdy był."""
    result = await db.execute(
        update(JobPreviousRecruiter)
        .where(
            JobPreviousRecruiter.job_id == job_id,
            JobPreviousRecruiter.user_id == user_id,
            _open(),
        )
        .values(
            cleared_at=datetime.now(timezone.utc),
            cleared_reason=reason,
            cleared_by_id=actor_id,
        )
        .execution_options(synchronize_session=False)
    )
    return bool(result.rowcount)


async def park_team(
    db: AsyncSession,
    job: Job,
    *,
    reason: str,
    actor_id: Optional[int],
    notify: bool,
    release_assignments: bool,
) -> list[int]:
    """Przenosi wszystkich, którzy pracują, do „Poprzedni rekruter”.

    Zespół liczony PRZED zmianą stanu requestu: ręczne zdjęcie prowadzącego
    liczy się od ``work_state_changed_at``, więc po zamknięciu osoba zdjęta
    wcześniej wróciłaby do zespołu i trafiła do poprzednich.

    ``release_assignments`` (zejście z P1): żywe przypisania tych osób
    dostają powód ``parked`` — automat nie liczy ich w obłożeniu ani nie
    uznaje requestu za pokryty. Zamknięcie ich nie rusza: automat zwalnia je
    sam (``finished``), a poranny skrót mówi wtedy „Request zakończony”.
    Zwraca identyfikatory uśpionych osób.
    """
    from app.services.job_team import recruiters_for_jobs, working  # noqa: PLC0415

    team = working((await recruiters_for_jobs(db, [job.id])).get(job.id, []))
    if not team:
        return []
    now = datetime.now(timezone.utc)
    parked: list[int] = []
    for person in team:
        inserted = await db.scalar(
            pg_insert(JobPreviousRecruiter)
            .values(
                job_id=job.id,
                user_id=person.user_id,
                via=person.via,
                assignment_source=(
                    person.assignment_source
                    if person.via == "assignment"
                    and person.assignment_source in ("auto", "manual")
                    else None
                ),
                reason=reason,
                parked_at=now,
                parked_by_id=actor_id,
            )
            .on_conflict_do_nothing(
                index_elements=["job_id", "user_id"],
                index_where=text("cleared_at IS NULL"),
            )
            .returning(JobPreviousRecruiter.id)
        )
        if inserted is not None:
            parked.append(person.user_id)
    if not parked:
        return []
    if release_assignments:
        await db.execute(
            update(JobWorkAssignment)
            .where(
                JobWorkAssignment.job_id == job.id,
                JobWorkAssignment.user_id.in_(parked),
                JobWorkAssignment.state == "active",
            )
            .values(
                state="released",
                released_at=now,
                release_reason=PARKED_RELEASE_REASON,
            )
            .execution_options(synchronize_session=False)
        )
    db.add(
        Activity(
            entity_type="job",
            entity_id=job.id,
            action="recruiters_parked",
            user_id=actor_id,
            details={"reason": reason, "user_ids": parked},
        )
    )
    await db.flush()
    if notify:
        await _notify(
            db,
            job_id=job.id,
            user_ids=[uid for uid in parked if uid != actor_id],
            ntype=NotificationType.recruiter_parked,
            title="Rekrutacja zeszła z P1",
            suffix="Przechodzisz do poprzednich rekruterów — wrócisz, gdy rekrutacja wróci na P1.",
        )
    return parked


async def restore_team(
    db: AsyncSession,
    job: Job,
    *,
    actor_id: Optional[int],
    notify: bool,
    exclude_user_ids: Iterable[int] = (),
    skip_bell_for: Iterable[int] = (),
) -> list[int]:
    """Osoby z „Poprzedni rekruter” znowu pracują nad rekrutacją.

    Konto nieaktywne albo bez roli rekrutera nie wraca (``skipped`` —
    rekruterem jest tylko rola rekrutera, decyzja Artura 14.10.2026). Osoba,
    która po zdjęciu znacznika nadal nie pracuje, dostaje drogę z powrotem:
    przypisanie automatu wraca jako przypisanie automatu (planer zwolni je
    za urlop jak każde inne), reszta — trwały wpis w zespole (prowadzący,
    którego fotel zajął ktoś inny, zostaje kolejną osobą).
    ``exclude_user_ids`` zostają wśród poprzednich. Zwraca przywróconych.
    """
    from app.services.job_team import (  # noqa: PLC0415
        WORK_ROLES,
        add_manual_member,
        recruiters_for_jobs,
        working,
    )

    excluded = set(exclude_user_ids)
    rows = (
        await db.scalars(
            select(JobPreviousRecruiter)
            .where(JobPreviousRecruiter.job_id == job.id, _open())
            .order_by(JobPreviousRecruiter.parked_at, JobPreviousRecruiter.id)
        )
    ).all()
    now = datetime.now(timezone.utc)
    restored: list[JobPreviousRecruiter] = []
    skipped: list[int] = []
    for row in rows:
        if row.user_id in excluded:
            continue
        person = await db.get(User, row.user_id)
        eligible = (
            person is not None and person.is_active and person.has_any_role(*WORK_ROLES)
        )
        row.cleared_at = now
        row.cleared_by_id = actor_id
        row.cleared_reason = "restored" if eligible else "skipped"
        if eligible:
            restored.append(row)
        else:
            skipped.append(row.user_id)
    if not restored and not skipped:
        return []
    await db.flush()

    working_ids = {
        person.user_id
        for person in working((await recruiters_for_jobs(db, [job.id])).get(job.id, []))
    }
    for row in restored:
        if row.user_id in working_ids:
            continue
        if row.via == "assignment" and row.assignment_source == "auto":
            await db.execute(
                pg_insert(JobWorkAssignment)
                .values(
                    job_id=job.id,
                    user_id=row.user_id,
                    role=WORK_ROLE,
                    source="auto",
                    state="active",
                    assigned_at=now,
                )
                .on_conflict_do_nothing(
                    index_elements=["job_id", "user_id"],
                    index_where=text("state <> 'released'"),
                )
            )
        else:
            await add_manual_member(
                db, job_id=job.id, user_id=row.user_id, actor_id=actor_id, unpark=False
            )
    restored_ids = [row.user_id for row in restored]
    details: dict = {"user_ids": restored_ids}
    if skipped:
        details["skipped_user_ids"] = skipped
    db.add(
        Activity(
            entity_type="job",
            entity_id=job.id,
            action="recruiters_restored",
            user_id=actor_id,
            details=details,
        )
    )
    await db.flush()
    if notify:
        quiet = set(skip_bell_for)
        if actor_id is not None:
            quiet.add(actor_id)
        await _notify(
            db,
            job_id=job.id,
            user_ids=[uid for uid in restored_ids if uid not in quiet],
            ntype=NotificationType.recruiter_restored,
            title="Rekrutacja wróciła na P1",
            suffix="Znowu pracujesz nad tą rekrutacją.",
        )
    return restored_ids


async def apply_priority_transition(
    db: AsyncSession,
    job: Job,
    *,
    previous_priority: object,
    actor_id: Optional[int],
) -> None:
    """Zmiana priorytetu otwartej rekrutacji: zejście z P1 usypia zespół,
    powrót na P1 go przywraca. P2 ↔ „Przyjmujemy kandydatów” i zmiana
    priorytetu zamkniętej rekrutacji niczego nie ruszają (zamknięta ma
    zespół wśród poprzednich od zamknięcia, wraca przy ponownym otwarciu).
    Wołający trzyma ``allocation_lock`` i blokadę wiersza."""
    if job.status != JobStatus.published:
        return
    before, after = level_of(previous_priority), level_of(job.priority)
    if before == after:
        return
    if before == "p1":
        await park_team(
            db,
            job,
            reason="priority",
            actor_id=actor_id,
            notify=True,
            release_assignments=True,
        )
    elif after == "p1":
        await restore_team(db, job, actor_id=actor_id, notify=True)


# ── Dzwonki ──────────────────────────────────────────────────────────────────


async def _notify(
    db: AsyncSession,
    *,
    job_id: int,
    user_ids: list[int],
    ntype: NotificationType,
    title: str,
    suffix: str,
) -> None:
    """Dzwonek do każdej osoby. Savepoint: nieudane powiadomienie nie cofa
    zmiany zespołu."""
    if not user_ids:
        return
    from app.services.job_working_title import job_display_title_expr  # noqa: PLC0415
    from app.services.notification_triggers import emit  # noqa: PLC0415

    row = (
        await db.execute(
            select(job_display_title_expr(), Client.name)
            .select_from(Job)
            .outerjoin(Client, Client.id == Job.client_id)
            .where(Job.id == job_id)
        )
    ).first()
    job_title, client_name = (row[0], row[1]) if row else ("Rekrutacja", None)
    head = f"{job_title} · {client_name}" if client_name else job_title
    for user_id in user_ids:
        try:
            async with db.begin_nested():
                await emit(
                    db,
                    user_id=user_id,
                    title=title,
                    message=f"{head}. {suffix}",
                    ntype=ntype,
                    related_entity_type="job",
                    related_entity_id=job_id,
                    link=f"/jobs/{job_id}",
                )
        except Exception:  # noqa: BLE001 — dzwonek nie może cofnąć zmiany zespołu
            logger.exception(
                "[previous_recruiters] dzwonek %s nie wyszedł job=%s user=%s",
                ntype.value,
                job_id,
                user_id,
            )
