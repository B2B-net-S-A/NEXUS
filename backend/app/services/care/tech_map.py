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

**Działy (D16, etap 2, 17.10.2026)** — wiersze mapy po działach klienta
(``client_areas`` — ten sam słownik co „Struktura u klienta”). Do działu
trafia karta z tym obszarem, rekrutacja, której hiring manager jest osobą
z tego działu, i nasz konsultant, którego menedżer u klienta jest z tego
działu. Notatki o stacku nie mają działu. Przy dziale: menedżer z drzewa
(osoba z działu z naszymi konsultantami pod sobą), „Nasi / w bazie” (liczba
osób w bazie z dwiema najmocniejszymi technologiami działu — ten sam
predykat co filtr umiejętności na liście kandydatów, z osobnym cache
``care:techbase:``) i luki do dopytania: dział bez źródła z 18 miesięcy,
technologia znana z jednego źródła (poza samymi CV naszych konsultantów —
CV opisuje człowieka, nie stack klienta) i menedżer naszych konsultantów
bez „podlega pod”.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_get, cache_invalidate, cache_set, cache_single_flight
from app.core.scheduling import DEFAULT_TZ, local_now
from app.models.candidate import Candidate
from app.models.candidate_skill_usage import CandidateSkillUsage
from app.models.client import Client
from app.models.client_knowledge import ClientKnowledge, KnowledgeCategory
from app.models.contact import Contact
from app.models.contract import Contract
from app.models.contract_care import (
    CONTACTS_ORG,
    CareConversation,
    ClientArea,
    RedeployQueueItem,
    TechCard,
    TechVendor,
)
from app.models.job import Job, JobStatus
from app.services import candidate_search_predicates as predicates
from app.services.care import records
from app.services.care import skills as care_skills
from app.services.care.access import LIVE_STATUSES
from app.services.skill_normalize import iter_skill_names

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 120
JOBS_WINDOW_DAYS = 365
SIGNALS_WINDOW_DAYS = 365
STALE_AFTER_DAYS = 548  # ok. 18 miesięcy (makieta „Technologie”)
SOURCES: tuple[str, ...] = ("cards", "jobs", "consultants", "notes")
#: Technologie działu pokazane w wierszu (reszta jako „+N”).
DEPARTMENT_TECHS = 6
#: Ile najmocniejszych technologii działu liczy „w bazie” (wszystkie naraz).
BASE_CORE_SKILLS = 2
BASE_COUNT_TTL_SECONDS = 3600
BASE_COUNT_TIMEOUT_MS = 3000
#: Po przekroczeniu limitu czasu nie liczymy znowu przy każdym przeliczeniu mapy.
BASE_COUNT_FAILED_TTL_SECONDS = 600
_BASE_FAILED = -1
#: Luki „znane z jednego źródła” — najwyżej tyle, najsłabiej udokumentowane.
SINGLE_SOURCE_GAPS = 6

_contacts_org = CONTACTS_ORG.alias("contacts_org")


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


@dataclass
class _Dept:
    """Dział klienta na mapie: technologie, nasi konsultanci, menedżerowie."""

    techs: dict[int, _Tech] = field(default_factory=dict)
    last_seen: Optional[date] = None
    contracts: set[int] = field(default_factory=set)
    managers: dict[int, int] = field(default_factory=dict)

    def tech(self, skill_id: int) -> _Tech:
        if skill_id not in self.techs:
            self.techs[skill_id] = _Tech(skill_id=skill_id)
        return self.techs[skill_id]

    def touch(self, when: Optional[date]) -> None:
        if when is not None and (self.last_seen is None or when > self.last_seen):
            self.last_seen = when


def _base_key(skills: Sequence[str]) -> str:
    return "care:techbase:" + json.dumps(
        sorted({name.casefold() for name in skills}), ensure_ascii=False
    )


async def base_counts(
    db: AsyncSession, groups: Sequence[Sequence[str]]
) -> list[Optional[int]]:
    """Ile osób w bazie ma WSZYSTKIE umiejętności z grupy (filtr listy kandydatów).

    Jedno przejście po tabeli dla wszystkich działów, z limitem czasu
    w savepoincie — liczba to dodatek: przekroczenie albo awaria = ``None``
    („—” na ekranie), nie błąd mapy. Wynik żyje godzinę w osobnym cache.
    """

    out: list[Optional[int]] = [None] * len(groups)
    missing: list[int] = []
    for index, group in enumerate(groups):
        if not group:
            continue
        cached = await cache_get(_base_key(group))
        if cached is None:
            missing.append(index)
        elif cached != _BASE_FAILED:
            out[index] = int(cached)
    if not missing:
        return out
    # Ta sama semantyka co lista (v2 — także umiejętności z screeningu).
    sem = predicates.semantics_for("list", 2)
    columns = [
        func.count().filter(
            and_(*[predicates.skill_match(name, sem) for name in groups[index]])
        )
        for index in missing
    ]
    try:
        async with db.begin_nested():
            previous = (
                await db.execute(text("SELECT current_setting('statement_timeout')"))
            ).scalar_one()
            await db.execute(
                text("SELECT set_config('statement_timeout', :ms, true)"),
                {"ms": f"{BASE_COUNT_TIMEOUT_MS}ms"},
            )
            row = (await db.execute(select(*columns).select_from(Candidate))).one()
            await db.execute(
                text("SELECT set_config('statement_timeout', :prev, true)"),
                {"prev": previous},
            )
    except Exception as exc:  # noqa: BLE001 — liczba to dodatek, nie bramka
        logger.warning("[care] liczba „w bazie” pominięta (%s)", type(exc).__name__)
        for index in missing:
            await cache_set(
                _base_key(groups[index]),
                _BASE_FAILED,
                ttl_seconds=BASE_COUNT_FAILED_TTL_SECONDS,
            )
        return out
    for index, value in zip(missing, row):
        out[index] = int(value or 0)
        await cache_set(
            _base_key(groups[index]), out[index], ttl_seconds=BASE_COUNT_TTL_SECONDS
        )
    return out


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


