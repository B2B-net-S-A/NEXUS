"""„Prowadzi” — ręczne przypisanie osoby prowadzącej kandydata w rekrutacji.

Prośba Olafa z 23.10.2026, decyzje Artura z 25.10.2026 (makiety:
https://claude.ai/artifact/RYRUWbkuSfYWnW2NfJ6FUu):

* przypisuje admin albo Head of Recruitment, z powodem zapisanym w historii;
* przypisać można aktywną osobę z rolą rekrutera — także Delivery Leada,
  który ma rolę rekrutera;
* przypisana osoba zastępuje „pierwszego weryfikującego” wszędzie, gdzie
  liczy się, czyj to kandydat: karta i panel, filtr „Kto dodał”, kto ma ruch
  i dzwonki, „Moi ludzie”, Liga i cele, premia rekrutera za placement.

Brak przypisania = jak dotąd. Przypisanie żyje na parze, nie na podejściu
procesu, więc przetrwa ponowne otwarcie; przy zapisie dostaje je też
bieżący proces (``owner_user_id``), żeby obie drogi wskazywały tę samą osobę.
Reguły: ``docs/claude/rekrutacja-tablica/prowadzi-przypisanie-osoby.md``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.candidate_job_owner import CandidateJobOwner, CandidateJobOwnerEvent
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.user import User, UserRole

REASON_MAX = 500


@dataclass(frozen=True)
class PairOwner:
    owner_user_id: int
    owner_name: Optional[str]
    assigned_by_name: Optional[str]
    assigned_at: datetime
    previous_owner_name: Optional[str]


def may_assign(user: User) -> bool:
    return user.has_any_role(UserRole.admin, UserRole.head_of_recruitment)


def can_own(user: User) -> bool:
    """Prowadzić może aktywna osoba z rolą rekrutera (także DL z tą rolą)."""

    return bool(user.is_active) and user.has_role(UserRole.recruiter)


async def owner_ids(
    db: AsyncSession, pairs: Iterable[tuple[int, int]]
) -> dict[tuple[int, int], int]:
    """Przypisani prowadzący dla par (kandydat, rekrutacja) — jedno zapytanie."""

    wanted = list(dict.fromkeys(pairs))
    if not wanted:
        return {}
    rows = await db.execute(
        select(
            CandidateJobOwner.candidate_id,
            CandidateJobOwner.job_id,
            CandidateJobOwner.owner_user_id,
        ).where(
            tuple_(CandidateJobOwner.candidate_id, CandidateJobOwner.job_id).in_(wanted)
        )
    )
    return {(cid, jid): uid for cid, jid, uid in rows.all()}


async def owners_for_job(db: AsyncSession, job_id: int) -> dict[int, PairOwner]:
    """Przypisania jednej rekrutacji z nazwami — dla Tablicy (dwa zapytania)."""

    rows = (
        await db.scalars(
            select(CandidateJobOwner).where(CandidateJobOwner.job_id == job_id)
        )
    ).all()
    if not rows:
        return {}
    user_ids = {
        uid
        for row in rows
        for uid in (row.owner_user_id, row.assigned_by, row.previous_owner_id)
        if uid is not None
    }
    names = dict(
        (
            await db.execute(select(User.id, User.name).where(User.id.in_(user_ids)))
        ).all()
    )
    return {
        row.candidate_id: PairOwner(
            owner_user_id=row.owner_user_id,
            owner_name=names.get(row.owner_user_id),
            assigned_by_name=names.get(row.assigned_by) if row.assigned_by else None,
            assigned_at=row.updated_at,
            previous_owner_name=(
                names.get(row.previous_owner_id) if row.previous_owner_id else None
            ),
        )
        for row in rows
    }


async def implicit_owner_id(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> Optional[int]:
    """Prowadzący bez przypisania: pierwszy weryfikujący, inaczej osoba,
    która dodała (pierwszy wiersz etapu) — jak karta na Tablicy."""

    pair = (
        CandidateStage.candidate_id == candidate_id,
        CandidateStage.job_id == job_id,
        CandidateStage.moved_by.is_not(None),
    )
    verifier = await db.scalar(
        select(CandidateStage.moved_by)
        .where(*pair, CandidateStage.stage == PipelineStage.verified)
        .order_by(
            func.coalesce(CandidateStage.approved_at, CandidateStage.moved_at),
            CandidateStage.id,
        )
        .limit(1)
    )
    if verifier is not None:
        return verifier
    return await db.scalar(
        select(CandidateStage.moved_by)
        .where(*pair)
        .order_by(CandidateStage.moved_at, CandidateStage.id)
        .limit(1)
    )


async def assign_owner(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    owner_user_id: int,
    reason: str,
    actor: User,
    previous_owner_id: Optional[int],
) -> CandidateJobOwner:
    """Zapisuje przypisanie, wpis historii i właściciela bieżącego procesu.

    ``previous_owner_id`` — kogo panel pokazywał jako prowadzącego przed
    zmianą (także wyliczonego, gdy wcześniej nikt nie przypisywał).
    """

    if not may_assign(actor):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Osobę prowadzącą przypisuje admin albo Head of Recruitment.",
        )
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise HTTPException(status_code=422, detail="Napisz, dlaczego zmieniasz osobę.")
    if len(reason) > REASON_MAX:
        raise HTTPException(
            status_code=422, detail=f"Powód może mieć najwyżej {REASON_MAX} znaków."
        )
    owner = await db.get(User, owner_user_id)
    if owner is None or not can_own(owner):
        raise HTTPException(
            status_code=422,
            detail="Prowadzić może tylko aktywna osoba z rolą rekrutera.",
        )
    # Ta sama kolejność blokad co przy ruchu karty: najpierw kandydat.
    locked = await db.scalar(
        select(Candidate.id).where(Candidate.id == candidate_id).with_for_update()
    )
    in_pipeline = await db.scalar(
        select(CandidateStage.id)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
        .limit(1)
    )
    if locked is None or in_pipeline is None:
        raise HTTPException(
            status_code=404, detail="Ten kandydat nie bierze udziału w tej rekrutacji."
        )
    now = datetime.now(timezone.utc)
    row = await db.get(CandidateJobOwner, (candidate_id, job_id), with_for_update=True)
    if row is None:
        row = CandidateJobOwner(
            candidate_id=candidate_id,
            job_id=job_id,
            owner_user_id=owner_user_id,
            previous_owner_id=previous_owner_id,
            assigned_by=actor.id,
            reason=reason,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.previous_owner_id = row.owner_user_id
        row.owner_user_id = owner_user_id
        row.assigned_by = actor.id
        row.reason = reason
        row.updated_at = now
    db.add(
        CandidateJobOwnerEvent(
            candidate_id=candidate_id,
            job_id=job_id,
            owner_user_id=owner_user_id,
            previous_owner_id=row.previous_owner_id,
            assigned_by=actor.id,
            reason=reason,
            created_at=now,
        )
    )
    process = await db.scalar(
        select(RecruitmentProcess)
        .where(
            RecruitmentProcess.candidate_id == candidate_id,
            RecruitmentProcess.job_id == job_id,
        )
        .order_by(RecruitmentProcess.attempt_no.desc(), RecruitmentProcess.id.desc())
        .limit(1)
        .with_for_update()
    )
    # Liga i cele liczą się od teraz z przypisania (``kpi_panel``).
    from app.services.priority_work_policy import invalidate_milestone_counts

    invalidate_milestone_counts()
    if process is not None and process.status == ProcessStatus.open:
        process.owner_user_id = owner_user_id
        process.ownership_confirmed_at = now
        process.ownership_confirmed_by_user_id = actor.id
        process.state_version = (process.state_version or 0) + 1
    await db.flush()
    return row


async def forget_pair(db: AsyncSession, *, candidate_id: int, job_id: int) -> None:
    """Korekcyjne usunięcie pary z rekrutacji zdejmuje też przypisanie.

    Historia (``candidate_job_owner_events``) zostaje jak archiwum etapów.
    """

    row = await db.get(CandidateJobOwner, (candidate_id, job_id))
    if row is not None:
        await db.delete(row)
