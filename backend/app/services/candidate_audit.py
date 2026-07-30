"""Minimal immutable audit events for sensitive candidate-module operations.

M2 audit PR 1 (access containment) requires an audit trail for:

- candidate exports (requested/completed),
- CV / document downloads (single, bulk ZIP, presigned URL),
- denied/blocked sensitive operations (anonymize, hard delete),
- bulk operations execute.

Events reuse the existing ``Activity`` audit table (``entity_type`` +
``action`` + JSONB ``details``) instead of introducing a parallel store.
``details`` MUST NOT contain raw PII (names, emails, phones, CV content,
query strings with personal data) — counts, formats, ids and reason codes
only.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity

logger = logging.getLogger(__name__)

# Audit actions (Activity.action) emitted by the candidate module.
EXPORT_REQUESTED = "export_requested"
CV_DOWNLOADED = "cv_downloaded"
BULK_CV_DOWNLOADED = "bulk_cv_downloaded"
DOCUMENT_DOWNLOADED = "document_downloaded"
DOCUMENT_URL_ISSUED = "document_url_issued"
SENSITIVE_OPERATION_BLOCKED = "sensitive_operation_blocked"
BULK_ACTION_EXECUTED = "bulk_action_executed"
# Client-facing pricing mutation („stawka do klienta"). Records old→new so a
# rate change leaves a trail (P1-11). Financial payload — must stay out of any
# non-finance-redacted read surface (e.g. the candidate timeline feed).
CLIENT_RATE_CHANGED = "client_rate_changed"
PROFILE_RATE_CHANGED = "profile_rate_changed"
LANGUAGES_REPLACED = "candidate_languages_replaced"
LOCATION_CHANGED = "candidate_location_changed"
IDENTITY_SOURCE_QUARANTINED = "candidate_identity_source_quarantined"
IDENTITY_SOURCE_QUARANTINE_OVERRIDDEN = (
    "candidate_identity_source_quarantine_overridden"
)


def record_candidate_audit(
    db: AsyncSession,
    *,
    action: str,
    user_id: Optional[int],
    entity_id: int = 0,
    details: Optional[dict[str, Any]] = None,
) -> None:
    """Stage an immutable audit event on the current session (no commit).

    ``entity_id=0`` marks module-level events (exports, bulk ops) that do not
    target a single candidate. Caller owns the transaction; endpoints that
    only read (downloads/exports) must ``await db.commit()`` themselves so
    the event survives the request.
    """
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=entity_id,
            action=action,
            user_id=user_id,
            details=details or {},
            external_source="audit",
        )
    )
