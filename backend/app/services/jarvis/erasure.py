"""Usunięcie kandydata (art. 17 RODO) kasuje rozmowy Jarvisa z jego danymi.

Treść rozmowy to JSON (bloki Anthropic), więc kaskada FK do niej nie sięga —
dlatego rozmowy znamy po ``jarvis_conversation_entities``: każda tura zapisuje
tam kandydatów, których ID padło w argumentach lub wynikach narzędzi albo był
na ekranie użytkownika. Kasujemy CAŁE rozmowy (wiadomości i akcje idą kaskadą):
wycinanie pojedynczych bloków zostawiłoby odpowiedzi modelu cytujące tę osobę.

Wołający (``DELETE /api/candidates/{id}``) jest właścicielem transakcji.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.jarvis import JarvisConversation, JarvisConversationEntity


async def erase_candidate(db: AsyncSession, candidate_id: int) -> dict[str, int]:
    linked = select(JarvisConversationEntity.conversation_id).where(
        JarvisConversationEntity.entity_type == "candidate",
        JarvisConversationEntity.entity_id == candidate_id,
    )
    result = await db.execute(
        delete(JarvisConversation).where(JarvisConversation.id.in_(linked))
    )
    return {"jarvis_conversations_deleted": int(result.rowcount or 0)}
