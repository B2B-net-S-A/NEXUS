"""Podpis umowy w NEXUSIE: kto obsługuje wysyłkę (zastępstwo).

Revision ID: 0605_esign_handler
Revises: 0604_esign_cc

Prośba zespołu z 27.10.2026 o „wysyłkę w zastępstwie”. Decyzja Artura
27.10.2026: bez nowego uprawnienia i bez wysyłki ze skrzynki innej osoby.
Zamiast tego ``handled_by`` — kto obsługuje wysyłkę po „Przejmij obsługę”
(pusta = nadawca). Przypomnienia, mail do reprezentanta i kopia umowy idą
z jego skrzynki, a dzwonki także do zastępcy z modułu „Urlopy”, gdy
obsługujący jest na urlopie. Lustro w ``entrypoint.sh``.
"""

import sqlalchemy as sa
from alembic import op

revision = "0605_esign_handler"
down_revision = "0604_esign_cc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "b2b_signing_requests",
        sa.Column(
            "handled_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("b2b_signing_requests", "handled_by")
