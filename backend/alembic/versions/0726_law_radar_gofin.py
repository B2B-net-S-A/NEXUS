"""Radar przepisów: źródło ``gofin`` (konto księgowej, jak LEX).

Revision ID: 0726_law_radar_gofin
Revises: 0725_premium_justification_ai

Przebudowa CHECK-a ``ck_law_radar_items_source``. SQL ma jedno źródło
(``app/services/law_radar/schema.py``, ``CONSTRAINT_DDL``); entrypoint wykonuje
je przy każdym starcie przez ``hr_schema_bundle``. Reguły:
``docs/claude/przepisy/radar-przepisow-dwa-boty.md``.
"""

from alembic import op

from app.services.law_radar import schema

revision = "0726_law_radar_gofin"
down_revision = "0725_premium_justification_ai"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.CONSTRAINT_DDL:
        op.execute(stmt)


def downgrade() -> None:
    sources = ", ".join(f"'{s}'" for s in schema.SOURCES if s != "gofin")
    op.execute("DELETE FROM law_radar_items WHERE source = 'gofin'")
    op.execute("ALTER TABLE law_radar_items DROP CONSTRAINT ck_law_radar_items_source")
    op.execute(
        "ALTER TABLE law_radar_items ADD CONSTRAINT ck_law_radar_items_source "
        f"CHECK (source IN ({sources}))"
    )
