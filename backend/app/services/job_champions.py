"""Championi rekrutacji — zapis listy, flaga „nie szukamy” i haki zamknięcia karty.

Decyzje Artura D1–D9 (15.10.2026), reguły w
``docs/claude/rekrutacja-tablica/podobne-rekrutacje-przepiecia-i-status-requestu.md``
(sekcja „Championi rekrutacji”). Czyste reguły: ``services/job_champion_rules``.

* Delivery Lead zapisuje PEŁNĄ listę championów (``set_champions``) — z okienka
  pod plakietką statusu w nagłówku rekrutacji. Nowa osoba musi stać od „CV
  wysłane” wzwyż (D4); już wskazanych lista nie wyrzuca.
* ``jobs.champion_found_at`` zostaje i znaczy „nie szukamy”; liczy ją
  ``sync_found_flag`` (championi ∪ zatrudnieni ≥ miejsca, D5). Jej odczyty
  (pula automatu, obłożenie P1, „Nowe rekrutacje P1”, status listy, API v1)
  nie zmieniły się. Zgaszenie oddaje ludzi dodanych ręcznie
  (``restore_after_champion_removed``) — wołający trzyma ``allocation_lock``
  przed blokadą wiersza rekrutacji.
* Karta championa zamknięta (odrzucenie, rezygnacja, „Rezerwa”) albo osoba
  usunięta z rekrutacji → champion schodzi sam (D7) — ``reconcile`` PO commicie
  ruchu, we własnej transakcji. Flaga sprzed 15.10 (bez osób) zostaje
  nietknięta, dopóki DL nie zapisze listy.
* Dzwonki (D8): ``champions_changed`` po zapisie listy, która coś zmieniła,
  ``champion_search_resumed`` przy powrocie do szukania. Do rekruterów
  i Delivery Leada rekrutacji, bez osoby, która zmieniła listę.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_champion import JobChampion
from app.models.notification import NotificationType
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.services import job_champion_rules as rules
from app.services.board_stage_badges import board_column_for
from app.services.pipeline_latest import latest_stage_ids

logger = logging.getLogger(__name__)


class ChampionsError(Exception):
    """Odmowa zapisu listy — ``status`` i ``detail`` idą wprost do HTTPException."""

    def __init__(self, status: int, detail: Any) -> None:
        super().__init__(str(detail))
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class PairPlace:
    candidate_id: int
    name: str
    column: Optional[str]
    stage_label: Optional[str]


@dataclass
class SetResult:
    changed: bool
    work_state_changed: bool
    before_stopped: bool
    after_stopped: bool
    added: list[int] = field(default_factory=list)
    removed: list[int] = field(default_factory=list)


def _value(raw: object) -> Optional[str]:
    if raw is None:
        return None
    return str(getattr(raw, "value", raw))


def _full_name(name: Optional[str], lastname: Optional[str]) -> str:
    return f"{name or ''} {lastname or ''}".strip() or "—"


async def pair_places(
    db: AsyncSession, job_id: int, candidate_ids: Optional[Iterable[int]] = None
) -> dict[int, PairPlace]:
    """Bieżąca kolumna Tablicy każdej osoby w rekrutacji (najnowszy wiersz pary).

    Ta sama reguła kolumny co karta i okno „Dodaj z CV”
    (``board_column_for`` na definicji etapu, bez niej na kodzie etapu).
    """
    latest = latest_stage_ids(job_ids=[job_id])
    stmt = (
        select(
            CandidateStage.candidate_id,
            CandidateStage.stage,
            Candidate.name,
            Candidate.lastname,
            PipelineStageDef.name,
            PipelineStageDef.category,
            PipelineStageDef.terminal_type,
        )
        .join(Candidate, Candidate.id == CandidateStage.candidate_id)
        .outerjoin(PipelineStageDef, PipelineStageDef.id == CandidateStage.stage_def_id)
        .where(CandidateStage.id.in_(select(latest.c.latest_id)))
    )
    if candidate_ids is not None:
        ids = sorted({int(cid) for cid in candidate_ids})
        if not ids:
            return {}
        stmt = stmt.where(CandidateStage.candidate_id.in_(ids))
    out: dict[int, PairPlace] = {}
    for cid, stage, name, lastname, def_name, category, terminal_type in (
        await db.execute(stmt)
    ).all():
        column = board_column_for(
            def_name,
            _value(stage),
            category=_value(category),
            terminal_type=_value(terminal_type),
        )
        out[int(cid)] = PairPlace(
            candidate_id=int(cid),
            name=_full_name(name, lastname),
            column=column,
            stage_label=def_name,
        )
    return out


async def live_rows(db: AsyncSession, job_ids: Iterable[int]) -> list[Any]:
    ids = sorted({int(j) for j in job_ids})
    if not ids:
        return []
    return list(
        (
            await db.execute(
                select(
                    JobChampion.job_id,
                    JobChampion.candidate_id,
                    JobChampion.marked_at,
                    Candidate.name,
                    Candidate.lastname,
                    User.name.label("marked_by_name"),
                )
                .join(Candidate, Candidate.id == JobChampion.candidate_id)
                .outerjoin(User, User.id == JobChampion.marked_by_id)
                .where(JobChampion.job_id.in_(ids), JobChampion.cleared_at.is_(None))
                .order_by(JobChampion.job_id, JobChampion.marked_at, JobChampion.id)
            )
        ).all()
    )


async def live_briefs(
    db: AsyncSession, job_ids: Iterable[int]
) -> dict[int, list[dict]]:
    """``{job_id: [{candidate_id, name}]}`` — nagłówek, wiersz listy, okno odrzucenia."""
    out: dict[int, list[dict]] = {}
    for row in await live_rows(db, job_ids):
        out.setdefault(int(row.job_id), []).append(
            {
                "candidate_id": int(row.candidate_id),
                "name": _full_name(row.name, row.lastname),
            }
        )
    return out


async def live_candidate_ids(db: AsyncSession, job_id: int) -> set[int]:
    """Żywi championi jednej rekrutacji — karty Tablicy."""
    return set(
        (
            await db.execute(
                select(JobChampion.candidate_id).where(
                    JobChampion.job_id == job_id, JobChampion.cleared_at.is_(None)
                )
            )
        ).scalars()
    )


def _hired_ids(places: dict[int, PairPlace]) -> set[int]:
    return {cid for cid, place in places.items() if place.column == "hired"}


async def detail_fields(db: AsyncSession, job: Job) -> dict:
    """Pola championów w detalu rekrutacji (nagłówek, okno odrzucenia).

    Champion w „Zatrudniony” ma ``hired: True`` — front liczy miejsca jak
    serwer (suma zbiorów championów i zatrudnionych), bez podwójnego liczenia.
    """
    from app.services.job_priority import priority_paused  # noqa: PLC0415

    briefs = (await live_briefs(db, [job.id])).get(job.id, [])
    hired: set[int] = set()
    if briefs:
        hired = _hired_ids(await pair_places(db, job.id))
        for brief in briefs:
            brief["hired"] = brief["candidate_id"] in hired
    return {
        "champions": briefs,
        "champion_seats": rules.seats(job.headcount),
        "hired_count": len(hired),
        "priority_paused": priority_paused(job),
    }


async def view(db: AsyncSession, job: Job, *, can_edit: bool) -> dict:
    """Odpowiedź ``GET /api/jobs/{id}/champions`` (kontrakt w odpowiedzi trasy)."""
    places = await pair_places(db, job.id)
    rows = await live_rows(db, [job.id])
    live_ids = {int(row.candidate_id) for row in rows}
    champions = []
    for row in rows:
        place = places.get(int(row.candidate_id))
        champions.append(
            {
                "candidate_id": int(row.candidate_id),
                "name": _full_name(row.name, row.lastname),
                "column": place.column if place else None,
                "stage_label": place.stage_label if place else None,
                "marked_by_name": row.marked_by_name,
                "marked_at": row.marked_at,
            }
        )
    eligible: list[dict] = []
    if can_edit:
        candidates = [
            place
            for place in places.values()
            if rules.is_eligible_column(place.column) or place.candidate_id in live_ids
        ]
        candidates.sort(key=lambda p: (rules.column_rank(p.column), p.name.lower()))
        eligible = [
            {
                "candidate_id": place.candidate_id,
                "name": place.name,
                "column": place.column,
                "stage_label": place.stage_label,
                "is_champion": place.candidate_id in live_ids,
            }
            for place in candidates
        ]
    stopped = job.champion_found_at is not None
    return {
        "job_id": job.id,
        "can_edit": can_edit,
        "seats": rules.seats(job.headcount),
        "hired_count": len(_hired_ids(places)),
        "search_stopped": stopped,
        "legacy_flag": stopped and not live_ids,
        "work_state": job.work_state,
        "champions": champions,
        "eligible": eligible,
    }


async def sync_found_flag(
    db: AsyncSession,
    job: Job,
    *,
    actor_id: Optional[int],
    now: datetime,
    champion_ids: Optional[Iterable[int]] = None,
    hired_ids: Optional[Iterable[int]] = None,
) -> tuple[bool, bool]:
    """Przelicz „nie szukamy” (D5). Zwraca (przed, po).

    Wołający trzyma ``allocation_lock`` i blokadę wiersza rekrutacji.
    """
    if champion_ids is None:
        champion_ids = await live_candidate_ids(db, job.id)
    if hired_ids is None:
        hired_ids = _hired_ids(await pair_places(db, job.id))
    before = job.champion_found_at is not None
    after = rules.search_stops(champion_ids, hired_ids, job.headcount)
    if before == after:
        return before, after
    from app.services.request_allocation import (  # noqa: PLC0415
        restore_after_champion_removed,
    )

    champion_since = job.champion_found_at
    job.champion_found_at = now if after else None
    job.champion_found_by = actor_id if after else None
    # Runda 8 (R8-N7-5): champion to widoczna zmiana stanu requestu — ręczne
    # zdjęcia sprzed niej przestają blokować powrót osoby.
    job.work_state_changed_at = now
    if not after:
        await restore_after_champion_removed(
            db, job_id=job.id, champion_since=champion_since, now=now
        )
    db.add(
        Activity(
            entity_type="job",
            entity_id=job.id,
            action="champion_found_changed",
            user_id=actor_id,
            details={"found": after},
        )
    )
    return before, after


async def set_champions(
    db: AsyncSession, job: Job, candidate_ids: Iterable[int], *, actor_id: int
) -> SetResult:
    """Zapisz pełną listę championów. Wołający: ``allocation_lock`` → wiersz
    rekrutacji ``FOR UPDATE``; commit po stronie trasy."""
    if job.status == JobStatus.closed or job.work_state == "finished":
        raise ChampionsError(
            409,
            "Rekrutacja jest zamknięta albo zakończona — championów nie da się zmienić.",
        )
    wanted = rules.ordered_unique(candidate_ids)
    current = [
        int(cid)
        for cid in (
            await db.execute(
                select(JobChampion.candidate_id)
                .where(JobChampion.job_id == job.id, JobChampion.cleared_at.is_(None))
                .order_by(JobChampion.marked_at, JobChampion.id)
            )
        ).scalars()
    ]
    added, removed = rules.diff(current, wanted)
    places = await pair_places(db, job.id)
    refused = [
        cid
        for cid in added
        if cid not in places or not rules.is_eligible_column(places[cid].column)
    ]
    if refused:
        raise ChampionsError(
            422,
            {
                "code": "champion_not_eligible",
                "message": (
                    "Championem może być tylko osoba z tej rekrutacji, która jest "
                    "u klienta (od „CV wysłane”). Odśwież listę i spróbuj ponownie."
                ),
                "candidate_ids": refused,
            },
        )
    now = datetime.now(timezone.utc)
    for cid in added:
        db.add(JobChampion(job_id=job.id, candidate_id=cid, marked_by_id=actor_id))
    if removed:
        await db.execute(
            update(JobChampion)
            .where(
                JobChampion.job_id == job.id,
                JobChampion.candidate_id.in_(removed),
                JobChampion.cleared_at.is_(None),
            )
            .values(cleared_at=now, cleared_reason="manual", cleared_by_id=actor_id)
        )
    work_state_changed = False
    if wanted and job.work_state in rules.WAKE_STATES:
        from app.services.request_work_state import set_work_state  # noqa: PLC0415

        work_state_changed = await set_work_state(
            db, job, "searching", actor_id=actor_id, reason="champion"
        )
    await db.flush()
    before, after = await sync_found_flag(
        db,
        job,
        actor_id=actor_id,
        now=now,
        champion_ids=wanted,
        hired_ids=_hired_ids(places),
    )
    changed = bool(added or removed)
    if changed:
        db.add(
            Activity(
                entity_type="job",
                entity_id=job.id,
                action="champions_changed",
                user_id=actor_id,
                details={"added": added, "removed": removed},
            )
        )
    return SetResult(
        changed=changed,
        work_state_changed=work_state_changed,
        before_stopped=before,
        after_stopped=after,
        added=added,
        removed=removed,
    )


async def reconcile(
    db: AsyncSession,
    *,
    job_id: int,
    candidate_ids: Iterable[int],
    actor_id: Optional[int],
    had_champions: bool = False,
) -> None:
    """Przelicz championów po zmianie spoza listy (D5, D7) — karta championa
    zamknięta, osoba usunięta z rekrutacji albo z bazy, ktoś zatrudniony.

    Woła się PO commicie ruchu karty / usunięcia, we własnej transakcji
    (``reconcile_after_commit`` albo ``_post_commit_effect`` w ``/move``):
    blokady przydział → rekrutacja, jak na pulpicie i w automacie. Wewnątrz
    ruchu karty transakcja trzyma już wiersz kandydata i blokadę klucza na
    rekrutacji, więc ``allocation_lock`` tam mógłby się zakleszczyć z każdą
    trasą zespołu (przegląd 15.10.2026).

    Champion schodzi, gdy jego karta stoi w „closed” (``card_closed``) albo
    pary już nie ma (``removed_from_job``). Rekrutacja bez żywego championa
    (także flaga sprzed 15.10 bez osób) zostaje nietknięta, chyba że
    ``had_champions`` — kaskada usunięcia kandydata zabrała już jego wiersz.
    """
    if not had_champions and not await live_candidate_ids(db, job_id):
        return
    from app.services.recruitment_allocation import allocation_lock  # noqa: PLC0415

    await allocation_lock(db)
    job = await db.get(Job, job_id, with_for_update=True, populate_existing=True)
    if job is None:
        return
    now = datetime.now(timezone.utc)
    live = await live_candidate_ids(db, job_id)
    places = await pair_places(db, job_id)
    gone: dict[int, str] = {}
    for cid in rules.ordered_unique(candidate_ids):
        if cid not in live:
            continue
        place = places.get(cid)
        if place is None:
            gone[cid] = "removed_from_job"
        elif place.column == "closed":
            gone[cid] = "card_closed"
    for reason in sorted(set(gone.values())):
        await db.execute(
            update(JobChampion)
            .where(
                JobChampion.job_id == job_id,
                JobChampion.candidate_id.in_(
                    [cid for cid, why in gone.items() if why == reason]
                ),
                JobChampion.cleared_at.is_(None),
            )
            .values(cleared_at=now, cleared_reason=reason, cleared_by_id=actor_id)
        )
    if gone:
        db.add(
            Activity(
                entity_type="job",
                entity_id=job_id,
                action="champions_changed",
                user_id=actor_id,
                details={"added": [], "removed": list(gone), "reason": "auto"},
            )
        )
    await db.flush()
    before, after = await sync_found_flag(
        db,
        job,
        actor_id=actor_id,
        now=now,
        champion_ids=live - set(gone),
        hired_ids=_hired_ids(places),
    )
    if before and not after:
        names = ", ".join(places[cid].name for cid in gone if cid in places)
        detail = (
            f"Champion {names} nie jest już w procesie."
            if names
            else "Championów jest mniej niż miejsc w rekrutacji."
        )
        await notify(
            db, job=job, actor_id=actor_id, kind=rules.NOTIFY_RESUMED, detail=detail
        )


async def reconcile_after_commit(
    db: AsyncSession,
    *,
    job_id: int,
    candidate_ids: Iterable[int],
    actor_id: Optional[int],
    had_champions: bool = False,
) -> None:
    """``reconcile`` po commicie wołającego — savepoint i własny commit.

    Nigdy nie rzuca: zmiana, po której biegnie (usunięcie osoby), jest już
    zapisana, a błąd przeliczenia zostaje w logu.
    """
    try:
        async with db.begin_nested():
            await reconcile(
                db,
                job_id=job_id,
                candidate_ids=candidate_ids,
                actor_id=actor_id,
                had_champions=had_champions,
            )
        await db.commit()
    except Exception:  # noqa: BLE001 — przeliczenie nie może cofnąć usunięcia
        logger.exception("[job_champions] przeliczenie po zmianie job=%s", job_id)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass


async def live_job_ids_for_candidate(db: AsyncSession, candidate_id: int) -> list[int]:
    return sorted(
        set(
            (
                await db.execute(
                    select(JobChampion.job_id).where(
                        JobChampion.candidate_id == candidate_id,
                        JobChampion.cleared_at.is_(None),
                    )
                )
            ).scalars()
        )
    )


async def recipients(
    db: AsyncSession, job: Job, *, actor_id: Optional[int]
) -> list[int]:
    """Rekruterzy (pracujący) i Delivery Lead rekrutacji, bez aktora."""
    from app.services.candidate_rate_change import job_delivery_leads  # noqa: PLC0415
    from app.services.job_team import recruiters_for_jobs, working  # noqa: PLC0415

    people = {
        person.user_id
        for person in working((await recruiters_for_jobs(db, [job.id])).get(job.id, []))
    }
    people.update(await job_delivery_leads(db, job))
    if actor_id is not None:
        people.discard(actor_id)
    return sorted(people)


async def notify(
    db: AsyncSession,
    *,
    job: Job,
    actor_id: Optional[int],
    kind: str,
    detail: str,
) -> None:
    """D8: jeden dzwonek na osobę. Savepoint na każdą — nieudany nie cofa zapisu."""
    from app.services.job_working_title import job_display_title_expr  # noqa: PLC0415
    from app.services.notification_triggers import emit  # noqa: PLC0415

    user_ids = await recipients(db, job, actor_id=actor_id)
    if not user_ids:
        return
    row = (
        await db.execute(
            select(job_display_title_expr(), Client.name)
            .select_from(Job)
            .outerjoin(Client, Client.id == Job.client_id)
            .where(Job.id == job.id)
        )
    ).first()
    job_title, client_name = (row[0], row[1]) if row else ("Rekrutacja", None)
    head = f"{job_title} · {client_name}" if client_name else job_title
    if kind == rules.NOTIFY_RESUMED:
        ntype = NotificationType.champion_search_resumed
        title = "Wracamy do szukania"
        message = f"{head}. {detail} Rekrutacja wraca do „Szukamy”, P1 znowu działa."
    else:
        ntype = NotificationType.champions_changed
        title = "Championi w rekrutacji"
        message = f"{head}. {detail}"
    for user_id in user_ids:
        try:
            async with db.begin_nested():
                await emit(
                    db,
                    user_id=user_id,
                    title=title,
                    message=message,
                    ntype=ntype,
                    # Bez ``related_entity_id``: dobowy dedup
                    # (``ix_notif_dedup_daily``) połknąłby drugą zmianę listy
                    # tego samego dnia. Dzwonki biorą się z ręcznych zapisów
                    # i ruchów kart, nie z pętli — jak czat rekrutacji.
                    related_entity_type="job",
                    related_entity_id=None,
                    link=f"/jobs/{job.id}",
                )
        except Exception:  # noqa: BLE001 — dzwonek nie może cofnąć zapisu listy
            logger.exception(
                "[job_champions] dzwonek %s nie wyszedł job=%s user=%s",
                ntype.value,
                job.id,
                user_id,
            )


async def notify_after_save(
    db: AsyncSession, *, job: Job, result: SetResult, actor_id: int
) -> None:
    kind = rules.notification_kind(
        before_stopped=result.before_stopped,
        after_stopped=result.after_stopped,
        changed=result.changed,
        has_champions=bool(await live_candidate_ids(db, job.id)),
    )
    if kind is None:
        return
    if kind == rules.NOTIFY_RESUMED:
        await notify(
            db,
            job=job,
            actor_id=actor_id,
            kind=kind,
            detail="Lista championów nie pokrywa już miejsc w rekrutacji.",
        )
        return
    briefs = (await live_briefs(db, [job.id])).get(job.id, [])
    names = ", ".join(b["name"] for b in briefs)
    if result.after_stopped:
        detail = f"Championi: {names}. Rekrutacja nie jest już pilna."
    else:
        detail = (
            f"Championi: {names}. Szukamy dalej — championa ma {len(briefs)} "
            f"z {rules.seats(job.headcount)} miejsc."
        )
    await notify(db, job=job, actor_id=actor_id, kind=kind, detail=detail)
