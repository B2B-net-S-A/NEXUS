"""Oddanie osoby z blokadą „Biorę”: prośba o oddanie i typy powiadomień.

Revision ID: 0777_claim_handover
Revises: 0776_settlement_extra_source_rcp

Rekruterka z blokadą 12 h nie mogła oddać osoby koleżance (prośba z 25.11.2026,
decyzja Artura: warianty A „Oddaj”, B „Poproś o oddanie” i C „Zwolnij”).
Oddanie i zwolnienie zmieniają istniejące ``claimed_*``; prośba potrzebuje
trzech kolumn na procesie. Lustro w ``entrypoint.sh``.
"""

import sqlalchemy as sa
from alembic import op

revision = "0777_claim_handover"
down_revision = "0776_settlement_extra_source_rcp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for value in (
            "candidate_claim_handover",
            "candidate_claim_request",
            "candidate_claim_request_answer",
        ):
            op.execute(f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'")
    op.add_column(
        "recruitment_processes",
        sa.Column(
            "claim_request_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "recruitment_processes",
        sa.Column("claim_request_reason", sa.String(300), nullable=True),
    )
    op.add_column(
        "recruitment_processes",
        sa.Column("claim_request_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("recruitment_processes", "claim_request_at")
    op.drop_column("recruitment_processes", "claim_request_reason")
    op.drop_column("recruitment_processes", "claim_request_user_id")
    # Wartość enuma zostaje — Postgres nie ma `ALTER TYPE … DROP VALUE`.
