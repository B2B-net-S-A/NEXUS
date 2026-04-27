"""Note + ScreeningNote mentions

Revision ID: 0066_note_mentions
Revises: 0065_chat_phase2
Create Date: 2026-04-27 18:00:00.000000

Context:
    @mention support w zwykłych notatkach (Note) i notatkach ze screeningu
    (ScreeningNote). Wzorzec mirror'owany z `job_chat_mentions` /
    `candidate_chat_mentions` z 0063/0065.

What this migration does:
    1. ALTER TYPE notificationtype ADD VALUE 'note_mention' (autocommit_block).
    2. CREATE TABLE note_mentions (note_id, user_id) UNIQUE.
    3. CREATE TABLE screening_note_mentions (screening_note_id, user_id) UNIQUE.

Safety-net: każde DDL idempotentne (IF NOT EXISTS).
"""

from alembic import op


revision = "0066_note_mentions"
down_revision = "0065_chat_phase2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Enum value note_mention (PG: ADD VALUE wymaga autocommit).
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'note_mention'"
        )

    # 2) note_mentions
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS note_mentions (
            id SERIAL PRIMARY KEY,
            note_id INTEGER NOT NULL
                REFERENCES notes(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_note_mentions_note_user
                UNIQUE (note_id, user_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_note_mentions_note_id "
        "ON note_mentions (note_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_note_mentions_user_id "
        "ON note_mentions (user_id)"
    )

    # 3) screening_note_mentions
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS screening_note_mentions (
            id SERIAL PRIMARY KEY,
            screening_note_id INTEGER NOT NULL
                REFERENCES screening_notes(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_screening_note_mentions_note_user
                UNIQUE (screening_note_id, user_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_screening_note_mentions_note_id "
        "ON screening_note_mentions (screening_note_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_screening_note_mentions_user_id "
        "ON screening_note_mentions (user_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS screening_note_mentions")
    op.execute("DROP TABLE IF EXISTS note_mentions")
    # Brak rollback dla enum value 'note_mention' — PG limitation.
