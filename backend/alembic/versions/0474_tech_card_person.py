"""„Ludzie w NEXUSIE” — imię i nazwisko konsultanta na karcie z Compassa.

Revision ID: 0474_tech_card_person
Revises: 0473_hr_leave_proofs

Karta Compassa bez pewnego kontraktu czeka przy kliencie na połączenie przez
Delivery Leada — kolumna mówi, o kogo chodzi. SQL ma jedno źródło
(``app/services/contract_care_schema.py``); entrypoint dokłada kolumnę przez
``hr_schema_bundle``.
"""

from alembic import op

from app.services import contract_care_schema as schema

revision = "0474_tech_card_person"
down_revision = "0473_hr_leave_proofs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.TECH_CARD_PERSON_DDL:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("ALTER TABLE tech_cards DROP COLUMN IF EXISTS compass_person_name")
