"""Ślad zmian HR (``hr_audit_events``).

Szczegóły niosą nazwy zmienionych pól i wartości niewrażliwe; kwoty i rodzaj
nieobecności idą z ``sensitivity`` = ``payroll`` / ``health`` — odczyt filtruje
wiersze po uprawnieniu czytającego. Logi aplikacji niosą tylko identyfikatory.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_ops import HrAuditEvent

Sensitivity = Literal["general", "health", "payroll"]


def record(
    db: AsyncSession,
    *,
    actor_user_id: Optional[int],
    subject_user_id: Optional[int],
    entity_type: str,
    entity_id: object,
    action: str,
    details: Optional[dict[str, Any]] = None,
    sensitivity: Sensitivity = "general",
) -> HrAuditEvent:
    event = HrAuditEvent(
        actor_user_id=actor_user_id,
        subject_user_id=subject_user_id,
        entity_type=entity_type,
        entity_id=None if entity_id is None else str(entity_id),
        action=action,
        details=details or {},
        sensitivity=sensitivity,
    )
    db.add(event)
    return event
