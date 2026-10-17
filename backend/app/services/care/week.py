"""Opieka · „Ten tydzień” (D15, etap 2, 17.10.2026).

Jedna kolejka na tydzień pracy (poniedziałek–piątek kalendarza firmy):

* **rozmowy z konsultantem** — otwarte punkty planu (dzień 7/30/90, kwartał,
  przed końcem) z terminem najpóźniej w piątek, czyli zaległe i te z tego
  tygodnia, oraz umówiony kontakt (follow-up) z ostatniej rozmowy. Jedna
  pozycja na kontrakt: rozmowa zamyka wszystkie zaległe punkty naraz, więc
  dwa wiersze tej samej osoby byłyby jednym telefonem. Follow-up liczy
  ``plan.live_follow_up`` (starszy niż ``plan.LOOKBACK_DAYS`` nie wraca) — jak
  karta kontraktu i dzienny przebieg (``reminders``);
* **prośby o opinię** — z ``client_people.feedback_requests``: jedna na
  menedżera u klienta ze wszystkimi jego konsultantami (D9). Liczone na dziś;
  Finanse ich nie widzą (D11 — trasa przekazuje ``include_feedback``).

Przy każdej rozmowie: menedżer u klienta z drzewa (``client_pm_contact_id``
kontaktu tego samego klienta, z działem), ostatnia rozmowa i aktywne sygnały
„Do przepięcia”, a przy kończących projekt — czy można przekazać do front
office i kiedy przekazano (``front_office``).

Zakres jak lista opieki: ``mine`` = kontrakty, których czytający jest
opiekunem; ``all`` = wszystkie w zakresie (DL — swoi klienci). Prośby
o opinię w ``mine`` jak ``GET /feedback-requests``: opiekun swoje, Delivery
Lead wszystkie z portfela.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.contract import Contract
from app.models.contract_care import (
    CONTACTS_ORG,
    CareConversation,
    CarePlanItem,
    ClientArea,
)
from app.models.user import User, UserRole
from app.services.care import access as care_access
from app.services.care import client_people, front_office
from app.services.care import plan as care_plan
from app.services.care.access import CareContract

WORK_DAYS = 5
NOTE_EXCERPT = 160

_contacts_org = CONTACTS_ORG.alias("contacts_org")


def week_bounds(day: date) -> tuple[date, date]:
    """Poniedziałek i piątek tygodnia, w którym leży ``day``."""

    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=WORK_DAYS - 1)


def default_day(today: date) -> date:
    """Dzień, od którego liczy się „Ten tydzień”: w weekend — następny tydzień."""

    if today.weekday() >= WORK_DAYS:
        return today + timedelta(days=7 - today.weekday())
    return today


def excerpt(text: Optional[str], limit: int = NOTE_EXCERPT) -> Optional[str]:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return None
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rstrip() + "…"


def conversation_signals(conversation: CareConversation) -> list[str]:
    return [
        name
        for name, on in (
            ("attrition_risk", conversation.attrition_risk),
            ("wants_change", conversation.wants_change),
            ("project_end", conversation.project_end_on is not None),
            ("client_hiring", conversation.client_hiring),
        )
        if on
    ]


def last_conversation_payload(
    conversation: Optional[CareConversation],
) -> Optional[dict[str, Any]]:
    if conversation is None:
        return None
    return {
        "id": conversation.id,
        "occurred_on": conversation.occurred_on,
        "satisfaction": conversation.satisfaction,
        "note_excerpt": excerpt(conversation.note),
        "signals": conversation_signals(conversation),
    }


async def client_managers(
    db: AsyncSession, contracts: Sequence[CareContract]
) -> dict[int, dict[str, Any]]:
    """Menedżer u klienta z drzewa: kontakt TEGO klienta z działem (albo brak)."""

    ids = [c.id for c in contracts]
    if not ids:
        return {}
    pointers = {
        contract_id: contact_id
        for contract_id, contact_id in (
            await db.execute(
                select(Contract.id, Contract.client_pm_contact_id).where(
                    Contract.id.in_(ids), Contract.client_pm_contact_id.is_not(None)
                )
            )
        ).all()
    }
    if not pointers:
        return {}
    contacts = {
        row[0]: row
        for row in (
            await db.execute(
                select(
                    Contact.id,
                    Contact.name,
                    Contact.position,
                    Contact.client_id,
                    ClientArea.id,
                    ClientArea.name,
                )
                .join(_contacts_org, _contacts_org.c.id == Contact.id)
                .outerjoin(ClientArea, ClientArea.id == _contacts_org.c.client_area_id)
                .where(Contact.id.in_(sorted(set(pointers.values()))))
            )
        ).all()
    }
    client_of = {c.id: c.client_id for c in contracts}
    out: dict[int, dict[str, Any]] = {}
    for contract_id, contact_id in pointers.items():
        row = contacts.get(contact_id)
        # Kontakt innego klienta (dane sprzed walidacji D8) nie jest menedżerem.
        if row is None or row[3] != client_of.get(contract_id):
            continue
        out[contract_id] = {
            "id": row[0],
            "name": row[1],
            "position": row[2],
            "area": {"id": row[4], "name": row[5]} if row[4] is not None else None,
        }
    return out


@dataclass(frozen=True)
class Reason:
    kind: str  # day_7 | day_30 | day_90 | quarterly | pre_end | follow_up
    due_on: date
    plan_item_id: Optional[int] = None
    from_conversation_on: Optional[date] = None

    def payload(self, today: date) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": care_plan.contact_label(self.kind),
            "due_on": self.due_on,
            "overdue": self.due_on < today,
            "plan_item_id": self.plan_item_id,
            "from_conversation_on": self.from_conversation_on,
        }


def contact_reasons(
    items: Iterable[CarePlanItem],
    latest: Optional[CareConversation],
    *,
    today: date,
    friday: date,
) -> list[Reason]:
    """Powody kontaktu w tym tygodniu (czysta reguła — testowalna bez bazy)."""

    reasons = [
        Reason(item.kind, item.due_on, plan_item_id=item.id)
        for item in items
        if item.status == "open" and item.due_on <= friday
    ]
    follow_up = care_plan.live_follow_up(latest, today)
    if follow_up is not None and follow_up <= friday:
        reasons.append(
            Reason(
                care_plan.FOLLOW_UP,
                follow_up,
                from_conversation_on=latest.occurred_on,
            )
        )
    return sorted(reasons, key=lambda r: (r.due_on, r.plan_item_id or 0))


async def _area_names(
    db: AsyncSession, contact_ids: Iterable[int]
) -> dict[int, dict[str, Any]]:
    ids = sorted(set(contact_ids))
    if not ids:
        return {}
    return {
        contact_id: {"id": area_id, "name": name}
        for contact_id, area_id, name in (
            await db.execute(
                select(_contacts_org.c.id, ClientArea.id, ClientArea.name)
                .join(ClientArea, ClientArea.id == _contacts_org.c.client_area_id)
                .where(_contacts_org.c.id.in_(ids))
            )
        ).all()
    }


async def _feedback(
    db: AsyncSession,
    *,
    user: User,
    allowed: Optional[frozenset[int]],
    live: Sequence[CareContract],
    owners: dict[int, care_access.OwnerChoice],
    scope: str,
    today: date,
    friday: date,
) -> list[dict[str, Any]]:
    # Te same kontrakty i opiekunowie co kolejka rozmów — bez drugiego liczenia.
    items = await client_people.feedback_requests_for(
        db, live, owners=owners, today=today
    )
    if scope == "mine" and not (
        allowed is not None and user.has_role(UserRole.delivery_lead)
    ):
        items = [item for item in items if user.id in item["owner_ids"]]
    items = [item for item in items if item["due_on"] <= friday]
    areas = await _area_names(db, (item["contact_id"] for item in items))
    return [
        {
            **{key: value for key, value in item.items() if key != "owner_ids"},
            "area": areas.get(item["contact_id"]),
        }
        for item in items
    ]


async def week_queue(
    db: AsyncSession,
    *,
    user: User,
    allowed: Optional[frozenset[int]],
    scope: str,
    day: date,
    today: date,
    include_feedback: bool,
) -> dict[str, Any]:
    monday, friday = week_bounds(day)
    # Odczyt niczego nie zapisuje: plan dopisuje dzienny przebieg i zmiana
    # opiekuna (``plan.ensure_plans``).
    live = await care_access.live_contracts(db, allowed=allowed)
    owners = await care_access.effective_owners(db, live)
    contracts = (
        [c for c in live if owners[c.id].user_id == user.id]
        if scope == "mine"
        else live
    )
    ids = [c.id for c in contracts]
    open_items: dict[int, list[CarePlanItem]] = {cid: [] for cid in ids}
    if ids:
        for item in (
            await db.scalars(
                select(CarePlanItem)
                .where(
                    CarePlanItem.contract_id.in_(ids),
                    CarePlanItem.status == "open",
                    CarePlanItem.due_on <= friday,
                )
                .order_by(CarePlanItem.due_on, CarePlanItem.id)
            )
        ).all():
            open_items[item.contract_id].append(item)
    latest = await care_plan.latest_conversations(db, ids)

    due: list[tuple[CareContract, list[Reason]]] = []
    for contract in contracts:
        reasons = contact_reasons(
            open_items[contract.id],
            latest.get(contract.id),
            today=today,
            friday=friday,
        )
        if reasons:
            due.append((contract, reasons))

    due_contracts = [contract for contract, _ in due]
    managers = await client_managers(db, due_contracts)
    redeploy = await front_office.active_redeploy(db, [c.id for c in due_contracts])
    handed = await front_office.handoffs(db, [c.id for c in due_contracts])
    names = await care_access.user_names(
        db, [owners[c.id].user_id for c in due_contracts]
    )

    contacts = []
    for contract, reasons in due:
        primary = reasons[0]
        active = redeploy[contract.id]
        events = handed[contract.id]
        owner_id = owners[contract.id].user_id
        contacts.append(
            {
                "contract_id": contract.id,
                "candidate_id": contract.candidate_id,
                "candidate_name": contract.candidate_name,
                "client_id": contract.client_id,
                "client_name": contract.client_name,
                "job_title": contract.job_title,
                "start_date": contract.start_date,
                "end_date": contract.end_date,
                "owner": (
                    {"id": owner_id, "name": names.get(owner_id, "")}
                    if owner_id is not None
                    else None
                ),
                "reasons": [reason.payload(today) for reason in reasons],
                "due_on": primary.due_on,
                "overdue": primary.due_on < today,
                "overdue_days": max((today - primary.due_on).days, 0),
                "plan_item_id": next(
                    (r.plan_item_id for r in reasons if r.plan_item_id is not None),
                    None,
                ),
                "manager": managers.get(contract.id),
                "last_conversation": last_conversation_payload(latest.get(contract.id)),
                "signals": sorted({item.reason for item in active}),
                "front_office": {
                    "reasons": front_office.eligibility(contract, active, today),
                    "handed_off_on": (
                        front_office.local_day(events[-1]) if events else None
                    ),
                },
            }
        )
    contacts.sort(
        key=lambda row: (row["due_on"], (row["candidate_name"] or "").casefold())
    )

    feedback = (
        await _feedback(
            db,
            user=user,
            allowed=allowed,
            live=live,
            owners=owners,
            scope=scope,
            today=today,
            friday=friday,
        )
        if include_feedback
        else []
    )
    overdue = sum(1 for row in contacts if row["overdue"]) + sum(
        1 for item in feedback if item["overdue"]
    )
    return {
        "week": {
            "from": monday,
            "to": friday,
            "today": today,
            "is_current": monday == week_bounds(default_day(today))[0],
        },
        "scope": scope,
        "contacts": contacts,
        "feedback": feedback,
        "feedback_visible": include_feedback,
        "counts": {
            "contacts": len(contacts),
            "overdue": overdue,
            "feedback": len(feedback),
            "front_office": sum(
                1 for row in contacts if row["front_office"]["reasons"]
            ),
        },
    }
