"""Dane firm z umów do potwierdzenia (E5a, decyzja Artura 22.11.2026).

Revision ID: 0755_contract_partner_reads
Revises: 0754_b2b_signing_accept_code

Tabela ``contract_partner_reads`` (dane firmy Partnera odczytane z podpisanej
umowy w Dokumentach kontraktu, sprawdzenie w rejestrze i decyzja człowieka)
oraz funkcja AI ``contract_partner_read``. DDL ma jedno źródło
(``app/services/contract_partner_reads/schema_sql.py``); entrypoint wykonuje je
przy każdym starcie przez ``hr_schema_bundle``. Same dodania: stary kod działa
na nowym schemacie.
"""

from alembic import op

from app.services.contract_partner_reads import schema_sql as schema

revision = "0755_contract_partner_reads"
down_revision = "0754_b2b_signing_accept_code"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'contract_partner_read'"
        )
    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        "SELECT 'contract_partner_read', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS "
        "(SELECT 1 FROM ai_features WHERE feature = 'contract_partner_read')"
    )
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE).
def downgrade() -> None:
    op.execute("DELETE FROM ai_features WHERE feature = 'contract_partner_read'")
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
