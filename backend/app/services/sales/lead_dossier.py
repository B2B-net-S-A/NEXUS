"""Teczka leada (decyzja Artura 13.11.2026, krok 4 planu botów).

Nowy lead z kartą firmy (z dowolnego źródła: sygnały, „Warto wrócić”, „Nowe
centra IT”, import, wpis ręczny) sam zamawia dla tej firmy trzy biegi bota:
Dane firm (``enrich``), Kontakty ze źródeł publicznych (``people``) i Research
(``briefing``, punkty na pierwszą rozmowę). Zamawia pętla ``tasks/sales_signals.py``,
nie żądanie tworzenia leada, więc błąd bota nie blokuje leada.

* **Jedna teczka na firmę, nie na lead:** firma z biegiem danego rodzaju z ostatnich
  7 dni nie wraca (nieudany start webhooka liczy się godzinę, potem ponowienie),
  wynik do przeglądu (``new``/``partial``) i punkty młodsze niż 7 dni też blokują.
* **Bez zamówienia:** lead bez karty, karta w archiwum, „Nie kontaktować”, nasza
  firma i klient NEXUSA (``signal_targets.eligible_companies``).
* **Kolejność:** Kontakty i Research czekają, aż bot odeśle Dane firm tej karty
  (domena z ``enrich`` daje botowi lepszy trop); karta z domeną nie czeka.
* **Limit:** jeden bieg pętli na rodzaj na godzinę, najwyżej ``BATCH`` firm.
* Tylko przy ``SALES_BOT_TASKS_ENABLED``. Do bota idą tylko nazwa i domena firmy
  (``signals.start_run``).

Odczyt (``dossiers``) liczy teczkę z danych NEXUSA jednym zapytaniem dla całej
listy leadów: karta, kontakty, opiekun i punkty z ``sales_company_briefings``.
→ docs/claude/sprzedaz/sygnaly-grok-bot.md, sekcja „Teczka leada”.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Iterable, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field
from sqlalchemy import and_, distinct, func, literal, or_, select, union_all
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import String

from app.models.sales import (
    SalesBotResult,
    SalesCompany,
    SalesCompanyBriefing,
    SalesCompanyContact,
    SalesContact,
    SalesLead,
    SalesSignalRun,
)
from app.models.user import User
from app.services.sales import bot_tasks, signals
from app.services.sales import signal_targets as targets
from app.services.sales.research_file import fold, level_from_title

logger = logging.getLogger(__name__)

#: Kolejność jak w planie botów: Dane firm → Kontakty → Research.
KINDS: tuple[str, ...] = ("enrich", "people", "briefing")
#: Lead z ostatnich 7 dni jest „nowy” dla teczki.
LEAD_WITHIN = timedelta(days=7)
#: Ta sama firma i rodzaj nie wracają do bota częściej niż raz na 7 dni.
REPEAT_AFTER = timedelta(days=7)
RETRY_FAILED_AFTER = timedelta(hours=1)
LOOP_EVERY = timedelta(hours=1)
BATCH = 10
#: Do tylu stanowisk w wierszu „Decydenci”.
MAX_DECISION_MAKERS = 4
OPEN_RESULT = ("new", "partial")
#: Tryby biegu ``briefing``, które zapisują punkty do rozmowy (haczyk nie).
POINT_MODES = ("first_call", "ongoing", "meeting_prep")


# ── Zamówienie ──────────────────────────────────────────────────────────────


async def lead_company_ids(
    db: AsyncSession, *, now: datetime, company_ids: Optional[Iterable[int]] = None
) -> list[int]:
    """Firmy nowych leadów (najświeższy lead najpierw), tylko te, o które wolno pytać."""

    query = (
        select(SalesLead.company_id)
        .where(
            SalesLead.company_id.is_not(None),
            SalesLead.created_at >= now - LEAD_WITHIN,
            SalesLead.status.in_(("new", "contacted")),
        )
        .group_by(SalesLead.company_id)
        .order_by(func.max(SalesLead.created_at).desc(), SalesLead.company_id.desc())
    )
    if company_ids is not None:
        query = query.where(SalesLead.company_id.in_(list(company_ids)))
    ordered = [int(cid) for cid in (await db.execute(query)).scalars()]
    if not ordered:
        return []
    allowed = await targets.eligible_companies(db, ordered)
    return [cid for cid in ordered if cid in allowed]


def _counted_run(now: datetime):
    """Bieg blokuje firmę 7 dni; nieudany start webhooka tylko godzinę."""

    return and_(
        SalesSignalRun.started_at >= now - REPEAT_AFTER,
        or_(
            SalesSignalRun.status != "failed",
            SalesSignalRun.started_at >= now - RETRY_FAILED_AFTER,
        ),
    )


def _not_cognism():
    return SalesSignalRun.request["source"].astext.is_distinct_from("cognism")


async def recently_ordered(db: AsyncSession, kind: str, *, now: datetime) -> set[int]:
    """Firmy z biegiem rodzaju z ostatnich 7 dni (w ``briefing`` tylko tryby z punktami)."""

    filters = [SalesSignalRun.kind == kind, _counted_run(now)]
    if kind == "people":
        filters.append(_not_cognism())
    rows = await db.execute(
        select(SalesSignalRun.company_ids, SalesSignalRun.modes).where(*filters)
    )
    sent: set[int] = set()
    for ids, modes in rows:
        for raw in ids or []:
            cid = int(raw)
            if kind == "briefing" and (modes or {}).get(str(cid)) not in POINT_MODES:
                continue
            sent.add(cid)
    return sent


async def _blocked(
    db: AsyncSession, kind: str, ids: list[int], *, now: datetime
) -> set[int]:
    """Firmy, których ten rodzaj teraz nie zamawia (poza biegami z 7 dni)."""

    if kind in ("enrich", "people"):
        rows = await db.execute(
            select(SalesBotResult.company_id).where(
                SalesBotResult.kind == kind,
                SalesBotResult.company_id.in_(ids),
                SalesBotResult.status.in_(OPEN_RESULT),
            )
        )
        return {int(cid) for cid in rows.scalars()}
    rows = await db.execute(
        select(SalesCompanyBriefing.company_id).where(
            SalesCompanyBriefing.company_id.in_(ids),
            SalesCompanyBriefing.generated_at >= now - REPEAT_AFTER,
        )
    )
    # Każdy bieg ``briefing`` z 24 godzin (też haczyk): ta sama reguła co punkty.
    return {int(cid) for cid in rows.scalars()} | await targets.recently_sent(
        db, now=now
    )


async def _waiting_for_enrich(
    db: AsyncSession, ids: list[int], *, now: datetime
) -> set[int]:
    """Karty bez domeny, dla których bieg Danych firm jeszcze trwa."""

    rows = await db.execute(
        select(SalesSignalRun.company_ids).where(
            SalesSignalRun.kind == "enrich",
            SalesSignalRun.status == "started",
            SalesSignalRun.token_expires_at > now,
        )
    )
    running = {int(cid) for company_ids in rows.scalars() for cid in company_ids}
    if not running & set(ids):
        return set()
    with_domain = await db.execute(
        select(SalesCompany.id).where(
            SalesCompany.id.in_(sorted(running & set(ids))),
            SalesCompany.domain.is_not(None),
        )
    )
    return (running & set(ids)) - set(with_domain.scalars())


async def _loop_ran(db: AsyncSession, kind: str, *, now: datetime) -> bool:
    """Bieg pętli tego rodzaju w ostatniej godzinie (przycisk na karcie się nie liczy)."""

    filters = [
        SalesSignalRun.kind == kind,
        SalesSignalRun.requested_by_user_id.is_(None),
        SalesSignalRun.started_at > now - LOOP_EVERY,
    ]
    if kind == "people":
        filters.append(_not_cognism())
    return bool(await db.scalar(select(func.count()).where(*filters)))


async def order(
    db: AsyncSession, *, now: datetime, company_ids: Optional[Iterable[int]] = None
) -> dict[str, int]:
    """Zamów teczki dla firm nowych leadów; zwraca liczbę firm wysłanych per rodzaj."""

    done = {kind: 0 for kind in KINDS}
    if not bot_tasks.enabled():
        return done
    candidates = await lead_company_ids(db, now=now, company_ids=company_ids)
    if not candidates:
        return done
    for kind in KINDS:
        if await _loop_ran(db, kind, now=now):
            continue
        if kind == "people":
            # Ta sama blokada co przycisk „Znajdź decydentów”: sprawdzenie i zapis
            # biegu widzą się nawzajem (zwalnia ją commit w ``start_run``).
            await targets.lock_people_starts(db)
        skip = await recently_ordered(db, kind, now=now)
        skip |= await _blocked(db, kind, candidates, now=now)
        if kind != "enrich":
            skip |= await _waiting_for_enrich(db, candidates, now=now)
        ids = [cid for cid in candidates if cid not in skip][:BATCH]
        if not ids:
            await db.rollback()
            continue
        modes = (
            await targets.modes_for(db, ids, now=now) if kind == "briefing" else None
        )
        try:
            run = await signals.start_run(db, kind, ids, now=now, modes=modes)
        except Exception:  # noqa: BLE001 - błąd jednego rodzaju nie zatrzymuje reszty
            await db.rollback()
            logger.exception(
                "lead_dossier kind=%s firms=%d start failed", kind, len(ids)
            )
            continue
        if run is not None and run.status in ("started", "received"):
            done[kind] = len(ids)
    return done


# ── Odczyt ──────────────────────────────────────────────────────────────────


class LeadDossier(BaseModel):
    """Co NEXUS wie o firmie leada, zanim handlowiec go otworzy."""

    company_id: int
    industry: Optional[str] = None
    city: Optional[str] = None
    nip: Optional[str] = None
    #: Domena karty albo host strony www (bez ``www.``).
    website: Optional[str] = None
    #: Osoby na karcie (kontakty poza archiwum) i ile z nich ma e-mail.
    known: int = 0
    known_with_email: int = 0
    owner: Optional[str] = None
    #: Do 4 stanowisk decyzyjnych (zarząd, VP, Head, Director) z kontaktów karty.
    decision_makers: list[str] = Field(default_factory=list)
    #: Punkty do rozmowy z ``sales_company_briefings``.
    points: int = 0
    points_at: Optional[datetime] = None

    def has_content(self) -> bool:
        return bool(
            self.industry
            or self.city
            or self.nip
            or self.website
            or self.known
            or self.owner
            or self.decision_makers
            or self.points
        )


def _host(domain: Optional[str], website_url: Optional[str]) -> Optional[str]:
    value = (domain or "").strip()
    if not value and website_url:
        value = urlparse(website_url.strip()).hostname or ""
    value = value.lower()
    return (value[4:] if value.startswith("www.") else value) or None


def decision_makers(titles: Iterable[Optional[str]]) -> list[str]:
    """Stanowiska poziomu 1–2 (zarząd i VP, potem Head i Director), bez powtórzeń."""

    seen: set[str] = set()
    ranked: list[tuple[int, int, str]] = []
    for index, raw in enumerate(titles):
        title = " ".join((raw or "").split())
        key = fold(title)
        if not title or key in seen:
            continue
        level = level_from_title(title)
        if level > 2:
            continue
        seen.add(key)
        ranked.append((level, index, title))
    return [title for _, _, title in sorted(ranked)[:MAX_DECISION_MAKERS]]


def _members(ids: list[int]):
    """Osoby karty: firma główna kontaktu albo bieżące powiązanie z firmą."""

    return union_all(
        select(
            SalesContact.company_id.label("company_id"),
            SalesContact.id.label("contact_id"),
            literal(None, String).label("title"),
        ).where(SalesContact.company_id.in_(ids)),
        select(
            SalesCompanyContact.company_id,
            SalesCompanyContact.contact_id,
            SalesCompanyContact.title,
        ).where(
            SalesCompanyContact.company_id.in_(ids),
            SalesCompanyContact.is_current.is_(True),
        ),
    ).subquery()


async def dossiers(
    db: AsyncSession, company_ids: Iterable[int]
) -> dict[int, LeadDossier]:
    """Teczki firm jednym zapytaniem; firma bez żadnych danych nie ma teczki."""

    ids = sorted({int(cid) for cid in company_ids if cid})
    if not ids:
        return {}
    members = _members(ids)
    title = func.coalesce(members.c.title, SalesContact.title)
    reachable = SalesContact.do_not_contact_at.is_(None)
    people = (
        select(
            members.c.company_id,
            func.count(distinct(SalesContact.id)).label("known"),
            func.count(distinct(SalesContact.id))
            .filter(reachable, func.coalesce(SalesContact.email, "") != "")
            .label("with_email"),
            func.array_agg(
                aggregate_order_by(
                    title, SalesContact.is_executive.desc(), SalesContact.id
                )
            )
            .filter(reachable, title.is_not(None))
            .label("titles"),
        )
        .join(SalesContact, SalesContact.id == members.c.contact_id)
        .where(SalesContact.archived_at.is_(None))
        .group_by(members.c.company_id)
        .subquery()
    )
    rows = await db.execute(
        select(
            SalesCompany.id,
            SalesCompany.industry,
            SalesCompany.hq_city,
            SalesCompany.nip,
            SalesCompany.domain,
            SalesCompany.website_url,
            User.name,
            people.c.known,
            people.c.with_email,
            people.c.titles,
            func.jsonb_array_length(SalesCompanyBriefing.points),
            SalesCompanyBriefing.generated_at,
        )
        .outerjoin(User, User.id == SalesCompany.owner_user_id)
        .outerjoin(people, people.c.company_id == SalesCompany.id)
        .outerjoin(
            SalesCompanyBriefing, SalesCompanyBriefing.company_id == SalesCompany.id
        )
        .where(SalesCompany.id.in_(ids))
    )
    out: dict[int, LeadDossier] = {}
    for (
        cid,
        industry,
        city,
        nip,
        domain,
        website_url,
        owner,
        known,
        with_email,
        titles,
        points,
        points_at,
    ) in rows:
        dossier = LeadDossier(
            company_id=cid,
            industry=(industry or "").strip() or None,
            city=(city or "").strip() or None,
            nip=(nip or "").strip() or None,
            website=_host(domain, website_url),
            known=int(known or 0),
            known_with_email=int(with_email or 0),
            owner=(owner or "").strip() or None,
            decision_makers=decision_makers(titles or []),
            points=int(points or 0),
            points_at=points_at if points else None,
        )
        if dossier.has_content():
            out[cid] = dossier
    return out
