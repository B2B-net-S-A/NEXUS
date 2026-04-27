"""Shared helpers for chat reactions aggregation (job + candidate)."""

from collections import defaultdict
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_reaction import (
    CandidateChatMessageReaction,
    JobChatMessageReaction,
)


async def aggregate_job_reactions(
    db: AsyncSession, message_ids: Iterable[int]
) -> dict[int, list[dict]]:
    """Zwraca {message_id: [{emoji, count, user_ids}, ...]}."""
    ids = list(message_ids)
    if not ids:
        return {}

    rows = (
        await db.execute(
            select(
                JobChatMessageReaction.message_id,
                JobChatMessageReaction.emoji,
                JobChatMessageReaction.user_id,
            ).where(JobChatMessageReaction.message_id.in_(ids))
        )
    ).all()

    return _aggregate(rows)


async def aggregate_candidate_reactions(
    db: AsyncSession, message_ids: Iterable[int]
) -> dict[int, list[dict]]:
    ids = list(message_ids)
    if not ids:
        return {}

    rows = (
        await db.execute(
            select(
                CandidateChatMessageReaction.message_id,
                CandidateChatMessageReaction.emoji,
                CandidateChatMessageReaction.user_id,
            ).where(CandidateChatMessageReaction.message_id.in_(ids))
        )
    ).all()

    return _aggregate(rows)


def _aggregate(rows) -> dict[int, list[dict]]:
    """Group by (message_id, emoji) → {emoji, count, user_ids}."""
    grouped: dict[int, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for msg_id, emoji, user_id in rows:
        grouped[msg_id][emoji].append(user_id)

    out: dict[int, list[dict]] = {}
    for msg_id, by_emoji in grouped.items():
        out[msg_id] = [
            {"emoji": emoji, "count": len(uids), "user_ids": sorted(uids)}
            for emoji, uids in sorted(by_emoji.items())
        ]
    return out
