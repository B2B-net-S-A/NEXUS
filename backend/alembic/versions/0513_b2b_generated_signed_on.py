"""Dzień podpisu umowy B2B z Generatora.

Revision ID: 0513_b2b_generated_signed_on
Revises: 0512_care_board_waiting_decision

* ``b2b_generated_contracts.signed_on`` — dzień, w którym umowę podpisano,
  wpisany w oknie „Oznacz jako podpisaną” (domyślnie dziś) albo dzień podpisu
  kontraktora w NEXUSIE. ``signed_at`` zostaje chwilą oznaczenia: na kopii
  produkcji z 22.10.2026 była 1–5 dni późniejsza niż data w arkuszu Delivery
  w 23 z 33 październikowych placementów. Starszych wierszy nie uzupełniamy —
  prawdziwej daty nie znamy, eksport bierze wtedy ``signed_at``.

Lustro w ``entrypoint.sh`` (alembic na prodzie bywa osierocony).
"""

from alembic import op

revision = "0513_b2b_generated_signed_on"
down_revision = "0512_care_board_waiting_decision"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE b2b_generated_contracts ADD COLUMN IF NOT EXISTS signed_on DATE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE b2b_generated_contracts DROP COLUMN IF EXISTS signed_on")
