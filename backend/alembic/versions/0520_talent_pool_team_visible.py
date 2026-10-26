"""Listy kandydatów: widoczność osobistej listy (``team_visible``).

Revision ID: 0520_talent_pool_team_visible
Revises: 0519_candidate_job_owners

Decyzja Artura 25.10.2026 (prośba Olafa: ręczne listy w „Moich ludziach”).
Lista to osobista pula (``is_personal``, 0137). Nowa lista z panelu jest
„Tylko ja” (``team_visible = false``) z przełącznikiem „Widzi zespół”.
Domyślne ``true`` zostawia dotychczasowe pule osobiste widoczne dla zespołu,
jak przed tą rewizją. Kolumna liczy się tylko przy ``is_personal``. Lustro
w ``entrypoint.sh``.
"""

from alembic import op

revision = "0520_talent_pool_team_visible"
down_revision = "0519_candidate_job_owners"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE talent_pools ADD COLUMN IF NOT EXISTS team_visible "
        "BOOLEAN NOT NULL DEFAULT true"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE talent_pools DROP COLUMN IF EXISTS team_visible")
