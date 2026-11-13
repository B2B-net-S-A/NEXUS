"""„Dodaj dodatek do rozliczenia” z karty sprawy (potrzeba Finansów z 13.11.2026).

Konsultant pisze w sprawie, że dolicza do faktury premię za polecenie,
weryfikację techniczną albo szkolenie („X doliczy 200 zł za weryfikację
techniczną za listopad”). Osoba z back office'u zapisuje to z karty: kto
(kontrakt — z karty albo wybrany), za jaki okres, jaką kwotę. Dodatek wchodzi
jako „zgłoszony” do rozliczeń klientów i czeka na Finanse
(``services/client_settlements/extras.py``).

Kwoty dodatków na karcie widzi ten, kto je wpisał, oraz osoby z dostępem do
kwot back office'u (Płace, admin) — jak reszta kart (``access.py``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.back_office import BoCard, BoCardEvent
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_settlement_extra import ClientSettlementExtra
from app.models.contract import Contract, ContractStatus
from app.services.back_office.access import Viewer
from app.services.client_settlements import extras as settlement_extras

PEOPLE_LIMIT = 20
_FULL_NAME = func.nullif(func.concat_ws(" ", Candidate.name, Candidate.lastname), "")
_LIVE = (ContractStatus.active, ContractStatus.ending, ContractStatus.ended)
EVENT_ACTION = "settlement_extra"


def month_label(month: str) -> str:
    """„2026-10” → „październik 2026”."""

    from app.services.client_settlements.consultant import MONTHS  # noqa: PLC0415

    year, mon = (int(x) for x in month.split("-"))
    return f"{MONTHS[mon - 1]} {year}"


async def _person(db: AsyncSession, contract_id: int) -> Optional[dict[str, Any]]:
    row = (
        await db.execute(
            select(Contract.id, _FULL_NAME, Client.name)
            .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
            .outerjoin(Client, Client.id == Contract.client_id)
            .where(Contract.id == contract_id)
        )
    ).first()
    if row is None:
        return None
    return {
        "contract_id": row[0],
        "person": row[1] or f"Kontrakt {row[0]}",
        "client": row[2],
    }


async def people(db: AsyncSession, query: str) -> list[dict[str, Any]]:
    """Osoby z kontraktem (trwającym albo zakończonym) po imieniu i nazwisku."""

    words = [w for w in " ".join(query.split()).split(" ") if len(w) >= 2][:3]
    if not words:
        return []
    rows = await db.execute(
        select(Contract.id, _FULL_NAME, Client.name)
        .join(Candidate, Candidate.id == Contract.candidate_id)
        .outerjoin(Client, Client.id == Contract.client_id)
        .where(
            Contract.status.in_(_LIVE),
            Contract.client_id.is_not(None),
            and_(
                *(
                    or_(
                        Candidate.name.ilike(f"%{w}%"),
                        Candidate.lastname.ilike(f"%{w}%"),
                    )
                    for w in words
                )
            ),
        )
        .order_by(Contract.status, Candidate.lastname, Contract.id.desc())
        .limit(PEOPLE_LIMIT)
    )
    return [
        {"contract_id": cid, "person": name or f"Kontrakt {cid}", "client": client}
        for cid, name, client in rows.all()
    ]


def _sees(extra: ClientSettlementExtra, viewer: Viewer) -> bool:
    return viewer.sees_amounts or extra.created_by == viewer.user_id


async def card_view(db: AsyncSession, card: BoCard, viewer: Viewer) -> dict[str, Any]:
    from app.services.back_office.board import user_names  # noqa: PLC0415

    items = list(
        (
            await db.scalars(
                select(ClientSettlementExtra)
                .where(ClientSettlementExtra.bo_card_id == card.id)
                .order_by(ClientSettlementExtra.created_at, ClientSettlementExtra.id)
            )
        ).all()
    )
    names = await user_names(db, [e.created_by for e in items])
    persons = {
        cid: await _person(db, cid)
        for cid in {e.contract_id for e in items}
        | ({card.contract_id} if card.contract_id else set())
    }
    return {
        "contract": persons.get(card.contract_id) if card.contract_id else None,
        "kinds": [
            {"key": k, "label": settlement_extras.KIND_LABELS[k]}
            for k in settlement_extras.STAFF_KINDS
        ],
        "items": [
            {
                **settlement_extras.as_dict(
                    e, [], amounts=_sees(e, viewer), names=names
                ),
                "person": (persons.get(e.contract_id) or {}).get("person"),
            }
            for e in items
        ],
    }


async def add(
    db: AsyncSession,
    card: BoCard,
    *,
    contract_id: int,
    month: str,
    kind: str,
    amount: Any,
    description: Optional[str],
    actor_id: int,
    now: datetime,
) -> ClientSettlementExtra:
    extra = await settlement_extras.create(
        db,
        contract_id,
        month,
        kind=kind,
        amount=amount,
        description=description,
        source=settlement_extras.SOURCE_BACK_OFFICE,
        actor_id=actor_id,
        now=now,
        bo_card_id=card.id,
    )
    person = await _person(db, contract_id)
    db.add(
        BoCardEvent(
            card_id=card.id,
            actor_user_id=actor_id,
            action=EVENT_ACTION,
            details={
                "note": f"{settlement_extras.KIND_LABELS[extra.kind]}"
                f" za {month_label(extra.period_month)}"
                f" ({(person or {}).get('person', 'kontrakt')}) — czeka na Finanse.",
                "extra_id": extra.id,
            },
            created_at=now,
        )
    )
    await db.flush()
    return extra
