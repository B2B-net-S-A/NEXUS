"""Po co oddzwaniamy: powód przy przypomnieniu (zgłoszenie dzwoniących, decyzja Artura 23.11.2026).

Powód to notatka, którą osoba dzwoniąca wpisała przy wyniku „Oddzwonić” albo „Oferta
ogólna wysłana” z terminem (pole „Po co oddzwaniamy?” na karcie). Bez nowej kolumny:
czytamy ostatni telefon rekordu z dziennika (``external_source = call_queue``,
``external_id = "<rekord>:<próba>"``). Powód należy do tego wyniku: gdy ostatni telefon
ma inny wynik albo pustą notatkę, powodu nie ma, bo starszy mógł już nie obowiązywać.

Rekord przeniesiony z Excela (11.11.2026) nie ma telefonu w dzienniku. Wtedy powodem
jest komentarz po rozmowie z notatki rekordu („Z Excela: komentarz · uwagi”).
Pole jest opcjonalne: moduł podpowiada, nie blokuje (``przekazanie-spotkania-i-werdykt.md``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_date
from app.models.sales import SalesActivity, SalesCallRecord
from app.models.user import User

#: Ten sam znacznik co ``calling.CALL_SOURCE`` (tu bez importu, bo ``calling`` importuje ten moduł).
CALL_SOURCE = "call_queue"
#: Wyniki, przy których termin powrotu ma powód.
REASON_OUTCOMES: frozenset[str] = frozenset({"call_back", "offer_sent"})
#: Początek notatki rekordu z Excela; po nim komentarz po rozmowie, potem „Uwagi”.
EXCEL_NOTE_PREFIX = "Z Excela: "
EXCEL_NOTE_SEPARATOR = " · "
REASON_CHARS = 300


@dataclass(frozen=True)
class CallbackReason:
    text: str
    #: Kto wpisał; ``None`` dla komentarza z Excela.
    author_name: Optional[str]
    noted_on: date
    from_excel: bool


def _short(text: str) -> str:
    text = " ".join(text.split())
    return (
        text if len(text) <= REASON_CHARS else text[: REASON_CHARS - 1].rstrip() + "…"
    )


def excel_comment(note: Optional[str]) -> Optional[str]:
    """Komentarz po rozmowie z notatki rekordu przeniesionego z Excela."""

    if not note or not note.startswith(EXCEL_NOTE_PREFIX):
        return None
    first = note[len(EXCEL_NOTE_PREFIX) :].split(EXCEL_NOTE_SEPARATOR, 1)[0].strip()
    return _short(first) if first else None


async def callback_reasons(
    db: AsyncSession, records: Iterable[SalesCallRecord]
) -> dict[int, CallbackReason]:
    """Powód powrotu dla każdego rekordu, który go ma (klucz: id rekordu)."""

    by_id = {record.id: record for record in records}
    if not by_id:
        return {}
    record_key = func.split_part(SalesActivity.external_id, ":", 1)
    rows = (
        await db.execute(
            select(
                record_key,
                SalesActivity.outcome,
                SalesActivity.body,
                SalesActivity.occurred_at,
                User.name,
            )
            .outerjoin(User, User.id == SalesActivity.created_by_user_id)
            .where(
                SalesActivity.external_source == CALL_SOURCE,
                SalesActivity.kind == "call",
                record_key.in_([str(record_id) for record_id in by_id]),
            )
            .order_by(
                record_key,
                SalesActivity.occurred_at.desc(),
                SalesActivity.id.desc(),
            )
            .distinct(record_key)
        )
    ).all()

    reasons: dict[int, CallbackReason] = {}
    called: set[int] = set()
    for key, outcome, body, occurred_at, author in rows:
        record_id = int(key)
        called.add(record_id)
        text = (body or "").strip()
        if outcome in REASON_OUTCOMES and text:
            reasons[record_id] = CallbackReason(
                text=_short(text),
                author_name=author,
                noted_on=business_date(occurred_at),
                from_excel=False,
            )
    for record_id, record in by_id.items():
        if record_id in called or record.state not in REASON_OUTCOMES:
            continue
        comment = excel_comment(record.note)
        if comment:
            reasons[record_id] = CallbackReason(
                text=comment,
                author_name=None,
                noted_on=business_date(record.created_at),
                from_excel=True,
            )
    return reasons
