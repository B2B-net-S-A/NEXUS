"""Shared guards and redaction for legacy financial API surfaces."""

from __future__ import annotations

from typing import Any, Protocol

from fastapi import HTTPException, status

from app.models.user import UserRole


class _RoleAwareUser(Protocol):
    def has_any_role(self, *roles: UserRole) -> bool: ...


_FINANCE_ROLES = (UserRole.admin, UserRole.delivery_lead)


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
