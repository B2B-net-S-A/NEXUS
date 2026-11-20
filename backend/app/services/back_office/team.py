"""Skład jednego zespołu back office'u (decyzje Artura 10.11 i 19.11.2026).

Jeden zespół zamiast czterech: wiersz w ``bo_members`` z rolą (zastępca Heada,
recepcja, księgowa, zespół) i przełącznikiem „przyjmuje rozmowy z portalu”.
Head zostaje w „Struktura” (``hr_divisions``); 19.11 Artur zostawił go pustym,
więc kierownikiem kolejki jest admin. Działy na zewnątrz z osobą kontaktową
leżą w ``app_settings['back_office'].outside_contacts``.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.back_office import BoCard, BoMember
from app.models.user import User
from app.services.back_office import access
from app.services.back_office.board import OUTSIDE_LABELS, user_names
from app.services.back_office_team_schema import MEMBER_ROLES, OUTSIDE_TEAMS
from app.services.hr import people
from app.services.hr.structure import load_division_heads

ROLE_LABELS = {
    "deputy": "Zastępca Heada",
    "reception": "Recepcja",
    "accountant": "Księgowa",
    "member": "Zespół",
}
INACTIVE_DETAIL = "Nie ma takiego aktywnego konta."


class TeamError(ValueError):
    """Odmowa z komunikatem dla użytkownika (422)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _open_cards_by_holder(db: AsyncSession) -> dict[int, list[BoCard]]:
    out: dict[int, list[BoCard]] = {}
    for card in (
        await db.scalars(
            select(BoCard).where(
                BoCard.state != "done", BoCard.assignee_user_id.is_not(None)
            )
        )
    ).all():
        out.setdefault(card.assignee_user_id, []).append(card)
    return out


async def staff_candidates(db: AsyncSession) -> list[dict[str, Any]]:
    integration_ids = await people.integration_account_ids(db)
    return [
        {"id": person.id, "name": person.name}
        for person in (
            await db.scalars(
                select(User).where(User.is_active.is_(True)).order_by(User.name)
            )
        ).all()
        if people.is_staff_account(person, integration_ids=integration_ids)
    ]


async def team_view(db: AsyncSession, *, today: date) -> dict[str, Any]:
    members = (
        await db.scalars(
            select(BoMember).order_by(BoMember.created_at, BoMember.user_id)
        )
    ).all()
    member_ids = [m.user_id for m in members]
    held = await _open_cards_by_holder(db)
    contacts = (await access.load_settings(db)).get("outside_contacts") or {}
    head_id = (await load_division_heads(db)).get("back_office")
    contact_ids = [v for v in contacts.values() if isinstance(v, int)]
    names = await user_names(db, [*member_ids, *held.keys(), *contact_ids, head_id])

    def _overdue(cards: list[BoCard]) -> int:
        return sum(1 for c in cards if c.due_on is not None and c.due_on < today)

    keep = await access.keep_ids(db) if member_ids else set()
    outsiders = (
        [
            {
                "user_id": uid,
                "name": names.get(uid),
                "cards": len(cards),
            }
            for uid, cards in sorted(held.items(), key=lambda kv: -len(kv[1]))
            if uid not in keep
        ]
        if member_ids
        else []
    )
    return {
        "members": [
            {
                "user_id": m.user_id,
                "name": names.get(m.user_id),
                "role": m.role,
                "role_label": ROLE_LABELS[m.role],
                "takes_calls": m.takes_calls,
                "in_progress": sum(
                    1 for c in held.get(m.user_id, []) if c.state == "in_progress"
                ),
                "open": len(held.get(m.user_id, [])),
                "overdue": _overdue(held.get(m.user_id, [])),
            }
            for m in members
        ],
        "roles": [{"id": r, "label": ROLE_LABELS[r]} for r in MEMBER_ROLES],
        "head": (
            {"id": head_id, "name": names.get(head_id)}
            if isinstance(head_id, int)
            else None
        ),
        "outsiders": outsiders,
        "outside_contacts": [
            {
                "id": team,
                "label": OUTSIDE_LABELS[team],
                "contact": (
                    {"id": contacts[team], "name": names.get(contacts[team])}
                    if isinstance(contacts.get(team), int)
                    else None
                ),
            }
            for team in OUTSIDE_TEAMS
        ],
        # Pusty skład = zespół jeszcze z uprawnień; ekran mówi to wprost.
        "from_permissions": not member_ids,
        "candidates": await staff_candidates(db),
    }


async def set_member(
    db: AsyncSession,
    *,
    actor: User,
    user_id: int,
    role: str,
    takes_calls: bool,
) -> None:
    """Dopisz albo zmień osobę. Nowy zastępca zdejmuje rolę poprzedniemu."""

    if role not in MEMBER_ROLES:
        raise TeamError("Nie ma takiej roli w zespole.")
    person = await db.get(User, user_id)
    if person is None or not person.is_active:
        raise TeamError(INACTIVE_DETAIL)
    now = _now()
    if role == "deputy":
        previous = await db.scalar(
            select(BoMember).where(
                BoMember.role == "deputy", BoMember.user_id != user_id
            )
        )
        if previous is not None:
            previous.role = "member"
            previous.updated_at = now
            await db.flush()
    member = await db.get(BoMember, user_id)
    if member is None:
        db.add(
            BoMember(
                user_id=user_id,
                role=role,
                takes_calls=takes_calls,
                added_by=actor.id,
                created_at=now,
                updated_at=now,
            )
        )
    else:
        member.role = role
        member.takes_calls = takes_calls
        member.updated_at = now
    await db.flush()


async def remove_member(db: AsyncSession, *, user_id: int) -> None:
    member = await db.get(BoMember, user_id)
    if member is None:
        raise TeamError("Tej osoby nie ma w zespole.")
    await db.delete(member)
    await db.flush()


async def outside_contacts_value(
    db: AsyncSession, contacts: dict[str, Optional[int]]
) -> dict[str, Optional[int]]:
    """Sprawdza działy i konta; zwraca pełną mapę do zapisu w ustawieniach."""

    unknown = set(contacts) - set(OUTSIDE_TEAMS)
    if unknown:
        raise TeamError("Nie ma takiego działu.")
    wanted = {v for v in contacts.values() if v is not None}
    if wanted:
        found = set(
            (
                await db.scalars(
                    select(User.id).where(User.id.in_(wanted), User.is_active.is_(True))
                )
            ).all()
        )
        if wanted - found:
            raise TeamError(INACTIVE_DETAIL)
    current = (await access.load_settings(db)).get("outside_contacts") or {}
    return {team: contacts.get(team, current.get(team)) for team in OUTSIDE_TEAMS}


async def member_count(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.count()).select_from(BoMember)) or 0)
