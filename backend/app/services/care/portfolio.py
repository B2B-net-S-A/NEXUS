"""Opieka · „Klienci” — portfel klientów z konsultantami (przebudowa opieki, 22.10.2026).

Jeden wiersz na klienta z trwającymi kontraktami w zakresie czytającego:
Delivery Leadzi, domyślny opiekun, liczba konsultantów, zdrowie relacji
(liczniki Dobrze/Uwaga/Ryzyko — tylko krąg D11), kompletność wiedzy
(menedżerowie znani, konsultanci bez menedżera, ostatnia opinia, prośby
o opinię — D11), mapa technologii, popyt i konsultanci kończący w 60 dni.

Liczone hurtem (zapytania grupowane po kliencie). Mapa technologii nie jest
liczona od nowa dla każdego klienta: jeśli jest w cache single-flight
(``care:techmap:<klient>:``), bierzemy z niej datę ostatniego źródła i liczbę
luk; inaczej lekkie przybliżenie — ostatnia sfinalizowana karta albo notatka
o stacku, luki ``null``.

``mine`` = klienci, u których czytający jest przypisanym Delivery Leadem,
domyślnym opiekunem albo opiekunem któregoś konsultanta; ``all`` = cały
zakres. Odczyt niczego nie zapisuje.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_get
from app.core.scheduling import DEFAULT_TZ
from app.models.client_knowledge import ClientKnowledge, KnowledgeCategory
from app.models.contact import Contact
from app.models.contract import Contract
from app.models.contract_care import ClientFeedbackSession, TechCard
from app.models.job import Job, JobStatus
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services.care import access as care_access
from app.services.care import client_people, demand, health, tech_map
from app.services.care.access import CareContract
from app.services.skill_normalize import iter_skill_names

ENDING_DAYS = 60
DEMAND_SKILLS = 5


def _latest(*values: Optional[date]) -> Optional[date]:
    known = [value for value in values if value is not None]
    return max(known) if known else None


def _cached_map(cached: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Ostatnie źródło i luki z policzonej mapy (cache)."""

    if not cached:
        return None
    seen: list[date] = []
    for item in cached.get("technologies") or []:
        if isinstance(item.get("last_seen"), date):
            seen.append(item["last_seen"])
    for dept in cached.get("departments") or []:
        if isinstance(dept.get("last_seen"), date):
            seen.append(dept["last_seen"])
    return {
        "last_source_on": max(seen) if seen else None,
        "gaps": len(cached.get("gaps") or []),
    }


async def _delivery_leads(
    db: AsyncSession, client_ids: Sequence[int]
) -> dict[int, list[tuple[int, str]]]:
    out: dict[int, list[tuple[int, str]]] = defaultdict(list)
    if not client_ids:
        return out
    rows = (
        await db.execute(
            select(DeliveryLeadClientAssignment.client_id, User)
            .join(User, User.id == DeliveryLeadClientAssignment.delivery_lead_user_id)
            .where(
                DeliveryLeadClientAssignment.client_id.in_(list(client_ids)),
                User.is_active.is_(True),
            )
            .order_by(
                DeliveryLeadClientAssignment.client_id,
                DeliveryLeadClientAssignment.is_head.desc(),
                DeliveryLeadClientAssignment.id,
            )
        )
    ).all()
    for client_id, user in rows:
        if user.has_role(UserRole.delivery_lead) and all(
            uid != user.id for uid, _ in out[client_id]
        ):
            out[client_id].append((user.id, user.name))
    return out


async def _managers(
    db: AsyncSession, contracts: Sequence[CareContract]
) -> dict[int, Optional[int]]:
    """Menedżer u klienta (kontakt TEGO klienta) per kontrakt albo ``None``."""

    if not contracts:
        return {}
    rows = (
        await db.execute(
            select(Contract.id, Contract.client_pm_contact_id, Contact.client_id)
            .outerjoin(Contact, Contact.id == Contract.client_pm_contact_id)
            .where(Contract.id.in_([c.id for c in contracts]))
        )
    ).all()
    client_of = {c.id: c.client_id for c in contracts}
    return {
        contract_id: (
            contact_id
            if contact_id is not None and owner == client_of.get(contract_id)
            else None
        )
        for contract_id, contact_id, owner in rows
    }


async def _light_map(
    db: AsyncSession, client_ids: Sequence[int]
) -> dict[int, Optional[date]]:
    cards = dict(
        (
            await db.execute(
                select(TechCard.client_id, func.max(TechCard.interview_on))
                .where(
                    TechCard.client_id.in_(list(client_ids)),
                    TechCard.is_draft.is_(False),
                )
                .group_by(TechCard.client_id)
            )
        ).all()
    )
    notes = dict(
        (
            await db.execute(
                select(ClientKnowledge.client_id, func.max(ClientKnowledge.created_at))
                .where(
                    ClientKnowledge.client_id.in_(list(client_ids)),
                    ClientKnowledge.category == KnowledgeCategory.tech_stack,
                )
                .group_by(ClientKnowledge.client_id)
            )
        ).all()
    )
    zone = ZoneInfo(DEFAULT_TZ)
    return {
        client_id: _latest(
            cards.get(client_id),
            notes[client_id].astimezone(zone).date() if notes.get(client_id) else None,
        )
        for client_id in client_ids
    }


