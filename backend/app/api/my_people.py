# UWAGA: bez `from __future__ import annotations` — `@limiter.limit` na
# funkcji z adnotacjami jako stringami (PEP 563) sprawia, że slowapi nie widzi
# typów zależności i ciało żądania ląduje jako parametr query (slowapi #579).
"""Router `/api/my-people` — lista „Moi ludzie" rekrutera.

Lista wylicza się sama z historii pipeline'u (``services/my_people.py``):
osoby, które rekruter zweryfikował jako pierwszy i które potem poszły do
klienta. Tutaj tylko odczyt, ręczne decyzje (uśpij / przypnij) i zakładka
„Do tej rekrutacji".

Bramka ``CandidateSearchAccess`` — te same role i ta sama sekcja co lista
kandydatów; wiersz niesie nazwisko i stawkę z profilu, które ta rola i tak
widzi na liście kandydatów. Każdy widzi WYŁĄCZNIE swoją listę.
"""

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import case, delete, func, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidateSearchAccess
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.candidate import Candidate
from app.models.my_people import MyPeopleOverride
from app.services import my_people as svc

router = APIRouter()

SnoozeReason = Literal["found_job", "not_interested", "no_contact", "other"]


class MyPeopleRow(BaseModel):
    candidate_id: int
    full_name: str
    category_id: Optional[int] = None
    furthest_stage: Optional[str] = None
    last_sent_at: Optional[datetime] = None
    last_sent_job_title: Optional[str] = None
    last_sent_client_name: Optional[str] = None
    sent_count: int = 0
    days_since_last_send: Optional[int] = None
    expected_rate_hourly: Optional[float] = None
    availability_status: Optional[str] = None
    city: Optional[str] = None
    source: Literal["auto", "pinned"] = "auto"
    active_processes: int = 0
    working: bool = False
    snoozed: bool = False
    snooze_reason: Optional[str] = None
    snoozed_at: Optional[datetime] = None
    new_matches: int = 0


class MyPeopleResponse(BaseModel):
    rows: list[MyPeopleRow]
    total: int
    active_count: int
    working_count: int
    snoozed_count: int
    truncated: bool = False


class UnseenMatch(BaseModel):
    job_id: int
    job_title: str
    candidate_id: int
    full_name: str
    score: Optional[float] = None
    created_at: datetime


class IdlePerson(BaseModel):
    candidate_id: int
    full_name: str
    days_since_last_send: int


class MyPeopleSummary(BaseModel):
    total: int
    new_matches: int
    jobs_with_matches: int
    latest_matches: list[UnseenMatch]
    idle_count: int
    idle_top: list[IdlePerson]
    idle_days: int = svc.IDLE_DAYS


class SnoozeRequest(BaseModel):
    reason: SnoozeReason
    note: Optional[str] = Field(default=None, max_length=500)


class SeenRequest(BaseModel):
    job_id: Optional[int] = None


class ForJobRow(BaseModel):
    candidate_id: int
    full_name: str
    category_id: Optional[int] = None
    score: Optional[int] = None
    measurement: str
    eligibility: Optional[dict] = None
    in_job: bool = False
    sent_to_client_at: Optional[datetime] = None
    last_sent_client_name: Optional[str] = None
    days_since_last_send: Optional[int] = None
    expected_rate_hourly: Optional[float] = None
    active_processes: int = 0


class ForJobResponse(BaseModel):
    job_id: int
    job_title: str
    rows: list[ForJobRow]
    in_job_count: int
    # Wektor/dostawca niedostępny — wyniki niepoliczone. Ekran MUSI to
    # powiedzieć zamiast pokazać listę bez liczb jak „nikt nie pasuje".
    degraded: bool = False


def _row(r: svc.PersonRow) -> MyPeopleRow:
    return MyPeopleRow(**r.__dict__)


@router.get("", response_model=MyPeopleResponse)
async def list_my_people(
    user: CandidateSearchAccess,
    db: AsyncSession = Depends(get_db),
) -> MyPeopleResponse:
    people = await svc.load_my_people(db, user.id)
    return MyPeopleResponse(
        rows=[_row(r) for r in people.rows],
        total=len(people.rows),
        active_count=sum(1 for r in people.rows if not r.snoozed and not r.working),
        working_count=sum(1 for r in people.rows if r.working and not r.snoozed),
        snoozed_count=sum(1 for r in people.rows if r.snoozed),
        truncated=people.truncated,
    )