def _tech_order(item: dict[str, Any]) -> tuple:
    """Najpierw świeże, potwierdzone w wielu źródłach i z wieloma odwołaniami."""

    return (
        item["stale"],
        -item["source_count"],
        -sum(item["counts"].values()),
        item["name"].lower(),
    )


def _dept_tech(entry: _Tech, name: str, stale_before: date) -> dict[str, Any]:
    counts = {source: len(entry.refs[source]) for source in SOURCES}
    return {
        "skill_id": entry.skill_id,
        "name": name,
        "counts": counts,
        "source_count": sum(1 for value in counts.values() if value),
        "last_seen": entry.last_seen,
        "stale": counts["consultants"] == 0
        and (entry.last_seen is None or entry.last_seen < stale_before),
    }


def gaps_for(
    *,
    departments: Sequence[dict[str, Any]],
    technologies: Sequence[dict[str, Any]],
    managers: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """„Luki do dopytania” (czysta reguła D16 — testowalna bez bazy).

    1. Dział bez żadnego źródła z ostatnich 18 miesięcy.
    2. Menedżer naszych konsultantów bez „podlega pod”.
    3. Technologia znana z jednego źródła (świeża, nie z samych CV naszych
       konsultantów) — najwyżej ``SINGLE_SOURCE_GAPS``, najpierw te
       z najmniejszą liczbą odwołań, potem najnowsze.
    """

    gaps: list[dict[str, Any]] = [
        {
            "kind": "area_no_source",
            "area": dept["area"],
            "last_seen": dept["last_seen"],
        }
        for dept in departments
        if not dept["has_fresh_source"]
    ]
    for manager in sorted(managers, key=lambda m: m["name"].casefold()):
        if manager["reports_to_id"] is None:
            gaps.append(
                {
                    "kind": "manager_unplaced",
                    "contact": {"id": manager["id"], "name": manager["name"]},
                    "position": manager["position"],
                    "area": manager["area"],
                    "consultants": manager["consultants"],
                }
            )
    single = [
        tech
        for tech in technologies
        if tech["source_count"] == 1
        and not tech["stale"]
        and tech["counts"]["consultants"] == 0
    ]
    single.sort(
        key=lambda tech: (
            sum(tech["counts"].values()),
            -(tech["last_seen"].toordinal() if tech["last_seen"] else 0),
            tech["name"].lower(),
        )
    )
    for tech in single[:SINGLE_SOURCE_GAPS]:
        source = next(name for name in SOURCES if tech["counts"][name])
        gaps.append(
            {
                "kind": "single_source",
                "skill_id": tech["skill_id"],
                "name": tech["name"],
                "source": source,
                "refs": tech["counts"][source],
                "last_seen": tech["last_seen"],
                "areas": list(tech["areas"]),
            }
        )
    return gaps


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
    depts: dict[int, _Dept] = {area.id: _Dept() for area in areas}
    # Osoby klienta: dział i „podlega pod” (struktura u klienta, etap 2).
    contacts = {
        row[0]: row
        for row in (
            await db.execute(
                select(
                    Contact.id,
                    Contact.name,
                    Contact.position,
                    _contacts_org.c.reports_to_contact_id,
                    _contacts_org.c.client_area_id,
                )
                .join(_contacts_org, _contacts_org.c.id == Contact.id)
                .where(Contact.client_id.in_(client_ids))
            )
        ).all()
    }
    contact_area = {cid: row[4] for cid, row in contacts.items() if row[4] in depts}
    area_cards: dict[int, int] = {}
    vendor_cards: dict[int, int] = {}
    for card in cards:
        area_name = area_names.get(card.client_area_id) if card.client_area_id else None
        if card.client_area_id:
            area_cards[card.client_area_id] = area_cards.get(card.client_area_id, 0) + 1
        dept = depts.get(card.client_area_id) if card.client_area_id else None
        if dept is not None:
            dept.touch(card.interview_on)
        for skill_id in card_skills.get(card.id, []):
            entry = tech(skill_id)
            entry.seen("cards", card.id, card.interview_on)
            if area_name:
                entry.areas.add(area_name)
            if dept is not None:
                dept.tech(skill_id).seen("cards", card.id, card.interview_on)
        for vendor_id in card_vendors.get(card.id, []):
            vendor_cards[vendor_id] = vendor_cards.get(vendor_id, 0) + 1

    # 2. Rekrutacje klienta.
    opened = func.coalesce(Job.opened_at, Job.created_at)
    jobs = (
        await db.execute(
            select(
                Job.id,
                Job.title,
                Job.status,
                Job.must_skills,
                Job.nice_skills,
                opened,
                Job.hiring_manager_contact_id,
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
    for job_id, title, job_status, must, nice, opened_at, hm_id in jobs:
        when = _local_date(opened_at)
        if job_status != JobStatus.closed:
            open_jobs.append({"id": job_id, "title": title, "opened_on": when})
        # Dział rekrutacji = dział jej hiring managera.
        area_id = contact_area.get(hm_id) if hm_id is not None else None
        dept = depts.get(area_id) if area_id is not None else None
        if dept is not None:
            dept.touch(when)
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
                if dept is not None:
                    dept.tech(skill_id).seen("jobs", job_id, when)
                    entry.areas.add(area_names[area_id])

    # 3. Nasi konsultanci (aktywne kontrakty).
    consultants = (
        await db.execute(
            select(
                Contract.id, Contract.candidate_id, Contract.client_pm_contact_id
            ).where(
                Contract.client_id.in_(client_ids),
                Contract.status.in_(LIVE_STATUSES),
                Contract.voided_at.is_(None),
                Contract.candidate_id.is_not(None),
            )
        )
    ).all()
    candidate_ids = sorted({candidate_id for _cid, candidate_id, _pm in consultants})
    # Menedżer u klienta (kontakt tego klienta) → dział konsultanta.
    managed: dict[int, int] = {}
    candidate_depts: dict[int, set[int]] = {}
    for contract_id, candidate_id, manager_id in consultants:
        if manager_id is None or manager_id not in contacts:
            continue
        managed[manager_id] = managed.get(manager_id, 0) + 1
        area_id = contact_area.get(manager_id)
        if area_id is None:
            continue
        dept = depts[area_id]
        dept.contracts.add(contract_id)
        dept.managers[manager_id] = dept.managers.get(manager_id, 0) + 1
        # Konsultant w projekcie to świeże źródło.
        dept.touch(today)
        candidate_depts.setdefault(candidate_id, set()).add(area_id)

    def consultant_seen(candidate_id: int, skill_id: int) -> None:
        for area_id in candidate_depts.get(candidate_id, ()):
            depts[area_id].tech(skill_id).seen("consultants", candidate_id, None)
            tech(skill_id).areas.add(area_names[area_id])

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
            consultant_seen(candidate_id, skill_id)
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
                    consultant_seen(candidate_id, skill_id)

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
    technologies.sort(key=_tech_order)
    display = {item["skill_id"]: item["name"] for item in technologies}

    departments = []
    for area in areas:
        dept = depts[area.id]
        rows = sorted(
            (
                _dept_tech(entry, display.get(entry.skill_id, ""), stale_before)
                for entry in dept.techs.values()
            ),
            key=_tech_order,
        )
        core = [row["name"] for row in rows if not row["stale"]][:BASE_CORE_SKILLS]
        departments.append(
            {
                "area": {"id": area.id, "name": area.name},
                "technologies": rows[:DEPARTMENT_TECHS],
                "technologies_total": len(rows),
                "managers": [
                    {
                        "id": contact_id,
                        "name": contacts[contact_id][1],
                        "position": contacts[contact_id][2],
                        "consultants": count,
                    }
                    for contact_id, count in sorted(
                        dept.managers.items(),
                        key=lambda pair: (
                            -pair[1],
                            contacts[pair[0]][1].casefold(),
                        ),
                    )
                ],
                "consultants": len(dept.contracts),
                "last_seen": dept.last_seen,
                "has_fresh_source": dept.last_seen is not None
                and dept.last_seen >= stale_before,
                "base": {"skills": core, "count": None},
            }
        )
    counts_in_base = await base_counts(
        db, [dept["base"]["skills"] for dept in departments]
    )
    for dept, count in zip(departments, counts_in_base):
        dept["base"]["count"] = count

    gaps = gaps_for(
        departments=departments,
        technologies=technologies,
        managers=[
            {
                "id": contact_id,
                "name": contacts[contact_id][1],
                "position": contacts[contact_id][2],
                "area": (
                    {
                        "id": contact_area[contact_id],
                        "name": area_names[contact_area[contact_id]],
                    }
                    if contact_id in contact_area
                    else None
                ),
                "reports_to_id": contacts[contact_id][3],
                "consultants": count,
            }
            for contact_id, count in managed.items()
        ],
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
        "consultants_count": len({cid for cid, _cand, _pm in consultants}),
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
        "departments": departments,
        "gaps": gaps,
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
