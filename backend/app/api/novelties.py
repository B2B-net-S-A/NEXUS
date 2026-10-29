"""Nowości do przeklikania (0625) — kropki, przeklikanie i panel „kto już umie”.

Treść nowości to rejestr ``app/data/novelties/novelties.json`` (bez danych
domenowych); tabela ``novelty_progress`` trzyma tylko stan osoby przy nowości.

- ``GET /novelties/mine`` i ``POST /novelties/{id}/events`` — każda zalogowana
  osoba, wyłącznie o sobie i o nowościach swojej roli;
- ``GET /novelties/adoption`` i ``POST /novelties/{id}/remind`` — admin i Head
  of Recruitment (decyzja Artura 28.10.2026), bo panel pokazuje imiennie, kto
  jeszcze nie umie.

Moduł ma ``@limiter.limit``, więc bez ``from __future__ import annotations``
(ciało żądania trafiłoby do query → 422).
"""

from datetime import datetime, time, timedelta, timezone
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, HeadOfRecruitmentPlus
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.core.scheduling import DEFAULT_TZ, business_today
from app.data.novelties import Novelty, in_audience, load_novelties
from app.models.novelty import NoveltyProgress
from app.models.user import User
from app.services.action_permissions import named_permissions_of

router = APIRouter()

NoveltyEvent = Literal[
    "seen", "card_dismissed", "postponed", "toured", "used", "dot_clicked"
]

#: Zdarzenie, które zalicza nowość, i jak to zapisujemy.
_COMPLETING: dict[str, str] = {"toured": "tour", "used": "used", "dot_clicked": "dot"}

#: Okno zmiany procesu wraca następnego dnia o tej godzinie (Europe/Warsaw).
POSTPONE_TO = time(8, 0)


class NoveltyEventIn(BaseModel):
    event: NoveltyEvent


class RemindIn(BaseModel):
    #: Brak listy = wszyscy z grupy docelowej, którzy jeszcze nie zaliczyli.
    user_ids: Optional[list[int]] = Field(default=None, max_length=500)


def _impersonating(request: Request) -> bool:
    return getattr(request.state, "impersonator_id", None) is not None


def _role_values(user: Any) -> set[str]:
    try:
        return {getattr(r, "value", str(r)) for r in user.get_all_roles()}
    except Exception:  # noqa: BLE001 — rola główna wystarcza jako zapas
        return {getattr(user.role, "value", str(user.role))}


def _audience_of(user: Any, novelty: Novelty) -> bool:
    return in_audience(novelty, _role_values(user), named_permissions_of(user))


def next_morning(now: datetime) -> datetime:
    """Jutro o 8:00 czasu firmy — do tej chwili okno zmiany procesu milczy."""
    tz = ZoneInfo(DEFAULT_TZ)
    tomorrow = now.astimezone(tz).date() + timedelta(days=1)
    return datetime.combine(tomorrow, POSTPONE_TO, tzinfo=tz)


def shape_for_user(
    novelty: Novelty, progress: Optional[NoveltyProgress], now: datetime
) -> dict[str, Any]:
    """Nowość z punktu widzenia osoby: co pokazać i czy już umie."""
    done = progress is not None and progress.completed_at is not None
    dismissed = progress is not None and progress.card_dismissed_at is not None
    reminded_after_dismiss = (
        dismissed
        and progress.reminded_at is not None
        and progress.reminded_at > progress.card_dismissed_at
    )
    postponed = (
        progress is not None
        and progress.postponed_until is not None
        and progress.postponed_until > now
    )
    return {
        "id": novelty.id,
        "title": novelty.title,
        "why": novelty.why,
        "tier": novelty.tier,
        "shipped_on": novelty.shipped_on.isoformat(),
        "where": novelty.where,
        "href": novelty.href,
        "dot_anchor": novelty.dot_anchor,
        "used_anchor": novelty.used_anchor,
        "path_prefix": novelty.path_prefix,
        "steps": [step.model_dump() for step in novelty.steps],
        "done": done,
        "completed_via": progress.completed_via if progress else None,
        # Karta przy kropce: aż do „Później”, chyba że ktoś potem przypomniał.
        "show_card": not done
        and novelty.tier != "dot"
        and (not dismissed or reminded_after_dismiss),
        # Okno zmiany procesu: do zaliczenia, poza czasem odłożenia.
        "required_now": not done and novelty.tier == "process" and not postponed,
        "can_postpone": novelty.tier == "process"
        and (progress is None or progress.postponed_until is None),
    }