@router.get("/summary", response_model=MyPeopleSummary)
async def my_people_summary(
    user: CandidateSearchAccess,
    db: AsyncSession = Depends(get_db),
) -> MyPeopleSummary:
    people = await svc.load_my_people(db, user.id)
    active = people.active
    idle = sorted(
        (
            r
            for r in active
            if r.active_processes == 0
            and r.days_since_last_send is not None
            and r.days_since_last_send > svc.IDLE_DAYS
        ),
        key=lambda r: r.days_since_last_send or 0,
    )
    new_matches, jobs = await svc.unseen_totals(db, user.id)
    latest = await svc.unseen_matches(db, user.id)
    return MyPeopleSummary(
        total=len(active),
        new_matches=new_matches,
        jobs_with_matches=jobs,
        latest_matches=[UnseenMatch(**m) for m in latest],
        idle_count=len(idle),
        # Najkrócej czekający najpierw: tych jeszcze da się „odzyskać" jednym
        # telefonem; osoby sprzed dwóch lat nie są pilne tego samego dnia.
        idle_top=[
            IdlePerson(
                candidate_id=r.candidate_id,
                full_name=r.full_name,
                days_since_last_send=r.days_since_last_send or 0,
            )
            for r in idle[:3]
        ],
    )


async def _require_candidate(db: AsyncSession, candidate_id: int) -> None:
    if await db.get(Candidate, candidate_id) is None:
        raise HTTPException(404, "Kandydat nie istnieje")


async def _set_override(
    db: AsyncSession,
    *,
    user_id: int,
    candidate_id: int,
    kind: str,
    reason: Optional[str] = None,
    note: Optional[str] = None,
) -> None:
    # Audyt 22.09 r2 (CAND-07): uśpienie PRZYPIĘTEJ osoby zapamiętuje
    # przypięcie w `restore_kind` (przypięcie ze stałego linku to jedyny powód,
    # dla którego osoba jest na liście) — „Przywróć” wraca do niego zamiast
    # kasować wiersz. Ponowne uśpienie uśpionej osoby zachowuje pamięć;
    # przypięcie ją zeruje (osoba JEST przypięta).
    if kind == "snoozed":
        restore_on_conflict = case(
            (MyPeopleOverride.kind == "pinned", "pinned"),
            else_=MyPeopleOverride.restore_kind,
        )
    else:
        restore_on_conflict = None
    await db.execute(
        pg_insert(MyPeopleOverride)
        .values(
            user_id=user_id,
            candidate_id=candidate_id,
            kind=kind,
            reason=reason,
            note=note,
            restore_kind=None,
        )
        .on_conflict_do_update(
            constraint="uq_my_people_overrides_user_candidate",
            set_={
                "kind": kind,
                "reason": reason,
                "note": note,
                "restore_kind": restore_on_conflict,
                "created_at": func.now(),
            },
        )
    )


async def _clear_override(
    db: AsyncSession, *, user_id: int, candidate_id: int, kind: str
) -> None:
    await db.execute(
        delete(MyPeopleOverride).where(
            MyPeopleOverride.user_id == user_id,
            MyPeopleOverride.candidate_id == candidate_id,
            MyPeopleOverride.kind == kind,
        )
    )


@router.post("/{candidate_id}/snooze", status_code=204)
async def snooze_person(
    candidate_id: int,
    body: SnoozeRequest,
    user: CandidateSearchAccess,
    db: AsyncSession = Depends(get_db),
) -> None:
    await _require_candidate(db, candidate_id)
    await _set_override(
        db,
        user_id=user.id,
        candidate_id=candidate_id,
        kind="snoozed",
        reason=body.reason,
        note=body.note,
    )
    await db.commit()


@router.delete("/{candidate_id}/snooze", status_code=204)
async def unsnooze_person(
    candidate_id: int,
    user: CandidateSearchAccess,
    db: AsyncSession = Depends(get_db),
) -> None:
    # CAND-07: uśpiona osoba przypięta wcześniej wraca do przypiętych.
    restored = await db.execute(
        update(MyPeopleOverride)
        .where(
            MyPeopleOverride.user_id == user.id,
            MyPeopleOverride.candidate_id == candidate_id,
            MyPeopleOverride.kind == "snoozed",
            MyPeopleOverride.restore_kind == "pinned",
        )
        .values(
            kind="pinned",
            reason=None,
            note=None,
            restore_kind=None,
            created_at=func.now(),
        )
    )
    if not restored.rowcount:
        await _clear_override(
            db, user_id=user.id, candidate_id=candidate_id, kind="snoozed"
        )
    await db.commit()


