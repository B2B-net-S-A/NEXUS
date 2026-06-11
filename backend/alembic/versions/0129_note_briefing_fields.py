"""Briefing DL — pola source_ref + audio_url na notes

Revision ID: 0129_note_briefing_fields
Revises: 0128_b2b_number_unique
Create Date: 2026-06-11 12:00:00.000000

Context:
    Breakout-session briefing dla rekruterów (Fireflies). Notatki meetingowe z
    fireflies_sync dostają:
      - source_ref  — zewnętrzny identyfikator ("fireflies:<transcript_id>"),
        używany do dedupu przy re-syncu (in-memory last_synced_at resetuje się
        po restarcie backendu, więc bez tego sync potrafił dublować notatki),
      - audio_url   — link do nagrania z Fireflies CDN (może wygasać; przy
        oznaczeniu meetingu jako briefing audio kopiujemy do Object Storage).

Safety net: idempotentne (ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT
EXISTS) — zgodnie ze wzorcem pozostałych migracji w repo.
"""

from alembic import op


revision = "0129_note_briefing_fields"
down_revision = "0128_b2b_number_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE notes ADD COLUMN IF NOT EXISTS source_ref VARCHAR(120)")
    op.execute("ALTER TABLE notes ADD COLUMN IF NOT EXISTS audio_url TEXT")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notes_source_ref ON notes (source_ref)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_notes_source_ref")
    op.execute("ALTER TABLE notes DROP COLUMN IF EXISTS audio_url")
    op.execute("ALTER TABLE notes DROP COLUMN IF EXISTS source_ref")
