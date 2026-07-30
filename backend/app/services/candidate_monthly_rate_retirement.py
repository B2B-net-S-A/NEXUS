"""Runtime guards for the retired candidate monthly-rate contract."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from urllib.parse import unquote_plus

from pydantic_core import PydanticCustomError

RETIRED_MONTHLY_RATE_CODE = "candidate_monthly_rate_retired"

# Historic API, URL-state and frontend aliases observed in saved searches.
RETIRED_MONTHLY_FILTER_KEYS = frozenset(
    {
        "salary_expectation",
        "salary_currency",
        "salary_min",
        "salary_max",
        "min_salary",
        "max_salary",
        "salaryMin",
        "salaryMax",
        "salaryCurrency",
        "salaryExpectation",
        "monthly_salary",
        "monthlySalary",
        "monthly_rate",
        "monthlyRate",
        "rate_monthly",
        "rateMonthly",
        "min_monthly_rate",
        "max_monthly_rate",
        "minMonthlyRate",
        "maxMonthlyRate",
    }
)

# Legacy free-form preference keys were used for candidate finance filters and
# must not provide a side door around the typed hourly-only contract.
RETIRED_PREFERENCE_RATE_KEYS = frozenset(
    {
        "rate_min",
        "rate_max",
        "rate_currency",
        "salary_expectation",
        "salary_currency",
        "salary_min",
        "salary_max",
        "min_salary",
        "max_salary",
    }
)


def payload_contains_retired_candidate_rate(value: Any) -> bool:
    """Detect retired monthly aliases anywhere in an untrusted payload.

    Presence is enough, including an explicit JSON ``null``. This prevents
    Pydantic's default extra-field handling from turning a retired write or
    filter into a silent no-op.
    """

    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            if key in RETIRED_MONTHLY_FILTER_KEYS:
                return True
            if key == "preferences" and isinstance(child, dict):
                if any(
                    str(preference_key) in RETIRED_PREFERENCE_RATE_KEYS
                    for preference_key in child
                ):
                    return True
            if payload_contains_retired_candidate_rate(child):
                return True
    elif isinstance(value, list):
        return any(payload_contains_retired_candidate_rate(item) for item in value)
    return False


def reject_retired_candidate_rate(value: Any) -> Any:
    """Pydantic ``mode=before`` helper with the stable public error code."""

    if payload_contains_retired_candidate_rate(value):
        raise PydanticCustomError(
            RETIRED_MONTHLY_RATE_CODE,
            RETIRED_MONTHLY_RATE_CODE,
        )
    return value


def sanitize_candidate_preferences(value: Any) -> Any:
    """Remove legacy candidate finance keys from read projections."""

    if not isinstance(value, dict):
        return value
    return {
        key: deepcopy(child)
        for key, child in value.items()
        if str(key) not in RETIRED_PREFERENCE_RATE_KEYS
    }


def _sanitize_query_string(value: str) -> tuple[str, bool]:
    prefix = "?" if value.startswith("?") else ""
    raw = value[1:] if prefix else value
    if not raw:
        return value, False

    kept: list[str] = []
    changed = False
    for part in raw.split("&"):
        key = unquote_plus(part.partition("=")[0])
        if key in RETIRED_MONTHLY_FILTER_KEYS:
            changed = True
            continue
        kept.append(part)
    return prefix + "&".join(kept), changed


def sanitize_candidate_saved_search(filters: dict[str, Any]) -> tuple[dict, bool]:
    """Remove only retired monthly candidate criteria, preserving other state."""

    changed = False

    def is_monthly_rate_item(value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        unit = str(value.get("unit") or "").strip().casefold()
        return unit in {
            "month",
            "monthly",
            "miesiac",
            "miesiąc",
            "mies.",
        }

    def walk(value: Any, *, parent_key: str | None = None) -> Any:
        nonlocal changed
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, child in value.items():
                if key in RETIRED_MONTHLY_FILTER_KEYS:
                    changed = True
                    continue
                if parent_key == "preferences" and key in RETIRED_PREFERENCE_RATE_KEYS:
                    changed = True
                    continue
                result[key] = walk(child, parent_key=key)
            return result
        if isinstance(value, list):
            result = []
            for item in value:
                if parent_key == "rates" and is_monthly_rate_item(item):
                    changed = True
                    continue
                result.append(walk(item, parent_key=parent_key))
            return result
        if parent_key == "qs" and isinstance(value, str):
            sanitized, query_changed = _sanitize_query_string(value)
            changed = changed or query_changed
            return sanitized
        return value

    sanitized = walk(deepcopy(filters))
    return sanitized, changed


async def retire_candidate_saved_searches(db: Any) -> int:
    """Idempotently sanitize every historic candidate search before serving.

    This runtime sweep mirrors migration 0207 because production has a known
    fail-open Alembic safety path.  Failure is intentionally propagated by the
    application startup caller: serving broader searches or active alerts is
    less safe than refusing the release.
    """

    from sqlalchemy import select

    from app.models.saved_search import SavedSearch

    rows = list(
        (
            await db.scalars(
                select(SavedSearch)
                .where(SavedSearch.entity.in_(("candidate", "candidates")))
                .order_by(SavedSearch.id)
                .with_for_update()
            )
        ).all()
    )
    changed_count = 0
    for row in rows:
        sanitized, changed = sanitize_candidate_saved_search(row.filters or {})
        if not changed:
            continue
        row.filters = sanitized
        row.notify_new_matches = False
        row.requires_reapproval = True
        changed_count += 1
    await db.commit()
    return changed_count
