"""Codzienne przypomnienia o brakujących ogłoszeniach (27.10.2026).

Decyzja Artura 27.10.2026 (makiety https://claude.ai/artifact/XJYxX56Www29d7P3d9k2ia).
Kopia produkcji z 22.10: żadna z 204 otwartych rekrutacji nie miała kompletu
— strony kariery brakowało w 201, Pracuj.pl w 181, JustJoin.IT w 187, a ludzie
chodzili po biurze i przypominali sobie nawzajem.

**Trzy kanały** każdej otwartej rekrutacji: strona kariery (zatwierdzony opis
— ``publications.career_pages_for_jobs``), Pracuj.pl i JustJoin.IT (aktywne
oznaczenie ``job_ad_publications``). Kanał z wierszem ``job_ad_channel_skips``
(„nie publikujemy tu”, z powodem) nie jest brakiem.

**Kto.** Strona kariery: Rekruterzy rekrutacji (``job_team``, bez propozycji),
bez nich Delivery Lead. Pracuj.pl i JustJoin.IT: Delivery Lead, bez aktywnego
DL-a — Head of Recruitment (``route_to_recipients``). DL („prowadzący”) widzi
w mailu wszystkie trzy kanały i to, czego nie zrobił rekruter.

**Kiedy.** Dni robocze od 8:00, raz dziennie (stan ``STATE_KEY`` przeżywa
restart). Rekrutacja otwarta po starcie przypomnień (próg „wysyłaj od” rodzaju
``job_ad_reminders``) dostaje osobny wpis ``job_ad_missing`` od dnia roboczego
po otwarciu; starsze idą jednym wpisem ``job_ad_backlog`` na osobę (decyzja
Artura 27.10: inaczej DL 14 dostałby pierwszego dnia 56 maili). Wczorajsze
nieprzeczytane wpisy tych typów gasną, żeby dzwonek nie rósł codziennie.

**Pracuj.pl przez opiekuna** (27.10.2026, ``job_ad.pracuj_mail``): po mailu
do opiekuna kanał ma stan ``requested`` — nie jest brakiem przez dzień wysyłki
i ``QUIET_BUSINESS_DAYS`` dni roboczych po nim; potem wraca jako brak.

**Mail** składa się przy wysyłce (``mail_card``), ze świeżego stanu: kanał
zrobiony od rana wypada, a gdy nic nie zostało — mail nie wychodzi. Przyciski
tylko otwierają okno „Ogłoszenie” na kanale (``?ogloszenie=``), nic nie
zapisują same (``maile-z-przyciskami-akcji.md``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterable, Literal, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import is_business_day
from app.models.app_setting import AppSetting
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_ad import JobAd
from app.models.job_ad_channel_skip import JobAdChannelSkip
from app.models.job_ad_publication import JobAdPublication
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services.job_ad_reminder_schema import (
    CHANNEL_CAREER,
    CHANNEL_JJIT,
    CHANNEL_PRACUJ,
    CHANNELS,
)
from app.services.job_ad import pracuj_mail
from app.services.notification_mail_card import MailButton, MailCard

logger = logging.getLogger(__name__)

FROM_HOUR = 8
UNTIL_HOUR = 17
STATE_KEY = "job_ad_reminders_state"
BACKLOG_LINK = "/jobs/ogloszenia"
BACKLOG_LISTED = 8
BUTTONS_MAX = 4
REASON_SHOWN = 60

CHANNEL_LABEL = {
    CHANNEL_CAREER: "Strona kariery",
    CHANNEL_PRACUJ: "Pracuj.pl",
    CHANNEL_JJIT: "JustJoin.IT",
}
CHANNEL_SHORT = {
    CHANNEL_CAREER: "kariera",
    CHANNEL_PRACUJ: "Pracuj",
    CHANNEL_JJIT: "JJIT",
}
BACKLOG_TITLE_MAX = 70
# Kolejność przycisków i treści: najpierw portale DL-a, potem strona kariery.
_BUTTON_ORDER = (CHANNEL_JJIT, CHANNEL_PRACUJ, CHANNEL_CAREER)
_BUTTON_LABEL = {
    CHANNEL_JJIT: "Wstaw na JustJoin.IT",
    CHANNEL_PRACUJ: "Wyślij do Pracuj.pl",
    CHANNEL_CAREER: "Opublikuj na stronie kariery",
}

TITLE_MISSING = "Brakujące ogłoszenia"
TITLE_BACKLOG = "Ogłoszenia do nadrobienia"
TITLE_NUDGE = "Prośba o stronę kariery"

ChannelStateName = Literal["live", "missing", "skipped", "requested"]


@dataclass(frozen=True)
class ChannelState:
    channel: str
    state: ChannelStateName
    # live: od kiedy wisi; skipped: kiedy zapisano „nie publikujemy”;
    # requested: kiedy poszedł mail do opiekuna portalu.
    since: Optional[datetime] = None
    # Kto ma to zrobić (gdy brak) — id kont.
    owners: tuple[int, ...] = ()
    skip_reason: Optional[str] = None
    skipped_by: Optional[int] = None


@dataclass(frozen=True)
class JobAdStatus:
    job_id: int
    title: str
    client: Optional[str]
    opened_at: Optional[datetime]
    # Prowadzący sprawę: aktywny DL, bez niego Head of Recruitment.
    leads: tuple[int, ...]
    delivery_lead_id: Optional[int]
    recruiter_ids: tuple[int, ...]
    has_ad: bool
    channels: tuple[ChannelState, ...]
    names: dict[int, str] = field(default_factory=dict)

    @property
    def missing(self) -> tuple[ChannelState, ...]:
        return tuple(c for c in self.channels if c.state == "missing")

    def channel(self, name: str) -> ChannelState:
        return next(c for c in self.channels if c.channel == name)

    def is_lead(self, user_id: int) -> bool:
        return user_id in self.leads

    def mine(self, user_id: int) -> tuple[ChannelState, ...]:
        """Braki, które robi ta osoba."""
        return tuple(c for c in self.missing if user_id in c.owners)

    def concerns(self, user_id: int) -> bool:
        """Czy osoba dostaje przypomnienie o tej rekrutacji."""
        if not self.missing:
            return False
        return self.is_lead(user_id) or bool(self.mine(user_id))


# ── Czyste reguły ────────────────────────────────────────────────────────────


def owners_for(
    channel: str,
    *,
    recruiter_ids: Iterable[int],
    leads: Iterable[int],
) -> tuple[int, ...]:
    """Strona kariery: rekruterzy, bez nich prowadzący; portale: prowadzący."""
    recruiters = tuple(dict.fromkeys(recruiter_ids))
    if channel == CHANNEL_CAREER and recruiters:
        return recruiters
    return tuple(dict.fromkeys(leads))


def channel_states(
    *,
    career_live: Optional[datetime],
    portals_live: dict[str, datetime],
    skips: dict[str, tuple[str, Optional[int], Optional[datetime]]],
    recruiter_ids: Iterable[int],
    leads: Iterable[int],
    requested: Optional[dict[str, datetime]] = None,
) -> tuple[ChannelState, ...]:
    """``requested`` = kanały, na których opiekun ma jeszcze czas (już po
    filtrze ``pracuj_mail.is_waiting``)."""
    waiting = requested or {}
    recruiters = tuple(recruiter_ids)
    lead_ids = tuple(leads)
    out: list[ChannelState] = []
    for channel in CHANNELS:
        live_at = (
            career_live if channel == CHANNEL_CAREER else portals_live.get(channel)
        )
        if live_at is not None:
            out.append(ChannelState(channel, "live", since=live_at))
        elif channel in skips:
            reason, by, at = skips[channel]
            out.append(
                ChannelState(
                    channel, "skipped", since=at, skip_reason=reason, skipped_by=by
                )
            )
        elif channel in waiting:
            out.append(ChannelState(channel, "requested", since=waiting[channel]))
        else:
            out.append(
                ChannelState(
                    channel,
                    "missing",
                    owners=owners_for(
                        channel, recruiter_ids=recruiters, leads=lead_ids
                    ),
                )
            )
    return tuple(out)


def is_new(opened_at: Optional[datetime], cutoff: Optional[datetime]) -> bool:
    """Rekrutacja otwarta po starcie przypomnień — osobne maile."""
    return opened_at is not None and cutoff is not None and opened_at >= cutoff


def due_today(opened_at: Optional[datetime], today: date) -> bool:
    """Pierwsze przypomnienie w dniu roboczym po otwarciu, nie w dniu otwarcia."""
    if opened_at is None:
        return True
    return _local(opened_at).date() < today


def local_day_start(moment: datetime) -> datetime:
    """Początek dnia firmy (Europe/Warsaw) dla chwili ``moment``."""
    return _local(moment).replace(hour=0, minute=0, second=0, microsecond=0)


def due_now(now_local: datetime, last_sent_on: Optional[str]) -> bool:
    if not is_business_day(now_local):
        return False
    if not FROM_HOUR <= now_local.hour < UNTIL_HOUR:
        return False
    return last_sent_on != now_local.date().isoformat()


def _local(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(ZoneInfo(settings.BUSINESS_TZ))


def today_local() -> date:
    """Dzisiejsza data w kalendarzu firmy."""
    return _local(datetime.now(timezone.utc)).date()


def _day(moment: Optional[datetime]) -> str:
    return _local(moment).strftime("%d.%m") if moment else "—"


def days_open(opened_at: Optional[datetime], today: date) -> Optional[int]:
    if opened_at is None:
        return None
    return max(0, (today - _local(opened_at).date()).days)


def short_name(name: Optional[str]) -> str:
    """„Julia Sowa” → „Julia S.”; jedno słowo zostaje."""
    parts = (name or "").split()
    if not parts:
        return "ktoś z zespołu"
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {parts[-1][0]}."


def _days_phrase(days: Optional[int]) -> str:
    if days is None:
        return ""
    if days == 1:
        return "1 dzień"
    return f"{days} dni"


def _jobs_phrase(count: int) -> str:
    """„1 rekrutacja”, „3 rekrutacje”, „12 rekrutacji”."""
    if count == 1:
        return "1 rekrutacja"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} rekrutacje"
    return f"{count} rekrutacji"


def _shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _owners_text(status: JobAdStatus, owners: Iterable[int]) -> str:
    return ", ".join(short_name(status.names.get(uid)) for uid in owners)


def channel_fact(
    status: JobAdStatus, state: ChannelState, *, viewer: int, today: date
) -> str:
    if state.state == "live":
        return f"✓ wisi od {_day(state.since)}"
    if state.state == "skipped":
        return f"— nie publikujemy: {_shorten(state.skip_reason or '', REASON_SHOWN)}"
    if state.state == "requested":
        return f"✉ wysłane do opiekuna {_day(state.since)} · czeka na publikację"
    if viewer in state.owners:
        return "✗ brak · robisz Ty"
    days = _days_phrase(days_open(status.opened_at, today))
    who = _owners_text(status, state.owners) or "nikt nie prowadzi"
    return f"✗ brak · robi {who}" + (f", {days}" if days else "")


def job_link(job_id: int, **params: str) -> str:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"/jobs/{job_id}" + (f"?{query}" if query else "")


def channel_link(job_id: int, channel: str) -> str:
    """Przycisk kanału w mailu: Pracuj.pl otwiera od razu mail do opiekuna."""
    if channel == CHANNEL_PRACUJ:
        return job_link(job_id, ogloszenie=channel, wyslij="opiekun")
    return job_link(job_id, ogloszenie=channel)


def bell_text(status: JobAdStatus, viewer: int) -> tuple[str, str, str]:
    """(tytuł, treść, link) wpisu ``job_ad_missing`` w dzwonku."""
    mine = status.mine(viewer)
    labels = ", ".join(CHANNEL_LABEL[c.channel] for c in status.missing)
    first = (mine or status.missing)[0].channel
    return (
        f"{TITLE_MISSING}: {status.title}"[:255],
        f"Brakuje: {labels}.",
        job_link(status.job_id, ogloszenie=first),
    )


def lead_card(status: JobAdStatus, viewer: int, today: date) -> Optional[MailCard]:
    """Mail do prowadzącego (DL, bez niego HoR): wszystkie trzy kanały."""
    if not status.missing:
        return None
    mine = sorted(status.mine(viewer), key=lambda c: _BUTTON_ORDER.index(c.channel))
    others_career = [
        c
        for c in status.missing
        if c.channel == CHANNEL_CAREER and viewer not in c.owners
    ]
    days = days_open(status.opened_at, today)
    none_live = all(c.state == "missing" for c in status.channels)
    if none_live:
        title = "Rekrutacja nie ma jeszcze żadnego ogłoszenia"
    elif mine:
        title = "Brakuje ogłoszenia: " + ", ".join(
            CHANNEL_LABEL[c.channel] for c in mine
        )
    else:
        title = "Strona kariery wciąż czeka"
    opened = (
        f"Rekrutacja jest otwarta od {_days_phrase(days)}"
        if days
        else "Rekrutacja jest otwarta"
    )
    parts = [f"{opened}, a kandydaci z kanałów bez ogłoszenia jej nie widzą."]
    if others_career:
        who = _owners_text(status, others_career[0].owners)
        parts.append(
            f"Stronę kariery wstawia {who} — dostaje o tym osobny mail codziennie."
        )
    facts = tuple(
        (CHANNEL_LABEL[c.channel], channel_fact(status, c, viewer=viewer, today=today))
        for c in status.channels
    )
    facts += (
        (
            "Otwarta",
            " · ".join(p for p in (_day(status.opened_at), status.client) if p),
        ),
    )
    buttons: list[MailButton] = [
        MailButton(
            _BUTTON_LABEL[c.channel],
            channel_link(status.job_id, c.channel),
            "primary" if index == 0 else "secondary",
        )
        for index, c in enumerate(mine)
    ]
    if others_career:
        owners = others_career[0].owners
        label = (
            f"Przypomnij: {short_name(status.names.get(owners[0]))}"
            if len(owners) == 1
            else "Przypomnij rekruterom"
        )
        buttons.append(
            MailButton(
                label,
                job_link(
                    status.job_id, ogloszenie=CHANNEL_CAREER, przypomnij="rekruter"
                ),
                "secondary" if buttons else "primary",
            )
        )
    buttons = buttons[: BUTTONS_MAX - 1]
    buttons.append(
        MailButton(
            "Nie publikujemy tej rekrutacji",
            job_link(status.job_id, ogloszenie="pomin"),
            "neg",
        )
    )
    return MailCard(
        action="Wstaw ogłoszenia" if mine else "Przypilnuj strony kariery",
        about=status.title,
        chip="Czeka na Ciebie" if mine else "Czeka na rekrutera",
        waiting=bool(mine),
        title=title,
        text=" ".join(parts),
        facts=facts,
        buttons=tuple(buttons),
        required=True,
    )


def recruiter_card(
    status: JobAdStatus,
    viewer: int,
    today: date,
    *,
    asked_by: Optional[str] = None,
) -> Optional[MailCard]:
    """Mail do rekrutera: strona kariery (jedyny kanał rekrutera)."""
    career = status.channel(CHANNEL_CAREER)
    if career.state != "missing" or viewer not in career.owners:
        return None
    content = (
        "Treść jest gotowa z Profilu Championa, bez nazwy klienta i stawek. "
        "Przeczytaj ją i kliknij „Opublikuj na stronie”."
        if status.has_ad
        else "Treść ułożysz jednym kliknięciem w oknie „Ogłoszenie” — bez nazwy "
        "klienta i stawek."
    )
    lead = (
        short_name(status.names.get(status.delivery_lead_id))
        if status.delivery_lead_id
        else None
    )
    tail = (
        f"{asked_by} prosi Cię o to dziś."
        if asked_by
        else (f"{lead} (Delivery Lead) widzi, że tego jeszcze brakuje." if lead else "")
    )
    text = " ".join(
        p
        for p in (
            content,
            "Zgłoszenia ze strony trafią od razu do „Nowych” tej rekrutacji.",
            tail,
        )
        if p
    )
    waiting = _days_phrase(days_open(status.opened_at, today))
    facts = tuple(
        (k, v)
        for k, v in (
            ("Rekrutacja", status.title),
            ("Klient", status.client),
            ("Delivery Lead", lead),
            ("Czeka", f"{waiting} · przypomnienie codziennie" if waiting else None),
        )
        if v
    )
    return MailCard(
        action="Opublikuj na stronie kariery",
        about=status.title,
        chip="Prośba od DL-a" if asked_by else "Czeka na Ciebie",
        waiting=True,
        title="Opublikuj rekrutację na stronie kariery",
        text=text,
        facts=facts,
        buttons=(
            MailButton(
                "Opublikuj na stronie kariery",
                job_link(status.job_id, ogloszenie=CHANNEL_CAREER),
                "primary",
            ),
        ),
        required=True,
    )


def backlog_card(statuses: list[JobAdStatus], viewer: int) -> Optional[MailCard]:
    """Jeden mail o rekrutacjach sprzed startu przypomnień."""
    rows = [s for s in statuses if s.concerns(viewer)]
    if not rows:
        return None
    rows.sort(
        key=lambda s: (
            s.opened_at or datetime.min.replace(tzinfo=timezone.utc),
            s.job_id,
        ),
        reverse=True,
    )

    def _visible(s: JobAdStatus) -> tuple[ChannelState, ...]:
        # Prowadzący widzi wszystkie braki, rekruter — swoje.
        return s.missing if s.is_lead(viewer) else s.mine(viewer)

    count = {
        ch: sum(1 for s in rows if any(c.channel == ch for c in _visible(s)))
        for ch in CHANNELS
    }
    missing_text = ", ".join(
        f"{CHANNEL_LABEL[ch].lower() if ch == CHANNEL_CAREER else CHANNEL_LABEL[ch]} w {n}"
        for ch, n in count.items()
        if n
    )
    # Krótka lista braków w lewej kolumnie (szablon jej nie łamie), nazwa
    # rekrutacji w prawej — długie nazwy wypychały braki poza mail (staging 27.10).
    facts: tuple[tuple[str, str], ...] = tuple(
        (
            "✗ " + ", ".join(CHANNEL_SHORT[c.channel] for c in _visible(s)),
            _shorten(s.title, BACKLOG_TITLE_MAX),
        )
        for s in rows[:BACKLOG_LISTED]
    )
    rest = len(rows) - BACKLOG_LISTED
    if rest > 0:
        facts += (("…", f"i {rest} starszych"),)
    phrase = _jobs_phrase(len(rows))
    return MailCard(
        action="Nadrób ogłoszenia",
        about=f"{phrase} sprzed startu przypomnień",
        chip="Zaległe",
        waiting=False,
        title=f"Twoje rekrutacje bez kompletu ogłoszeń: {len(rows)}",
        text=(
            "To rekrutacje otwarte przed startem przypomnień, więc nie dostajesz "
            f"o nich osobnych maili. Brakuje: {missing_text}. Najnowsze:"
        ),
        facts=facts,
        buttons=(MailButton("Nadrabiaj po kolei", BACKLOG_LINK, "primary"),),
        required=True,
    )


# ── Odczyt stanu z bazy ──────────────────────────────────────────────────────


async def _hor_ids(db: AsyncSession) -> list[int]:
    return sorted(
        (
            await db.scalars(
                select(User.id).where(
                    User.is_active.is_(True),
                    or_(
                        User.role == UserRole.head_of_recruitment,
                        User.roles.contains([UserRole.head_of_recruitment.value]),
                    ),
                )
            )
        ).all()
    )


async def load_statuses(
    db: AsyncSession, job_ids: Optional[Iterable[int]] = None
) -> list[JobAdStatus]:
    """Stan trzech kanałów otwartych rekrutacji (wszystkich albo podanych)."""
    from app.services.job_ad.publications import career_pages_for_jobs
    from app.services.job_team import recruiters_for_jobs, working
    from app.services.job_working_title import display_title
    from app.services.request_allocation_notices import route_to_recipients

    query = (
        select(Job, Client.name)
        .outerjoin(Client, Client.id == Job.client_id)
        .where(Job.status == JobStatus.published)
    )
    if job_ids is not None:
        ids = sorted(set(job_ids))
        if not ids:
            return []
        query = query.where(Job.id.in_(ids))
    jobs = (await db.execute(query)).all()
    if not jobs:
        return []
    ids = [job.id for job, _ in jobs]

    career_live = await _career_since(db, await career_pages_for_jobs(db, ids))
    portals: dict[int, dict[str, datetime]] = {}
    for job_id, portal, at in (
        await db.execute(
            select(
                JobAdPublication.job_id,
                JobAdPublication.portal,
                JobAdPublication.published_at,
            ).where(
                JobAdPublication.job_id.in_(ids),
                JobAdPublication.removed_at.is_(None),
            )
        )
    ).all():
        portals.setdefault(job_id, {})[portal] = at
    skips: dict[int, dict[str, tuple[str, Optional[int], Optional[datetime]]]] = {}
    for row in (
        await db.scalars(
            select(JobAdChannelSkip).where(JobAdChannelSkip.job_id.in_(ids))
        )
    ).all():
        skips.setdefault(row.job_id, {})[row.channel] = (
            row.reason,
            row.created_by,
            row.created_at,
        )
    with_ad = set(
        (await db.scalars(select(JobAd.job_id).where(JobAd.job_id.in_(ids)))).all()
    )
    today = today_local()
    pracuj_waiting = {
        job_id: req.sent_at
        for job_id, req in (await pracuj_mail.last_requests(db, ids)).items()
        if pracuj_mail.is_waiting(req.sent_at, today)
    }
    team = await recruiters_for_jobs(db, ids)

    lead_ids = {job.delivery_lead_id for job, _ in jobs if job.delivery_lead_id}
    users = (
        {
            u.id: u
            for u in (await db.scalars(select(User).where(User.id.in_(lead_ids)))).all()
        }
        if lead_ids
        else {}
    )
    active_leads = {uid for uid, u in users.items() if u.is_active}
    hor: Optional[list[int]] = None

    statuses: list[JobAdStatus] = []
    names: dict[int, str] = {uid: u.name or u.email for uid, u in users.items()}
    for job, client_name in jobs:
        if job.delivery_lead_id not in active_leads and hor is None:
            hor = await _hor_ids(db)
        leads = tuple(
            route_to_recipients(job.delivery_lead_id, active_leads, hor or [])
        )
        people = working(team.get(job.id, []))
        recruiter_ids = tuple(p.user_id for p in people)
        for p in people:
            names.setdefault(p.user_id, p.name)
        statuses.append(
            JobAdStatus(
                job_id=job.id,
                title=display_title(job),
                client=client_name,
                opened_at=job.opened_at or job.created_at,
                leads=leads,
                delivery_lead_id=job.delivery_lead_id,
                recruiter_ids=recruiter_ids,
                has_ad=job.id in with_ad,
                channels=channel_states(
                    career_live=career_live.get(job.id),
                    portals_live=portals.get(job.id, {}),
                    skips=skips.get(job.id, {}),
                    recruiter_ids=recruiter_ids,
                    leads=leads,
                    requested=(
                        {CHANNEL_PRACUJ: pracuj_waiting[job.id]}
                        if job.id in pracuj_waiting
                        else None
                    ),
                ),
                names=names,
            )
        )
    missing_names = {
        uid
        for s in statuses
        for uid in (*s.leads, *s.recruiter_ids)
        if uid not in names
    }
    if missing_names:
        for uid, name, email in (
            await db.execute(
                select(User.id, User.name, User.email).where(User.id.in_(missing_names))
            )
        ).all():
            names[uid] = name or email
    return statuses


async def _career_since(db: AsyncSession, job_ids: set[int]) -> dict[int, datetime]:
    from app.models.job_public_profile import JobPublicProfile

    if not job_ids:
        return {}
    return {
        job_id: at
        for job_id, at in (
            await db.execute(
                select(JobPublicProfile.job_id, JobPublicProfile.approved_at).where(
                    JobPublicProfile.job_id.in_(job_ids)
                )
            )
        ).all()
        if at is not None
    }


# ── Codzienne wpisy ──────────────────────────────────────────────────────────


async def _load_state(db: AsyncSession) -> dict[str, Any]:
    row = await db.get(AppSetting, STATE_KEY)
    return dict(row.value or {}) if row is not None else {}


async def _save_state(db: AsyncSession, value: dict[str, Any]) -> None:
    await db.execute(
        pg_insert(AppSetting)
        .values(key=STATE_KEY, value=value)
        .on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": value, "updated_at": datetime.now(timezone.utc)},
        )
    )


async def launch_cutoff(db: AsyncSession) -> Optional[datetime]:
    """Start przypomnień = próg „wysyłaj od” rodzaju; wyłączony = ``None``."""
    from app.services.notification_delivery import JOB_AD_KIND, load_policy

    policy = await load_policy(db)
    if not policy.kind_enabled(JOB_AD_KIND):
        return None
    return policy.cutoff_for(JOB_AD_KIND)


def plan_day(
    statuses: list[JobAdStatus], *, cutoff: datetime, today: date
) -> tuple[list[tuple[int, JobAdStatus]], dict[int, int]]:
    """(wpisy o rekrutacjach, osoba → liczba zaległych rekrutacji)."""
    per_job: list[tuple[int, JobAdStatus]] = []
    backlog: dict[int, int] = {}
    for status in statuses:
        if not status.missing:
            continue
        people = dict.fromkeys(
            (*status.leads, *(o for c in status.missing for o in c.owners))
        )
        if is_new(status.opened_at, cutoff):
            if not due_today(status.opened_at, today):
                continue
            per_job.extend((uid, status) for uid in people if status.concerns(uid))
        else:
            for uid in people:
                if status.concerns(uid):
                    backlog[uid] = backlog.get(uid, 0) + 1
    return per_job, backlog


async def send_daily(db: AsyncSession, now: datetime) -> int:
    """Wpisy dnia (raz dziennie, dni robocze 8–17). Nie commituje."""
    from app.services.notification_triggers import emit  # noqa: PLC0415

    local = _local(now)
    state = await _load_state(db)
    if not due_now(local, state.get("last_sent_on")):
        return 0
    cutoff = await launch_cutoff(db)
    if cutoff is None:
        return 0
    today = local.date()
    statuses = await load_statuses(db)
    per_job, backlog = plan_day(statuses, cutoff=cutoff, today=today)

    # Wczorajsze nieprzeczytane przypomnienia gasną — dzwonek nie rośnie co dzień.
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    await db.execute(
        update(Notification)
        .where(
            Notification.notification_type.in_(
                [NotificationType.job_ad_missing, NotificationType.job_ad_backlog]
            ),
            Notification.created_at < day_start,
            Notification.is_read.is_(False),
        )
        .values(is_read=True)
    )

    created = 0
    for user_id, status in per_job:
        title, message, link = bell_text(status, user_id)
        row = await emit(
            db,
            user_id=user_id,
            title=title,
            message=message,
            ntype=NotificationType.job_ad_missing,
            related_entity_type="job",
            related_entity_id=status.job_id,
            link=link,
        )
        created += int(row is not None)
    for user_id, count in backlog.items():
        row = await emit(
            db,
            user_id=user_id,
            title=f"{TITLE_BACKLOG}: {_jobs_phrase(count)}",
            message=(
                "Rekrutacje sprzed startu przypomnień bez strony kariery, "
                "Pracuj.pl albo JustJoin.IT."
            ),
            ntype=NotificationType.job_ad_backlog,
            related_entity_type="user",
            related_entity_id=user_id,
            link=BACKLOG_LINK,
        )
        created += int(row is not None)
    await _save_state(db, {"last_sent_on": today.isoformat()})
    logger.info(
        "job_ad_reminders: %d wpisów (rekrutacje %d, zaległe %d osób)",
        created,
        len(per_job),
        len(backlog),
    )
    return created


# ── Mail przy wysyłce ────────────────────────────────────────────────────────


async def mail_card(
    db: AsyncSession, notif: Notification, user: User
) -> Optional[MailCard]:
    """Karta maila ze świeżego stanu; ``None`` = nic już nie brakuje."""
    today = _local(datetime.now(timezone.utc)).date()
    ntype = notif.notification_type
    if ntype == NotificationType.job_ad_backlog:
        cutoff = await launch_cutoff(db)
        if cutoff is None:
            return None
        statuses = [
            s for s in await load_statuses(db) if not is_new(s.opened_at, cutoff)
        ]
        return backlog_card(statuses, user.id)
    if notif.related_entity_id is None:
        return None
    found = await load_statuses(db, [notif.related_entity_id])
    if not found:
        return None
    status = found[0]
    if ntype == NotificationType.job_ad_nudge:
        return recruiter_card(status, user.id, today, asked_by=_asked_by(notif.message))
    if status.is_lead(user.id):
        return lead_card(status, user.id, today)
    return recruiter_card(status, user.id, today)


NUDGE_PREFIX = "Prosi: "
NUDGE_SEPARATOR = " — "


def nudge_message(asker_name: Optional[str]) -> str:
    return f"{NUDGE_PREFIX}{short_name(asker_name)}{NUDGE_SEPARATOR}opublikuj rekrutację na stronie kariery."


def _asked_by(message: Optional[str]) -> Optional[str]:
    if not message or not message.startswith(NUDGE_PREFIX):
        return None
    # Separator, nie kropka: „Martyna W.” ma kropkę po inicjale.
    return message[len(NUDGE_PREFIX) :].split(NUDGE_SEPARATOR, 1)[0] or None


# ── Lista „Ogłoszenia do nadrobienia” i panel w oknie ───────────────────────


def can_manage(user: User, status: JobAdStatus) -> bool:
    """„Nie publikujemy” i „Przypomnij”: prowadzący, Head of Recruitment, admin."""
    return status.is_lead(user.id) or user.has_any_role(
        UserRole.head_of_recruitment, UserRole.admin
    )


def channel_view(status: JobAdStatus, state: ChannelState, viewer: int) -> dict:
    return {
        "channel": state.channel,
        "state": state.state,
        "since": state.since,
        "mine": viewer in state.owners,
        "owner_names": [status.names.get(uid) or "" for uid in state.owners],
        "skip_reason": state.skip_reason,
        "skipped_by_name": status.names.get(state.skipped_by)
        if state.skipped_by
        else None,
    }


def panel(status: JobAdStatus, user: User) -> dict:
    """Stan kanałów dla okna „Ogłoszenie”."""
    return {
        "channels": [channel_view(status, c, user.id) for c in status.channels],
        "can_manage": can_manage(user, status),
        "recruiter_names": [
            status.names.get(uid) or "" for uid in status.recruiter_ids
        ],
    }


async def with_skip_authors(db: AsyncSession, statuses: list[JobAdStatus]) -> None:
    """Imiona autorów „nie publikujemy” (nie muszą być w zespole rekrutacji)."""
    authors = {
        c.skipped_by
        for s in statuses
        for c in s.channels
        if c.skipped_by and c.skipped_by not in s.names
    }
    if not authors:
        return
    names = {
        uid: name or email
        for uid, name, email in (
            await db.execute(
                select(User.id, User.name, User.email).where(User.id.in_(authors))
            )
        ).all()
    }
    for status in statuses:
        status.names.update({k: v for k, v in names.items() if k not in status.names})


__all__ = [
    "BACKLOG_LINK",
    "CHANNEL_LABEL",
    "ChannelState",
    "JobAdStatus",
    "backlog_card",
    "can_manage",
    "channel_link",
    "channel_states",
    "due_now",
    "due_today",
    "is_new",
    "lead_card",
    "load_statuses",
    "mail_card",
    "nudge_message",
    "owners_for",
    "panel",
    "plan_day",
    "recruiter_card",
    "send_daily",
    "short_name",
]
