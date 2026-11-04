"""Poprawki w bibliotece ról i słowniczku (admin + Head of Recruitment).

Każda realna zmiana zostawia wpis w ``plain_knowledge_events`` (diff pól,
kto, kiedy) i ustawia ``origin='manual'`` — od tej chwili ani zasiew z repo,
ani research tego wiersza nie nadpiszą.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.plain_knowledge import PlainKnowledgeEvent, PlainTerm, RoleProfile

ROLE_FIELDS = (
    "name",
    "summary",
    "example",
    "day_to_day",
    "candidate_questions",
    "typical_skills",
)
TERM_FIELDS = ("display_name", "summary", "does", "cv_hints", "confused_with")
_LIST_FIELDS = frozenset(
    {"day_to_day", "candidate_questions", "typical_skills", "cv_hints"}
)


def _norm(field: str, value: Any) -> Any:
    if field in _LIST_FIELDS:
        items = [
            re.sub(r"\s+", " ", str(v)).strip()[:300]
            for v in (value or [])
            if str(v).strip()
        ]
        return items[:12]
    if value is None:
        return None
    text = re.sub(r"[ \t]+", " ", str(value)).strip()
    return text[:2000] or None


async def apply_changes(
    db: AsyncSession,
    row: Any,
    entity_type: str,
    fields: tuple[str, ...],
    payload: dict[str, Any],
    user: Any,
) -> bool:
    changes: dict[str, dict[str, Any]] = {}
    for field in fields:
        if field not in payload:
            continue
        new = _norm(field, payload[field])
        if field in ("name", "display_name") and not new:
            continue
        old = getattr(row, field)
        if (old or ([] if field in _LIST_FIELDS else None)) != (
            new or ([] if field in _LIST_FIELDS else None)
        ):
            changes[field] = {"old": old, "new": new}
            setattr(row, field, new)
    if not changes:
        return False
    row.origin = "manual"
    row.status = "ready"
    row.claimed_at = None
    row.updated_by = user.id
    db.add(
        PlainKnowledgeEvent(
            entity_type=entity_type,
            entity_id=row.id,
            action="edited",
            changes=changes,
            user_id=user.id,
            user_name=getattr(user, "name", None),
        )
    )
    return True


async def history(
    db: AsyncSession, entity_type: str, entity_id: int
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(PlainKnowledgeEvent)
            .where(
                PlainKnowledgeEvent.entity_type == entity_type,
                PlainKnowledgeEvent.entity_id == entity_id,
            )
            .order_by(
                desc(PlainKnowledgeEvent.created_at), desc(PlainKnowledgeEvent.id)
            )
            .limit(50)
        )
    ).scalars()
    return [
        {
            "created_at": r.created_at,
            "user_name": r.user_name,
            "changes": r.changes or {},
        }
        for r in rows
    ]


def term_row_payload(
    row: PlainTerm, *, in_dictionary: bool, updated_by_name: Optional[str]
) -> dict[str, Any]:
    return {
        "id": row.id,
        "term_key": row.term_key,
        "display_name": row.display_name,
        "summary": row.summary,
        "does": row.does,
        "cv_hints": list(row.cv_hints or []),
        "confused_with": row.confused_with,
        "sources": [s for s in (row.sources or []) if isinstance(s, dict)][:8],
        "origin": row.origin,
        "status": row.status,
        "in_dictionary": in_dictionary,
        "updated_at": row.updated_at,
        "updated_by_name": updated_by_name,
    }


__all__ = [
    "ROLE_FIELDS",
    "TERM_FIELDS",
    "apply_changes",
    "history",
    "term_row_payload",
    "RoleProfile",
]
