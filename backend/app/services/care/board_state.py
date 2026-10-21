"""Stan kart opieki na tablicy „Do zrobienia” (``care_board_states``, 0504).

Karty liczą się przy odczycie (``care/board.py``); tabela pamięta tylko to,
co człowiek przestawił: „W toku” z terminem (``scheduled_at``), „Czeka na
kogoś” z datą ponowienia (``retry_on``), notatkę i — przy popycie —
rozstrzygnięcie (``outcome``). Karta w „Nowa” wiersza nie ma.

Klucz karty mówi, czego dotyczy (format w ``parse_key``); tabela nie ma
kluczy obcych do kontraktów — wiersz po zniknięciu karty (rozmowa zamknęła
punkt planu, wpis „Do przepięcia” zamknięty) jest martwy i nikomu się nie
pokazuje.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    Date,
    DateTime,
    Integer,
    String,
    column,
    delete,
    select,
    table,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.care_board_schema import BOARD_NOTE_MAX

#: Lekkie odwzorowanie tabeli (bez modelu ORM — jak ``CONTRACTS_CARE``).
CARE_BOARD_STATES = table(
    "care_board_states",
    column("id", Integer),
    column("key", String),
    column("kind", String),
    column("board_column", String),
    column("scheduled_at", DateTime(timezone=True)),
    column("retry_on", Date),
    column("outcome", String),
    column("job_id", Integer),
    column("note", String),
    column("updated_by", Integer),
    column("updated_at", DateTime(timezone=True)),
)

_KEY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("contact_plan", re.compile(r"^contact:plan:(\d+)$")),
    ("contact_followup", re.compile(r"^contact:followup:(\d+)$")),
    ("feedback", re.compile(r"^feedback:(\d+)$")),
    ("decision", re.compile(r"^decision:(\d+)$")),
    ("demand", re.compile(r"^demand:(\d+):(\d+):(\d+)$")),
)


@dataclass(frozen=True)
class CardKey:
    """Rozebrany klucz karty: rodzaj tablicy i identyfikatory."""

    raw: str
    variant: str  # contact_plan | contact_followup | feedback | decision | demand
    ids: tuple[int, ...]

    @property
    def kind(self) -> str:
        return self.variant.split("_", 1)[0]


def parse_key(raw: str) -> Optional[CardKey]:
    """``contact:plan:<punkt>``, ``contact:followup:<rozmowa>``,
    ``feedback:<kontakt>``, ``decision:<wpis>``,
    ``demand:<klient>:<dział albo 0>:<rozmowa>``; inny tekst = ``None``."""

    for variant, pattern in _KEY_PATTERNS:
        match = pattern.match(raw or "")
        if match:
            return CardKey(raw, variant, tuple(int(g) for g in match.groups()))
    return None


def demand_key(client_id: int, area_id: Optional[int], conversation_id: int) -> str:
    return f"demand:{client_id}:{area_id or 0}:{conversation_id}"


@dataclass(frozen=True)
class BoardState:
    key: str
    kind: str
    column: str
    scheduled_at: Optional[datetime]
    retry_on: Optional[date]
    outcome: Optional[str]
    job_id: Optional[int]
    note: Optional[str]
    updated_by: Optional[int]
    updated_at: Optional[datetime]

    def payload(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "column": self.column,
            "scheduled_at": self.scheduled_at,
            "retry_on": self.retry_on,
            "note": self.note,
            "outcome": self.outcome,
        }


def _row(row) -> BoardState:
    return BoardState(
        key=row.key,
        kind=row.kind,
        column=row.board_column,
        scheduled_at=row.scheduled_at,
        retry_on=row.retry_on,
        outcome=row.outcome,
        job_id=row.job_id,
        note=row.note,
        updated_by=row.updated_by,
        updated_at=row.updated_at,
    )


_SELECT = select(
    CARE_BOARD_STATES.c.key,
    CARE_BOARD_STATES.c.kind,
    CARE_BOARD_STATES.c.board_column,
    CARE_BOARD_STATES.c.scheduled_at,
    CARE_BOARD_STATES.c.retry_on,
    CARE_BOARD_STATES.c.outcome,
    CARE_BOARD_STATES.c.job_id,
    CARE_BOARD_STATES.c.note,
    CARE_BOARD_STATES.c.updated_by,
    CARE_BOARD_STATES.c.updated_at,
)


async def states_for(db: AsyncSession, keys: Iterable[str]) -> dict[str, BoardState]:
    wanted = sorted(set(keys))
    if not wanted:
        return {}
    rows = (await db.execute(_SELECT.where(CARE_BOARD_STATES.c.key.in_(wanted)))).all()
    return {row.key: _row(row) for row in rows}


async def states_of_kind(
    db: AsyncSession, kind: str, *, prefix: Optional[str] = None
) -> dict[str, BoardState]:
    query = _SELECT.where(CARE_BOARD_STATES.c.kind == kind)
    if prefix:
        query = query.where(CARE_BOARD_STATES.c.key.startswith(prefix))
    rows = (await db.execute(query)).all()
    return {row.key: _row(row) for row in rows}


async def updated_between(
    db: AsyncSession, first: datetime, last: datetime, *, kind: str
) -> list[BoardState]:
    rows = (
        await db.execute(
            _SELECT.where(
                CARE_BOARD_STATES.c.kind == kind,
                CARE_BOARD_STATES.c.updated_at >= first,
                CARE_BOARD_STATES.c.updated_at <= last,
            )
        )
    ).all()
    return [_row(row) for row in rows]


def clean_note(value: Optional[str]) -> Optional[str]:
    cleaned = " ".join((value or "").replace("\x00", "").split())
    return cleaned[:BOARD_NOTE_MAX] or None


async def save(
    db: AsyncSession,
    *,
    key: str,
    kind: str,
    column_value: str,
    actor_id: Optional[int],
    now: datetime,
    scheduled_at: Optional[datetime] = None,
    retry_on: Optional[date] = None,
    outcome: Optional[str] = None,
    job_id: Optional[int] = None,
    note: Optional[str] = None,
) -> None:
    """Wstawia albo podmienia wiersz karty (jeden na klucz)."""

    values = {
        "key": key,
        "kind": kind,
        "board_column": column_value,
        "scheduled_at": scheduled_at,
        "retry_on": retry_on,
        "outcome": outcome,
        "job_id": job_id,
        "note": clean_note(note),
        "updated_by": actor_id,
        "updated_at": now,
    }
    statement = insert(CARE_BOARD_STATES).values(**values)
    statement = statement.on_conflict_do_update(
        index_elements=["key"],
        set_={name: statement.excluded[name] for name in values if name != "key"},
    )
    await db.execute(statement)


async def clear(db: AsyncSession, keys: Iterable[str]) -> None:
    wanted = sorted(set(keys))
    if wanted:
        await db.execute(
            delete(CARE_BOARD_STATES).where(CARE_BOARD_STATES.c.key.in_(wanted))
        )


def column_for(state: Optional[BoardState], today: date) -> str:
    """Kolumna karty: bez wiersza „Nowa”; „Czeka” po dacie ponowienia wraca do „Nowa”."""

    if state is None:
        return "new"
    if state.column == "waiting" and state.retry_on is not None:
        return "new" if state.retry_on <= today else "waiting"
    return state.column
