"""Konsultanci i klienci oczami back office'u (decyzje Artura z 19.11.2026).

Bez opiekuna i bez „Moi / Mój zakres”: każdy z zespołu widzi wszystkich, bo
sprawę bierze pierwsza wolna osoba. Ekrany Opieki (``/api/care/*``) zostają dla
modułu wyłączonego; tu są osobne odczyty za bramką członka zespołu, bez kwot.

* lista konsultantów — klient, koniec, otwarte sprawy (etykiety), ostatnia rozmowa,
* karta konsultanta — trzy fakty, sprawy, rozmowy, umowa,
* klienci i ściąga klienta — jak u klienta robimy rozliczenia, wejście nowej
  osoby, zamówienia i kontakty (``bo_client_notes``) plus fakty z bazy.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.back_office import BoCard, BoClientNote
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.contract_care import CareConversation
from app.models.job import Job
from app.models.user import User
from app.services.admin_cases.queries import CANDIDATE_FULL_NAME
from app.services.back_office.access import Viewer
from app.services.back_office.board import LABELS, user_names, visible_title
from app.services.back_office_team_schema import CLIENT_NOTE_BLOCKS, CLIENT_NOTE_MAX

#: Kontrakty, które back office obsługuje: trwają albo kończą się.
LIVE = (ContractStatus.active, ContractStatus.ending)
CASES_LOOKBACK_DAYS = 120
NOTE_EXCERPT = 240
BLOCK_LABELS = {
    "settlement": "Rozliczenia",
    "onboarding": "Wejście nowej osoby",
    "orders": "Zamówienia",
    "contacts": "Kontakty",
}


class SheetError(ValueError):
    """Odmowa z komunikatem dla użytkownika (422)."""


def _label(card: BoCard) -> dict[str, Any]:
    return {"id": card.id, "lane": card.lane, "label": LABELS.get(card.lane, card.lane)}


async def _open_cards_by(db: AsyncSession, column) -> dict[int, list[BoCard]]:
    out: dict[int, list[BoCard]] = {}
    for card in (
        await db.scalars(
            select(BoCard)
            .where(
                BoCard.state != "done",
                BoCard.lane != "triage",
                BoCard.source_kind != "step",
                column.is_not(None),
            )
            .order_by(BoCard.due_on.asc().nulls_last(), BoCard.id)
        )
    ).all():
        out.setdefault(getattr(card, column.key), []).append(card)
    return out


async def _last_conversations(
    db: AsyncSession, contract_ids: list[int]
) -> dict[int, tuple[date, Optional[int]]]:
    if not contract_ids:
        return {}
    out: dict[int, tuple[date, Optional[int]]] = {}
    for contract_id, occurred_on, author in (
        await db.execute(
            select(
                CareConversation.contract_id,
                CareConversation.occurred_on,
                CareConversation.author_user_id,
            )
            .where(CareConversation.contract_id.in_(contract_ids))
            .order_by(CareConversation.occurred_on, CareConversation.id)
        )
    ).all():
        out[contract_id] = (occurred_on, author)
    return out


async def consultants(db: AsyncSession) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(
                Contract.id,
                Contract.client_id,
                Client.name,
                CANDIDATE_FULL_NAME,
                Job.title,
                Contract.contract_type,
                Contract.start_date,
                Contract.end_date,
            )
            .join(Client, Client.id == Contract.client_id)
            .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
            .outerjoin(Job, Job.id == Contract.job_id)
            .where(Contract.status.in_(LIVE))
            .order_by(Client.name, CANDIDATE_FULL_NAME)
        )
    ).all()
    contract_ids = [row[0] for row in rows]
    cases = await _open_cards_by(db, BoCard.contract_id)
    talks = await _last_conversations(db, contract_ids)
    names = await user_names(db, [author for _d, author in talks.values()])
    return {
        "items": [
            {
                "contract_id": contract_id,
                "client_id": client_id,
                "client_name": client_name,
                "name": (candidate or "").strip() or f"kontrakt #{contract_id}",
                "job_title": job_title,
                "contract_type": getattr(contract_type, "value", contract_type),
                "start_date": start_date,
                "end_date": end_date,
                "open_cases": [_label(c) for c in cases.get(contract_id, [])],
                "last_conversation": (
                    {
                        "on": talks[contract_id][0],
                        "by": names.get(talks[contract_id][1]),
                    }
                    if contract_id in talks
                    else None
                ),
            }
            for (
                contract_id,
                client_id,
                client_name,
                candidate,
                job_title,
                contract_type,
                start_date,
                end_date,
            ) in rows
        ]
    }


async def consultant_card(
    db: AsyncSession, contract_id: int, *, viewer: Viewer, user: User, today: date
) -> Optional[dict[str, Any]]:
    row = (
        await db.execute(
            select(Contract, Client.name, CANDIDATE_FULL_NAME, Job.title)
            .join(Client, Client.id == Contract.client_id)
            .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
            .outerjoin(Job, Job.id == Contract.job_id)
            .where(Contract.id == contract_id)
        )
    ).first()
    if row is None:
        return None
    contract, client_name, candidate, job_title = row
    since = datetime.now(timezone.utc) - timedelta(days=CASES_LOOKBACK_DAYS)
    cards = (
        await db.scalars(
            select(BoCard)
            .where(
                BoCard.contract_id == contract_id,
                BoCard.source_kind != "step",
                BoCard.lane != "triage",
                (BoCard.state != "done") | (BoCard.closed_at >= since),
            )
            .order_by(BoCard.state == "done", BoCard.due_on.asc().nulls_last())
        )
    ).all()
    talks = (
        await db.scalars(
            select(CareConversation)
            .where(CareConversation.contract_id == contract_id)
            .order_by(CareConversation.occurred_on.desc(), CareConversation.id.desc())
            .limit(5)
        )
    ).all()
    names = await user_names(
        db, [c.assignee_user_id for c in cards] + [t.author_user_id for t in talks]
    )
    open_cards = [c for c in cards if c.state != "done"]
    end = contract.end_date
    return {
        "contract_id": contract.id,
        "client_id": contract.client_id,
        "client_name": client_name,
        "name": (candidate or "").strip() or f"kontrakt #{contract.id}",
        "job_title": job_title,
        "contract_type": getattr(
            contract.contract_type, "value", contract.contract_type
        ),
        "status": getattr(contract.status, "value", contract.status),
        "start_date": contract.start_date,
        "end_date": end,
        "days_to_end": (end - today).days if end is not None else None,
        "last_conversation": (
            {"on": talks[0].occurred_on, "by": names.get(talks[0].author_user_id)}
            if talks
            else None
        ),
        "open_count": len(open_cards),
        "cases": [
            {
                **_label(c),
                "title": visible_title(c, viewer=viewer, user=user),
                "state": c.state,
                "due_on": c.due_on,
                "closed_at": c.closed_at,
                "assignee": (
                    {"id": c.assignee_user_id, "name": names.get(c.assignee_user_id)}
                    if c.assignee_user_id
                    else None
                ),
            }
            for c in cards
        ],
        "conversations": [
            {
                "on": t.occurred_on,
                "by": names.get(t.author_user_id),
                "channel": t.channel,
                "satisfaction": t.satisfaction,
                "note": (t.note or "")[:NOTE_EXCERPT] or None,
            }
            for t in talks
        ],
    }


async def _delivery_leads(
    db: AsyncSession, client_ids: list[int]
) -> dict[int, list[str]]:
    from app.services.care.portfolio import _delivery_leads as care_leads  # noqa: PLC0415

    leads = await care_leads(db, client_ids)
    return {
        client_id: [name for _uid, name in rows] for client_id, rows in leads.items()
    }


async def clients(db: AsyncSession, *, today: date) -> dict[str, Any]:
    horizon = today + timedelta(days=60)
    rows = (
        await db.execute(
            select(
                Client.id,
                Client.name,
                func.count(Contract.id),
                func.count(Contract.id).filter(
                    Contract.end_date.is_not(None),
                    Contract.end_date >= today,
                    Contract.end_date <= horizon,
                ),
            )
            .join(Contract, Contract.client_id == Client.id)
            .where(Contract.status.in_(LIVE))
            .group_by(Client.id, Client.name)
            .order_by(func.count(Contract.id).desc(), Client.name)
        )
    ).all()
    client_ids = [row[0] for row in rows]
    cases = await _open_cards_by(db, BoCard.client_id)
    leads = await _delivery_leads(db, client_ids)
    noted = set(
        (
            await db.scalars(
                select(BoClientNote.client_id).where(
                    BoClientNote.client_id.in_(client_ids or [0])
                )
            )
        ).all()
    )
    return {
        "items": [
            {
                "client_id": client_id,
                "name": name,
                "consultants": int(count),
                "ending_60": int(ending),
                "open_cases": len(cases.get(client_id, [])),
                "delivery_leads": leads.get(client_id, []),
                "has_sheet": client_id in noted,
            }
            for client_id, name, count, ending in rows
        ]
    }


async def client_sheet(
    db: AsyncSession, client_id: int, *, today: date
) -> Optional[dict[str, Any]]:
    client = await db.get(Client, client_id)
    if client is None:
        return None
    notes = {
        n.block: n
        for n in (
            await db.scalars(
                select(BoClientNote).where(BoClientNote.client_id == client_id)
            )
        ).all()
    }
    rule = (
        await db.execute(
            text(
                "SELECT mode, instructions FROM client_settlement_rules "
                "WHERE client_id = :client_id"
            ),
            {"client_id": client_id},
        )
    ).first()
    horizon = today + timedelta(days=60)
    live = (
        await db.execute(
            select(Contract.id, CANDIDATE_FULL_NAME, Contract.end_date)
            .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
            .where(Contract.client_id == client_id, Contract.status.in_(LIVE))
            .order_by(Contract.end_date.asc().nulls_last())
        )
    ).all()
    open_cases = int(
        await db.scalar(
            select(func.count())
            .select_from(BoCard)
            .where(
                BoCard.client_id == client_id,
                BoCard.state != "done",
                BoCard.source_kind != "step",
                BoCard.lane != "triage",
            )
        )
        or 0
    )
    names = await user_names(db, [n.updated_by for n in notes.values()])
    leads = (await _delivery_leads(db, [client_id])).get(client_id, [])
    return {
        "client_id": client_id,
        "name": client.name,
        "consultants": len(live),
        "open_cases": open_cases,
        "ending_60": [
            {"contract_id": cid, "name": (who or "").strip(), "end_date": end}
            for cid, who, end in live
            if end is not None and today <= end <= horizon
        ],
        "delivery_leads": leads,
        "settlement_rule": (
            {"mode": rule[0], "instructions": rule[1] or None} if rule else None
        ),
        "blocks": [
            {
                "id": block,
                "label": BLOCK_LABELS[block],
                "body": notes[block].body if block in notes else "",
                "updated_by": names.get(notes[block].updated_by)
                if block in notes
                else None,
                "updated_at": notes[block].updated_at if block in notes else None,
            }
            for block in CLIENT_NOTE_BLOCKS
        ],
    }


async def save_note(
    db: AsyncSession, *, client_id: int, block: str, body: str, actor: User
) -> None:
    if block not in CLIENT_NOTE_BLOCKS:
        raise SheetError("Nie ma takiej części ściągi.")
    if await db.get(Client, client_id) is None:
        raise SheetError("Nie ma takiego klienta.")
    value = (body or "").replace("\x00", "").strip()
    if len(value) > CLIENT_NOTE_MAX:
        raise SheetError(f"Ta część może mieć najwyżej {CLIENT_NOTE_MAX} znaków.")
    note = await db.get(BoClientNote, (client_id, block))
    now = datetime.now(timezone.utc)
    if not value:
        if note is not None:
            await db.delete(note)
        await db.flush()
        return
    if note is None:
        db.add(
            BoClientNote(
                client_id=client_id,
                block=block,
                body=value,
                updated_by=actor.id,
                updated_at=now,
            )
        )
    else:
        note.body = value
        note.updated_by = actor.id
        note.updated_at = now
    await db.flush()