async def _open_jobs(
    db: AsyncSession, client_ids: Sequence[int]
) -> tuple[dict[int, int], dict[int, list[str]]]:
    counts: dict[int, int] = defaultdict(int)
    skills: dict[int, Counter] = defaultdict(Counter)
    rows = (
        await db.execute(
            select(Job.client_id, Job.must_skills).where(
                Job.client_id.in_(list(client_ids)),
                Job.status != JobStatus.closed,
            )
        )
    ).all()
    for client_id, must in rows:
        counts[client_id] += 1
        for name in iter_skill_names(must):
            cleaned = " ".join(name.split())
            if cleaned:
                skills[client_id][cleaned] += 1
    top = {
        client_id: [name for name, _ in counter.most_common(DEMAND_SKILLS)]
        for client_id, counter in skills.items()
    }
    return counts, top


async def clients(
    db: AsyncSession, user: User, *, scope: str, today: date
) -> dict[str, Any]:
    allowed = await care_access.allowed_client_ids(user, db)
    include_feedback = care_access.reads_client_people(user)
    live = await care_access.live_contracts(db, allowed=allowed)
    owners = await care_access.effective_owners(db, live)
    by_client: dict[int, list[CareContract]] = defaultdict(list)
    for contract in live:
        by_client[contract.client_id].append(contract)
    client_ids = sorted(by_client)
    leads = await _delivery_leads(db, client_ids)
    if scope == "mine":
        keep = {
            client_id
            for client_id, contracts in by_client.items()
            if any(uid == user.id for uid, _ in leads.get(client_id, []))
            or any(c.client_default_owner_id == user.id for c in contracts)
            or any(owners[c.id].user_id == user.id for c in contracts)
        }
        client_ids = [cid for cid in client_ids if cid in keep]
    contracts = [c for cid in client_ids for c in by_client[cid]]

    healths = (
        await health.health_for(db, contracts, today=today) if include_feedback else {}
    )
    managers = await _managers(db, contracts)
    default_owner_names = await care_access.user_names(
        db, [by_client[cid][0].client_default_owner_id for cid in client_ids]
    )
    last_feedback: dict[int, date] = {}
    pending: Counter = Counter()
    if include_feedback and client_ids:
        last_feedback = dict(
            (
                await db.execute(
                    select(
                        ClientFeedbackSession.client_id,
                        func.max(ClientFeedbackSession.held_on),
                    )
                    .where(ClientFeedbackSession.client_id.in_(client_ids))
                    .group_by(ClientFeedbackSession.client_id)
                )
            ).all()
        )
        for item in await client_people.feedback_requests_for(
            db, contracts, owners=owners, today=today
        ):
            pending[item["client_id"]] += 1
    light = await _light_map(db, client_ids) if client_ids else {}
    open_jobs, job_skills = await _open_jobs(db, client_ids) if client_ids else ({}, {})
    # Nierozstrzygnięty sygnał „klient zatrudnia” z 90 dni (jak karta popytu).
    hiring_clients = {
        signal.client_id
        for group, _state in await demand.open_groups(db, client_ids, today=today)
        for signal in group.signals
    }

    rows = []
    for client_id in client_ids:
        group = by_client[client_id]
        known = {managers.get(c.id) for c in group if managers.get(c.id) is not None}
        counts = Counter(
            (healths.get(c.id) or {}).get("level") for c in group if healths.get(c.id)
        )
        cached = _cached_map(await cache_get(tech_map.cache_key(client_id)))
        ending = sorted(
            (
                {
                    "contract_id": c.id,
                    "name": c.candidate_name,
                    "end_on": c.end_date,
                }
                for c in group
                if c.end_date is not None
                and today <= c.end_date <= today + timedelta(days=ENDING_DAYS)
            ),
            key=lambda row: (row["end_on"], row["name"] or ""),
        )
        rows.append(
            {
                "client_id": client_id,
                "name": group[0].client_name,
                "delivery_leads": [name for _uid, name in leads.get(client_id, [])],
                "default_owner_name": default_owner_names.get(
                    group[0].client_default_owner_id
                ),
                "consultants": len(group),
                "health": (
                    {
                        "ok": counts.get("ok", 0),
                        "watch": counts.get("watch", 0),
                        "risk": counts.get("risk", 0),
                    }
                    if include_feedback
                    else None
                ),
                "managers_known": len(known),
                "structure_open": sum(1 for c in group if managers.get(c.id) is None),
                "last_feedback_on": last_feedback.get(client_id),
                "feedback_pending": pending.get(client_id, 0),
                "map": cached or {"last_source_on": light.get(client_id), "gaps": None},
                "demand": {
                    "skills": job_skills.get(client_id, []),
                    "open_jobs": open_jobs.get(client_id, 0),
                    "hiring_signal": client_id in hiring_clients,
                },
                "ending_60": ending,
            }
        )
    rows.sort(key=lambda row: row["name"].casefold())
    return {"rows": rows, "scope": scope, "health_visible": include_feedback}
