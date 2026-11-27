"""Sprawdzenie Partnera w Krajowym Rejestrze Zadłużonych przed podpisem umowy B2B.

Revision ID: 0800_b2b_krz_check
Revises: 0799_cp_document_invoice_fields

Prośba Błażeja i decyzje Artura z 27.11.2026: półautomat w Generatorze
(człowiek sprawdza w portalu KRZ, NEXUS zapisuje wynik), wpis w rejestrze
zatrzymuje wysyłkę do podpisu i „Oznacz jako podpisaną” do decyzji Delivery
Leada. Wynik leży w ``b2b_generated_contracts.krz_check`` (JSONB, bez PESEL-u),
dwa nowe typy dzwonków. Lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0800_b2b_krz_check"
down_revision = "0799_cp_document_invoice_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE b2b_generated_contracts ADD COLUMN IF NOT EXISTS krz_check JSONB"
    )
    with op.get_context().autocommit_block():
        for value in ("b2b_krz_entry", "b2b_krz_allowed"):
            op.execute(f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    op.execute("ALTER TABLE b2b_generated_contracts DROP COLUMN IF EXISTS krz_check")
    # Wartości enuma zostają — Postgres nie ma `ALTER TYPE … DROP VALUE`.
