"""Poniedziałkowy skrót „propozycje czekają na decyzję” dla Delivery Leadów.

Decyzja Artura 30.09.2026: do tego dnia żadna z 57 nocnych propozycji nie
miała decyzji. W poniedziałek (Europe/Warsaw) każdy Delivery Lead dostaje
JEDEN dzwonek z liczbą osób, które czekają w „Do przejrzenia” jego
opublikowanych rekrutacji w pracy (``request_work_state.IN_WORK_STATES``).

Typ powiadomienia to istniejący ``auto_match_proposals`` (bez migracji enuma),
ale z własnym ``related_entity_type`` (``proposals_digest``) i numerem tygodnia
ISO w ``related_entity_id`` — to klucz dedupu „raz na tydzień na DL-a”
(sprawdzany wprost; dobowy indeks ``ix_notif_dedup_daily`` zostaje siatką).

Funkcja NIE jest wpięta w żadną pętlę — woła ją nocny przegląd.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.job import Job, JobStatus
from app.models.job_proposal import JobProposal
from app.services.request_work_state import IN_WORK_STATES

logger = logging.getLogger(__name__)

DIGEST_ENTITY_TYPE = "proposals_digest"
MAX_TITLES_IN_MESSAGE = 3


@dataclass(frozen=True)
class PendingJob:
    job_id: int
    title: str
    delivery_lead_id: int
    pending: int


@dataclass
class DigestPlan:
    delivery_lead_id: int
    total: int = 0
    jobs: list[PendingJob] = field(default_factory=list)

    @property
    def link(self) -> str:
        if len(self.jobs) == 1:
            return f"/jobs/{self.jobs[0].job_id}?tab=similar"
        return "/jobs?mine=1"

    @property
    def title(self) -> str:
        return f"W Twoich rekrutacjach {pending_phrase(self.total)} na decyzję"

    @property
    def message(self) -> str:
        top = sorted(self.jobs, key=lambda j: (-j.pending, j.job_id))
        parts = [f"„{j.title}” ({j.pending})" for j in top[:MAX_TITLES_IN_MESSAGE]]
        rest = len(top) - MAX_TITLES_IN_MESSAGE
        tail = f" i {rest} inn{'a' if rest == 1 else 'e'}" if rest > 0 else ""
        return (
            f"Najwięcej w: {', '.join(parts)}{tail}. Dodaj albo pomiń z powodem "
            "— bez decyzji nie wiemy, czy propozycje są dobre."
        )


def pending_phrase(count: int) -> str:
    """„1 propozycja czeka”, „3 propozycje czekają”, „12 propozycji czeka”."""
    if count == 1:
        return "1 propozycja czeka"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} propozycje czekają"
    return f"{count} propozycji czeka"


def is_digest_day(now: datetime) -> bool:
    """Poniedziałek w kalendarzu firmy (nie UTC — niedziela 23:30 UTC to już poniedziałek w Warszawie)."""
    return now.astimezone(ZoneInfo(settings.BUSINESS_TZ)).weekday() == 0


def week_key(now: datetime) -> int:
    """Tydzień ISO w kalendarzu firmy jako liczba ``RRRRTT`` (np. 202640)."""
    iso = now.astimezone(ZoneInfo(settings.BUSINESS_TZ)).isocalendar()
    return iso.year * 100 + iso.week


def plan_digests(rows: Iterable[PendingJob]) -> dict[int, DigestPlan]:
    """Kto dostaje ile — czysta, testowana bez bazy. Rekrutacje bez czekających pomijane."""
    plans: dict[int, DigestPlan] = {}
    for row in rows:
        if row.pending <= 0:
            continue
        plan = plans.setdefault(row.delivery_lead_id, DigestPlan(row.delivery_lead_id))
        plan.total += row.pending
        plan.jobs.append(row)
    return plans


async def _pending_jobs(db: AsyncSession) -> list[PendingJob]:
    """Ile osób czeka w skrzynce — ta sama reguła co lista i licznik skrzynki.

    ``open_counts_for_jobs``: status PARY ``proposed`` (pominięta albo dodana
    para się nie liczy, wygasłe wiersze też nie), bez osób już w pipeline'ie
    i z globalnej czarnej listy. Do 07.10.2026 skrót liczył surowe wiersze
    ``proposed`` — od publikacji bez limitu urósłby o osoby, których lista
    nie pokazuje.
    """
    from app.services.job_proposals import open_counts_for_jobs  # noqa: PLC0415
    from app.services.job_working_title import job_display_title_expr  # noqa: PLC0415

    jobs = (
        await db.execute(
            select(Job.id, job_display_title_expr(), Job.delivery_lead_id).where(
                Job.status == JobStatus.published,
                Job.work_state.in_(IN_WORK_STATES),
                Job.delivery_lead_id.is_not(None),
                exists().where(
                    JobProposal.job_id == Job.id, JobProposal.status == "proposed"
                ),
            )
        )
    ).all()
    counts = await open_counts_for_jobs(db, [int(jid) for jid, _t, _dl in jobs])
    return [
        PendingJob(int(jid), str(title or f"#{jid}"), int(dl), counts.get(int(jid), 0))
        for jid, title, dl in jobs
    ]


async def _already_sent(db: AsyncSession, user_id: int, key: int) -> bool:
    from app.models.notification import Notification, NotificationType  # noqa: PLC0415

    return bool(
        await db.scalar(
            select(Notification.id)
            .where(
                Notification.user_id == user_id,
                Notification.notification_type == NotificationType.auto_match_proposals,
                Notification.related_entity_type == DIGEST_ENTITY_TYPE,
                Notification.related_entity_id == key,
            )
            .limit(1)
        )
    )


async def send_pending_proposals_digest(
    db: AsyncSession, now: Optional[datetime] = None
) -> int:
    """Wysyła skróty (tylko w poniedziałek). Zwraca liczbę utworzonych powiadomień.

    Nie commituje — robi to wołający. Błąd jednego odbiorcy (savepoint) nie
    zatrzymuje pozostałych.
    """
    from app.models.notification import NotificationType  # noqa: PLC0415
    from app.services.notification_triggers import emit  # noqa: PLC0415

    moment = now or datetime.now(ZoneInfo(settings.BUSINESS_TZ))
    if not is_digest_day(moment):
        return 0
    key = week_key(moment)
    plans = plan_digests(await _pending_jobs(db))
    sent = 0
    for dl_id, plan in sorted(plans.items()):
        try:
            async with db.begin_nested():
                if await _already_sent(db, dl_id, key):
                    continue
                created = await emit(
                    db,
                    user_id=dl_id,
                    title=plan.title[:255],
                    message=plan.message,
                    ntype=NotificationType.auto_match_proposals,
                    related_entity_type=DIGEST_ENTITY_TYPE,
                    related_entity_id=key,
                    link=plan.link,
                )
                if created is not None:
                    sent += 1
        except Exception:  # noqa: BLE001 — jeden odbiorca nie blokuje reszty
            logger.exception("[proposals_digest] digest failed user=%s", dl_id)
    return sent
