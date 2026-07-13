"""Small append-only-style audit helpers for sensitive reads.

Downloads and bulk exports do not mutate their business entity, so they were
historically invisible in ``activities``.  Recording them in the same audit
table gives incident response one consistent query surface without coupling
response streaming to a second logging backend.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.user import User


async def record_sensitive_read(
    db: AsyncSession,
    *,
    user: User | None,
    entity_type: str,
    entity_id: int,
    action: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Persist an audit row before sensitive data leaves the application.

    ``entity_id=0`` is reserved for collection-level exports.  Callers should
    never include raw document contents, tokens, or presigned URLs in details.

    This helper commits deliberately instead of relying on the request
    dependency finalizer.  File and streaming responses can fail or be
    disconnected after their headers are issued; the access attempt must still
    be durable by then.  Sensitive-read endpoints are read-only apart from this
    audit row, so committing here does not split a business mutation.
    """
    if action not in {"data_exported", "document_downloaded", "public_data_viewed"}:
        raise ValueError(f"unsupported sensitive-read audit action: {action}")
    audit_details = dict(details or {})
    audit_actor_id = user.id if user is not None else None
    if user is not None:
        impersonator_id = getattr(user, "_security_audit_actor_id", None)
        if impersonator_id is not None:
            audit_actor_id = impersonator_id
            audit_details["effective_user_id"] = user.id
    db.add(
        Activity(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            user_id=audit_actor_id,
            external_source="security_audit",
            details=audit_details,
        )
    )
    await db.commit()
