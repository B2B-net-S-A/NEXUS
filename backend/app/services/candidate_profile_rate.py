"""Immutable semantics for the candidate-global B2B profile rate."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, text

CANONICAL_PROFILE_RATE_CURRENCY = "PLN"
CANONICAL_PROFILE_RATE_DATABASE_TYPE = "numeric(10,2)"

_PROFILE_RATE_TYPE_PROBE = text(
    """
    SELECT format_type(attribute.atttypid, attribute.atttypmod)
    FROM pg_attribute AS attribute
    WHERE attribute.attrelid = to_regclass('candidates')
      AND attribute.attname = 'expected_rate_hourly'
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped
    """
)


class CandidateProfileRateSchemaError(RuntimeError):
    """The database cannot safely persist the decimal profile-rate contract."""


async def assert_candidate_profile_rate_schema(connection: Any) -> None:
    """Fail startup unless the canonical decimal column is physically ready."""

    observed_type = await connection.scalar(_PROFILE_RATE_TYPE_PROBE)
    if observed_type != CANONICAL_PROFILE_RATE_DATABASE_TYPE:
        raise CandidateProfileRateSchemaError(
            "candidates.expected_rate_hourly must be NUMERIC(10,2); "
            f"observed={observed_type or 'missing'}"
        )


def normalized_profile_rate_currency(value: Any) -> str:
    return str(value or "").strip().upper()


def is_canonical_profile_rate_currency(value: Any) -> bool:
    """NULL/blank is documented legacy PLN; any explicit other value conflicts."""

    return normalized_profile_rate_currency(value) in {
        "",
        CANONICAL_PROFILE_RATE_CURRENCY,
    }


def canonical_profile_rate_amount(
    amount: Any,
    currency: Any,
) -> Decimal | None:
    """Return an amount only when it is safe to interpret as PLN net/hour."""

    if amount is None or not is_canonical_profile_rate_currency(currency):
        return None
    return amount if isinstance(amount, Decimal) else Decimal(str(amount))


def canonical_profile_rate_currency_clause(currency_column):  # type: ignore[no-untyped-def]
    """SQL predicate selecting PLN and documented NULL/blank legacy values."""

    normalized = func.upper(func.trim(currency_column))
    return or_(
        currency_column.is_(None),
        normalized == "",
        normalized == CANONICAL_PROFILE_RATE_CURRENCY,
    )


def conflicting_profile_rate_currency_clause(currency_column):  # type: ignore[no-untyped-def]
    """SQL predicate for explicit values that require manual correction."""

    return ~canonical_profile_rate_currency_clause(currency_column)


def write_profile_rate(candidate: Any, amount: Decimal | None, *, source: str) -> dict:
    """Mutate the complete PLN/hour fact and version under the caller's row lock.

    All canonical writers use this primitive; the caller records the returned
    audit payload and invalidates matching in the same transaction.
    """
    amount = amount.quantize(Decimal("0.01")) if amount is not None else None
    old_version = getattr(candidate, "profile_rate_version", 0) or 0
    details = {
        "old_amount": str(candidate.expected_rate_hourly)
        if candidate.expected_rate_hourly is not None
        else None,
        "old_currency": candidate.expected_rate_currency,
        "new_amount": str(amount) if amount is not None else None,
        "new_currency": "PLN" if amount is not None else None,
        "unit": "hour",
        "tax_basis": "net",
        "contract_type": "b2b",
        "old_version": old_version,
        "new_version": old_version + 1,
        "source": source,
    }
    candidate.expected_rate_hourly = amount
    candidate.expected_rate_currency = details["new_currency"]
    candidate.profile_rate_version = old_version + 1
    candidate.profile_rate_updated_at = datetime.now(timezone.utc)
    return details
