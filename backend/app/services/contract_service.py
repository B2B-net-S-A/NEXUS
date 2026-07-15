"""Contract service helpers — validation logic shared across endpoints.

Isolated from the route handlers so it can be unit-tested without an
AsyncSession / FastAPI rig.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import and_, or_

from app.models.contract import Contract, ContractStatus


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


# --- "Ending soon" — one definition, shared everywhere -----------------------
#
# A contract is "ending soon" when it is LIVE (status active or ending) and its
# ``end_date`` falls within the next ``ENDING_SOON_WINDOW_DAYS`` days. This is the
# same window the daily ``_promote_statuses`` cron uses to flip active→ending,
# but expressed as a date predicate so it does NOT depend on the cron having run
# yet. Relying on the stored ``status == ending`` alone diverged from the
# date-based register filter: a contract that just crossed the 30-day threshold
# is still ``active`` until the next cron tick (under-count), and a contract past
# its ``end_date`` may linger as ``ending`` until demoted to ``ended`` (over-count).
ENDING_SOON_WINDOW_DAYS = 30

_LIVE_STATUSES = (ContractStatus.active, ContractStatus.ending)


def ending_soon_window(today: Optional[date] = None) -> tuple[date, date]:
    """Return the inclusive ``[start, cutoff]`` date window for "ending soon"."""
    start = today or date.today()
    return start, start + timedelta(days=ENDING_SOON_WINDOW_DAYS)


def is_ending_soon(contract: Contract, today: Optional[date] = None) -> bool:
    """Python predicate: a live contract whose ``end_date`` is within the window.

    Mirrors :func:`ending_soon_clause` exactly so in-Python bucketing (stats)
    and SQL filtering (list) never drift.
    """
    if contract.status not in _LIVE_STATUSES or contract.end_date is None:
        return False
    start, cutoff = ending_soon_window(today)
    return start <= contract.end_date <= cutoff


def ending_soon_clause(today: Optional[date] = None):
    """SQLAlchemy predicate mirroring :func:`is_ending_soon`."""
    start, cutoff = ending_soon_window(today)
    return and_(
        Contract.status.in_(_LIVE_STATUSES),
        Contract.end_date.isnot(None),
        Contract.end_date >= start,
        Contract.end_date <= cutoff,
    )


def live_not_ending_clause(today: Optional[date] = None):
    """SQLAlchemy predicate: live but NOT ending soon — the "active" bucket.

    Complement of :func:`ending_soon_clause` within the live set, so the
    active/ending tabs stay mutually exclusive and sum to the live total.
    ``end_date`` in the past (expired but not yet demoted by the cron) stays
    here until the cron flips it to ``ended`` and it drops off the roster.
    """
    start, cutoff = ending_soon_window(today)
    return and_(
        Contract.status.in_(_LIVE_STATUSES),
        or_(
            Contract.end_date.is_(None),
            Contract.end_date < start,
            Contract.end_date > cutoff,
        ),
    )
