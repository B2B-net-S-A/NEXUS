"""Odpowiedź klienta jako zadanie Delivery Leada (S-C2, decyzje Artura 08.11.2026).

Po audycie: 85% czasu do zatrudnienia to czekanie na klienta, a 278 z 789 par stoi
u klienta ponad 30 dni. Pas nad Tablicą zbiera to, co dotąd było plakietką na
pojedynczej karcie, i daje DL-owi trzy ruchy: przypomnij, klient odpowiedział, zamknij.

* czeka = bieżąca karta w „CV wysłane” albo „Rozmowie u klienta”, bez rozmowy przed
  nami i bez otwartego wniosku o terminy (klient już odpowiedział, jak w follow-upie);
* zegar: późniejsze z wejścia na etap, ostatniej rozmowy, ostatniego wniosku
  o terminy i „Klient odpowiedział”;
* na pasie i na karcie od 6. dnia roboczego;
* NEXUS nic nie wysyła do klienta: „Przypomnij klientowi” tylko przygotowuje treść;
* automat zamyka tylko „CV wysłane”, po 30 dniach kalendarzowych, za wyłącznikiem.

Reguła: ``docs/claude/rekrutacja-tablica/czeka-na-odpowiedz-klienta.md``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_date, business_today
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate
from app.models.client_interview_slot_request import (
    OPEN_SLOT_STATUSES,
    ClientInterviewSlotRequest,
    all_slots_past,
)
from app.models.client_panel import ClientPanelRequest, ClientPanelView
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.services import client_panel as panel_service
from app.services.dl_send_queue import waiting_workdays
from app.services.job_close_client_cards import client_side_rows, end_card
from app.services.rejection_reason_labels import CLIENT_NO_RESPONSE

logger = logging.getLogger(__name__)

#: Na pasie i na karcie ponad tyle dni roboczych.
WAIT_AFTER_WORKDAYS = 5
#: Automat: dni kalendarzowe od początku ciszy.
AUTO_CLOSE_DAYS = 30
#: Pary starsze niż próg przy włączeniu wyłącznika dostają tyle dni na ruch DL-a.
BACKLOG_GRACE_DAYS = 7

SETTING_KEY = "client_wait"
ENDED_BY_SILENT = "client_silent"
ACTION_REMINDED = "client_reminder_prepared"
ACTION_RESPONDED = "client_responded"
AUTO_CLOSE_COLUMN = "cv_sent"
_NOTE = "Klient nie odpowiedział przez 30 dni"


@dataclass(frozen=True)
class WaitSettings:
    auto_close: bool = False
    auto_close_since: Optional[date] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "auto_close": self.auto_close,
            "auto_close_since": (
                self.auto_close_since.isoformat() if self.auto_close_since else None
            ),
        }


async def read_settings(db: AsyncSession) -> WaitSettings:
    row = await db.get(AppSetting, SETTING_KEY)
    if row is None or not isinstance(row.value, dict):
        return WaitSettings()
    raw = row.value.get("auto_close_since")
    try:
        since = date.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError:
        since = None
    return WaitSettings(
        auto_close=row.value.get("auto_close") is True, auto_close_since=since
    )


async def write_settings(
    db: AsyncSession,
    auto_close: bool,
    *,
    user_id: Optional[int],
    today: Optional[date] = None,
) -> WaitSettings:
    """Zapis; pierwsze włączenie ustawia dzień, od którego liczy się okres ochronny."""
    current = await read_settings(db)
    since = current.auto_close_since
    if auto_close and not current.auto_close:
        since = today or business_today()
    value = WaitSettings(
        auto_close=auto_close, auto_close_since=since if auto_close else None
    )
    row = await db.get(AppSetting, SETTING_KEY)
    if row is None:
        db.add(AppSetting(key=SETTING_KEY, value=value.as_dict(), updated_by=user_id))
    else:
        row.value = value.as_dict()
        row.updated_by = user_id
    return value


def closes_on(silent_since: datetime, settings_: WaitSettings) -> Optional[date]:
    """Dzień automatycznego zamknięcia albo ``None``, gdy wyłącznik jest wyłączony."""
    if not settings_.auto_close:
        return None
    due = business_date(silent_since) + timedelta(days=AUTO_CLOSE_DAYS)
    if settings_.auto_close_since is not None:
        due = max(due, settings_.auto_close_since + timedelta(days=BACKLOG_GRACE_DAYS))
    return due


def workdays_noun(count: int) -> str:
    """„1 dzień roboczy”, „2 dni robocze”, „5 dni roboczych”."""
    if count == 1:
        return "1 dzień roboczy"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} dni robocze"
    return f"{count} dni roboczych"


@dataclass(frozen=True)
class PanelState:
    state: str
    label: str
    views: int = 0
    last_view_at: Optional[datetime] = None


PANEL_OFF = PanelState("off", "Panel wyłączony")


def panel_state_for(
    enabled: bool,
    views: int,
    last_view_at: Optional[datetime],
    decision: Optional[tuple[str, list[str], datetime]],
) -> PanelState:
    """Zdanie przy osobie: „Panel: otwarty 3× · ostatnio 05.11 · bez decyzji”."""
    if not enabled:
        return PANEL_OFF
    if decision is not None:
        kind, reasons, at = decision
        day = business_date(at).strftime("%d.%m")
        if kind == "interview":
            return PanelState(
                "interview", f"Panel: klient chce rozmowy {day}", views, last_view_at
            )
        why = f": {reasons[0]}" if reasons else ""
        return PanelState("not_fit", f"Panel: nie pasuje{why}", views, last_view_at)
    if views <= 0 or last_view_at is None:
        return PanelState("unseen", "Panel: klient nie otworzył", views, last_view_at)
    day = business_date(last_view_at).strftime("%d.%m")
    return PanelState(
        "viewed",
        f"Panel: otwarty {views}× · ostatnio {day} · bez decyzji",
        views,
        last_view_at,
    )


@dataclass(frozen=True)
class WaitingPerson:
    candidate_id: int
    name: str
    column: str
    entered_at: datetime
    silent_since: datetime
    workdays: int
    panel: PanelState
    reminded_at: Optional[datetime]
    closes_on: Optional[date]
    added_by: Optional[str]

    @property
    def needs_action(self) -> bool:
        return self.workdays > WAIT_AFTER_WORKDAYS

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "name": self.name,
            "column": self.column,
            "entered_at": self.entered_at.isoformat(),
            "silent_since": self.silent_since.isoformat(),
            "workdays": self.workdays,
            "needs_action": self.needs_action,
            "panel_state": self.panel.state,
            "panel_label": self.panel.label,
            "reminded_at": self.reminded_at.isoformat() if self.reminded_at else None,
            "closes_on": self.closes_on.isoformat() if self.closes_on else None,
            "added_by": self.added_by,
        }


async def _marks(
    db: AsyncSession, job_id: int
) -> tuple[dict[int, datetime], dict[int, datetime]]:
    """{kandydat: ostatnie „przypomnij”}, {kandydat: ostatnie „klient odpowiedział”}."""
    rows = await db.execute(
        select(Activity.action, Activity.details, Activity.created_at).where(
            Activity.entity_type == "job",
            Activity.entity_id == job_id,
            Activity.action.in_((ACTION_REMINDED, ACTION_RESPONDED)),
        )
    )
    reminded: dict[int, datetime] = {}
    responded: dict[int, datetime] = {}
    for action, details, created_at in rows.all():
        target = reminded if action == ACTION_REMINDED else responded
        for candidate_id in (details or {}).get("candidate_ids") or ():
            cid = int(candidate_id)
            if cid not in target or created_at > target[cid]:
                target[cid] = created_at
    return reminded, responded


async def _interview_signals(
    db: AsyncSession, job_id: int, candidate_ids: Iterable[int], now: datetime
) -> tuple[set[int], dict[int, datetime]]:
    """(osoby z rozmową przed nami lub otwartym wnioskiem, ostatni sygnał klienta)."""
    ids = list(candidate_ids)
    paused: set[int] = set()
    last: dict[int, datetime] = {}
    if not ids:
        return paused, last

    def offer(cid: int, at: datetime) -> None:
        if cid not in last or at > last[cid]:
            last[cid] = at

    events = await db.execute(
        select(
            CalendarEvent.candidate_id, CalendarEvent.start_time, CalendarEvent.end_time
        ).where(
            CalendarEvent.event_type == EventType.client_interview,
            CalendarEvent.status != EventStatus.cancelled,
            CalendarEvent.candidate_id.in_(ids),
            CalendarEvent.job_id == job_id,
        )
    )
    for cid, start, end in events.all():
        if start > now:
            paused.add(cid)
            continue
        offer(cid, end if end is not None and end <= now else start)
    slots = await db.execute(
        select(
            ClientInterviewSlotRequest.candidate_id,
            ClientInterviewSlotRequest.status,
            ClientInterviewSlotRequest.created_at,
            ClientInterviewSlotRequest.slots,
        ).where(
            ClientInterviewSlotRequest.candidate_id.in_(ids),
            ClientInterviewSlotRequest.job_id == job_id,
        )
    )
    for cid, status, created_at, terms in slots.all():
        if status in OPEN_SLOT_STATUSES and not all_slots_past(terms or (), now):
            paused.add(cid)
        offer(cid, created_at)
    return paused, last


async def _panel_states(
    db: AsyncSession, job_id: int, candidate_ids: list[int]
) -> tuple[bool, dict[int, PanelState]]:
    panel = await panel_service.panel_for_job(db, job_id)
    enabled = bool(panel and panel.enabled)
    if panel is None or not candidate_ids:
        return enabled, {}
    views = {
        cid: (count, last)
        for cid, count, last in (
            await db.execute(
                select(
                    ClientPanelView.candidate_id,
                    func.count(ClientPanelView.id),
                    func.max(ClientPanelView.created_at),
                )
                .where(
                    ClientPanelView.panel_id == panel.id,
                    ClientPanelView.action == "candidate",
                    ClientPanelView.candidate_id.in_(candidate_ids),
                )
                .group_by(ClientPanelView.candidate_id)
            )
        ).all()
    }
    decisions: dict[int, tuple[str, list[str], datetime]] = {}
    for cid, kind, reasons, created_at in (
        await db.execute(
            select(
                ClientPanelRequest.candidate_id,
                ClientPanelRequest.kind,
                ClientPanelRequest.reasons,
                ClientPanelRequest.created_at,
            )
            .where(
                ClientPanelRequest.panel_id == panel.id,
                ClientPanelRequest.kind.in_(("interview", "not_fit")),
                ClientPanelRequest.candidate_id.in_(candidate_ids),
            )
            .order_by(ClientPanelRequest.created_at)
        )
    ).all():
        decisions[cid] = (kind, list(reasons or ()), created_at)
    return enabled, {
        cid: panel_state_for(enabled, *views.get(cid, (0, None)), decisions.get(cid))
        for cid in candidate_ids
    }


@dataclass(frozen=True)
class JobWait:
    people: tuple[WaitingPerson, ...]
    panel_enabled: bool
    settings: WaitSettings


def _silent_since(
    moved_at: datetime, signal: Optional[datetime], responded: Optional[datetime]
) -> datetime:
    """Zegar ciszy: późniejsze z wejścia na etap, sygnału klienta i „odpowiedział”."""
    return max(at for at in (moved_at, signal, responded) if at is not None)


async def silent_workdays(
    db: AsyncSession,
    job: Job,
    *,
    now: Optional[datetime] = None,
    today: Optional[date] = None,
) -> dict[int, int]:
    """{kandydat: dni robocze ciszy} par ponad progiem, ta sama reguła co pas."""
    now = now or datetime.now(timezone.utc)
    today = today or business_today()
    rows = await client_side_rows(db, job)
    if not rows:
        return {}
    paused, signals = await _interview_signals(db, job.id, sorted(rows), now)
    _, responded = await _marks(db, job.id)
    out: dict[int, int] = {}
    for cid, (_, moved_at) in rows.items():
        if cid in paused:
            continue
        days = waiting_workdays(
            _silent_since(moved_at, signals.get(cid), responded.get(cid)), today
        )
        if days > WAIT_AFTER_WORKDAYS:
            out[cid] = days
    return out


async def silent_workdays_safely(db: AsyncSession, job: Job) -> dict[int, int]:
    """Dla Tablicy: awaria = brak plakietki + log, nigdy 500 całej Tablicy."""
    try:
        async with db.begin_nested():
            return await silent_workdays(db, job)
    except Exception:  # noqa: BLE001
        logger.exception("client_wait: cisza klienta job_id=%s", job.id)
        return {}


async def load_wait(
    db: AsyncSession,
    job: Job,
    *,
    now: Optional[datetime] = None,
    today: Optional[date] = None,
) -> JobWait:
    """Osoby u klienta tej rekrutacji, od najdłużej czekających."""
    now = now or datetime.now(timezone.utc)
    today = today or business_today()
    cfg = await read_settings(db)
    rows = await client_side_rows(db, job)
    if not rows:
        return JobWait((), False, cfg)
    ids = sorted(rows)
    paused, signals = await _interview_signals(db, job.id, ids, now)
    reminded, responded = await _marks(db, job.id)
    panel_enabled, panel_states = await _panel_states(db, job.id, ids)
    cvs = await panel_service.pair_cvs(db, job.id, ids)
    names = {
        row.id: row
        for row in (
            await db.execute(
                select(Candidate.id, Candidate.name, Candidate.lastname).where(
                    Candidate.id.in_(ids)
                )
            )
        ).all()
    }
    first_movers = {
        cid: user_id
        for cid, user_id in (
            await db.execute(
                select(CandidateStage.candidate_id, CandidateStage.moved_by)
                .where(
                    CandidateStage.job_id == job.id,
                    CandidateStage.candidate_id.in_(ids),
                )
                .order_by(
                    CandidateStage.candidate_id,
                    CandidateStage.moved_at,
                    CandidateStage.id,
                )
                .distinct(CandidateStage.candidate_id)
            )
        ).all()
    }
    user_ids = {uid for uid in first_movers.values() if uid is not None}
    user_names = (
        dict(
            (
                await db.execute(
                    select(User.id, User.name).where(User.id.in_(user_ids))
                )
            ).all()
        )
        if user_ids
        else {}
    )
    people: list[WaitingPerson] = []
    for cid, (column, moved_at) in rows.items():
        if cid in paused or cid not in names:
            continue
        silent_since = _silent_since(moved_at, signals.get(cid), responded.get(cid))
        people.append(
            WaitingPerson(
                candidate_id=cid,
                name=panel_service.person_name(names[cid], cvs.get(cid)),
                column=column,
                entered_at=moved_at,
                silent_since=silent_since,
                workdays=waiting_workdays(silent_since, today),
                panel=panel_states.get(cid, PANEL_OFF),
                reminded_at=reminded.get(cid),
                closes_on=closes_on(silent_since, cfg)
                if column == AUTO_CLOSE_COLUMN
                else None,
                added_by=user_names.get(first_movers.get(cid)),
            )
        )
    people.sort(key=lambda p: (-p.workdays, p.candidate_id))
    return JobWait(tuple(people), panel_enabled, cfg)


def wait_payload(wait: JobWait, today: Optional[date] = None) -> dict[str, Any]:
    today = today or business_today()
    needing = [p for p in wait.people if p.needs_action]
    nearest = min((p.closes_on for p in needing if p.closes_on), default=None)
    return {
        "after_workdays": WAIT_AFTER_WORKDAYS,
        "count": len(needing),
        "longest_workdays": needing[0].workdays if needing else 0,
        "panel_enabled": wait.panel_enabled,
        "auto_close": wait.settings.auto_close,
        "auto_close_days": AUTO_CLOSE_DAYS,
        "nearest_close_on": nearest.isoformat() if nearest else None,
        "nearest_close_in": (nearest - today).days if nearest else None,
        "people": [p.as_dict() for p in wait.people],
    }


def reminder_text(
    *,
    job_title: str,
    people: list[WaitingPerson],
    panel_url: Optional[str],
    sender_name: Optional[str],
) -> tuple[str, str]:
    """Temat i treść gotowej wiadomości. NEXUS jej nie wysyła: kopiuje ją DL."""
    subject = f"Prośba o informację zwrotną: {job_title}"
    listing = "\n".join(
        f"- {p.name}, CV przesłane {business_date(p.entered_at).strftime('%d.%m.%Y')}"
        for p in people
    )
    parts = [
        "Dzień dobry,",
        "",
        f"czekamy na Państwa informację zwrotną w rekrutacji {job_title}:",
        listing,
        "",
    ]
    if panel_url:
        parts += ["Odpowiedź można zostawić w panelu:", panel_url, ""]
    parts.append("Czy mogą Państwo przekazać, czy zapraszają Państwo na rozmowę?")
    parts += ["", "Pozdrawiam,", sender_name or ""]
    return subject, "\n".join(parts).rstrip()


def mark(
    db: AsyncSession, job_id: int, action: str, candidate_ids: list[int], user_id: int
) -> None:
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action=action,
            user_id=user_id,
            details={"candidate_ids": sorted(candidate_ids)},
        )
    )


def due_for_close(wait: JobWait, today: date) -> list[WaitingPerson]:
    """Pary, które automat może dziś zamknąć."""
    return [p for p in wait.people if p.closes_on is not None and p.closes_on <= today]


async def run_auto_close(
    db: AsyncSession, *, today: Optional[date] = None
) -> dict[str, int]:
    """Przebieg automatu; bez wyłącznika nic nie robi. Każda para osobno."""
    today = today or business_today()
    if not (await read_settings(db)).auto_close:
        return {"closed": 0, "skipped": 0}
    job_ids = list(
        (
            await db.scalars(select(Job.id).where(Job.status == JobStatus.published))
        ).all()
    )
    closed = skipped = 0
    for job_id in job_ids:
        job = await db.get(Job, job_id)
        if job is None:
            continue
        wait = await load_wait(db, job, today=today)
        for person in due_for_close(wait, today):
            try:
                stage = await end_card(
                    db,
                    job,
                    person.candidate_id,
                    reason_key=CLIENT_NO_RESPONSE,
                    actor_id=None,
                    note=_NOTE,
                    source="client_wait_auto_close",
                    ended_by=ENDED_BY_SILENT,
                )
                await db.commit()
            except Exception:  # noqa: BLE001 — jedna para nie zatrzymuje reszty
                logger.exception(
                    "client_wait: para job_id=%s candidate_id=%s",
                    job_id,
                    person.candidate_id,
                )
                await db.rollback()
                job = await db.get(Job, job_id)
                skipped += 1
                continue
            if stage is None:
                skipped += 1
            else:
                closed += 1
    return {"closed": closed, "skipped": skipped}
