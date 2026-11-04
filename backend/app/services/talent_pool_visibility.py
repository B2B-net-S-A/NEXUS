"""Kto widzi pulę talentów — jedna reguła dla tras pul, list kandydatów i Jarvisa.

Decyzja Artura 25.10.2026 (listy kandydatów w „Moich ludziach”): osobista pula
z ``team_visible = false`` to lista „Tylko ja” — widzi ją wyłącznie właściciel,
także admin jej nie dostaje. Pula firmowa i osobista „Widzi zespół” są
widoczne dla każdego, kto ma dostęp do kandydatów.

Prywatna lista cudzej osoby ma wyglądać jak nieistniejąca (404, brak w
listach, brak nazwy przy kandydacie), bo sama nazwa listy bywa opinią
o człowieku („nie dzwonić”, „słaby angielski”).
"""

from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.talent_pool import TalentPool

# Żadna pula nie ma tego id — filtr z samymi niewidocznymi pulami ma dać pusty
# wynik, a nie zniknąć i zwrócić całą bazę.
NO_VISIBLE_POOL = -1


def is_public(pool: TalentPool) -> bool:
    """Widoczna dla każdego: firmowa albo osobista „Widzi zespół”."""
    return not pool.is_personal or bool(pool.team_visible)


def is_visible_to(pool: TalentPool, user_id: Optional[int]) -> bool:
    return is_public(pool) or (user_id is not None and pool.created_by == user_id)


def visible_clause(user_id: Optional[int]) -> ColumnElement[bool]:
    """Ten sam warunek w SQL — do zapytań o listy pul."""
    public = or_(TalentPool.is_personal.is_(False), TalentPool.team_visible.is_(True))
    if user_id is None:
        return public
    return or_(public, TalentPool.created_by == user_id)


async def visible_pool_ids(
    db: AsyncSession, user_id: Optional[int], pool_ids: Optional[Sequence[int]]
) -> Optional[list[int]]:
    """Zawęża filtr ``talent_pool_id`` do pul widocznych dla patrzącego.

    ``None``/pusta lista = brak filtra (bez zmian). Same niewidoczne pule =
    ``[NO_VISIBLE_POOL]``, czyli zero wyników.
    """
    if not pool_ids:
        return list(pool_ids) if pool_ids is not None else None
    rows = await db.execute(
        select(TalentPool.id).where(
            TalentPool.id.in_(list(pool_ids)), visible_clause(user_id)
        )
    )
    allowed = {r[0] for r in rows.all()}
    kept = [pid for pid in pool_ids if pid in allowed]
    return kept or [NO_VISIBLE_POOL]
