"""Retire candidate monthly-rate filters in saved searches.

Revision ID: 0207_monthly_rate_retired
Revises: 0206_candidate_summary_security
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Sequence, Union
from urllib.parse import unquote_plus

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0207_monthly_rate_retired"
down_revision: Union[str, None] = "0206_candidate_summary_security"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RETIRED_KEYS = {
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
_RETIRED_PREFERENCE_KEYS = {
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


def _sanitize(filters: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    changed = False

    def is_monthly_rate_item(value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        unit = str(value.get("unit") or "").strip().casefold()
        return unit in {"month", "monthly", "miesiac", "miesiąc", "mies."}

    def walk(value: Any, parent_key: str | None = None) -> Any:
        nonlocal changed
        if isinstance(value, dict):
            result = {}
            for key, child in value.items():
                if key in _RETIRED_KEYS:
                    changed = True
                    continue
                if parent_key == "preferences" and key in _RETIRED_PREFERENCE_KEYS:
                    changed = True
                    continue
                result[key] = walk(child, key)
            return result
        if isinstance(value, list):
            result = []
            for item in value:
                if parent_key == "rates" and is_monthly_rate_item(item):
                    changed = True
                    continue
                result.append(walk(item, parent_key))
            return result
        if parent_key == "qs" and isinstance(value, str):
            prefix = "?" if value.startswith("?") else ""
            raw = value[1:] if prefix else value
            kept = []
            for part in raw.split("&") if raw else []:
                if unquote_plus(part.partition("=")[0]) in _RETIRED_KEYS:
                    changed = True
                else:
                    kept.append(part)
            return prefix + "&".join(kept)
        return value

    return walk(deepcopy(filters)), changed


def upgrade() -> None:
    # Keep the deprecated columns physically present, but stop new rows from
    # acquiring a misleading currency when no monthly value is written.
    op.execute("ALTER TABLE candidates ALTER COLUMN salary_currency DROP DEFAULT")
    # The production entrypoint mirrors this column when Alembic fail-opens.
    # Keep the migration replay-safe so a later repaired upgrade can still
    # record revision 0207 instead of stopping on DuplicateColumn.
    op.execute(
        """
        ALTER TABLE saved_searches
        ADD COLUMN IF NOT EXISTS requires_reapproval
        BOOLEAN NOT NULL DEFAULT FALSE
        """
    )

    saved_searches = sa.table(
        "saved_searches",
        sa.column("id", sa.Integer()),
        sa.column("entity", sa.String()),
        sa.column("filters", postgresql.JSONB()),
        sa.column("notify_new_matches", sa.Boolean()),
        sa.column("requires_reapproval", sa.Boolean()),
    )
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(saved_searches.c.id, saved_searches.c.filters).where(
            saved_searches.c.entity.in_(("candidate", "candidates"))
        )
    )
    for row in rows:
        sanitized, changed = _sanitize(row.filters or {})
        if not changed:
            continue
        bind.execute(
            saved_searches.update()
            .where(saved_searches.c.id == row.id)
            .values(
                filters=sanitized,
                notify_new_matches=False,
                requires_reapproval=True,
            )
        )


def downgrade() -> None:
    # Removed criteria and disabled alerts cannot be reconstructed safely.
    op.drop_column("saved_searches", "requires_reapproval")
    op.execute("ALTER TABLE candidates ALTER COLUMN salary_currency SET DEFAULT 'PLN'")
