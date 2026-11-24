"""Rekrutacja wybrana na dziś w porcji dnia (zgłoszenie rekruterów 16.11.2026).

Rekruterzy umawiają się rano, kto robi który request, a porcja dzieli P0 po
równo między przypisanych (``review_batch_plan``). Osoba może więc wybrać jedną
ze swoich rekrutacji na dziś:

* porcja bierze osoby najpierw z wybranej rekrutacji, a czego tam brakuje,
  dochodzi jak zwykle (najpierw pilne) z pozostałych rekrutacji osoby;
* liczba osób do decyzji się nie zmienia: z wybranej przychodzi tyle osób, ile
  naprawdę przechodzi jej reguły, a z innych rekrutacji schodzi tylko nadwyżka
  ponad porcję (nieruszone osoby wracają do puli zespołu);
* kto wybrał pierwszy, ten bierze pierwszy najlepsze wolne osoby, a nikt nie
  traci kart, które już ma;
* wybór obowiązuje do końca dnia firmy: następnego dnia porcja wraca do
  kolejności z poziomów.

Stan siedzi w ``app_settings['review_batch_focus']``, jak poziomy i plan dnia.
Reguła: ``docs/claude/rekrutacja-tablica/porcja-wybor-rekrutacji-na-dzis.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Mapping, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.scheduling import business_today
from app.models.app_setting import AppSetting
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User

if TYPE_CHECKING:
    from app.services.review_batch_plan import PlanInputs

FOCUS_KEY = "review_batch_focus"
# Ślad każdego wyboru do pomiaru (stan w ``app_settings`` trzyma tylko dzisiejszy dzień).
FOCUS_ACTION = "review_batch.focus"


@dataclass(frozen=True)
class Focus:
    user_id: int
    job_id: int
    at: datetime

    def as_dict(self) -> dict:
        return {"job_id": self.job_id, "at": self.at.isoformat()}


def parse(value: object, day: str) -> dict[int, Focus]:
    """Wybory z dnia ``day``; wczorajszy wybór już nie obowiązuje."""
    if not isinstance(value, dict) or value.get("day") != day:
        return {}
    users = value.get("users")
    if not isinstance(users, dict):
        return {}
    out: dict[int, Focus] = {}
    for raw_user, raw in users.items():
        try:
            user_id = int(raw_user)
            job_id = int(raw["job_id"])
            at = datetime.fromisoformat(str(raw["at"]))
        except (KeyError, TypeError, ValueError):
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        out[user_id] = Focus(user_id=user_id, job_id=job_id, at=at)
    return out


def in_order(focus: Mapping[int, Focus]) -> tuple[tuple[int, int], ...]:
    """(osoba, rekrutacja) od najwcześniejszego wyboru: kto pierwszy, ten bierze."""
    return tuple(
        (item.user_id, item.job_id)
        for item in sorted(focus.values(), key=lambda f: (f.at, f.user_id))
    )


async def read_focus(db: AsyncSession) -> dict[int, Focus]:
    row = await db.get(AppSetting, FOCUS_KEY)
    return parse(row.value if row is not None else None, business_today().isoformat())


async def _write(
    db: AsyncSession, user_id: int, job_id: Optional[int], *, now: datetime
) -> None:
    """Zapis pod blokadą wiersza: dwa wybory naraz idą po kolei, więc „kto
    pierwszy” jest jednoznaczne."""
    await db.execute(
        insert(AppSetting)
        .values(key=FOCUS_KEY, value={})
        .on_conflict_do_nothing(index_elements=[AppSetting.key])
    )
    row = await db.get(
        AppSetting, FOCUS_KEY, with_for_update=True, populate_existing=True
    )
    day = business_today().isoformat()
    current = parse(row.value, day)
    if job_id is None:
        current.pop(user_id, None)
    elif current.get(user_id) is None or current[user_id].job_id != job_id:
        # Ponowny wybór tej samej rekrutacji nie oddaje miejsca w kolejce.
        current[user_id] = Focus(user_id=user_id, job_id=job_id, at=now)
    row.value = {
        "day": day,
        "users": {str(item.user_id): item.as_dict() for item in current.values()},
    }
    row.updated_by = user_id
    await db.flush()


@dataclass(frozen=True)
class Preview:
    """Co się stanie po wyborze: ile osób przyjdzie z wybranej rekrutacji i ile
    nieruszonych z innych wróci do puli zespołu, żeby porcja się nie zmieniła."""

    take: int
    release: int


def preview(
    *,
    seats: int,
    take: int,
    held: Mapping[int, int],
    pinned: Mapping[int, int],
    job_id: int,
) -> Preview:
    """``take`` = ile przyjdzie z wybranej (plan z prawdziwą pulą, ``_with_capacity``).
    Z innych rekrutacji schodzi tylko nadwyżka ponad porcję (``seats``) i tylko
    z kart, których nikt nie wziął (``pinned`` zostają)."""
    surplus = sum(held.values()) + take - seats
    movable = sum(
        max(0, n - pinned.get(job, 0)) for job, n in held.items() if job != job_id
    )
    return Preview(take=take, release=max(0, min(surplus, movable)))


async def _exhausted_today(db: AsyncSession) -> set[int]:
    """Rekrutacje, w których dopełnianie dało dziś mniej, niż planowano: plan
    liczy w nich tylko karty bez właściciela (jak przebieg porcji)."""
    from app.services.new_column_autofill import BATCH_DAY_KEY

    row = await db.get(AppSetting, BATCH_DAY_KEY)
    state = row.value if row is not None and isinstance(row.value, dict) else {}
    if state.get("day") != business_today().isoformat():
        return set()
    return {int(job) for job in state.get("exhausted") or []}


async def _inputs_for(
    db: AsyncSession,
    user_id: int,
    job_ids: list[int],
    *,
    now: datetime,
    exhausted: frozenset[int] = frozenset(),
) -> PlanInputs:
    """Dane planu dla rekrutacji osoby i wszystkich rekrutacji jej zespołów
    (porcja kolegi w P0 gdzie indziej zmienia to, co zostaje tutaj)."""
    from app.services import review_batch as rb
    from app.services import review_batch_plan as plan

    teams = await rb.recruiter_ids_for_jobs(db, job_ids)
    people = {user_id} | {u for team in teams.values() for u in team}
    scope = await plan.jobs_worked_by(db, people)
    return await plan.load_inputs(
        db,
        scope | set(job_ids),
        now=now,
        exhausted=await _exhausted_today(db) | exhausted,
    )


async def _with_capacity(
    db: AsyncSession, inputs: PlanInputs, user_id: int, job_id: int, *, now: datetime
) -> PlanInputs:
    """Plan z prawdziwą liczbą osób, które wybrana rekrutacja da teraz: karty bez
    właściciela i pula od progu po regułach dopełniania (``batch_capacity``).
    Sama pula od progu to szacunek: 24.11.2026 na kopii produkcji „91 wolnych”
    w P0 dało po regułach 6 osób, a wybór zdjął za nie 10 kart z innych."""
    from app.services.new_column_autofill import batch_capacity

    unowned = inputs.unowned.get(job_id, 0)
    need = max(0, inputs.caps.get(user_id, 0) - unowned)
    pool = await batch_capacity(db, job_id, now=now, need=need)
    return replace(inputs, free={**inputs.free, job_id: unowned + pool})


def _without(focus: tuple[tuple[int, int], ...], user_id: int) -> list[tuple[int, int]]:
    return [(user, job) for user, job in focus if user != user_id]


async def _own_jobs(db: AsyncSession, user: User, *, now: datetime) -> list[int]:
    """Rekrutacje w pracy, z których osoba ma porcję; 409/403, gdy wybór jej nie dotyczy."""
    from app.services import review_batch as rb

    if not rb.enabled():
        raise HTTPException(status_code=409, detail="Porcja dnia jest wyłączona.")
    status = await rb.status_for(db, user, now=now)
    if not status.applies:
        raise HTTPException(
            status_code=403,
            detail="Rekrutację na dziś wybiera rekruter, który ma dziś porcję.",
        )
    return [job.job_id for job in status.team_jobs]


def _refuse_foreign(job_id: int, job_ids: list[int]) -> None:
    if job_id not in job_ids:
        raise HTTPException(
            status_code=403,
            detail=(
                "Na dziś wybierasz jedną ze swoich rekrutacji w pracy: prowadzisz ją, "
                "masz przypisanie albo współpracę."
            ),
        )


async def options_for(db: AsyncSession, user: User, *, now: datetime) -> dict:
    """Rekrutacje do wyboru: ile osób z porcji masz w każdej, ilu jest przypisanych
    i kto już ją dziś wybrał (kto pierwszy, ten bierze)."""
    from app.services import review_batch as rb

    status = await rb.status_for(db, user, now=now)
    if not rb.enabled() or not status.applies:
        return {"items": [], "focus": None, "seats": 0}
    job_ids = [job.job_id for job in status.team_jobs]
    inputs = await _inputs_for(db, user.id, job_ids, now=now)
    chosen = await read_focus(db)
    names = (
        {
            row.id: (row.name or row.email or str(row.id))
            for row in (
                await db.scalars(select(User).where(User.id.in_(list(chosen))))
            ).all()
        }
        if chosen
        else {}
    )
    items = []
    for job in status.team_jobs:
        team = inputs.teams.get(job.job_id, [])
        if user.id not in team:
            continue
        items.append(
            {
                **job.as_dict(),
                "team_size": len(team),
                "picked_by": [
                    {
                        "user_id": item.user_id,
                        "name": names.get(item.user_id, ""),
                        "at": item.at.isoformat(),
                        "cards": (inputs.owned.get(item.user_id) or {}).get(
                            job.job_id, 0
                        ),
                    }
                    for item in sorted(chosen.values(), key=lambda f: f.at)
                    if item.job_id == job.job_id and item.user_id != user.id
                ],
            }
        )
    mine = chosen.get(user.id)
    return {
        "items": items,
        "focus": mine.as_dict() if mine is not None else None,
        "seats": max(0, inputs.caps.get(user.id, 0)),
    }


async def preview_for(
    db: AsyncSession, user: User, job_id: int, *, now: datetime
) -> dict:
    """Co się stanie po wyborze tej rekrutacji: ile osób przyjdzie z niej (pula
    po regułach dopełniania) i ile nieruszonych wróci z innych do zespołu."""
    job_ids = await _own_jobs(db, user, now=now)
    _refuse_foreign(job_id, job_ids)
    inputs = await _inputs_for(db, user.id, job_ids, now=now)
    inputs = await _with_capacity(db, inputs, user.id, job_id, now=now)
    want = inputs.portions(focus=[*_without(inputs.focus, user.id), (user.id, job_id)])
    held = inputs.owned.get(user.id, {})
    result = preview(
        seats=max(0, inputs.caps.get(user.id, 0)),
        take=max(0, want.get(user.id, {}).get(job_id, 0) - held.get(job_id, 0)),
        held=held,
        pinned=inputs.pinned.get(user.id, {}),
        job_id=job_id,
    )
    return {
        "job_id": job_id,
        "available": inputs.free.get(job_id, 0),
        "take": result.take,
        "release": result.release,
    }


async def _held(db: AsyncSession, user_id: int, job_ids: list[int], *, now) -> dict:
    """Karty porcji osoby w rekrutacjach (bez odłożonych, jak plan)."""
    from app.services import review_batch as rb

    min_score = (await rb.read_settings(db)).min_score
    out: dict[int, int] = {}
    for card in rb.batch_cards(
        await rb.pending_cards(db, job_ids=job_ids, owner_id=user_id),
        now,
        min_score,
        fresh_only=True,
    ):
        out[card.job_id] = out.get(card.job_id, 0) + 1
    return out


async def _release_surplus(
    db: AsyncSession,
    user_id: int,
    job_ids: list[int],
    *,
    keep: int,
    surplus: int,
    tiers: Mapping[int, int],
    now: datetime,
) -> None:
    """Zdejmuje osobie ``surplus`` kart, których nikt nie wziął, z rekrutacji
    innych niż ``keep``: najpierw z najniższego priorytetu, w rekrutacji od
    najsłabszej w kolejce „Nowych”. Karta wzięta („Biorę”, „Dzwonię”) zostaje
    i nie zmniejsza tego, co trzeba zdjąć."""
    from app.services import review_batch as rb

    if surplus <= 0:
        return
    min_score = (await rb.read_settings(db)).min_score
    mine: dict[int, set[int]] = {}
    for card in rb.batch_cards(
        await rb.pending_cards(db, job_ids=job_ids, owner_id=user_id),
        now,
        min_score,
        fresh_only=True,
    ):
        if card.job_id != keep and not card.taken:
            mine.setdefault(card.job_id, set()).add(card.process_id)
    released: list[int] = []
    for job in sorted(mine, key=lambda j: (-tiers.get(j, 2), -j)):
        # Cała kolumna, nie tylko moje karty: kolejność „Nowych” jak na Tablicy.
        column = rb.batch_cards(
            await rb.pending_cards(db, job_ids=[job]), now, min_score, fresh_only=True
        )
        ordered = await rb._board_order(db, job, column, now=now)
        weakest = [c.process_id for c in reversed(ordered) if c.process_id in mine[job]]
        released += weakest[: surplus - len(released)]
        if len(released) >= surplus:
            break
    if not released:
        return
    for process in (
        await db.scalars(
            select(RecruitmentProcess).where(RecruitmentProcess.id.in_(released))
        )
    ).all():
        meta = dict(process.entry_meta or {})
        meta.pop(rb.OWNER_KEY, None)
        process.entry_meta = meta
        flag_modified(process, "entry_meta")
    await db.flush()


async def choose(
    db: AsyncSession, user: User, job_id: Optional[int], *, now: datetime
) -> dict:
    """Wybór rekrutacji na dziś (``None`` = powrót do zwykłej kolejności).

    Zapis pod blokadą. Wybrana rekrutacja dostaje, ile naprawdę może dać
    (``fill_job`` z planem, w którym jej pula jest policzona po regułach), a z
    innych rekrutacji osoby schodzi tylko nadwyżka ponad porcję. Powrót kasuje
    wybór, a osoby zostają u rekrutera. Bez commitu."""
    from app.services import review_batch_levels as levels
    from app.services.new_column_autofill import fill_job

    job_ids = await _own_jobs(db, user, now=now)
    if job_id is not None:
        _refuse_foreign(job_id, job_ids)
    await _write(db, user.id, job_id, now=now)
    focus = (await read_focus(db)).get(user.id)
    result = {
        "focus": focus.as_dict() if focus is not None else None,
        "released": 0,
        "added": 0,
    }
    if job_id is None:
        _log(db, user.id, result)
        return result
    inputs = await _inputs_for(db, user.id, job_ids, now=now)
    inputs = await _with_capacity(db, inputs, user.id, job_id, now=now)
    before = await _held(db, user.id, job_ids, now=now)
    await fill_job(
        db,
        job_id,
        now=now,
        limit=levels.CAP,
        batch=True,
        want=inputs.plan().want_for(job_id),
    )
    taken = await _held(db, user.id, job_ids, now=now)
    await _release_surplus(
        db,
        user.id,
        job_ids,
        keep=job_id,
        surplus=sum(taken.values()) - max(0, inputs.caps.get(user.id, 0)),
        tiers=inputs.tiers,
        now=now,
    )
    after = await _held(db, user.id, job_ids, now=now)
    result["added"] = max(0, after.get(job_id, 0) - before.get(job_id, 0))
    result["released"] = sum(
        max(0, taken.get(job, 0) - after.get(job, 0))
        for job in job_ids
        if job != job_id
    )
    _log(db, user.id, result)
    return result


def _log(db: AsyncSession, user_id: int, result: dict) -> None:
    from app.models.activity import Activity
    from app.services.review_batch import BLOCK_ENTITY

    focus = result.get("focus") or {}
    db.add(
        Activity(
            entity_type=BLOCK_ENTITY,
            entity_id=user_id,
            action=FOCUS_ACTION,
            user_id=user_id,
            details={
                "job_id": focus.get("job_id"),
                "added": result["added"],
                "released": result["released"],
            },
        )
    )
