"""Partial index on candidate_stages WHERE stage='hired' for time-to-hire report.

Revision ID: 0121_candidate_stages_hired_partial_idx
Revises: 0120_jobs_client_id_not_null
Create Date: 2026-05-27 16:00:00.000000

Performance fix: QA 2026-05-27 zgłosił że /api/reports/time-to-hire trwa
>15s. Endpoint scanuje wszystkie CandidateStage rows w 180-day window
(~55k rows w prod) tylko żeby znaleźć 145 hires + ich starting points.

Partial index zawiera tylko 928 hired rows (`stage='hired'`), zamiast
158k całkowitych — szybsze seek dla każdego "find all hires" query
w time-to-hire i innych endpointach (recruitment funnel KPIs).

CONCURRENTLY żeby nie blokować writes na prod (`candidate_stages` jest
hot path dla pipeline moves).
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0121_candidate_stages_hired_partial_idx"
down_revision: Union[str, None] = "0120_jobs_client_id_not_null"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # CONCURRENTLY musi być poza transakcją — wyłączamy autocommit batch.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_candidate_stages_hired_moved_at "
            "ON candidate_stages (moved_at DESC) "
            "WHERE stage = 'hired'"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_candidate_stages_hired_moved_at"
        )
