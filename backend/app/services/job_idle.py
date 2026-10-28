"""Rekrutacje bez ruchu po stronie Delivery Leada (decyzja Artura 28.10.2026).

Na kopii produkcji z 22.10 było 204 otwartych rekrutacji, z czego 39 od
28+ dni bez CV do klienta i bez odpowiedzi klienta. „Porządek w requestach”
(24.09) nic nie wymuszał — 194 stało w „Szukamy”, 1 w „Klient milczy”.
Artur odrzucił rozbudowaną wersję (lista „Do decyzji”, okno z powodami)
i wybrał jedną regułę z dwoma przyciskami:

* **ruch** = CV wysłane do klienta albo karta przesunięta po odpowiedzi
  klienta (rozmowa, akceptacja, umowa, odrzucenie przez klienta). Screening,
  notatki i aplikacje z ogłoszeń nie są ruchem — w 12 z 36 martwych
  rekrutacji rekruter ruszał karty w ostatnich 14 dniach;
* licznik liczy od późniejszego z: ostatniego ruchu, otwarcia rekrutacji,
  „Jeszcze trwa” (``jobs.idle_snoozed_at``) i startu reguły minus 14 dni
  (zaległe dostają przypomnienie w dniu włączenia);
* **14 dni** → dzwonek i mail do Delivery Leada (bez DL: Head of Recruitment),
  **21 dni** → to samo i do Head of Recruitment, **28 dni** → NEXUS zamyka
  rekrutację powodem ``no_activity``, który liczy się jak przegrana
  (``metric_definitions.HIT_RATIO_LOST_CLOSE_REASONS``);
* zamknięcie dopiero 7 dni po przypomnieniu do Head of Recruitment w tym
  samym cyklu — przestój pętli nie zamknie niczego bez ostrzeżenia;
* jeden zbiorczy wpis dziennie na osobę (``job_idle_reminder``, mail
  obowiązkowy); znaczniki etapów w ``Activity`` (``idle_notice``) z datą
  początku cyklu, więc „Jeszcze trwa” zaczyna nowy cykl.

Automaty nie piszą do rekruterów osób w toku (reguła zamykania), ale pasek
zamkniętej Tablicy pokazuje im ich osoby. Reguła:
``docs/claude/rekrutacja-tablica/rekrutacje-bez-ruchu-zamykaja-sie-same.md``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import exists, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import settings
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.client import Client
from app.models.job import Job, JobCloseReason, JobStatus
from app.models.notification import NotificationType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.job_similarity import CLIENT_STAGES

logger = logging.getLogger(__name__)

REMIND_DAYS = 14
HOR_DAYS = 21
CLOSE_DAYS = 28
# Zamknięcie najwcześniej tyle dni (kalendarz firmy) po przypomnieniu do Head
# of Recruitment — liczone dniami, bo wpis dzwonka jest jeden na dzień.
CLOSE_AFTER_HOR_DAYS = 7
STARTED_KEY = "job_idle:started_at"
MARKER_ACTION = "idle_notice"
SNOOZE_ACTION = "idle_snoozed"
CLOSE_NOTE = "Zamknięta przez NEXUS: 28 dni bez CV do klienta i bez odpowiedzi klienta."
# Okno wysyłki w kalendarzu firmy — mail o 20:54 po wieczornym deployu
# (incydent przeglądu requestów) nikomu nie pomaga.
SEND_FROM_HOUR = 8
SEND_UNTIL_HOUR = 17
TITLES_MAX = 8
_LOCK_ID = 617_2810_26

# Odrzucenie liczy się jako odpowiedź klienta tylko u osoby, która była już
# u klienta — odrzucenie na screeningu to praca rekrutera.
_CLOSED_STAGES = (PipelineStage.rejected, PipelineStage.withdrawn)


@dataclass(frozen=True)
class IdleFacts:
    job_id: int
    opened_at: Optional[datetime]
    last_move_at: Optional[datetime]
    last_move_kind: Optional[str]  # "cv" | "client"
    snoozed_at: Optional[datetime]


@dataclass(frozen=True)
class IdleState:
    job_id: int
    since: datetime
    days: int
    stage: Optional[str]  # None | "remind" | "hor" | "close"
    remind_on: date
    hor_on: date
    close_on: date
    last_move_at: Optional[datetime]
    last_move_kind: Optional[str]


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.BUSINESS_TZ)


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _local_day(moment: datetime) -> date:
    return _aware(moment).astimezone(_tz()).date()


def stage_for(days: int) -> Optional[str]:
    if days >= CLOSE_DAYS:
        return "close"
    if days >= HOR_DAYS:
        return "hor"
    if days >= REMIND_DAYS:
        return "remind"
    return None


def idle_state(facts: IdleFacts, *, started_at: datetime, now: datetime) -> IdleState:
    """Czysta reguła: od kiedy cisza, ile dni (kalendarz firmy) i jaki etap."""
    floor = _aware(started_at) - timedelta(days=REMIND_DAYS)
    candidates = [floor] + [
        _aware(m)
        for m in (facts.opened_at, facts.last_move_at, facts.snoozed_at)
        if m is not None
    ]
    since = max(candidates)
    start_day = _local_day(since)
    days = max(0, (_local_day(now) - start_day).days)
    return IdleState(
        job_id=facts.job_id,
        since=since,
        days=days,
        stage=stage_for(days),
        remind_on=start_day + timedelta(days=REMIND_DAYS),
        hor_on=start_day + timedelta(days=HOR_DAYS),
        close_on=start_day + timedelta(days=CLOSE_DAYS),
        last_move_at=facts.last_move_at,
        last_move_kind=facts.last_move_kind,
    )


def in_send_window(now: datetime) -> bool:
    from app.core.scheduling import is_business_day  # noqa: PLC0415

    local = _aware(now).astimezone(_tz())
    return (
        is_business_day(local, settings.BUSINESS_TZ)
        and SEND_FROM_HOUR <= local.hour < SEND_UNTIL_HOUR
    )


def last_move_text(state: IdleState) -> str:
    if state.last_move_at is None:
        return "żadnego CV do klienta"
    day = _local_day(state.last_move_at).strftime("%d.%m")
    if state.last_move_kind == "cv":
        return f"ostatnie CV do klienta {day}, bez odpowiedzi"
    return f"ostatnia odpowiedź klienta {day}"


# ── Odczyt z bazy ────────────────────────────────────────────────────────────


async def started_at(
    db: AsyncSession, *, create: bool, now: datetime
) -> Optional[datetime]:
    """Start reguły; pierwszy przebieg pętli zapisuje go sam."""
    value = await db.scalar(
        select(AppSetting.value).where(AppSetting.key == STARTED_KEY)
    )
    raw = value.get("at") if isinstance(value, dict) else None
    if isinstance(raw, str):
        try:
            return _aware(datetime.fromisoformat(raw))
        except ValueError:
            logger.warning("job_idle: nieczytelny start reguły")
    if not create:
        return None
    db.add(AppSetting(key=STARTED_KEY, value={"at": now.isoformat()}))
    await db.flush()
    return now


async def load_facts(db: AsyncSession, job_ids: Sequence[int]) -> dict[int, IdleFacts]:
    ids = list(job_ids)
    if not ids:
        return {}
    earlier = aliased(CandidateStage)
    was_at_client = exists().where(
        earlier.job_id == CandidateStage.job_id,
        earlier.candidate_id == CandidateStage.candidate_id,
        earlier.stage.in_(CLIENT_STAGES),
        earlier.moved_at <= CandidateStage.moved_at,
    )
    moves = (
        await db.execute(
            select(
                CandidateStage.job_id,
                func.max(CandidateStage.moved_at).filter(
                    CandidateStage.stage.in_(CLIENT_STAGES)
                    | (CandidateStage.stage.in_(_CLOSED_STAGES) & was_at_client)
                ),
                func.max(CandidateStage.moved_at).filter(
                    CandidateStage.stage == PipelineStage.cv_sent
                ),
            )
            .where(CandidateStage.job_id.in_(ids))
            .group_by(CandidateStage.job_id)
        )
    ).all()
    by_job = {job_id: (last, last_cv) for job_id, last, last_cv in moves}
    jobs = (
        await db.execute(
            select(Job.id, Job.opened_at, Job.created_at, Job.idle_snoozed_at).where(
                Job.id.in_(ids)
            )
        )
    ).all()
    facts: dict[int, IdleFacts] = {}
    for job_id, opened_at, created_at, snoozed_at in jobs:
        last, last_cv = by_job.get(job_id, (None, None))
        kind = None
        if last is not None:
            kind = "cv" if last_cv is not None and last_cv >= last else "client"
        facts[job_id] = IdleFacts(
            job_id=job_id,
            opened_at=opened_at or created_at,
            last_move_at=last,
            last_move_kind=kind,
            snoozed_at=snoozed_at,
        )
    return facts


async def state_for_job(
    db: AsyncSession, job: Job, *, now: datetime
) -> Optional[IdleState]:
    """Stan jednej otwartej rekrutacji (pasek na stronie) albo ``None``."""
    if job.status != JobStatus.published:
        return None
    start = await started_at(db, create=False, now=now)
    if start is None:
        return None
    facts = (await load_facts(db, [job.id])).get(job.id)
    if facts is None:
        return None
    return idle_state(facts, started_at=start, now=now)


async def snooze_count(db: AsyncSession, job_id: int) -> int:
    return int(
        await db.scalar(
            select(func.count(Activity.id)).where(
                Activity.entity_type == "job",
                Activity.entity_id == job_id,
                Activity.action == SNOOZE_ACTION,
            )
        )
        or 0
    )


async def snooze(db: AsyncSession, job: Job, *, actor_id: int, now: datetime) -> None:
    """„Jeszcze trwa” — licznik liczy od teraz; wpis do historii rekrutacji."""
    before = await state_for_job(db, job, now=now)
    job.idle_snoozed_at = now
    job.idle_snoozed_by = actor_id
    db.add(
        Activity(
            entity_type="job",
            entity_id=job.id,
            action=SNOOZE_ACTION,
            user_id=actor_id,
            details={"days": before.days if before else None},
        )
    )


def state_payload(state: Optional[IdleState], *, snoozes: int) -> dict[str, Any]:
    if state is None:
        return {"stage": None, "days": 0, "snooze_count": snoozes}
    return {
        "stage": state.stage,
        "days": state.days,
        "since": state.since.isoformat(),
        "last_move_at": state.last_move_at.isoformat() if state.last_move_at else None,
        "last_move_kind": state.last_move_kind,
        "remind_on": state.remind_on.isoformat(),
        "hor_on": state.hor_on.isoformat(),
        "close_on": state.close_on.isoformat(),
        "snooze_count": snoozes,
    }


# ── Przebieg dzienny ─────────────────────────────────────────────────────────


@dataclass
class _Line:
    job_id: int
    title: str
    client: Optional[str]
    lead_id: Optional[int]
    days: int
    detail: str


def _line_text(line: _Line) -> str:
    head = f"{line.title} · {line.client}" if line.client else line.title
    return f"{head} ({line.days} dni, {line.detail})"


def _list_text(lines: Sequence[_Line]) -> str:
    shown = "; ".join(_line_text(line) for line in lines[:TITLES_MAX])
    rest = len(lines) - TITLES_MAX
    return shown + (f" i {rest} innych." if rest > 0 else ".")


def _plural_jobs(count: int) -> str:
    if count == 1:
        return "1 rekrutacja"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return f"{count} rekrutacje"
    return f"{count} rekrutacji"


async def _markers(
    db: AsyncSession, job_ids: Iterable[int]
) -> dict[int, dict[str, Any]]:
    """Znaczniki etapów: job_id → {"stage|since_iso": dzień przebiegu}."""
    ids = list(job_ids)
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(Activity.entity_id, Activity.details, Activity.created_at).where(
                Activity.entity_type == "job",
                Activity.entity_id.in_(ids),
                Activity.action == MARKER_ACTION,
            )
        )
    ).all()
    out: dict[int, dict[str, Any]] = {}
    for job_id, details, created_at in rows:
        if isinstance(details, dict):
            key = f"{details.get('stage')}|{details.get('since')}"
            try:
                on = date.fromisoformat(str(details.get("on")))
            except ValueError:
                on = _local_day(created_at)
            out.setdefault(job_id, {})[key] = on
    return out


async def run_idle_sweep(
    db: AsyncSession,
    effects: Any,
    *,
    now: datetime,
    only_job_ids: Optional[Sequence[int]] = None,
) -> dict[str, int]:
    """Przypomnienia i zamknięcia — bez commitu; wołający commituje.

    ``only_job_ids`` zawęża przebieg (testy na wspólnej bazie).
    """
    from app.services.job_lifecycle import close_job_core  # noqa: PLC0415
    from app.services.notification_triggers import emit  # noqa: PLC0415

    acquired = await db.scalar(
        text("SELECT pg_try_advisory_xact_lock(:lock_id)"), {"lock_id": _LOCK_ID}
    )
    if not acquired:
        return {"skipped": 1}
    start = await started_at(db, create=True, now=now)
    jobs = (
        await db.execute(
            select(
                Job.id, Job.title, Job.working_title, Job.delivery_lead_id, Client.name
            )
            .join(Client, Client.id == Job.client_id, isouter=True)
            .where(
                Job.status == JobStatus.published,
                *([Job.id.in_(list(only_job_ids))] if only_job_ids is not None else []),
            )
        )
    ).all()
    facts = await load_facts(db, [row[0] for row in jobs])
    states = {
        job_id: idle_state(f, started_at=start, now=now) for job_id, f in facts.items()
    }
    due = {job_id: s for job_id, s in states.items() if s.stage is not None}
    markers = await _markers(db, due)

    users = (
        await db.execute(select(User.id, User.name, User.is_active, User.roles))
    ).all()
    active = {uid for uid, _n, is_active, _r in users if is_active}
    names = {uid: name for uid, name, _a, _r in users}
    hor_ids = sorted(
        uid
        for uid, _n, is_active, roles in users
        if is_active and UserRole.head_of_recruitment.value in (roles or [])
    )

    def leads_of(lead_id: Optional[int]) -> list[int]:
        return [lead_id] if lead_id in active else list(hor_ids)

    to_lead: dict[int, list[_Line]] = {}
    to_hor: list[_Line] = []
    closed: list[_Line] = []
    counts = {"remind": 0, "hor": 0, "closed": 0}
    info = {row[0]: row for row in jobs}

    for job_id, state in sorted(due.items(), key=lambda kv: -kv[1].days):
        _id, title, working_title, lead_id, client = info[job_id]
        line = _Line(
            job_id=job_id,
            title=working_title or title,
            client=client,
            lead_id=lead_id,
            days=state.days,
            detail=last_move_text(state),
        )
        since = state.since.isoformat()
        seen = markers.get(job_id, {})
        hor_at = seen.get(f"hor|{since}")
        stage = state.stage
        if stage == "close" and (
            hor_at is None or (_local_day(now) - hor_at).days < CLOSE_AFTER_HOR_DAYS
        ):
            # Bez ostrzeżenia Head of Recruitment w tym cyklu nie zamykamy.
            stage = "hor"
        if stage == "close":
            job = await db.scalar(select(Job).where(Job.id == job_id).with_for_update())
            if job is None or job.status != JobStatus.published:
                continue
            await close_job_core(
                db,
                job,
                reason=JobCloseReason.no_activity,
                notes=CLOSE_NOTE,
                actor_id=None,
                effects=effects,
            )
            closed.append(line)
            counts["closed"] += 1
            continue
        if f"{stage}|{since}" in seen:
            continue
        db.add(
            Activity(
                entity_type="job",
                entity_id=job_id,
                action=MARKER_ACTION,
                user_id=None,
                details={
                    "stage": stage,
                    "since": since,
                    "days": state.days,
                    "on": _local_day(now).isoformat(),
                },
            )
        )
        to_lead.setdefault(lead_id or 0, []).append(line)
        if stage == "hor":
            to_hor.append(line)
        counts[stage] += 1

    recipients: dict[int, dict[str, list[_Line]]] = {}
    for lead_id, lines in to_lead.items():
        for uid in leads_of(lead_id or None):
            recipients.setdefault(uid, {}).setdefault("mine", []).extend(lines)
    for line in to_hor:
        for uid in hor_ids:
            recipients.setdefault(uid, {}).setdefault("team", []).append(line)
    for line in closed:
        for uid in set(leads_of(line.lead_id)) | set(hor_ids):
            recipients.setdefault(uid, {}).setdefault("closed", []).append(line)

    sent = 0
    for uid, parts in sorted(recipients.items()):
        title, message, link = notice_text(parts, names=names, uid=uid)
        created = await emit(
            db,
            user_id=uid,
            title=title,
            message=message,
            ntype=NotificationType.job_idle_reminder,
            related_entity_type="user",
            related_entity_id=uid,
            link=link,
        )
        sent += int(created is not None)
    counts["sent"] = sent
    await db.flush()
    return counts


def notice_text(
    parts: dict[str, list[_Line]], *, names: dict[int, str], uid: int
) -> tuple[str, str, str]:
    """Tytuł, treść i link jednego zbiorczego wpisu dla osoby."""
    mine = _dedupe(parts.get("mine", []))
    team = [line for line in _dedupe(parts.get("team", [])) if line not in mine]
    closed = _dedupe(parts.get("closed", []))
    chunks: list[str] = []
    if mine:
        chunks.append(
            "Od 2 tygodni lub dłużej nie poszło CV do klienta ani nie wpisano "
            f"odpowiedzi klienta: {_list_text(mine)} Zamknij je albo kliknij "
            "„Jeszcze trwa” na rekrutacji. Po 28 dniach NEXUS zamknie je jako przegrane."
        )
    if team:
        per_lead: dict[str, int] = {}
        for line in team:
            who = names.get(line.lead_id or 0) or "bez Delivery Leada"
            per_lead[who] = per_lead.get(who, 0) + 1
        by_lead = ", ".join(
            f"{who}: {n}" for who, n in sorted(per_lead.items(), key=lambda kv: -kv[1])
        )
        chunks.append(
            f"Bez ruchu od 3 tygodni w zespole ({by_lead}): {_list_text(team)} "
            "Delivery Leadzi dostali przypomnienie tydzień temu."
        )
    if closed:
        chunks.append(
            f"NEXUS zamknął po 28 dniach bez ruchu: {_list_text(closed)} "
            "Liczą się jako przegrane; „Otwórz ponownie” na rekrutacji, jeśli to pomyłka."
        )
    total = len(mine) + len(team)
    if total and closed:
        title = f"{_plural_jobs(total)} bez ruchu, {len(closed)} zamkniętych"
    elif closed:
        title = f"NEXUS zamknął {_plural_jobs(len(closed))} bez ruchu"
    else:
        title = f"{_plural_jobs(total)} bez ruchu"
    first = (mine or team or closed)[0]
    return title, " ".join(chunks), f"/jobs/{first.job_id}"


def _dedupe(lines: Sequence[_Line]) -> list[_Line]:
    seen: set[int] = set()
    out = []
    for line in sorted(lines, key=lambda item: -item.days):
        if line.job_id not in seen:
            seen.add(line.job_id)
            out.append(line)
    return out


async def run_once_safely(now: Optional[datetime] = None) -> Optional[dict[str, int]]:
    """Własna sesja, commit, efekty po commicie; nigdy nie rzuca."""
    from app.core.database import AsyncSessionLocal  # noqa: PLC0415
    from app.services.job_lifecycle import PostCommit, run_post_commit  # noqa: PLC0415

    moment = now or datetime.now(timezone.utc)
    if not in_send_window(moment):
        return None
    effects = PostCommit()
    try:
        async with AsyncSessionLocal() as db:
            counts = await run_idle_sweep(db, effects, now=moment)
            await db.commit()
    except Exception:  # noqa: BLE001 — pętla nie może przez to stanąć
        logger.exception("job_idle: przebieg nie powiódł się")
        return None
    await run_post_commit(effects)
    if any(counts.get(k) for k in ("remind", "hor", "closed")):
        logger.info("job_idle: %s", counts)
    return counts
