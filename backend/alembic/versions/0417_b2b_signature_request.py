"""Prośba rekrutera o potwierdzenie podpisu umowy B2B.

Revision ID: 0417_b2b_signature_request
Revises: 0416_job_intake_forms

Od 04.10.2026 umowę generuje rekruter prowadzący proces (decyzja Artura), ale
podpis potwierdzają nadal admin, Delivery Lead i TCM („Podpis B2B”). Rekruter
prosi o potwierdzenie: wiersz rejestru pamięta, kto i kiedy poprosił (pulpit,
karta na Tablicy), a odbiorca dostaje dzwonek ``b2b_signature_requested``.

SQL ma jedno źródło (stałe niżej) — to samo czyta lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0417_b2b_signature_request"
down_revision = "0416_job_intake_forms"
branch_labels = None
depends_on = None

COLUMNS = (
    "ALTER TABLE b2b_generated_contracts ADD COLUMN IF NOT EXISTS "
    "signature_requested_at TIMESTAMPTZ",
    "ALTER TABLE b2b_generated_contracts ADD COLUMN IF NOT EXISTS "
    "signature_requested_by INTEGER REFERENCES users(id) ON DELETE SET NULL",
)
ENUM = "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'b2b_signature_requested'"


def upgrade() -> None:
    for statement in COLUMNS:
        op.execute(statement)
    with op.get_context().autocommit_block():
        op.execute(ENUM)


def downgrade() -> None:
    # Kolumny zostają (prośby to ślad pracy); wartość enuma też — Postgres nie
    # ma `ALTER TYPE … DROP VALUE`.
    pass
