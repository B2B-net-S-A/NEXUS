"""Shared guards and redaction for legacy financial API surfaces."""

from __future__ import annotations

from typing import Any, Protocol

from fastapi import HTTPException, status

from app.models.user import UserRole
from app.services.candidate_audit import CLIENT_RATE_CHANGED


class _RoleAwareUser(Protocol):
    def has_any_role(self, *roles: UserRole) -> bool: ...


_FINANCE_ROLES = (UserRole.admin, UserRole.delivery_lead)

# Activity actions whose ``details`` carry raw candidate pricing (rate) amounts.
# Mirrors the candidate timeline's ``_HIDDEN_TIMELINE_ACTIONS``: these audit rows
# are finance-only, so non-finance readers never see them in an activity feed.
# The audit payload keys (``old_client_rate`` / ``new_client_rate``) are NOT
# covered by ``_is_financial_key``, so the whole row is dropped rather than
# key-redacted — matching how the timeline omits the action entirely.
_RATE_AUDIT_ACTIONS = frozenset({CLIENT_RATE_CHANGED})


def has_financial_access(user: _RoleAwareUser) -> bool:
    """Return whether any primary or secondary role grants finance access."""

    return user.has_any_role(*_FINANCE_ROLES)


def require_financial_access(user: _RoleAwareUser) -> None:
    """Fail closed before a legacy endpoint can query or serialize rates."""

    if not has_financial_access(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Financial contract data requires admin or delivery_lead role",
        )


def _is_financial_key(key: str) -> bool:
    normalized = key.lower()
    return (
        normalized == "rate"
        or "rate_candidate" in normalized
        or "rate_client" in normalized
        or normalized.startswith(("rate_", "client_rate", "expected_rate"))
        or "rate_schedule" in normalized
        or "margin" in normalized
        or normalized
        in {
            "billing_hours_per_month",
            "currency",
            "framework_rate",
            "target_rate_min",
            "target_rate_max",
            "total_value",
            "pnl",
            "p&l",
            "profit",
            "revenue",
            "cost",
        }
    )


def redact_financial_fields(value: Any) -> Any:
    """Recursively remove known financial keys from flexible audit payloads."""

    if isinstance(value, dict):
        return {
            key: redact_financial_fields(item)
            for key, item in value.items()
            if not _is_financial_key(str(key))
        }
    if isinstance(value, list):
        return [redact_financial_fields(item) for item in value]
    return value


def redact_feed_activity(action: str, details: Any, *, finance_ok: bool) -> Any | None:
    """Return safe ``details`` for one activity-feed row, or ``None`` to drop it.

    Activity feeds (``/api/activities/feed``, ``/api/dashboard/recent-activity``,
    ``/api/contracts/{id}/activities``) serialize raw ``Activity.details``, which
    can carry rate amounts. This applies the same finance protection the candidate
    timeline already uses:

    - finance roles (``has_financial_access``) see everything unchanged;
    - for non-finance readers, rate-change audit rows are omitted entirely
      (mirrors ``_HIDDEN_TIMELINE_ACTIONS``), because their payload keys are not
      redactable field-by-field;
    - any residual finance keys on other rows (e.g. a contract ``updated`` event
      carrying ``rate_candidate`` / ``margin``) are stripped via
      :func:`redact_financial_fields`.
    """

    if finance_ok:
        return details
    if action in _RATE_AUDIT_ACTIONS:
        return None
    return redact_financial_fields(details or {})