@router.post("/{candidate_id}/pin", status_code=204)
async def pin_person(
    candidate_id: int,
    user: CandidateSearchAccess,
    db: AsyncSession = Depends(get_db),
) -> None:
    await _require_candidate(db, candidate_id)
    await _set_override(db, user_id=user.id, candidate_id=candidate_id, kind="pinned")
    await db.commit()


@router.delete("/{candidate_id}/pin", status_code=204)
async def unpin_person(
    candidate_id: int,
    user: CandidateSearchAccess,
    db: AsyncSession = Depends(get_db),
) -> None:
    await _clear_override(db, user_id=user.id, candidate_id=candidate_id, kind="pinned")
    # Odpięcie uśpionej osoby: „Przywróć” nie może jej już przypiąć z powrotem.
    await db.execute(
        update(MyPeopleOverride)
        .where(
            MyPeopleOverride.user_id == user.id,
            MyPeopleOverride.candidate_id == candidate_id,
            MyPeopleOverride.kind == "snoozed",
        )
        .values(restore_kind=None)
    )
    await db.commit()


@router.post("/matches/seen", status_code=200)
async def mark_seen(
    body: SeenRequest,
    user: CandidateSearchAccess,
    db: AsyncSession = Depends(get_db),
) -> dict:
    updated = await svc.mark_matches_seen(db, user.id, job_id=body.job_id)
    await db.commit()
    return {"updated": updated}


@router.get("/for-job/{job_id}", response_model=ForJobResponse)
# Liczy na żądanie (embedding zapytania + wektor + scoring do 60 osób).
# Panel pyta raz na otwarcie zakładki (staleTime 60 s) — to sufit na
# rozpędzonego klienta, nie budżet zwykłej pracy.
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def my_people_for_job(
    request: Request,
    job_id: int,
    user: CandidateSearchAccess,
    db: AsyncSession = Depends(get_db),
) -> ForJobResponse:
    from app.api.candidate_search import _authorized_job  # noqa: PLC0415
    from app.services.auto_match_service import AutoMatchUnavailable  # noqa: PLC0415
    from app.services.my_people_matching import (  # noqa: PLC0415
        candidates_in_job,
        last_sent_to_client,
        score_people_for_job,
    )

    job = await _authorized_job(db, user, job_id)
    people = await svc.load_my_people(db, user.id)
    active = {r.candidate_id: r for r in people.active}
    in_job = await candidates_in_job(db, job.id, active)
    candidates = [cid for cid in active if cid not in in_job]

    degraded = False
    scored: dict[int, object] = {}
    if candidates:
        try:
            scored = {
                p.candidate_id: p
                for p in await score_people_for_job(
                    db,
                    job=job,
                    candidate_ids=candidates,
                    profile_user_id=user.id,
                    pool_limit=settings.MY_PEOPLE_PANEL_POOL,
                )
            }
        except AutoMatchUnavailable:
            degraded = True
    sent = await last_sent_to_client(db, job.client_id, candidates)

    rows: list[ForJobRow] = []
    for cid in candidates:
        person = active[cid]
        s = scored.get(cid)
        if s is not None and getattr(s, "hidden", False):
            continue
        rows.append(
            ForJobRow(
                candidate_id=cid,
                full_name=person.full_name,
                category_id=person.category_id,
                score=getattr(s, "score", None),
                measurement=getattr(
                    s, "measurement", "unavailable" if degraded else "not_in_pool"
                ),
                eligibility=getattr(s, "eligibility", None),
                sent_to_client_at=sent.get(cid),
                last_sent_client_name=person.last_sent_client_name,
                days_since_last_send=person.days_since_last_send,
                expected_rate_hourly=person.expected_rate_hourly,
                active_processes=person.active_processes,
            )
        )
    rows.sort(key=lambda r: (r.score is None, -(r.score or 0), r.full_name.lower()))
    return ForJobResponse(
        job_id=job.id,
        job_title=job.title,
        rows=rows,
        in_job_count=len(in_job),
        degraded=degraded,
    )
