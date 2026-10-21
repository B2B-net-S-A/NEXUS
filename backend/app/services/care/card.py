"""Karta konsultanta i „Co u klienta” (przebudowa opieki, 22.10.2026).

Jedna karta w panelu ``/care?contract=<id>`` i w zakładce „Opieka” kontraktu
(zastępuje „Oś konsultanta” i „Oś opieki”). Agregat dla jednego kontraktu:
opiekun, rytm, zdrowie relacji (krąg D11), liczby (ostatni kontakt,
zadowolenie, opinia menedżera — D11, koniec zamówienia), następny krok,
to, co wiemy o projekcie (ostatnia karta technologiczna), sprawy i plan.

Następny krok (pierwszy, który pasuje):

1. zaległa rozmowa (``plan.next_contact`` po terminie),
2. „Przekaż do front office” — kończy projekt w 60 dni albo chce zmiany,
   jeszcze nie przekazany (pasujące rekrutacje z „Pasuje też do”),
3. prośba o opinię menedżera (D9; tylko krąg D11),
4. „podnieść rytm?” (``cadence.suggestion``),
5. rozmowa w najbliższych 7 dniach,
6. nic pilnego (``kind: null``).

Karta, jak zakładka „Opieka”, dopisuje plan żywego kontraktu (świeży kontrakt
nie czeka na noc); poza tym odczyt niczego nie zapisuje. Bez stawek.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.models.contract_care import (
    CarePlanItem,
    ClientArea,
    ClientFeedbackSession,
    TechCard,
    TechVendor,
)
from app.models.skill import Skill
from app.models.user import User
from app.services.care import access as care_access
from app.services.care import cadence as care_cadence
from app.services.care import (
    client_feedback,
    client_people,
    front_office,
    health,
    records,
)
from app.services.care import plan as care_plan
from app.services.care import skills as care_skills
from app.services.care import tech_map
from app.services.care.access import CareContract
from app.services.care.cadence_rules import level_on
from app.services.care.demand import TECH_CARDS_LINK
from app.services.care.week import client_managers

logger = logging.getLogger(__name__)

UPCOMING_STEP_DAYS = 7
MATCHES_SHOWN = 3
QUESTIONS_MAX = 4

FEEDBACK_REASON_LABELS = {
    "pre_end": "konsultant kończy współpracę w 30 dni",
    "quarterly": "kwartał bez opinii",
}
FRONT_OFFICE_LABELS = {
    "project_end": "kończy projekt w 60 dni",
    "wants_change": "chce zmiany projektu",
}
SIGNAL_LABELS = {
    "weak_feedback": "słaba opinia menedżera",
    "order_end": "koniec zamówienia blisko",
    "wants_change": "chce zmiany projektu",
    "attrition_risk": "ryzyko odejścia",
}


def _days(count: int) -> str:
    return "1 dzień" if count == 1 else f"{count} dni"


def as_date(value: Any) -> Optional[date]:
    """Data z mapy — świeżo policzonej albo z cache (tam jako tekst ISO)."""

    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def month_text(value: Optional[date]) -> Optional[str]:
    return value.strftime("%Y-%m") if value is not None else None


# ── Wiedza o projekcie (ostatnia karta) ─────────────────────────────────────


async def latest_card(db: AsyncSession, contract_id: int) -> Optional[TechCard]:
    return await db.scalar(
        select(TechCard)
        .where(TechCard.contract_id == contract_id, TechCard.is_draft.is_(False))
        .order_by(TechCard.interview_on.desc(), TechCard.id.desc())
        .limit(1)
    )


async def _card_conversation(db: AsyncSession, card_id: int) -> Optional[int]:
    return await db.scalar(
        select(TECH_CARDS_LINK.c.care_conversation_id).where(
            TECH_CARDS_LINK.c.id == card_id
        )
    )


async def known_project(
    db: AsyncSession, contract: CareContract, *, card: Optional[TechCard] = None
) -> Optional[dict[str, Any]]:
    """Co wiemy o projekcie: ostatnia sfinalizowana karta + menedżer z drzewa.

    ``None``, gdy nie ma ani karty, ani menedżera. Bez karty ``source`` jest
    ``null`` (wiemy tylko, kto jest menedżerem).
    """

    card = card if card is not None else await latest_card(db, contract.id)
    manager = (await client_managers(db, [contract])).get(contract.id)
    if card is None and manager is None:
        return None
    manager_ref = (
        {
            "contact_id": manager["id"],
            "name": manager["name"],
            "position": manager["position"],
        }
        if manager
        else None
    )
    if card is None:
        return {
            "source": None,
            "area": manager["area"] if manager else None,
            "manager": manager_ref,
            "team_size": None,
            "team_externals": None,
            "technologies": [],
            "vendors": [],
            "hiring": None,
            "project_end_month": None,
            "quote": None,
        }
    skills, vendors = await records.card_relations(db, [card.id])
    skill_rows = (
        (
            await db.execute(
                select(Skill.id, Skill.canonical_name).where(
                    Skill.id.in_(skills.get(card.id) or [-1])
                )
            )
        ).all()
        if skills.get(card.id)
        else []
    )
    vendor_names = (
        (
            await db.scalars(
                select(TechVendor.name)
                .where(TechVendor.id.in_(vendors.get(card.id) or [-1]))
                .order_by(TechVendor.name)
            )
        ).all()
        if vendors.get(card.id)
        else []
    )
    area = None
    if card.client_area_id is not None:
        area_name = await db.scalar(
            select(ClientArea.name).where(ClientArea.id == card.client_area_id)
        )
        if area_name is not None:
            area = {"id": card.client_area_id, "name": area_name}
    if area is None and manager is not None:
        area = manager["area"]
    names = await care_access.user_names(db, [card.author_user_id])
    conversation_id = await _card_conversation(db, card.id)
    return {
        "source": {
            "on": card.interview_on,
            "author_name": names.get(card.author_user_id)
            if card.author_user_id
            else None,
            "kind": "conversation" if conversation_id is not None else "tech_card",
        },
        "area": area,
        "manager": manager_ref,
        "team_size": card.team_size,
        "team_externals": card.team_externals,
        "technologies": sorted(
            (
                {"skill_id": sid, "name": care_skills.display_name(name)}
                for sid, name in skill_rows
            ),
            key=lambda item: item["name"].casefold(),
        ),
        "vendors": list(vendor_names),
        "hiring": (
            {"roles": list(card.hiring_roles or []), "source": card.hiring_source}
            if card.hiring
            else None
        ),
        "project_end_month": (
            None if card.project_end_unknown else month_text(card.project_end_on)
        ),
        "quote": card.memorable_quote,
    }


# ── Sprawy (serwis B2) ──────────────────────────────────────────────────────


async def contract_cases(
    db: AsyncSession, contract_id: int, viewer: User
) -> list[dict[str, Any]]:
    """Sprawy kontraktu z serwisu spraw (``admin_cases.queries.cases_for_contract``)."""

    # Import w funkcji: moduł spraw ciągnie serwisy HR, a karta jest w opiece.
    from app.services.admin_cases.queries import cases_for_contract  # noqa: PLC0415

    return list(await cases_for_contract(db, contract_id, viewer))


# ── Następny krok ───────────────────────────────────────────────────────────


def _empty_step(upcoming: Optional[care_plan.NextContact]) -> dict[str, Any]:
    detail = None
    if upcoming is not None:
        detail = f"następna rozmowa {upcoming.due_on.strftime('%d.%m')}"
    return {"kind": None, "label": "Nic pilnego", "detail": detail}


async def next_step(
    db: AsyncSession,
    contract: CareContract,
    *,
    user: User,
    today: date,
    upcoming: Optional[care_plan.NextContact],
    owners: dict[int, care_access.OwnerChoice],
    level: Optional[str],
    include_feedback: bool,
    scope_clause: Optional[ColumnElement],
) -> dict[str, Any]:
    if not contract.is_live:
        return {"kind": None, "label": "Kontrakt zakończony", "detail": None}
    overdue = upcoming is not None and upcoming.due_on < today
    if overdue:
        days = (today - upcoming.due_on).days
        return {
            "kind": "conversation",
            "label": "Porozmawiaj z konsultantem",
            "detail": f"zaległe {_days(days)} · {upcoming.label}",
        }
    active = (await front_office.active_redeploy(db, [contract.id]))[contract.id]
    reasons = front_office.eligibility(contract, active, today)
    handed = (await front_office.handoffs(db, [contract.id]))[contract.id]
    if reasons and not handed:
        step: dict[str, Any] = {
            "kind": "front_office",
            "label": "Przekaż do front office",
            "detail": " · ".join(FRONT_OFFICE_LABELS.get(r, r) for r in reasons),
            "matches": [],
        }
        try:
            result = await front_office.overview(
                db,
                contract,
                today=today,
                profile_user_id=user.id,
                scope_clause=scope_clause,
            )
            step["matches"] = [
                {
                    "job_id": job["job_id"],
                    "title": job["title"],
                    "client_name": job["client_name"],
                    "score": job["score"],
                }
                for job in result["jobs"][:MATCHES_SHOWN]
            ]
        except Exception:  # noqa: BLE001 — dopasowania to dodatek, nie bramka
            logger.exception("[care] pasujące rekrutacje dla karty pominięte")
        return step
    if include_feedback:
        requests = await client_people.feedback_requests_for(
            db, [contract], owners=owners, today=today
        )
        if requests:
            request = requests[0]
            return {
                "kind": "feedback",
                "label": f"Zbierz opinię: {request['contact_name']}",
                "detail": " · ".join(
                    FEEDBACK_REASON_LABELS.get(r, r) for r in request["reasons"]
                ),
            }
    if level is not None:
        signals = (
            await care_cadence.signals_for(
                db,
                [contract],
                today=today,
                overdue_days={},
                include_feedback=include_feedback,
            )
        )[contract.id]
        suggested = care_cadence.suggestion(level, signals)
        if suggested is not None:
            return {
                "kind": "raise_cadence",
                "label": "Podnieś rytm: "
                + care_cadence.LEVEL_LABELS.get(suggested, suggested),
                "detail": " · ".join(
                    SIGNAL_LABELS[s["kind"]]
                    for s in signals
                    if s["kind"] in SIGNAL_LABELS
                ),
            }
    if upcoming is not None and upcoming.due_on <= today + timedelta(
        days=UPCOMING_STEP_DAYS
    ):
        return {
            "kind": "conversation",
            "label": "Rozmowa " + upcoming.due_on.strftime("%d.%m"),
            "detail": upcoming.label,
        }
    return _empty_step(upcoming)


# ── Karta ───────────────────────────────────────────────────────────────────


async def _manager_feedback(
    db: AsyncSession, contract_id: int
) -> Optional[dict[str, Any]]:
    last = (await client_feedback.last_by_contract(db, [contract_id])).get(contract_id)
    if last is None:
        return None
    extension = await db.scalar(
        select(ClientFeedbackSession.extension_outlook).where(
            ClientFeedbackSession.id == last.session_id
        )
    )
    return {"avg": last.average, "extension": extension, "on": last.held_on}


def plan_row(item: CarePlanItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "kind": item.kind,
        "label": care_plan.KIND_LABELS.get(item.kind, item.kind),
        "due_on": item.due_on,
        "status": item.status,
        "skip_reason": item.skip_reason,
    }


async def consultant_card(
    db: AsyncSession,
    contract: CareContract,
    user: User,
    *,
    today: date,
    scope_clause: Optional[ColumnElement],
) -> dict[str, Any]:
    if contract.is_live:
        await care_plan.ensure_plan(
            db,
            contract.id,
            start=contract.start_date,
            end=contract.end_date,
            today=today,
        )
    include_feedback = care_access.reads_client_people(user)
    plan_items = (
        await db.scalars(
            select(CarePlanItem)
            .where(CarePlanItem.contract_id == contract.id)
            .order_by(CarePlanItem.due_on, CarePlanItem.id)
        )
    ).all()
    latest = (await care_plan.latest_conversations(db, [contract.id])).get(contract.id)
    upcoming = care_plan.next_contact(plan_items, latest, today)
    owners = await care_access.effective_owners(db, [contract])
    owner = owners[contract.id]
    periods = (await care_plan.periods_by_contract(db, [contract.id])).get(
        contract.id, []
    )
    effective = (
        level_on(contract.start_date, periods, today)
        if contract.start_date is not None
        else None
    )
    names = await care_access.user_names(db, [owner.user_id])
    satisfaction = (await health.last_satisfactions(db, [contract.id])).get(contract.id)
    overdue = (
        {contract.id: (today - upcoming.due_on).days}
        if upcoming is not None and upcoming.due_on < today
        else {}
    )
    health_value = (
        (
            await health.health_for(
                db,
                [contract],
                today=today,
                overdue_days=overdue,
                periods={contract.id: periods},
            )
        ).get(contract.id)
        if include_feedback
        else None
    )
    end = contract.end_date
    writer = await care_access.is_care_writer(db, user)
    return {
        "contract_id": contract.id,
        "candidate_id": contract.candidate_id,
        "candidate_name": contract.candidate_name,
        "client_id": contract.client_id,
        "client_name": contract.client_name,
        "role": contract.job_title,
        "form": contract.contract_type,
        "start_on": contract.start_date,
        "end_on": end,
        "owner": {
            "user_id": owner.user_id,
            "name": names.get(owner.user_id) if owner.user_id else None,
            "source": owner.source,
        },
        "cadence": (
            {
                "level": effective.level,
                "label": care_cadence.LEVEL_LABELS.get(
                    effective.level, effective.level
                ),
                "until_on": effective.until_on,
            }
            if effective is not None
            else None
        ),
        "health": health_value,
        "kpis": {
            "last_contact": (
                {
                    "on": latest.occurred_on,
                    "days_ago": (today - latest.occurred_on).days,
                }
                if latest is not None
                else None
            ),
            "satisfaction": (
                {"value": satisfaction.value, "previous": satisfaction.previous}
                if satisfaction is not None
                else None
            ),
            "manager_feedback": (
                await _manager_feedback(db, contract.id) if include_feedback else None
            ),
            "order_end": (
                {"on": end, "days": (end - today).days} if end is not None else None
            ),
        },
        "next_step": await next_step(
            db,
            contract,
            user=user,
            today=today,
            upcoming=upcoming,
            owners=owners,
            level=effective.level if effective is not None else None,
            include_feedback=include_feedback,
            scope_clause=scope_clause,
        ),
        "known_project": await known_project(db, contract),
        "cases": await contract_cases(db, contract.id, user),
        "plan": [plan_row(item) for item in plan_items],
        "can_edit": writer,
        "can_change_owner": writer,
        "can_see_feedback": include_feedback,
    }


# ── „Co u klienta” w oknie rozmowy ──────────────────────────────────────────


def gap_questions(
    gaps: list[dict[str, Any]],
    *,
    area: Optional[dict[str, Any]],
    manager_contact_id: Optional[int],
    limit: int = QUESTIONS_MAX,
) -> list[dict[str, Any]]:
    """Luki mapy klienta dotyczące działu konsultanta albo jego menedżera.

    Czysta reguła: najpierw „komu podlega” menedżer, potem dział bez źródła,
    potem technologie działu znane z jednego źródła; najwyżej ``limit``.
    """

    area_id = area["id"] if area else None
    area_name = area["name"] if area else None
    reports: list[dict[str, Any]] = []
    areas: list[dict[str, Any]] = []
    singles: list[dict[str, Any]] = []
    for gap in gaps:
        kind = gap.get("kind")
        if (
            kind == "manager_unplaced"
            and manager_contact_id is not None
            and gap["contact"]["id"] == manager_contact_id
        ):
            position = gap.get("position")
            reports.append(
                {
                    "key": f"reports_to:{manager_contact_id}",
                    "kind": "reports_to",
                    "subject": gap["contact"]["name"],
                    "detail": "Komu podlega "
                    + gap["contact"]["name"]
                    + (f" ({position})" if position else "")
                    + "?",
                    "contact_id": manager_contact_id,
                }
            )
        elif (
            kind == "area_no_source"
            and area_id is not None
            and (gap.get("area") or {}).get("id") == area_id
        ):
            seen = as_date(gap.get("last_seen"))
            areas.append(
                {
                    "key": f"area:{area_id}",
                    "kind": "area_without_source",
                    "subject": area_name,
                    "detail": (
                        "Na czym pracuje dział? Ostatnie źródło: "
                        + seen.strftime("%d.%m.%Y")
                        if isinstance(seen, date)
                        else "Na czym pracuje dział? Nie mamy żadnego źródła."
                    ),
                    "area_id": area_id,
                }
            )
        elif (
            kind == "single_source"
            and area_name is not None
            and area_name in (gap.get("areas") or [])
        ):
            singles.append(
                {
                    "key": f"single:{gap['skill_id']}",
                    "kind": "single_source",
                    "subject": gap["name"],
                    "detail": f"Czy dział używa {gap['name']}? Znamy to z jednego źródła.",
                    "area_id": area_id,
                }
            )
    return [*reports, *areas, *singles][:limit]


async def client_state(
    db: AsyncSession, contract: CareContract, *, today: date
) -> dict[str, Any]:
    """Ostatni stan „Co u klienta” i pytania z mapy klienta (odczyt)."""

    project = await known_project(db, contract)
    state = None
    source = None
    if project is not None:
        source = project["source"]
        state = {key: value for key, value in project.items() if key != "source"}
    manager = (project or {}).get("manager") or {}
    result = await tech_map.client_tech_map(db, contract.client_id, today=today)
    questions = gap_questions(
        list(result.get("gaps") or []),
        area=(project or {}).get("area"),
        manager_contact_id=manager.get("contact_id"),
    )
    return {"state": state, "source": source, "questions": questions}
