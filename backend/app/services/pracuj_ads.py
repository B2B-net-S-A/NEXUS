"""Ogłoszenia ze strefy Pracuj.pl ↔ rekrutacje (decyzja Artura 23.11.2026, wariant A).

Powód i tabele: ``app/services/pracuj_ad_schema.py``. Przebieg:

1. Scraper strefy na Macu przy każdym biegu oddaje listę opublikowanych
   ogłoszeń (``upsert_ads``) i każdą aplikację z numerem ogłoszenia
   (``portal_application`` → ``record_application``).
2. Delivery Lead wybiera w oknie „Ogłoszenie” (karta Pracuj.pl) albo
   w kolejce braków, które ogłoszenie należy do rekrutacji (``pair``).
   Tytuł tylko podpowiada (``suggests``): trzy aktywne ogłoszenia miały
   22.11 ten sam tytuł „Tester Manualny (k/m/x)”, więc nigdy nie łączymy
   po tytule sami.
3. Połączenie dociąga zaległe aplikacje z dziennika do „Nowi” tą samą drogą
   co nowe (``portal_application.place_application``: bramki rekrutera,
   źródło z rekrutacją, kolejka warunków — ta pomija aplikacje starsze niż
   3 dni, więc dociąganie nie wysyła maili).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job, JobStatus
from app.models.pracuj_ad import PracujAd, PracujAdApplication
from app.models.user import User

logger = logging.getLogger(__name__)

PORTAL = "pracuj"
#: Ogłoszenie jest „na portalu”, gdy ostatni bieg importu je widział. Bieg
#: idzie raz dziennie, bywa przesunięty o kilka godzin i pomija weekendowe
#: przestoje Maca, stąd zapas.
LIVE_SLACK = timedelta(days=3)
#: Dociąganie zaległych — górna granica na jedno połączenie (22.11 najwięcej
#: było 457 aplikacji na jeden tytuł w 30 dni).
BACKFILL_LIMIT = 500
OPTIONS_LIMIT = 120
SUGGESTIONS_PER_AD = 3

_STREFA_ID_RE = re.compile(r"^[0-9]{3,32}$")
_GENDER_RE = re.compile(r"\(\s*[kmfxn](?:\s*/\s*[kmfxn])*\s*\)", re.IGNORECASE)
_REF_RE = re.compile(r"\((?:zob-\d+|ritm\d+|[a-z]{0,6}[\d.#/ -]{3,})\)", re.IGNORECASE)
_PREFIX_RE = re.compile(r"^[^:()]{2,30}:\s+")
_INVISIBLE_RE = re.compile(r"[​-‏⁠﻿­]")
_SHORT_TAIL_RE = re.compile(r"^(?:x\s?\d+|\d+\s?x|\d+)$")


def valid_strefa_id(value: str) -> bool:
    return bool(_STREFA_ID_RE.match(value or ""))


def normalize_title(title: Optional[str]) -> str:
    """Tytuł do porównań: bez „(k/m/x)”, numeru zlecenia i prefiksu klienta."""
    text = _INVISIBLE_RE.sub("", title or "")
    text = _GENDER_RE.sub(" ", text)
    text = _REF_RE.sub(" ", text)
    text = _PREFIX_RE.sub("", text.strip())
    return re.sub(r"\s+", " ", text).strip(" -–—|").lower()


def suggests(ad_title: str, job_title: str) -> bool:
    """Czy tytuł rekrutacji podpowiada to ogłoszenie (tylko podpowiedź dla DL-a)."""
    ad, job = normalize_title(ad_title), normalize_title(job_title)
    if not ad or not job:
        return False
    if ad == job:
        return True
    longer, shorter = (ad, job) if len(ad) > len(job) else (job, ad)
    if not longer.startswith(shorter + " "):
        return False
    return bool(_SHORT_TAIL_RE.match(longer[len(shorter) + 1 :]))


@dataclass(frozen=True)
class AdIn:
    strefa_id: str
    title: str
    applications: int = 0


async def upsert_ads(
    db: AsyncSession, ads: Iterable[AdIn], *, seen_at: Optional[datetime] = None
) -> int:
    """Lista ogłoszeń z biegu importu. Połączenia z rekrutacją nie rusza."""
    now = seen_at or datetime.now(timezone.utc)
    rows = {ad.strefa_id: ad for ad in ads if valid_strefa_id(ad.strefa_id)}
    for ad in rows.values():
        stmt = pg_insert(PracujAd).values(
            strefa_id=ad.strefa_id,
            title=ad.title.strip()[:255],
            applications=max(0, int(ad.applications)),
            first_seen_at=now,
            last_seen_at=now,
        )
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=[PracujAd.strefa_id],
                set_={
                    "title": stmt.excluded.title,
                    "applications": stmt.excluded.applications,
                    "last_seen_at": stmt.excluded.last_seen_at,
                },
            )
        )
    return len(rows)


async def record_application(
    db: AsyncSession,
    *,
    strefa_id: str,
    candidate_id: int,
    applied_at: Optional[datetime],
    ad_title: Optional[str] = None,
) -> None:
    """Kto aplikował na które ogłoszenie — także zanim ma rekrutację."""
    if ad_title:
        # Aplikacja może przyjść przed listą ogłoszeń (inny bieg, ponowienie).
        await db.execute(
            pg_insert(PracujAd)
            .values(strefa_id=strefa_id, title=ad_title.strip()[:255])
            .on_conflict_do_nothing(index_elements=[PracujAd.strefa_id])
        )
    await db.execute(
        pg_insert(PracujAdApplication)
        .values(strefa_id=strefa_id, candidate_id=candidate_id, applied_at=applied_at)
        .on_conflict_do_nothing(constraint="uq_pracuj_ad_applications")
    )


async def job_for_ad(db: AsyncSession, strefa_id: str) -> Optional[int]:
    job_id = await db.scalar(
        select(PracujAd.job_id).where(
            PracujAd.strefa_id == strefa_id, PracujAd.internal_at.is_(None)
        )
    )
    return int(job_id) if job_id is not None else None


async def _live_since(db: AsyncSession) -> Optional[datetime]:
    last = await db.scalar(select(func.max(PracujAd.last_seen_at)))
    return last - LIVE_SLACK if last is not None else None


async def _application_counts(
    db: AsyncSession, strefa_ids: list[str]
) -> dict[str, int]:
    if not strefa_ids:
        return {}
    rows = await db.execute(
        select(PracujAdApplication.strefa_id, func.count())
        .where(PracujAdApplication.strefa_id.in_(strefa_ids))
        .group_by(PracujAdApplication.strefa_id)
    )
    return {sid: int(n) for sid, n in rows.all()}


def _ad_dict(ad: PracujAd, logged: int, *, live: bool, suggested: bool = False) -> dict:
    return {
        "strefa_id": ad.strefa_id,
        "title": ad.title,
        "applications": ad.applications,
        "logged_applications": logged,
        "first_seen_at": ad.first_seen_at,
        "last_seen_at": ad.last_seen_at,
        "live": live,
        "suggested": suggested,
        "paired_at": ad.paired_at,
    }


async def panel_for_job(db: AsyncSession, job: Job) -> dict:
    """Karta Pracuj.pl: połączone ogłoszenia i lista do wyboru (podpowiedzi pierwsze)."""
    since = await _live_since(db)
    paired = list(
        (
            await db.scalars(
                select(PracujAd)
                .where(PracujAd.job_id == job.id)
                .order_by(PracujAd.first_seen_at.desc())
            )
        ).all()
    )
    options: list[PracujAd] = []
    if since is not None:
        options = list(
            (
                await db.scalars(
                    select(PracujAd)
                    .where(
                        PracujAd.job_id.is_(None),
                        PracujAd.internal_at.is_(None),
                        PracujAd.last_seen_at >= since,
                    )
                    .order_by(PracujAd.first_seen_at.desc())
                    .limit(OPTIONS_LIMIT)
                )
            ).all()
        )
    counts = await _application_counts(db, [a.strefa_id for a in paired + options])
    marked = [
        _ad_dict(
            a,
            counts.get(a.strefa_id, 0),
            live=since is not None and a.last_seen_at >= since,
            suggested=suggests(a.title, job.title),
        )
        for a in options
    ]
    marked.sort(key=lambda d: (not d["suggested"],))
    return {
        "paired": [
            _ad_dict(
                a,
                counts.get(a.strefa_id, 0),
                live=since is not None and a.last_seen_at >= since,
            )
            for a in paired
        ],
        "options": marked,
        "last_import_at": (since + LIVE_SLACK) if since is not None else None,
    }


class AdNotFound(Exception):
    pass


class AdTaken(Exception):
    def __init__(self, job_id: int, job_title: str) -> None:
        super().__init__(job_title)
        self.job_id = job_id
        self.job_title = job_title


@dataclass
class PairResult:
    strefa_id: str
    added: int = 0
    already: int = 0
    skipped: int = 0
    job_not_open: bool = False
    added_candidate_ids: list[int] = field(default_factory=list)


async def pair(db: AsyncSession, *, job: Job, strefa_id: str, user: User) -> PairResult:
    """Połącz ogłoszenie z rekrutacją i dociągnij zaległe aplikacje. Bez commita."""
    from app.services import portal_application  # noqa: PLC0415

    ad = await db.get(PracujAd, strefa_id, with_for_update=True)
    if ad is None:
        raise AdNotFound(strefa_id)
    if ad.job_id is not None and ad.job_id != job.id:
        other = await db.get(Job, ad.job_id)
        raise AdTaken(ad.job_id, other.title if other is not None else "")
    if ad.job_id != job.id:
        ad.job_id = job.id
        ad.paired_by = user.id
        ad.paired_at = datetime.now(timezone.utc)
    ad.internal_at = None
    ad.internal_by = None
    await db.flush()

    result = PairResult(strefa_id=strefa_id)
    rows = (
        await db.execute(
            select(PracujAdApplication.candidate_id, PracujAdApplication.applied_at)
            .where(PracujAdApplication.strefa_id == strefa_id)
            .order_by(PracujAdApplication.applied_at.asc().nulls_last())
            .limit(BACKFILL_LIMIT)
        )
    ).all()
    for candidate_id, applied_at in rows:
        placed = await portal_application.place_application(
            db,
            candidate_id=candidate_id,
            portal=PORTAL,
            ad_id=strefa_id,
            ad_title=ad.title,
            applied_at=applied_at,
        )
        if placed.outcome == "added":
            result.added += 1
            result.added_candidate_ids.append(candidate_id)
        elif placed.outcome == "already_in_job":
            result.already += 1
        elif placed.outcome == "job_not_open":
            result.job_not_open = True
        else:
            result.skipped += 1
    return result


async def unpair(db: AsyncSession, *, job: Job, strefa_id: str) -> bool:
    """Odłącz ogłoszenie. Karty w rekrutacji zostają — to już decyzje ludzi."""
    ad = await db.get(PracujAd, strefa_id)
    if ad is None or ad.job_id != job.id:
        return False
    ad.job_id = None
    ad.paired_by = None
    ad.paired_at = None
    await db.flush()
    return True


async def mark_internal(
    db: AsyncSession, *, strefa_id: str, user: User, internal: bool
) -> bool:
    """„Rekrutacja wewnętrzna” — ogłoszenie znika z kolejki braków."""
    ad = await db.get(PracujAd, strefa_id)
    if ad is None:
        return False
    if internal:
        ad.internal_at = datetime.now(timezone.utc)
        ad.internal_by = user.id
        ad.job_id = None
    else:
        ad.internal_at = None
        ad.internal_by = None
    await db.flush()
    return True


async def unpaired_queue(db: AsyncSession) -> dict:
    """Ogłoszenia na Pracuj.pl bez rekrutacji, z podpowiedziami otwartych rekrutacji."""
    since = await _live_since(db)
    if since is None:
        return {"items": [], "last_import_at": None}
    ads = list(
        (
            await db.scalars(
                select(PracujAd)
                .where(
                    PracujAd.job_id.is_(None),
                    PracujAd.internal_at.is_(None),
                    PracujAd.last_seen_at >= since,
                )
                .order_by(PracujAd.first_seen_at.desc())
            )
        ).all()
    )
    counts = await _application_counts(db, [a.strefa_id for a in ads])
    open_jobs = (
        await db.execute(
            select(Job.id, Job.title, Job.delivery_lead_id, User.name)
            .outerjoin(User, User.id == Job.delivery_lead_id)
            .where(Job.status == JobStatus.published)
        )
    ).all()
    items = []
    for ad in ads:
        hits = [
            {"job_id": j.id, "title": j.title, "delivery_lead_name": j.name}
            for j in open_jobs
            if suggests(ad.title, j.title)
        ]
        items.append(
            {
                **_ad_dict(ad, counts.get(ad.strefa_id, 0), live=True),
                "suggestions": hits[:SUGGESTIONS_PER_AD],
                "more_suggestions": max(0, len(hits) - SUGGESTIONS_PER_AD),
            }
        )
    items.sort(key=lambda i: -(i["logged_applications"] or i["applications"]))
    return {"items": items, "last_import_at": since + LIVE_SLACK}


async def notify_backfill(db: AsyncSession, *, job_id: int, added: int) -> None:
    """Jeden dzwonek zbiorczy dla prowadzącego zamiast N pojedynczych. Nie rzuca."""
    if added <= 0:
        return
    try:
        from app.models.notification import NotificationType  # noqa: PLC0415
        from app.services.hr.time_suggest import plural  # noqa: PLC0415
        from app.services.job_previous_recruiters import working_owner_id  # noqa: PLC0415
        from app.services.notification_triggers import emit  # noqa: PLC0415

        job = await db.get(Job, job_id)
        if job is None:
            return
        user_id = await working_owner_id(db, job)
        if user_id is None:
            return
        who = plural(added, "osoba czeka", "osoby czekają", "osób czeka")
        await emit(
            db,
            user_id=user_id,
            title="Aplikacje z Pracuj.pl w rekrutacji",
            message=f"{added} {who} w „Nowi” w „{job.title}” — aplikowali na ogłoszenie na Pracuj.pl.",
            ntype=NotificationType.new_application,
            related_entity_type="job",
            related_entity_id=job.id,
            link=f"/jobs/{job.id}",
        )
        await db.commit()
    except Exception:  # noqa: BLE001 - dzwonek nie może cofnąć kart
        logger.exception("[pracuj-ads] notify failed job=%s", job_id)