async def _progress_rows(
    db: AsyncSession, user_id: int, ids: list[str]
) -> dict[str, NoveltyProgress]:
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(NoveltyProgress).where(
                NoveltyProgress.user_id == user_id, NoveltyProgress.novelty_id.in_(ids)
            )
        )
    ).scalars()
    return {row.novelty_id: row for row in rows}


@router.get("/novelties/mine")
async def my_novelties(
    request: Request, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    """W podglądzie jako inna osoba bez karty i bez okna zmiany procesu:
    zapisy są wtedy zablokowane (``deps.py``), więc okna nie dałoby się zamknąć."""
    today = business_today()
    mine = [
        n
        for n in load_novelties().values()
        if n.active_on(today) and _audience_of(current_user, n)
    ]
    progress = await _progress_rows(db, current_user.id, [n.id for n in mine])
    now = datetime.now(timezone.utc)
    shaped = [shape_for_user(n, progress.get(n.id), now) for n in mine]
    if _impersonating(request):
        return [quiet_for_preview(item) for item in shaped]
    return shaped


def quiet_for_preview(item: dict[str, Any]) -> dict[str, Any]:
    """Podgląd admina pokazuje kropki, ale niczego nie wymusza."""
    return {**item, "show_card": False, "required_now": False, "can_postpone": False}


async def _locked_row(
    db: AsyncSession, user_id: int, novelty_id: str
) -> NoveltyProgress:
    """Wiersz osoby przy nowości, założony bez wyścigu i zablokowany do końca
    transakcji. Dwie karty przeglądarki wysyłają pierwsze ``seen`` naraz —
    ``db.get`` + ``db.add`` dawało wtedy 500 na kluczu głównym."""
    await db.execute(
        pg_insert(NoveltyProgress)
        .values(user_id=user_id, novelty_id=novelty_id, seen_count=0)
        .on_conflict_do_nothing(index_elements=["user_id", "novelty_id"])
    )
    return (
        await db.execute(
            select(NoveltyProgress)
            .where(
                NoveltyProgress.user_id == user_id,
                NoveltyProgress.novelty_id == novelty_id,
            )
            .with_for_update()
        )
    ).scalar_one()


def apply_event(
    row: NoveltyProgress, novelty: Novelty, event: str, now: datetime
) -> None:
    """Jedno zdarzenie na wierszu osoby. Odłożenie drugi raz = 409."""
    if event == "seen":
        row.first_seen_at = row.first_seen_at or now
        row.seen_count = (row.seen_count or 0) + 1
    elif event == "card_dismissed":
        row.card_dismissed_at = now
    elif event == "postponed":
        if novelty.tier != "process":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "postpone_not_allowed",
                    "message": "Odłożyć można tylko zmianę procesu.",
                },
            )
        if row.postponed_until is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "postpone_used",
                    "message": "Tę zmianę odłożono już raz — przeklikaj ją teraz.",
                },
            )
        row.postponed_until = next_morning(now)
    elif event in _COMPLETING:
        if row.completed_at is None:
            row.completed_at = now
            row.completed_via = _COMPLETING[event]
    row.updated_at = now


