"""Zamknięcia okresów konkursów płatnych (frozen / no_winner / tie_pending).

Revision ID: 0344_competition_period_closures
Revises: 0341_job_champion_similar

Wiersz na (typ konkursu, okres) — także gdy nikt nie wygrał albo remis na
płatnym miejscu czeka na decyzję admina. Bez niego autofreeze liczył taki okres
od nowa co godzinę. Lustro DDL w ``entrypoint.sh`` (prod alembic bywa
osierocony).
"""

from alembic import op

revision = "0344_competition_period_closures"
down_revision = "0341_job_champion_similar"
branch_labels = None
depends_on = None

CREATE_SQL = """CREATE TABLE IF NOT EXISTS competition_period_closures (
        id BIGSERIAL PRIMARY KEY,
        competition_type VARCHAR(50) NOT NULL,
        period VARCHAR(20) NOT NULL,
        status VARCHAR(20) NOT NULL,
        details JSONB NULL,
        resolved_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        resolved_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_competition_period_closures UNIQUE (competition_type, period),
        CONSTRAINT ck_competition_period_closures_status
            CHECK (status IN ('frozen', 'no_winner', 'tie_pending', 'tie_resolved'))
    )"""


def upgrade() -> None:
    op.execute(CREATE_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS competition_period_closures")
