"""Contract service helpers — validation logic shared across endpoints.

Isolated from the route handlers so it can be unit-tested without an
AsyncSession / FastAPI rig.
"""

from __future__ import annotations

from app.models.contract import Contract


# Minimum set of fields that must be populated before a draft contract
# can transition to `active`. Derived from the contractor module plan:
# without these, downstream reporting (margin, finance, end-date alerts)
# would show garbage.
ACTIVATION_REQUIRED_FIELDS: tuple[str, ...] = (
    "start_date",
    "end_date",
    "rate_candidate",
    "rate_client",
    "contract_type",
    "work_mode",
)


def validate_ready_for_activation(contract: Contract) -> list[str]:
    """Return the list of required fields that are still missing on the draft.

    Empty list means the contract is ready to activate. The order matches
    ACTIVATION_REQUIRED_FIELDS so the UI can render a stable checklist.
    """
    missing: list[str] = []
    for field in ACTIVATION_REQUIRED_FIELDS:
        value = getattr(contract, field, None)
        if value is None:
            missing.append(field)
    return missing
