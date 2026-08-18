"""Cykliczna ekstrakcja notatek: AIFeatureKey ``notes_extraction`` + seed.

Revision ID: 0230_notes_extraction_ai_feature
Revises: 0229_help_materials_invite_template
Create Date: 2026-08-17

Klucz kwotowy dla pętli ``notes_insights_sync`` (świeżość
``cv_extracted_data._notes_insights`` po imporcie 08.2026). OSOBNY kubełek od
``cv_parser``/``cv_backfill`` z tego samego powodu co przy 0214: bieg tła nie
może wyczerpać limitu funkcji interaktywnych rekruterów ani wymusić limitu tak
wysokiego, że przestaje chronić.

Kalka 0214: ADD VALUE w autocommit (wymóg ALTER TYPE), seed idempotentny.
Zdublowane w safety-net ``entrypoint.sh`` (prod alembic bywa orphaned).
"""

from alembic import op

revision = "0230_notes_extraction_ai_feature"
down_revision = "0229_help_materials_invite_template"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'notes_extraction'"
        )

    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        "SELECT 'notes_extraction', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS (SELECT 1 FROM ai_features WHERE feature = 'notes_extraction')"
    )


def downgrade() -> None:
    # PostgreSQL nie kasuje wartości enuma in-place — 'notes_extraction'
    # zostaje w typie (bezpieczne, nieużywane po usunięciu seedu).
    op.execute("DELETE FROM ai_features WHERE feature = 'notes_extraction'")
