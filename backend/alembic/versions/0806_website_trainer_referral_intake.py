"""Zgłoszenia trenera i polecenia ze strony B2B Network od osób spoza B2B.

Revision ID: 0806_website_trainer_referral_intake
Revises: 0805_altcha_spent_challenges

Decyzje Artura z 28.11.2026: trenerem może zgłosić się każdy z rynku, polecić
inżyniera może każdy. Dwie nowe tabele (``market_trainer_applications``,
``candidate_referrals``), same dodania, stary kod działa na nowym schemacie.
DDL w ``app/services/website_intake_schema.py``; lustro w ``entrypoint.sh``.
→ docs/claude/integracje/strona-www-trener-i-polecenie.md
"""

from alembic import op

from app.services import website_intake_schema as schema

revision = "0806_website_trainer_referral_intake"
down_revision = "0805_altcha_spent_challenges"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in schema.ALL_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in schema.DOWNGRADE_DDL:
        op.execute(statement)
