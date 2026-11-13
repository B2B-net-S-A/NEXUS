"""Bot Listy: listy do dzwonienia z briefu kampanii (decyzje Artura 13.11.2026).

Kampania dostaje brief (``sales_call_campaigns.bot_brief``, 0690): do kogo dzwonimy
(rola), segment, źródła, paczka na osobę tygodniowo i osoby dzwoniące. Bot wybiera
osoby i zapisuje je do kampanii **od razu**, przez te same bramki co import listy
(``calling_import.apply_import``): klient NEXUSA, sprzeciw, otwarta szansa, cudzy
rekord, rekord w kampanii, brak telefonu. Nic się nie wysyła i nie dzwoni samo.

L1–L2 (ten moduł): źródło „baza NEXUSA” — kontakty z telefonem w firmach, do
których nikt nie dzwonił w ostatnich 6 miesiącach i które nie mają otwartej szansy.
Kolejność ról bierze się z wyników kampanii („Co działa”, ``role_rates``): rola,
która częściej kończy się spotkaniem, idzie pierwsza. Dosypka w poniedziałek do
poziomu paczki, zawsze (decyzja Artura: bez wstrzymania przy zaległych oddzwonieniach).

Logi są publiczne: numery kampanii i liczby, bez nazw firm i osób.
Reguły: ``docs/claude/sprzedaz/bot-listy-kampanie.md``.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import (
    SalesCallCampaign,
    SalesCallRecord,
    SalesCompany,
    SalesContact,
    SalesOpportunity,
)
from app.models.user import User
from app.services import sales_schema as schema
from app.services.sales import calling_import
from app.services.sales.calling_file import ListFile, ListRow
from app.services.sales.factories import COMPANY_DO_NOT_CONTACT
from app.services.sales.task_scope import live_opportunity

logger = logging.getLogger(__name__)

#: Role w kolejności domyślnej. Klucz ↔ podpis na ekranie.
ROLE_LABELS: dict[str, str] = {
    "manager": "Manager / Lead",
    "head": "Head / Director",
    "cxo": "CTO / CIO",
    "board": "Zarząd",
    "other": "Inne stanowiska",
}
ROLES = tuple(ROLE_LABELS)
#: Domyślnie dzwonimy do Managerów i Headów: w „BE Leady” (13.11.2026) Manager/Lead
#: 2,9% spotkań, CTO/CIO 1,4%, zarząd 0 z 131.
DEFAULT_ROLES: tuple[str, ...] = ("manager", "head")
_ROLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "board",
        re.compile(
            r"\b(ceo|prezes|president|zarz[aą]d|board|owner|w[lł]a[sś]ciciel|"
            r"founder|wsp[oó][lł]w[lł]a[sś]ciciel|managing director)\b",
            re.I,
        ),
    ),
    (
        "cxo",
        re.compile(
            r"\b(cto|cio|cdo|ciso|chief (technology|information|digital|data))",
            re.I,
        ),
    ),
    ("head", re.compile(r"\b(head|director|dyrektor|vp|vice president)\b", re.I)),
    (
        "manager",
        re.compile(
            r"\b(manager|mened[zż]er|kierownik|lead|leader|lider|team ?lead)\b", re.I
        ),
    ),
)

SIZE_BUCKETS: tuple[str, ...] = ("1-49", "50-249", "250-999", "1000+")
SOURCES: tuple[str, ...] = ("base", "rejestr", "research", "cognism")
SOURCE_LABELS = {
    "base": "baza NEXUSA",
    "rejestr": "rejestr.io",
    "research": "research",
    "cognism": "Cognism",
}
TRIGGERS: tuple[str, ...] = ("board_change", "it_center", "acquisition", "hiring")

#: Firma dzwoniona w tym oknie nie wraca na nową listę.
RECENT_CALL_WINDOW = timedelta(days=183)
#: Wygładzenie skuteczności ról: rola bez historii nie wygrywa przypadkiem.
PRIOR_CALLS = 30
PRIOR_RATE = 0.02
BUILD_NOTE = "Bot Listy"


def role_of(title: Optional[str]) -> str:
    """Rola ze stanowiska; pierwsze dopasowanie od najwyższej, inaczej „inne”."""

    text = (title or "").strip()
    for role, pattern in _ROLE_PATTERNS:
        if pattern.search(text):
            return role
    return "other"


def size_bucket(size_range: Optional[str]) -> Optional[str]:
    """Przedział z karty („51-200”, „5000+”, „250-999”) → przedział briefu po dolnej granicy."""

    match = re.match(r"\s*(\d[\d\s]*)", size_range or "")
    if not match:
        return None
    low = int(re.sub(r"\D", "", match.group(1)))
    if low >= 1000:
        return "1000+"
    if low >= 250:
        return "250-999"
    if low >= 50:
        return "50-249"
    return "1-49"


class Brief(BaseModel):
    """Brief kampanii dla Bota Listy; dane z ekranu, więc walidowane na granicy."""

    model_config = ConfigDict(extra="forbid")

    roles: list[Literal[ROLES]] = Field(  # type: ignore[valid-type]
        default_factory=lambda: list(DEFAULT_ROLES), min_length=1, max_length=5
    )
    #: Słowa z branży karty (np. „bank”, „finans”, „oprogramowanie”).
    industries: list[str] = Field(default_factory=list, max_length=10)
    #: Kody PKD (dział 2 cyfry albo dokładniej) dla źródeł zewnętrznych (L3).
    pkd: list[str] = Field(default_factory=list, max_length=15)
    #: Województwa dla źródeł zewnętrznych, miasta siedziby dla bazy.
    regions: list[str] = Field(default_factory=list, max_length=16)
    sizes: list[Literal[SIZE_BUCKETS]] = Field(  # type: ignore[valid-type]
        default_factory=list, max_length=4
    )
    triggers: list[Literal[TRIGGERS]] = Field(  # type: ignore[valid-type]
        default_factory=list, max_length=4
    )
    sources: list[Literal[SOURCES]] = Field(  # type: ignore[valid-type]
        default_factory=lambda: ["base"], min_length=1, max_length=4
    )
    #: Karty bez branży, miasta albo wielkości też wchodzą (dziś ma je ~2% kart).
    include_unknown: bool = True
    per_caller: int = Field(default=40, ge=1, le=200)
    caller_ids: list[int] = Field(min_length=1, max_length=10)
    auto_refill: bool = True

    @field_validator("industries", "regions")
    @classmethod
    def _words(cls, values: list[str]) -> list[str]:
        cleaned = [re.sub(r"\s+", " ", v).strip()[:60] for v in values]
        return list(dict.fromkeys(v for v in cleaned if len(v) >= 2))

    @field_validator("pkd")
    @classmethod
    def _pkd(cls, values: list[str]) -> list[str]:
        out = []
        for value in values:
            code = re.sub(r"[^\d.A-Za-z]", "", value)[:7]
            if not re.fullmatch(r"\d{2}(\.\d{1,2}[A-Za-z]?)?", code):
                raise ValueError(f"Nieprawidłowy kod PKD: {value}")
            out.append(code.upper())
        return list(dict.fromkeys(out))


def load_brief(campaign: SalesCallCampaign) -> Optional[Brief]:
    if not campaign.bot_brief:
        return None
    try:
        return Brief.model_validate(campaign.bot_brief)
    except ValueError:
        logger.warning("bot_lists campaign=%s brief invalid", campaign.id)
        return None


# ── „Co działa”: skuteczność ról ─────────────────────────────────────────


@dataclass(frozen=True)
class RoleRate:
    role: str
    calls: int
    meetings: int
    not_interested: int

    @property
    def rate(self) -> float:
        return self.meetings / self.calls if self.calls else 0.0

    @property
    def smoothed(self) -> float:
        return (self.meetings + PRIOR_RATE * PRIOR_CALLS) / (self.calls + PRIOR_CALLS)


async def rated_records(
    db: AsyncSession, campaign_id: Optional[int]
) -> list[tuple[Optional[str], str, Optional[str]]]:
    stmt = select(
        SalesCallRecord.person_title,
        SalesCallRecord.state,
        SalesCallRecord.contact_source,
    ).where(SalesCallRecord.state != schema.CALL_RECORD_NEW)
    if campaign_id is not None:
        stmt = stmt.where(SalesCallRecord.campaign_id == campaign_id)
    return [tuple(row) for row in (await db.execute(stmt)).all()]


def rates_by(
    rows: list[tuple[Optional[str], str, Optional[str]]], key: str
) -> list[RoleRate]:
    """Rozmowy z wynikiem (bez „nowy”) po roli albo po źródle kontaktu."""

    buckets: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for title, state, source in rows:
        name = role_of(title) if key == "role" else (source or "—")
        item = buckets[name]
        item[0] += 1
        item[1] += int(state == "meeting_booked")
        item[2] += int(state == "not_interested")
    out = [RoleRate(name, *values) for name, values in buckets.items()]
    if key == "role":
        return sorted(out, key=lambda r: ROLES.index(r.role))
    return sorted(out, key=lambda r: -r.calls)


async def role_order(db: AsyncSession, roles: list[str]) -> list[str]:
    """Role briefu od najskuteczniejszej (wszystkie kampanie, wygładzone)."""

    rates = {r.role: r for r in rates_by(await rated_records(db, None), "role")}
    prior = RoleRate("x", 0, 0, 0).smoothed
    return sorted(
        roles,
        key=lambda role: (
            -(rates[role].smoothed if role in rates else prior),
            ROLES.index(role),
        ),
    )


# ── Kandydaci z bazy ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class Candidate:
    company_id: int
    company: str
    domain: Optional[str]
    website: Optional[str]
    nip: Optional[str]
    industry: Optional[str]
    city: Optional[str]
    person: str
    title: Optional[str]
    phone: str
    email: Optional[str]
    linkedin: Optional[str]
    role: str


def _matches_segment(brief: Brief, row: Any) -> bool:
    def fits(values: list[str], value: Optional[str], *, contains: bool) -> bool:
        if not values:
            return True
        if not value:
            return brief.include_unknown
        low = value.lower()
        return any((v.lower() in low) if contains else v.lower() == low for v in values)

    if not fits(brief.industries, row.industry, contains=True):
        return False
    if not fits(brief.regions, row.hq_city, contains=True):
        return False
    if brief.sizes:
        bucket = size_bucket(row.size_range)
        if bucket is None:
            return brief.include_unknown
        return bucket in brief.sizes
    return True


async def base_candidates(
    db: AsyncSession, brief: Brief, *, limit: int, now: datetime
) -> list[Candidate]:
    """Osoby z telefonem w firmach bez rozmowy od pół roku i bez otwartej szansy.

    Jedna osoba na firmę, w kolejności ról briefu od najskuteczniejszej. Klient
    NEXUSA, sprzeciw i rekord w kampanii odpadają i tak w bramkach importu, ale
    filtr tutaj oszczędza miejsce w paczce.
    """

    recent_call = exists(
        select(SalesCallRecord.id).where(
            SalesCallRecord.company_id == SalesCompany.id,
            or_(
                SalesCallRecord.created_at >= now - RECENT_CALL_WINDOW,
                SalesCallRecord.last_outcome_at >= now - RECENT_CALL_WINDOW,
                # „Nie zainteresowany — nigdy”: rekord bez daty powrotu nie wraca.
                and_(
                    SalesCallRecord.state == "not_interested",
                    SalesCallRecord.callback_on.is_(None),
                ),
            ),
        )
    )
    open_opportunity = exists(
        select(SalesOpportunity.id).where(
            SalesOpportunity.company_id == SalesCompany.id, live_opportunity()
        )
    )
    phone = func.coalesce(SalesContact.mobile_phone, SalesContact.phone)
    rows = (
        await db.execute(
            select(
                SalesCompany.id.label("company_id"),
                SalesCompany.name,
                SalesCompany.domain,
                SalesCompany.website_url,
                SalesCompany.nip,
                SalesCompany.industry,
                SalesCompany.hq_city,
                SalesCompany.size_range,
                SalesContact.full_name,
                SalesContact.title,
                phone.label("phone"),
                SalesContact.email,
                SalesContact.linkedin_url,
                SalesContact.id.label("contact_id"),
            )
            .join(SalesContact, SalesContact.company_id == SalesCompany.id)
            .where(
                SalesCompany.archived_at.is_(None),
                SalesCompany.client_id.is_(None),
                SalesCompany.status != COMPANY_DO_NOT_CONTACT,
                SalesContact.archived_at.is_(None),
                SalesContact.do_not_contact_at.is_(None),
                phone.is_not(None),
                SalesContact.title.is_not(None),
                ~recent_call,
                ~open_opportunity,
            )
            .order_by(SalesContact.id.desc())
        )
    ).all()
    order = await role_order(db, list(brief.roles))
    rank = {role: index for index, role in enumerate(order)}
    best: dict[int, tuple[int, Candidate]] = {}
    for row in rows:
        role = role_of(row.title)
        if role not in rank or not _matches_segment(brief, row):
            continue
        candidate = Candidate(
            company_id=row.company_id,
            company=row.name,
            domain=row.domain,
            website=row.website_url,
            nip=row.nip,
            industry=row.industry,
            city=row.hq_city,
            person=row.full_name,
            title=row.title,
            phone=row.phone,
            email=row.email,
            linkedin=row.linkedin_url,
            role=role,
        )
        current = best.get(row.company_id)
        if current is None or rank[role] < current[0]:
            best[row.company_id] = (rank[role], candidate)
    ranked = sorted(best.values(), key=lambda item: item[0])
    return [candidate for _, candidate in ranked[:limit]]


# ── Budowa i dosypka ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class BuildResult:
    campaign_id: int
    added: int
    per_caller: dict[int, int]
    skipped: dict[str, int]
    candidates: int


async def _new_per_caller(
    db: AsyncSession, campaign_id: int, caller_ids: list[int]
) -> dict[int, int]:
    rows = await db.execute(
        select(SalesCallRecord.assigned_user_id, func.count())
        .where(
            SalesCallRecord.campaign_id == campaign_id,
            SalesCallRecord.state == schema.CALL_RECORD_NEW,
            SalesCallRecord.assigned_user_id.in_(caller_ids),
        )
        .group_by(SalesCallRecord.assigned_user_id)
    )
    counts = dict.fromkeys(caller_ids, 0)
    counts.update({int(uid): int(n) for uid, n in rows.all()})
    return counts


def _why(candidate: Candidate) -> str:
    parts = [ROLE_LABELS[candidate.role]]
    if candidate.industry:
        parts.append(candidate.industry.lower()[:40])
    if candidate.city:
        parts.append(candidate.city[:40])
    return f"{BUILD_NOTE}: " + " · ".join(parts)


async def build(
    db: AsyncSession,
    campaign: SalesCallCampaign,
    *,
    user_id: Optional[int],
    now: Optional[datetime] = None,
) -> BuildResult:
    """Dosyp każdej osobie dzwoniącej do poziomu paczki; zapis od razu, bez commita."""

    moment = now or datetime.now(timezone.utc)
    brief = load_brief(campaign)
    if brief is None:
        raise ValueError("Kampania nie ma briefu dla Bota Listy.")
    users = (
        await db.execute(
            select(User.id, User.name).where(
                User.id.in_(brief.caller_ids), User.is_active.is_(True)
            )
        )
    ).all()
    callers = {int(uid): name for uid, name in users if name}
    if not callers:
        raise ValueError("Brief nie ma aktywnej osoby dzwoniącej.")
    have = await _new_per_caller(db, campaign.id, list(callers))
    need = {uid: max(0, brief.per_caller - have.get(uid, 0)) for uid in callers}
    total = sum(need.values())
    if total == 0 or "base" not in brief.sources:
        return BuildResult(campaign.id, 0, dict.fromkeys(callers, 0), {}, 0)
    # Zapas na odpady w bramkach (klient, cudzy rekord, powtórka NIP-u).
    candidates = await base_candidates(db, brief, limit=total * 2, now=moment)
    rows: list[ListRow] = []
    assigned: dict[int, int] = dict.fromkeys(callers, 0)
    for line, candidate in enumerate(candidates, start=2):
        # Na zmianę między osobami, proporcjonalnie do brakującej paczki.
        open_callers = [uid for uid in callers if assigned[uid] < need[uid]]
        if not open_callers:
            break
        uid = min(open_callers, key=lambda u: (assigned[u] / max(need[u], 1), u))
        assigned[uid] += 1
        rows.append(
            ListRow(
                line=line,
                company=candidate.company,
                person=candidate.person,
                title=candidate.title,
                phone=candidate.phone,
                email=candidate.email,
                website=candidate.website,
                nip=candidate.nip,
                industry=candidate.industry,
                note=_why(candidate),
                linkedin=candidate.linkedin,
                caller=callers[uid],
            )
        )
    people = calling_import.caller_keys(list(callers.items()))
    plan, added = await calling_import.apply_import(
        db,
        campaign.id,
        ListFile(rows=rows, without_company=0),
        contact_source=f"{BUILD_NOTE} · {SOURCE_LABELS['base']}",
        assignee_id=next(iter(callers)),
        user_id=user_id or next(iter(callers)),
        people=people,
    )
    per_caller: dict[int, int] = dict.fromkeys(callers, 0)
    skipped: dict[str, int] = {}
    for row_plan in plan.rows:
        if row_plan.fate in calling_import.ADDABLE:
            uid = row_plan.assignee_id or next(iter(callers))
            per_caller[uid] = per_caller.get(uid, 0) + 1
        else:
            skipped[row_plan.fate] = skipped.get(row_plan.fate, 0) + 1
    campaign.bot_built_at = moment
    logger.info(
        "bot_lists campaign=%s candidates=%d added=%d skipped=%d",
        campaign.id,
        len(candidates),
        added,
        sum(skipped.values()),
    )
    return BuildResult(campaign.id, added, per_caller, skipped, len(candidates))


def refill_due(local: datetime) -> bool:
    """Poniedziałek od 7:00 kalendarza firmy; raz w tygodniu pilnuje ``bot_built_at``."""

    return local.weekday() == 0 and local.hour >= 7


async def refill_campaigns(db: AsyncSession, *, now: datetime) -> int:
    """Poniedziałkowa dosypka: kampanie z briefem i ``auto_refill``; commit tutaj."""

    campaigns = (
        (
            await db.execute(
                select(SalesCallCampaign).where(
                    SalesCallCampaign.archived_at.is_(None),
                    SalesCallCampaign.bot_brief.is_not(None),
                    or_(
                        SalesCallCampaign.bot_built_at.is_(None),
                        SalesCallCampaign.bot_built_at < now - timedelta(days=6),
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    added = 0
    for campaign in campaigns:
        brief = load_brief(campaign)
        if brief is None or not brief.auto_refill:
            continue
        try:
            result = await build(db, campaign, user_id=None, now=now)
        except ValueError:
            continue
        await db.commit()
        added += result.added
    return added
