"""b2b_generated_contracts.render_payload — zapis do ponownego pobrania DOCX.

Revision ID: 0132_b2b_render_payload
Revises: 0131_saved_search_match_log
Create Date: 2026-06-16

Standalone render (``/render?format=docx``) zapisuje tu surowe pola formularza
(``B2BRenderRequest`` jako JSON), żeby umowę dało się odtworzyć i pobrać ponownie
z zakładki „Wygenerowane umowy". Stare wiersze mają NULL → dla nich re-download
jest niedostępny (trzeba wygenerować ponownie).

Idempotentne (IF NOT EXISTS) — bezpieczne przy ewentualnym re-runie.
"""

from alembic import op

revision = "0132_b2b_render_payload"
down_revision = "0131_saved_search_match_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE b2b_generated_contracts "
        "ADD COLUMN IF NOT EXISTS render_payload JSONB"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE b2b_generated_contracts DROP COLUMN IF EXISTS render_payload"
    )
