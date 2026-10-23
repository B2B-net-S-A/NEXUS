"""Opinie klienta o pracy konsultantów (etap 2, D9–D11, 17.10.2026).

Opinia to rozmowa z menedżerem u klienta (kontakt klienta) zapisana przez
opiekuna albo Delivery Leada po telefonie, spotkaniu czy mailu — formularza
wysyłanego do klienta nie ma (D10). Jedna rozmowa ocenia kilku konsultantów
(kontrakty) w skali 1–5: jakość pracy, komunikacja, samodzielność; „pomiń” =
brak wiersza oceny. Notatka jest wspólna dla rozmowy, bez danych o zdrowiu
i bez stawek (zdanie w oknie, jak w rozmowach opieki).

Kto widzi (D11): opiekun kontraktu, Delivery Lead klienta, Head of Recruitment
i administrator — bramka w ``api/contract_care.py``. Konsultant nie.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.contract import Contract, ContractStatus
from app.models.contract_care import ClientFeedbackScore, ClientFeedbackSession
from app.services.care import board_state
from app.services.contract_care_schema import FEEDBACK_SCORE_FIELDS
from app.services.hr import audit

_UNPROCESSABLE = status.HTTP_422_UNPROCESSABLE_ENTITY

FUTURE_DATE = "Rozmowa nie może mieć daty z przyszłości."
FOREIGN_CONTACT = "Opinię zapisujemy od osoby z firmy tego klienta."
FOREIGN_CONTRACT = "Oceniać można tylko konsultantów pracujących u tego klienta."
DUPLICATE_CONTRACT = "Każdego konsultanta oceniasz w jednej rozmowie raz."


@dataclass(frozen=True)
class ScoreInput:
    contract_id: int
    quality: Optional[int] = None
    communication: Optional[int] = None
    autonomy: Optional[int] = None

    @property
    def is_empty(self) -> bool:
        return all(getattr(self, field) is None for field in FEEDBACK_SCORE_FIELDS)


@dataclass(frozen=True)
class FeedbackInput:
    contact_id: int
    held_on: date
    channel: str
    extension_outlook: Optional[str]
    note: Optional[str]
    scores: tuple[ScoreInput, ...]


def average(values: Iterable[Optional[int]]) -> Optional[float]:
    """Średnia ocen bez pustych, do jednego miejsca po przecinku."""

    known = [value for value in values if value is not None]
    if not known:
        return None
    return round(sum(known) / len(known), 1)


def _score_values(score: ClientFeedbackScore) -> list[Optional[int]]:
    return [getattr(score, field) for field in FEEDBACK_SCORE_FIELDS]


def _clean(value: Optional[str]) -> Optional[str]:
    cleaned = (value or "").strip()
    return cleaned or None


async def save_feedback(
    db: AsyncSession,
    *,
    client_id: int,
    payload: FeedbackInput,
    actor_id: int,
    today: date,
) -> ClientFeedbackSession:
    """Zapisz rozmowę i oceny. Kontakt i kontrakty muszą być TEGO klienta."""

    if payload.held_on > today:
        raise HTTPException(_UNPROCESSABLE, FUTURE_DATE)
    contact = await db.get(Contact, payload.contact_id)
    if contact is None or contact.client_id != client_id:
        raise HTTPException(_UNPROCESSABLE, FOREIGN_CONTACT)
    scores = [score for score in payload.scores if not score.is_empty]
    contract_ids = [score.contract_id for score in scores]
    if len(set(contract_ids)) != len(contract_ids):
        raise HTTPException(_UNPROCESSABLE, DUPLICATE_CONTRACT)
    if contract_ids:
        rows = (
            await db.execute(
                select(Contract.id, Contract.client_id, Contract.status).where(
                    Contract.id.in_(contract_ids)
                )
            )
        ).all()
        known = {
            row[0]
            for row in rows
            if row[1] == client_id and row[2] != ContractStatus.void
        }
        if known != set(contract_ids):
            raise HTTPException(_UNPROCESSABLE, FOREIGN_CONTRACT)
    session = ClientFeedbackSession(
        client_id=client_id,
        contact_id=contact.id,
        held_on=payload.held_on,
        channel=payload.channel,
        extension_outlook=payload.extension_outlook,
        note=_clean(payload.note),
        created_by=actor_id,
    )
    db.add(session)
    await db.flush()
    for score in scores:
        db.add(
            ClientFeedbackScore(
                session_id=session.id,
                contract_id=score.contract_id,
                quality=score.quality,
                communication=score.communication,
                autonomy=score.autonomy,
            )
        )
    await db.flush()
    # Ślad bez treści notatki — tylko kto, od kogo i o których kontraktach.
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=None,
        entity_type="client",
        entity_id=client_id,
        action="care.client_feedback_saved",
        details={
            "session_id": session.id,
            "contact_id": contact.id,
            "contract_ids": sorted(contract_ids),
        },
    )
    # Klucz karty opinii jest per kontakt i wraca przy następnej prośbie —
    # zapis opinii kończy życie jej stanu na tablicy (audyt 22.10, F2).
    await board_state.clear(db, [f"feedback:{contact.id}"])
    return session


@dataclass(frozen=True)
class LastFeedback:
    session_id: int
    held_on: date
    average: Optional[float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "held_on": self.held_on,
            "average": self.average,
        }


async def _scores_by_session(
    db: AsyncSession, session_ids: Sequence[int]
) -> dict[int, list[ClientFeedbackScore]]:
    out: dict[int, list[ClientFeedbackScore]] = {sid: [] for sid in session_ids}
    if not session_ids:
        return out
    for score in (
        await db.scalars(
            select(ClientFeedbackScore)
            .where(ClientFeedbackScore.session_id.in_(list(session_ids)))
            .order_by(ClientFeedbackScore.id)
        )
    ).all():
        out[score.session_id].append(score)
    return out


async def last_by_contact(
    db: AsyncSession, contact_ids: Iterable[int]
) -> dict[int, LastFeedback]:
    """Ostatnia rozmowa z każdym menedżerem i średnia jej ocen."""

    ids = sorted(set(contact_ids))
    if not ids:
        return {}
    latest: dict[int, ClientFeedbackSession] = {}
    for session in (
        await db.scalars(
            select(ClientFeedbackSession)
            .where(ClientFeedbackSession.contact_id.in_(ids))
            .order_by(
                ClientFeedbackSession.contact_id,
                ClientFeedbackSession.held_on.desc(),
                ClientFeedbackSession.id.desc(),
            )
        )
    ).all():
        latest.setdefault(session.contact_id, session)
    scores = await _scores_by_session(db, [s.id for s in latest.values()])
    return {
        contact_id: LastFeedback(
            session_id=session.id,
            held_on=session.held_on,
            average=average(
                value for score in scores[session.id] for value in _score_values(score)
            ),
        )
        for contact_id, session in latest.items()
    }


async def last_by_contract(
    db: AsyncSession, contract_ids: Iterable[int]
) -> dict[int, LastFeedback]:
    """Ostatnia ocena każdego konsultanta (kontraktu) i jej średnia."""

    ids = sorted(set(contract_ids))
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(ClientFeedbackScore, ClientFeedbackSession.held_on)
            .join(
                ClientFeedbackSession,
                ClientFeedbackSession.id == ClientFeedbackScore.session_id,
            )
            .where(ClientFeedbackScore.contract_id.in_(ids))
            .order_by(
                ClientFeedbackScore.contract_id,
                ClientFeedbackSession.held_on.desc(),
                ClientFeedbackSession.id.desc(),
            )
        )
    ).all()
    out: dict[int, LastFeedback] = {}
    for score, held_on in rows:
        if score.contract_id in out:
            continue
        out[score.contract_id] = LastFeedback(
            session_id=score.session_id,
            held_on=held_on,
            average=average(_score_values(score)),
        )
    return out


async def contract_history(
    db: AsyncSession, contract_id: int, *, limit: int = 20
) -> list[dict[str, Any]]:
    """Opinie o konsultancie (kontrakcie), od najnowszej."""

    rows = (
        await db.execute(
            select(ClientFeedbackScore, ClientFeedbackSession, Contact.name)
            .join(
                ClientFeedbackSession,
                ClientFeedbackSession.id == ClientFeedbackScore.session_id,
            )
            .outerjoin(Contact, Contact.id == ClientFeedbackSession.contact_id)
            .where(ClientFeedbackScore.contract_id == contract_id)
            .order_by(
                ClientFeedbackSession.held_on.desc(), ClientFeedbackSession.id.desc()
            )
            .limit(limit)
        )
    ).all()
    return [
        {
            "session_id": session.id,
            "held_on": session.held_on,
            "channel": session.channel,
            "contact": (
                {"id": session.contact_id, "name": contact_name}
                if session.contact_id is not None
                else None
            ),
            "quality": score.quality,
            "communication": score.communication,
            "autonomy": score.autonomy,
            "average": average(_score_values(score)),
            "extension_outlook": session.extension_outlook,
            "note": session.note,
            "created_by": session.created_by,
        }
        for score, session, contact_name in rows
    ]
