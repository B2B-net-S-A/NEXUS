"""Odczyt tablicy back office'u: zespoły, kolumny, karty, liczby, panel karty.

Kwoty dostaje przy odczycie tylko osoba z Płacami. Tytuł sprawy, której czytający
nie ma prawa czytać, zostaje „Sprawa: <obszar>” (reguła ``redact_case_title``),
negocjacje też. Odczyt niczego nie zapisuje.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.back_office import BoCard, BoCardEvent
from app.models.user import User
from app.services.admin_cases import rules as case_rules
from app.services.admin_cases import service as cases
from app.services.back_office.access import Viewer
from app.services.back_office.service import (
    IN_PROGRESS_LIMIT,
    in_progress_count,
    reads_case,
)
from app.services.back_office_schema import TEAM_LANES, TEAMS, TRIAGE_LANE

TEAM_LABELS = {
    "care": "Opieka",
    "finance": "Finanse",
    "contracts": "Umowy",
    "orders": "Zamówienia",
}
LANE_META: dict[str, dict[str, str]] = {
    "help": {"label": "Pomoc", "description": "Pytania, portal, kontakt 7. dnia"},
    "entry": {"label": "Wejścia", "description": "Nowa osoba u klienta"},
    "bench": {
        "label": "Ławka",
        "description": "60 dni przed końcem, bezpiecznik 14 dni",
    },
    "exit": {"label": "Wyjścia", "description": "Po decyzji „nie przepinamy”"},
    "timesheet": {"label": "Raporty", "description": "Raporty godzin do akceptu"},
    "bonus": {
        "label": "Premie",
        "description": "Jedna karta na okres, akcept zbiorczy",
    },
    "invoice": {
        "label": "Faktury konsultantów",
        "description": "Z portalu i rozliczenia@",
    },
    "changes": {
        "label": "Zmiany w zamówieniach",
        "description": "Audyt miesiąca: nieodhaczone",
    },
    "draft": {"label": "Do umowy", "description": "Kontrakt w szkicu, bez umowy"},
    "sign": {"label": "Podpis", "description": "Umowy czekające na podpis"},
    "annex": {"label": "Aneksy i stawki", "description": "Negocjacje, zmiany stawek"},
    "ending": {
        "label": "Zakończenia",
        "description": "Kontrakty w stanie „kończy się”",
    },
    "mail": {"label": "Poczta zamówień", "description": "Do przejrzenia"},
    "gap": {"label": "Przerwy", "description": "Osoba pracuje bez zamówienia"},
    "extend": {
        "label": "Przedłużenia",
        "description": "45 dni przed końcem zamówienia",
    },
    "md": {
        "label": "Zużycie MD",
        "description": "Ostatni import: wiersze bez przypisania",
    },
}
_ACTIONS = {
    "timesheet": ("approve", "return"),
    "bonus": ("approve_all", "cancel_all"),
    "changes": ("mark_done",),
}


def _case_hidden(card: BoCard, *, viewer: Viewer, user: User) -> bool:
    return (
        card.source_kind == "case"
        and card.assignee_user_id != user.id
        and not reads_case(card, viewer=viewer, user=user)
    )


def visible_title(card: BoCard, *, viewer: Viewer, user: User) -> str:
    if not _case_hidden(card, viewer=viewer, user=user):
        return card.title
    area = (card.meta or {}).get("area", "other")
    return f"Sprawa: {case_rules.AREA_LABELS.get(area, area)}"


async def user_names(db: AsyncSession, ids: Iterable[Optional[int]]) -> dict[int, str]:
    wanted = {uid for uid in ids if uid is not None}
    if not wanted:
        return {}
    return dict(
        (await db.execute(select(User.id, User.name).where(User.id.in_(wanted)))).all()
    )


async def bonus_totals(db: AsyncSession) -> dict[tuple[int, int], list[dict[str, Any]]]:
    rows = (
        (
            await db.execute(
                text(
                    """
                    SELECT period_year AS y, period_month AS m, currency,
                           sum(amount) AS total
                    FROM hr_bonuses WHERE status = 'proposed'
                    GROUP BY 1, 2, 3
                    """
                )
            )
        )
        .mappings()
        .all()
    )
    out: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault((row["y"], row["m"]), []).append(
            {"total": str(row["total"]), "currency": row["currency"]}
        )
    return out


def card_payload(
    card: BoCard,
    *,
    viewer: Viewer,
    user: User,
    names: dict[int, str],
    steps: Optional[dict[int, list[BoCard]]] = None,
    totals: Optional[dict[tuple[int, int], list[dict[str, Any]]]] = None,
) -> dict[str, Any]:
    meta = card.meta or {}
    children = (steps or {}).get(card.id) or []
    hidden = _case_hidden(card, viewer=viewer, user=user)
    amounts = None
    if card.source_kind == "bonus" and viewer.sees_amounts and totals is not None:
        amounts = totals.get((meta.get("year"), meta.get("month")))
    actions: tuple[str, ...] = ()
    if viewer.owns(card.team) and card.source_kind in _ACTIONS:
        actions = _ACTIONS[card.source_kind]
        if card.source_kind == "bonus" and not viewer.sees_amounts:
            actions = ()
    return {
        "id": card.id,
        "team": card.team,
        "lane": card.lane,
        "source_kind": card.source_kind,
        "title": visible_title(card, viewer=viewer, user=user),
        "person": None if hidden else card.person,
        "client": None if hidden else card.client_label,
        "state": card.state,
        "waiting_on": card.waiting_on,
        "due_on": card.due_on,
        "href": card.href,
        "assignee": (
            {"id": card.assignee_user_id, "name": names.get(card.assignee_user_id)}
            if card.assignee_user_id
            else None
        ),
        "substituting": card.substituting,
        "created_at": meta.get("since") or card.created_at,
        "updated_at": card.updated_at,
        "escalated": card.escalated_at is not None,
        "priority": (
            {
                "user_id": card.priority_user_id,
                "name": names.get(card.priority_user_id),
                "until": card.priority_until,
            }
            if card.priority_user_id
            else None
        ),
        "needs_review": card.needs_review,
        "triage_guess": meta.get("triage_guess"),
        "case_id": card.case_id if card.source_kind == "case" else None,
        "case_source": meta.get("case_source"),
        "actions": list(actions),
        "amounts": amounts,
        "count": meta.get("count"),
        "steps": (
            {
                "done": sum(1 for c in children if c.state == "done"),
                "total": len(children),
            }
            if children
            else None
        ),
        "parent_title": meta.get("parent_title"),
        "meta": {
            k: meta[k]
            for k in ("timesheet_id", "year", "month", "item_key", "gap_id")
            if k in meta
        },
    }


async def board(
    db: AsyncSession, *, user: User, viewer: Viewer, today: date
) -> dict[str, Any]:
    rows = (
        await db.scalars(
            select(BoCard)
            .where(BoCard.state != "done")
            .order_by(BoCard.due_on.asc().nulls_last(), BoCard.id)
        )
    ).all()
    # Krok własnego zespołu widać w panelu sprawy, nie drugi raz w kolumnie.
    parent_team = {c.id: c.team for c in rows}
    children: dict[int, list[BoCard]] = {}
    all_children = (
        await db.scalars(select(BoCard).where(BoCard.source_kind == "step"))
    ).all()
    for child in all_children:
        children.setdefault(child.parent_card_id, []).append(child)
    cards = [
        c
        for c in rows
        if c.lane != TRIAGE_LANE
        and not (c.parent_card_id and parent_team.get(c.parent_card_id) == c.team)
    ]
    names = await user_names(
        db, [c.assignee_user_id for c in rows] + [c.priority_user_id for c in rows]
    )
    totals = await bonus_totals(db) if viewer.sees_amounts else None
    payload = [
        card_payload(
            c, viewer=viewer, user=user, names=names, steps=children, totals=totals
        )
        for c in cards
    ]
    triage = (
        [
            card_payload(c, viewer=viewer, user=user, names=names)
            for c in rows
            if c.lane == TRIAGE_LANE
        ]
        if viewer.is_lead
        else []
    )
    return {
        "today": today,
        "teams": [
            {
                "id": team,
                "label": TEAM_LABELS[team],
                "lanes": [{"id": lane, **LANE_META[lane]} for lane in TEAM_LANES[team]],
            }
            for team in TEAMS
        ],
        "cards": payload,
        "triage": triage,
        "me": {
            "user_id": user.id,
            "name": user.name,
            "teams": sorted(viewer.teams),
            "is_lead": viewer.is_lead,
            "cases_handler": cases.is_handler(user),
            "sees_amounts": viewer.sees_amounts,
            "in_progress": await in_progress_count(db, user.id),
            "limit": IN_PROGRESS_LIMIT,
        },
        "counts": {
            "unassigned": sum(1 for c in cards if c.assignee_user_id is None),
            "overdue_unassigned": sum(
                1
                for c in cards
                if c.assignee_user_id is None and c.due_on and c.due_on < today
            ),
            "escalated": sum(1 for c in cards if c.escalated_at is not None),
            "review": sum(1 for c in cards if c.needs_review),
        },
    }


async def card_detail(
    db: AsyncSession, card: BoCard, *, user: User, viewer: Viewer
) -> dict[str, Any]:
    children = list(
        (
            await db.scalars(
                select(BoCard)
                .where(BoCard.parent_card_id == card.id)
                .order_by(BoCard.step_order)
            )
        ).all()
    )
    events = (
        await db.scalars(
            select(BoCardEvent)
            .where(BoCardEvent.card_id == card.id)
            .order_by(BoCardEvent.created_at.desc(), BoCardEvent.id.desc())
            .limit(50)
        )
    ).all()
    names = await user_names(
        db,
        [card.assignee_user_id, card.priority_user_id]
        + [c.assignee_user_id for c in children]
        + [e.actor_user_id for e in events],
    )
    totals = await bonus_totals(db) if viewer.sees_amounts else None
    out = card_payload(
        card,
        viewer=viewer,
        user=user,
        names=names,
        steps={card.id: children},
        totals=totals,
    )
    out["step_cards"] = [
        {
            "id": c.id,
            "label": c.title,
            "team": c.team,
            "team_label": TEAM_LABELS[c.team],
            "state": c.state,
            "updated_at": c.updated_at,
            "assignee": (
                {"id": c.assignee_user_id, "name": names.get(c.assignee_user_id)}
                if c.assignee_user_id
                else None
            ),
            "can_act": viewer.owns(c.team),
        }
        for c in children
    ]
    can_read_notes = viewer.owns(card.team) or card.assignee_user_id == user.id
    out["events"] = [
        {
            "action": e.action,
            "actor": names.get(e.actor_user_id) if e.actor_user_id else None,
            "at": e.created_at,
            "note": (e.details or {}).get("note") or (e.details or {}).get("body")
            if can_read_notes
            else None,
        }
        for e in events
    ]
    if card.source_kind == "bonus" and viewer.sees_amounts:
        out["bonuses"] = await _bonus_rows(db, card)
    return out


async def _bonus_rows(db: AsyncSession, card: BoCard) -> list[dict[str, Any]]:
    meta = card.meta or {}
    rows = (
        (
            await db.execute(
                text(
                    """
                    SELECT b.id, u.name AS person, b.category, b.amount, b.currency,
                           b.eligible_on
                    FROM hr_bonuses b JOIN users u ON u.id = b.recipient_user_id
                    WHERE b.status = 'proposed' AND b.period_year = :y
                      AND b.period_month = :m
                    ORDER BY u.name, b.id
                    """
                ),
                {"y": meta.get("year"), "m": meta.get("month")},
            )
        )
        .mappings()
        .all()
    )
    return [{**dict(row), "amount": str(row["amount"])} for row in rows]
