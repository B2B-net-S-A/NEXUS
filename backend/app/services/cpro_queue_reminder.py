"""Przypomnienie osobie od Cpro o kartach z kolejki Cpro w Traffit (08.10.2026).

Dzwonek „Do wrzucenia do Cpro” (`stage_handoff_recipients`) wychodzi przy ruchu
karty w NEXUSIE. Pomiar z produkcji 08.10.2026: w 14 dniach były 122 wejścia
na „NORDEA: Wysłać do Cpro” i WSZYSTKIE w Traffit — NEXUS widzi je dopiero
z importu (surowy SQL, bez powiadomień), więc osoba od Cpro nie dostała ani
jednego dzwonka. Decyzja Artura 08.10.2026: ma dostawać powiadomienie i mail.

Po fazie `pipelines` importu liczymy STAN: pary, których najnowszy wiersz to
zaimportowany etap kolejki Cpro u klienta z kolejką Cpro (Nordea). Karty już
wysłane mają późniejszy wiersz i odpadają — przy imporcie nocnym to większość
(93 ze 122), dlatego przypomnienie nie jest dzwonkiem na każdy wiersz importu.

Jedno powiadomienie na osobę na dzień (`ix_notif_dedup_daily`, encja = odbiorca),
typ ``board_task_waiting``: nie da się go wyciszyć i kolejka maili wysyła go
od razu (rodzaj `dl_review`). Tylko w dni robocze — sobotni i niedzielny import
powtarzałby piątkową listę.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import settings
from app.core.scheduling import is_business_day
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.notification import NotificationType
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage
from app.services import cpro_sender
from app.services.board_stage_badges import cpro_enabled_for_client, stage_badge_kind
from app.services.notification_triggers import emit
from app.services.stage_handoff_recipients import TITLE_CPRO_QUEUE

logger = logging.getLogger(__name__)

TRAFFIT_SOURCE = "traffit"
# Ile kart wymieniamy z nazwiska; reszta to „oraz N kolejnych”.
MAX_LISTED = 10
# Tytuły rekrutacji z Traffita mają po 100+ znaków — w dzwonku wystarczy początek.
MAX_JOB_TITLE = 60


@dataclass(frozen=True)
class WaitingCard:
    stage_id: int
    candidate_id: int
    job_id: int
    candidate_name: str
    job_title: str
    waiting_since: datetime


async def _queue_stage_def_ids(db: AsyncSession) -> list[int]:
    """Etapy kolejki Cpro — po nazwie, tą samą regułą co Tablica."""

    rows = await db.execute(
        select(PipelineStageDef.id, PipelineStageDef.name).where(
            PipelineStageDef.name.ilike("%cpro%")
        )
    )
    return sorted(
        def_id for def_id, name in rows.all() if stage_badge_kind(name) == "cpro"
    )


async def waiting_cards(db: AsyncSession, *, now: datetime) -> list[WaitingCard]:
    """Karty z importu Traffita, które nadal stoją w kolejce Cpro.

    „Nadal” = para nie ma późniejszego wiersza etapu (kolejność jak na
    Tablicy: `moved_at`, potem `id`). Najdłużej czekające pierwsze.
    """

    def_ids = await _queue_stage_def_ids(db)
    if not def_ids:
        return []
    cutoff = now - timedelta(
        days=max(1, int(settings.TRAFFIT_CPRO_REMINDER_WINDOW_DAYS))
    )
    later = aliased(CandidateStage)
    moved_on = (
        select(later.id)
        .where(
            later.candidate_id == CandidateStage.candidate_id,
            later.job_id == CandidateStage.job_id,
            tuple_(later.moved_at, later.id)
            > tuple_(CandidateStage.moved_at, CandidateStage.id),
        )
        .exists()
    )
    rows = await db.execute(
        select(
            CandidateStage.id,
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.moved_at,
            Candidate.name,
            Candidate.lastname,
            Job.title,
            Job.working_title,
            Job.client_id,
        )
        .join(Candidate, Candidate.id == CandidateStage.candidate_id)
        .join(Job, Job.id == CandidateStage.job_id)
        .where(
            CandidateStage.stage_def_id.in_(def_ids),
            CandidateStage.external_source == TRAFFIT_SOURCE,
            CandidateStage.moved_at >= cutoff,
            ~moved_on,
        )
        .order_by(CandidateStage.moved_at, CandidateStage.id)
    )
    cards: list[WaitingCard] = []
    for row in rows.all():
        if not cpro_enabled_for_client(row.client_id):
            continue
        name = " ".join(p for p in (row.name, row.lastname) if p)
        cards.append(
            WaitingCard(
                stage_id=row.id,
                candidate_id=row.candidate_id,
                job_id=row.job_id,
                candidate_name=name or f"#{row.candidate_id}",
                job_title=row.working_title or row.title,
                waiting_since=row.moved_at,
            )
        )
    return cards


def build_notice(cards: Sequence[WaitingCard], *, tz: str) -> tuple[str, str, str]:
    """``(tytuł, treść, link)`` przypomnienia. Link otwiera kartę, która czeka
    najdłużej; pozostałe wymienia treść."""

    zone = ZoneInfo(tz)

    def line(card: WaitingCard) -> str:
        since = card.waiting_since.astimezone(zone).strftime("%d.%m, %H:%M")
        job_title = card.job_title
        if len(job_title) > MAX_JOB_TITLE:
            job_title = job_title[: MAX_JOB_TITLE - 1].rstrip() + "…"
        return f"{card.candidate_name} — „{job_title}” (od {since})"

    first = cards[0]
    link = f"/jobs/{first.job_id}?candidate={first.candidate_id}"
    if len(cards) == 1:
        return (
            f"{TITLE_CPRO_QUEUE} {first.candidate_name}",
            f"Po imporcie z Traffita w kolejce Cpro czeka: {line(first)}.",
            link,
        )
    listed = "; ".join(line(card) for card in cards[:MAX_LISTED])
    rest = len(cards) - MAX_LISTED
    more = f"; oraz {rest} kolejnych" if rest > 0 else ""
    return (
        f"{TITLE_CPRO_QUEUE} {len(cards)} kandydatów",
        f"Po imporcie z Traffita w kolejce Cpro czeka {len(cards)} kandydatów: "
        f"{listed}{more}.",
        link,
    )


async def remind(db: AsyncSession, *, now: Optional[datetime] = None) -> int:
    """Wysyła przypomnienie osobie od Cpro; zwraca liczbę kart w powiadomieniu
    (0 = nic nie wyszło). Nie commituje."""

    if not settings.TRAFFIT_CPRO_REMINDER_ENABLED:
        return 0
    moment = now or datetime.now(timezone.utc)
    if not is_business_day(moment, settings.BUSINESS_TZ):
        return 0
    sender_id = (await cpro_sender.effective_sender(db, moment)).user_id
    if sender_id is None:
        logger.info("cpro queue reminder: nobody is set as the Cpro sender")
        return 0
    cards = await waiting_cards(db, now=moment)
    if not cards:
        return 0
    title, message, link = build_notice(cards, tz=settings.BUSINESS_TZ)
    notif = await emit(
        db,
        user_id=sender_id,
        title=title,
        message=message,
        ntype=NotificationType.board_task_waiting,
        related_entity_type="user",
        related_entity_id=sender_id,
        link=link,
    )
    return len(cards) if notif is not None else 0


__all__ = ["MAX_LISTED", "WaitingCard", "build_notice", "remind", "waiting_cards"]
