"""Podpis umowy w NEXUSIE: osoby w DW przy wysyłce.

Revision ID: 0604_esign_cc
Revises: 0603_esign_events

Prośba zespołu z 27.10.2026: przy wysyłce umowy do podpisu dodać do DW osobę,
która zastępuje rekrutera albo przejmuje proces. Decyzja Artura 27.10.2026:
mail zawsze z własnej skrzynki nadawcy, rekruter w DW, w DW tylko osoby
z NEXUSA (w umowie są stawki). ``cc_user_ids`` — konta w DW; dostają mail
z linkiem, kopię podpisanej umowy i dzwonki. Lustro w ``entrypoint.sh``.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0604_esign_cc"
down_revision = "0603_esign_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "b2b_signing_requests",
        sa.Column(
            "cc_user_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("b2b_signing_requests", "cc_user_ids")