@router.post("/novelties/{novelty_id}/events", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def record_novelty_event(
    request: Request,
    novelty_id: str,
    payload: NoveltyEventIn,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Kropka pokazana, karta odłożona, nowość przeklikana albo użyta.

    Podgląd jako inna osoba tu nie dochodzi — ``deps.py`` odmawia w nim zapisów."""
    novelty = load_novelties().get(novelty_id)
    if novelty is None or not _audience_of(current_user, novelty):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Nie ma takiej nowości."
        )
    row = await _locked_row(db, current_user.id, novelty_id)
    apply_event(row, novelty, payload.event, datetime.now(timezone.utc))
    await db.commit()


def person_state(progress: Optional[NoveltyProgress]) -> str:
    if progress is None or (
        progress.first_seen_at is None and progress.completed_at is None
    ):
        return "untouched"
    if progress.completed_at is not None:
        return progress.completed_via or "used"
    return "seen"


async def _active_users(db: AsyncSession) -> list[User]:
    return list(
        (await db.execute(select(User).where(User.is_active.is_(True)))).scalars().all()
    )


async def _audience_users(db: AsyncSession, novelty: Novelty) -> list[User]:
    return [u for u in await _active_users(db) if _audience_of(u, novelty)]


@router.get("/novelties/adoption")
async def novelties_adoption(
    current_user: HeadOfRecruitmentPlus, db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    """Kto już umie: per nowość z ostatnich 90 dni, imiennie (admin, HoR)."""
    today = business_today()
    novelties = [n for n in load_novelties().values() if n.in_panel_on(today)]
    rows = (
        (
            await db.execute(
                select(NoveltyProgress).where(
                    NoveltyProgress.novelty_id.in_([n.id for n in novelties] or [""])
                )
            )
        )
        .scalars()
        .all()
    )
    by_key = {(r.novelty_id, r.user_id): r for r in rows}
    active = await _active_users(db)
    out = []
    for novelty in novelties:
        people = []
        for user in (u for u in active if _audience_of(u, novelty)):
            progress = by_key.get((novelty.id, user.id))
            people.append(
                {
                    "user_id": user.id,
                    "name": user.name,
                    "state": person_state(progress),
                    "completed_at": progress.completed_at.isoformat()
                    if progress and progress.completed_at
                    else None,
                    "seen_count": progress.seen_count if progress else 0,
                    "reminded_at": progress.reminded_at.isoformat()
                    if progress and progress.reminded_at
                    else None,
                }
            )
        counts = {s: 0 for s in ("used", "tour", "dot", "seen", "untouched")}
        for person in people:
            counts[person["state"]] += 1
        out.append(
            {
                "id": novelty.id,
                "title": novelty.title,
                "tier": novelty.tier,
                "shipped_on": novelty.shipped_on.isoformat(),
                "pr": novelty.pr,
                "where": novelty.where,
                "active": novelty.active_on(today),
                "audience": len(people),
                "counts": counts,
                "people": sorted(
                    people,
                    key=lambda p: (p["state"] in ("used", "tour", "dot"), p["name"]),
                ),
            }
        )
    return out


@router.post("/novelties/{novelty_id}/remind")
async def remind_novelty(
    novelty_id: str,
    payload: RemindIn,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Przypomnienie = karta przy kropce wraca u wskazanych osób (bez maila)."""
    novelty = load_novelties().get(novelty_id)
    if novelty is None or not novelty.active_on(business_today()):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nie ma takiej aktywnej nowości.",
        )
    audience = {u.id for u in await _audience_users(db, novelty)}
    wanted = audience if payload.user_ids is None else audience & set(payload.user_ids)
    if not wanted:
        return {"reminded": 0}
    # Brakujące wiersze bez wyścigu z pierwszym kliknięciem tej osoby, potem
    # jeden UPDATE tylko u tych, którzy jeszcze nie zaliczyli.
    await db.execute(
        pg_insert(NoveltyProgress)
        .values(
            [
                {"user_id": uid, "novelty_id": novelty_id, "seen_count": 0}
                for uid in sorted(wanted)
            ]
        )
        .on_conflict_do_nothing(index_elements=["user_id", "novelty_id"])
    )
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(NoveltyProgress)
        .where(
            NoveltyProgress.novelty_id == novelty_id,
            NoveltyProgress.user_id.in_(sorted(wanted)),
            NoveltyProgress.completed_at.is_(None),
        )
        .values(reminded_at=now, reminded_by_user_id=current_user.id, updated_at=now)
    )
    await db.commit()
    return {"reminded": int(result.rowcount or 0)}
