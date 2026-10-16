"""Mapa technologii klienta — liczona przy odczycie z czterech źródeł.

1. **Karty technologiczne** (``tech_cards`` sfinalizowane) — co konsultanci
   widzą u klienta; mają datę i obszar.
2. **Rekrutacje klienta** — wymagania „musi” i „mile widziane” rekrutacji
   otwartych albo otwartych w ostatnich 12 miesiącach.
3. **Nasi konsultanci** — umiejętności osób z aktywnymi kontraktami u klienta
   (``candidate_skill_usage`` z CV oraz umiejętności profilu).
4. **Notatki o stacku** — istniejąca wiedza o kliencie
   (``client_knowledge``, kategoria ``tech_stack``); „Dodaj notatkę o stacku”
   na zakładce Technologie dopisuje właśnie taki wpis, więc notatki DL
   sprzed modułu też się liczą.

Mapa niczego nie zgaduje: technologia pojawia się tylko wtedy, gdy któreś
źródło wskazuje umiejętność ze słownika (nazwa albo alias). Nazwy spoza
słownika zostają na kartach jako tekst. Wynik trafia do krótkiego cache
(single-flight, ``care:techmap:<klient>:``) i jest unieważniany przy zapisie
karty, rozmowy i notatki.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_get, cache_invalidate, cache_set, cache_single_flight
from app.core.scheduling import DEFAULT_TZ, local_now
from app.models.candidate import Candidate
from app.models.candidate_skill_usage import CandidateSkillUsage
from app.models.client import Client
from app.models.client_knowledge import ClientKnowledge, KnowledgeCategory
from app.models.contract import Contract
from app.models.contract_care import (
    CareConversation,
    ClientArea,
    RedeployQueueItem,
    TechCard,
    TechVendor,
)
from app.models.job import Job, JobStatus
from app.services.care import records
from app.services.care import skills as care_skills
from app.services.care.access import LIVE_STATUSES
from app.services.skill_normalize import iter_skill_names

CACHE_TTL_SECONDS = 120
JOBS_WINDOW_DAYS = 365
SIGNALS_WINDOW_DAYS = 365
STALE_AFTER_DAYS = 548  # ok. 18 miesięcy (makieta „Technologie”)
SOURCES: tuple[str, ...] = ("cards", "jobs", "consultants", "notes")


def cache_key(client_id: int) -> str:
    # Dwukropek na końcu: unieważnienie klienta 1 nie może zdjąć klienta 12.
    return f"care:techmap:{client_id}:"


async def invalidate(client_ids: Iterable[int]) -> None:
    for client_id in set(client_ids):
        await cache_invalidate(cache_key(client_id))


def _local_date(moment: Optional[datetime]) -> Optional[date]:
    if moment is None:
        return None
    return moment.astimezone(ZoneInfo(DEFAULT_TZ)).date()


@dataclass
class _Tech:
    skill_id: int
    refs: dict[str, set[int]] = field(
        default_factory=lambda: {source: set() for source in SOURCES}
    )
    last_seen: Optional[date] = None
    areas: set[str] = field(default_factory=set)
    raw_forms: list[str] = field(default_factory=list)
    consultant_months: int = 0
    must_jobs: set[int] = field(default_factory=set)

    def seen(self, source: str, ref: int, when: Optional[date]) -> None:
        self.refs[source].add(ref)
        if when is not None and (self.last_seen is None or when > self.last_seen):
            self.last_seen = when


def note_pattern(dictionary: care_skills.SkillDictionary) -> Optional[re.Pattern[str]]:
    """Wzorzec nazw ze słownika do wyszukania w notatce.

    Krótkie słowa (poniżej 3 znaków, np. „go”, „r”) w polskim tekście częściej
    są zwykłym słowem niż technologią — pomijamy je, chyba że mają znak
    techniczny („c#”, „c++”).
    """

    keys = [
        key
        for key in dictionary.by_key
        if len(key) >= 3 or re.search(r"[^a-z0-9 ]", key)
    ]
    if not keys:
        return None
    alternation = "|".join(
        re.escape(key) for key in sorted(keys, key=len, reverse=True)
    )
    return re.compile(rf"(?<![\w#+.])(?:{alternation})(?![\w#+])", re.IGNORECASE)


def skills_in_note(
    text: str,
    dictionary: care_skills.SkillDictionary,
    pattern: Optional[re.Pattern[str]],
) -> set[int]:
    if not text or pattern is None:
        return set()
    found: set[int] = set()
    for match in pattern.finditer(text):
        skill_id = dictionary.resolve(match.group(0))
        if skill_id is not None:
            found.add(skill_id)
    return found


async def related_client_ids(db: AsyncSession, client_id: int) -> list[int]:
    """Klient i scaleni do niego duplikaci (historia zostaje na duplikacie)."""

    merged = (
        await db.scalars(
            select(Client.id).where(Client.merged_into_client_id == client_id)
        )
    ).all()
    return sorted({client_id, *merged})


async def compute(db: AsyncSession, client_id: int, *, today: date) -> dict[str, Any]:
    client_ids = await related_client_ids(db, client_id)
    dictionary = await care_skills.load_dictionary(db)
    techs: dict[int, _Tech] = {}

    def tech(skill_id: int) -> _Tech:
        if skill_id not in techs:
            techs[skill_id] = _Tech(skill_id=skill_id)
        return techs[skill_id]

    # 1. Karty technologiczne.
    cards = (
        await db.scalars(
            select(TechCard)
            .where(TechCard.client_id.in_(client_ids), TechCard.is_draft.is_(False))
            .order_by(TechCard.interview_on.desc(), TechCard.id.desc())
        )
    ).all()
    card_skills, card_vendors = await records.card_relations(
        db, [card.id for card in cards]
    )
    areas = (
        await db.scalars(
            select(ClientArea)
            .where(ClientArea.client_id.in_(client_ids))
            .order_by(ClientArea.name)
        )
    ).all()
    area_names = {area.id: area.name for area in areas}
    area_cards: dict[int, int] = {}
    vendor_cards: dict[int, int] = {}
    for card in cards:
        area_name = area_names.get(card.client_area_id) if card.client_area_id else None
        if card.client_area_id:
            area_cards[card.client_area_id] = area_cards.get(card.client_area_id, 0) + 1
        for skill_id in card_skills.get(card.id, []):
            entry = tech(skill_id)
            entry.seen("cards", card.id, card.interview_on)
            if area_name:
                entry.areas.add(area_name)
        for vendor_id in card_vendors.get(card.id, []):
            vendor_cards[vendor_id] = vendor_cards.get(vendor_id, 0) + 1

    # 2. Rekrutacje klienta.
    opened = func.coalesce(Job.opened_at, Job.created_at)
    jobs = (
        await db.execute(
            select(
                Job.id, Job.title, Job.status, Job.must_skills, Job.nice_skills, opened
            )
            .where(
                Job.client_id.in_(client_ids),
                or_(
                    Job.status != JobStatus.closed,
                    opened >= local_now() - timedelta(days=JOBS_WINDOW_DAYS),
                ),
            )
            .order_by(opened.desc())
        )
    ).all()
    open_jobs = []
    for job_id, title, job_status, must, nice, opened_at in jobs:
        when = _local_date(opened_at)
        if job_status != JobStatus.closed:
            open_jobs.append({"id": job_id, "title": title, "opened_on": when})
        for is_must, raw in ((True, must), (False, nice)):
            for name in iter_skill_names(raw):
                skill_id = dictionary.resolve(name)
                if skill_id is None:
                    continue
                entry = tech(skill_id)
                entry.seen("jobs", job_id, when)
                entry.raw_forms.append(name)
                if is_must:
                    entry.must_jobs.add(job_id)

    # 3. Nasi konsultanci (aktywne kontrakty).
    consultants = (
        await db.execute(
            select(Contract.id, Contract.candidate_id).where(
                Contract.client_id.in_(client_ids),
                Contract.status.in_(LIVE_STATUSES),
                Contract.voided_at.is_(None),
                Contract.candidate_id.is_not(None),
            )
        )
    ).all()
    candidate_ids = sorted({candidate_id for _cid, candidate_id in consultants})
    if candidate_ids:
        for candidate_id, canonical, raw, months in (
            await db.execute(
                select(
                    CandidateSkillUsage.candidate_id,
                    CandidateSkillUsage.skill_canonical,
                    CandidateSkillUsage.skill_raw,
                    CandidateSkillUsage.months,
                ).where(CandidateSkillUsage.candidate_id.in_(candidate_ids))
            )
        ).all():
            skill_id = dictionary.resolve(canonical) or dictionary.resolve(raw)
            if skill_id is None:
                continue
            entry = tech(skill_id)
            if candidate_id not in entry.refs["consultants"]:
                entry.consultant_months += int(months or 0)
            entry.seen("consultants", candidate_id, None)
            entry.raw_forms.append(raw)
        for candidate_id, profile_skills in (
            await db.execute(
                select(Candidate.id, Candidate.skills).where(
                    Candidate.id.in_(candidate_ids)
                )
            )
        ).all():
            for name in iter_skill_names(profile_skills):
                skill_id = dictionary.resolve(name)
                if skill_id is not None:
                    tech(skill_id).seen("consultants", candidate_id, None)
                    tech(skill_id).raw_forms.append(name)

    # 4. Notatki o stacku.
    notes = (
        await db.execute(
            select(
                ClientKnowledge.id, ClientKnowledge.content, ClientKnowledge.created_at
            )
            .where(
                ClientKnowledge.client_id.in_(client_ids),
                ClientKnowledge.category == KnowledgeCategory.tech_stack,
            )
            .order_by(ClientKnowledge.created_at.desc())
        )
    ).all()
    pattern = note_pattern(dictionary)
    for note_id, content, created_at in notes:
        for skill_id in skills_in_note(content or "", dictionary, pattern):
            tech(skill_id).seen("notes", note_id, _local_date(created_at))

    stale_before = today - timedelta(days=STALE_AFTER_DAYS)
    technologies = []
    for entry in techs.values():
        counts = {source: len(entry.refs[source]) for source in SOURCES}
        technologies.append(
            {
                "skill_id": entry.skill_id,
                "name": care_skills.display_name(
                    dictionary.names.get(entry.skill_id, ""), entry.raw_forms
                ),
                "category": dictionary.categories.get(entry.skill_id),
                "counts": counts,
                "source_count": sum(1 for value in counts.values() if value),
                "must_jobs": len(entry.must_jobs),
                "consultant_months": entry.consultant_months,
                "areas": sorted(entry.areas),
                "last_seen": entry.last_seen,
                "stale": counts["consultants"] == 0
                and (entry.last_seen is None or entry.last_seen < stale_before),
            }
        )
    technologies.sort(
        key=lambda item: (
            item["stale"],
            -item["source_count"],
            -sum(item["counts"].values()),
            item["name"].lower(),
        )
    )

    vendors = []
    if vendor_cards:
        names = dict(
            (
                await db.execute(
                    select(TechVendor.id, TechVendor.name).where(
                        TechVendor.id.in_(sorted(vendor_cards))
                    )
                )
            ).all()
        )
        vendors = sorted(
            (
                {"id": vid, "name": names.get(vid, ""), "cards": count}
                for vid, count in vendor_cards.items()
            ),
            key=lambda item: (-item["cards"], item["name"].lower()),
        )

    signals_since = today - timedelta(days=SIGNALS_WINDOW_DAYS)
    signals: list[dict[str, Any]] = []
    for card in cards:
        if card.hiring is True and card.interview_on >= signals_since:
            signals.append(
                {
                    "kind": "tech_card",
                    "id": card.id,
                    "contract_id": card.contract_id,
                    "on": card.interview_on,
                    "roles": list(card.hiring_roles or []),
                    "source": card.hiring_source,
                    "area": area_names.get(card.client_area_id)
                    if card.client_area_id
                    else None,
                    "note": None,
                    "sales_status": card.sales_status,
                }
            )
    for conv_id, contract_id, occurred_on, note in (
        await db.execute(
            select(
                CareConversation.id,
                CareConversation.contract_id,
                CareConversation.occurred_on,
                CareConversation.client_hiring_note,
            )
            .join(Contract, Contract.id == CareConversation.contract_id)
            .where(
                Contract.client_id.in_(client_ids),
                CareConversation.client_hiring.is_(True),
                CareConversation.occurred_on >= signals_since,
            )
        )
    ).all():
        signals.append(
            {
                "kind": "conversation",
                "id": conv_id,
                "contract_id": contract_id,
                "on": occurred_on,
                "roles": [],
                "source": None,
                "area": None,
                "note": note,
                "sales_status": None,
            }
        )
    signals.sort(key=lambda item: (item["on"], item["id"]), reverse=True)

    redeploy_active = await db.scalar(
        select(func.count())
        .select_from(RedeployQueueItem)
        .join(Contract, Contract.id == RedeployQueueItem.contract_id)
        .where(
            Contract.client_id.in_(client_ids),
            RedeployQueueItem.status.in_(("open", "in_progress")),
        )
    )

    return {
        "client_id": client_id,
        "technologies": technologies,
        "areas": [
            {"id": area.id, "name": area.name, "cards": area_cards.get(area.id, 0)}
            for area in areas
        ],
        "vendors": vendors,
        "signals": signals[:20],
        "open_jobs": open_jobs[:10],
        "open_jobs_count": len(open_jobs),
        "consultants_count": len({cid for cid, _ in consultants}),
        "cards_count": len(cards),
        "notes": [
            {
                "id": note_id,
                "content": (content or "")[:400],
                "created_on": _local_date(created_at),
            }
            for note_id, content, created_at in notes[:5]
        ],
        "notes_count": len(notes),
        "redeploy_active": int(redeploy_active or 0),
        "generated_at": local_now().isoformat(),
    }


async def client_tech_map(
    db: AsyncSession, client_id: int, *, today: date
) -> dict[str, Any]:
    """Mapa z krótkiego cache; liczy jeden wykonawca na klucz."""

    key = cache_key(client_id)
    async with cache_single_flight(key, db=db):
        cached = await cache_get(key)
        if cached is not None:
            return cached
        result = await compute(db, client_id, today=today)
        await cache_set(key, result, ttl_seconds=CACHE_TTL_SECONDS, jitter_seconds=15)
        return result
