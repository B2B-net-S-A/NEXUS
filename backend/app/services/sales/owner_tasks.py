"""Otwarte zadania przy szansie idą za jej opiekunem (decyzja Artura 10.11.2026).

Zadanie przy szansie należy do opiekuna szansy (decyzja z 28.10.2026), ale liczyło się
to tylko przy zapisie zadania. Po zmianie opiekuna nowy widział krok w „Co dalej”
i na pasku karty (``next_step.py`` nie patrzy na wykonawcę), a nie miał go w „Zadania →
Moje” ani w „Mój dzień → Zaległe”. Dlatego każda ścieżka, która zmienia opiekuna
szansy, woła ``hand_over``: okno „Zmień opiekuna” (``PATCH`` szansy), „Przejmij”,
„Umów spotkanie” z innym prowadzącym i przekazanie w ``scripts/sales_cleanup.py``.

Przechodzą otwarte pozycje listy „Zadania” (``task_scope.task_items``) przypisane do
poprzedniego opiekuna. Pozycja przypisana komuś trzeciemu zostaje, bo jawne przypisanie
wygrywa; zrobiona zostaje, bo mówi, kto wykonał pracę. Gdy szansa traci opiekuna
i nikt go nie zastępuje, nie ma komu ich dać, więc też zostają.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import and_, case, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.sales import SalesActivity
from app.services.sales.offer_steps import OFFER_STEP_SOURCE
from app.services.sales.task_scope import task_items


def open_items_of(user_id: int) -> ColumnElement[bool]:
    """Otwarta pozycja listy „Zadania” przypisana do ``user_id``."""

    return and_(
        SalesActivity.assignee_user_id == user_id,
        SalesActivity.done_at.is_(None),
        task_items(),
    )


async def hand_over(
    db: AsyncSession,
    opportunity_id: int,
    *,
    previous_owner_id: Optional[int],
    new_owner_id: Optional[int],
) -> int:
    """Przenieś otwarte zadania poprzedniego opiekuna szansy na nowego.

    Zwraca liczbę przeniesionych pozycji; wywołujący robi commit.
    """

    if (
        previous_owner_id is None
        or new_owner_id is None
        or previous_owner_id == new_owner_id
    ):
        return 0
    moved = await db.execute(
        update(SalesActivity)
        .where(
            SalesActivity.opportunity_id == opportunity_id,
            open_items_of(previous_owner_id),
        )
        .values(
            assignee_user_id=new_owner_id,
            # Krok po ofercie ma autora równego wykonawcy (``offer_steps.py``),
            # bo zadanie usuwa tylko autor.
            created_by_user_id=case(
                (SalesActivity.external_source == OFFER_STEP_SOURCE, new_owner_id),
                else_=SalesActivity.created_by_user_id,
            ),
        )
        .execution_options(synchronize_session=False)
    )
    return int(moved.rowcount or 0)
