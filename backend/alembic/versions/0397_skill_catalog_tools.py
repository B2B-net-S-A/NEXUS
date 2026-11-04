"""Słownik umiejętności: narzędzia, standardy i pojęcia AI (Jira, Confluence, Git…).

Revision ID: 0397_skill_catalog_tools
Revises: 0396_search_screening_skills_corpus

Lista: ``app/data/skill_catalog_tools.json`` (``services/skill_catalog_tools``).
Zasiew tylko dokłada — nazwa albo alias, które już są w słowniku, zostają.
Downgrade usuwa wyłącznie pozycje w kategoriach tego zasiewu.
"""

from alembic import op
from sqlalchemy import text

from app.services import skill_catalog_tools as tools

revision = "0397_skill_catalog_tools"
down_revision = "0396_search_screening_skills_corpus"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tools.seed(op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    for name, category, _aliases in tools.entries():
        bind.execute(
            text("DELETE FROM skills WHERE canonical_name = :n AND category = :c"),
            {"n": name, "c": category},
        )
