"""Wejście trenera z rynku do panelu: dane firmy, szkolenie bez kontraktu, sesje.

Revision ID: 0807_market_trainer_portal
Revises: 0806_website_trainer_referral_intake

Decyzje Artura z 28.11.2026: osobne wejście trenera (link z maila na /konsultant,
tylko „Szkolenia” i „Trener”), dane firmy wpisuje TCM z Białej Listy, własny
włącznik. Same dodania (kolumny NULL/z domyślną, dwie tabele, CHECK dopuszczający
tylko nowe wiersze), stary kod działa na nowym schemacie. DDL w
``app/services/market_trainer_portal_schema.py``; lustro w ``entrypoint.sh``.
→ docs/claude/ludzie/panel-trenera-z-rynku.md
"""

from alembic import op

from app.services import market_trainer_portal_schema as schema

revision = "0807_market_trainer_portal"
down_revision = "0806_website_trainer_referral_intake"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in schema.ALL_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in schema.DOWNGRADE_DDL:
        op.execute(statement)
