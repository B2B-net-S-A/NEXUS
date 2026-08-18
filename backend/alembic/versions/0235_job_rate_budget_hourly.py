"""jobs.rate_budget_hourly — jawny budżet PLN/h dla kandydata (dealbreaker-switch).

Jedyna para porównywalna ze stawką kandydata (PLN/h ↔ PLN/h). Legacy
``salary_min/max`` jest w PLN/mies. i porównywalne nie będzie (patrz docstring
``_score_salary``); stawka Championa istnieje tylko na części ofert (860
historycznych, 0 aktywnych w dniu migracji). To pole ustawia rekruter na
formularzu; ``dealbreaker_filters.resolve_job_budget_hourly`` bierze je jako
źródło pierwsze, Championa jako fallback.

Revision ID: 0235_job_rate_budget_hourly
Revises: 0234_park_traffit_acceptance_marker
"""

import sqlalchemy as sa

from alembic import op

revision = "0235_job_rate_budget_hourly"
down_revision = "0234_park_traffit_acceptance_marker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("rate_budget_hourly", sa.Numeric(8, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jobs", "rate_budget_hourly")
