"""Chat Phase 2 — per-candidate chat, reactions, email fallback columns

Revision ID: 0065_chat_phase2
Revises: 0064_merge_microsoft365_job_chat
Create Date: 2026-04-27 16:00:00.000000

Context:
    Phase 2 chat features (5 z out-of-scope):
      F2  per-candidate chat (3 tabele: candidate_chat_messages,
          candidate_chat_mentions, candidate_chat_read_state)
      F7  message reactions (2 tabele: job_chat_message_reactions,
          candidate_chat_message_reactions)
      F9  full read receipts — derive z istniejących read_state, brak DDL
      F10 admin "read-all" superpower — brak DDL, kontrolerska zmiana
      F11 email fallback >15min offline — 2 nowe kolumny:
          users.last_seen_at, notifications.email_sent_at

What this migration does:
    1. CREATE TABLE candidate_chat_messages (mirror job_chat_messages)
       + GIN FTS index + auto-update trigger (na content)
       + partial pinned index
    2. CREATE TABLE candidate_chat_mentions (mirror job_chat_mentions)
    3. CREATE TABLE candidate_chat_read_state (mirror job_chat_read_state)
    4. CREATE TABLE job_chat_message_reactions
    5. CREATE TABLE candidate_chat_message_reactions
    6. ALTER TABLE users ADD COLUMN last_seen_at
    7. ALTER TABLE notifications ADD COLUMN email_sent_at

Safety-net: każde DDL idempotentne (IF NOT EXISTS / CREATE OR REPLACE).
"""

from alembic import op


revision = "0065_chat_phase2"
down_revision = "0064_merge_microsoft365_job_chat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) candidate_chat_messages
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_chat_messages (
            id SERIAL PRIMARY KEY,
            candidate_id INTEGER NOT NULL
                REFERENCES candidates(id) ON DELETE CASCADE,
            author_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            content TEXT NOT NULL,
            reply_to_message_id INTEGER NULL
                REFERENCES candidate_chat_messages(id) ON DELETE SET NULL,
            is_edited BOOLEAN NOT NULL DEFAULT FALSE,
            edited_at TIMESTAMP WITH TIME ZONE NULL,
            is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
            deleted_at TIMESTAMP WITH TIME ZONE NULL,
            pinned BOOLEAN NOT NULL DEFAULT FALSE,
            pinned_at TIMESTAMP WITH TIME ZONE NULL,
            pinned_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            external_platform VARCHAR(32) NULL,
            external_message_id VARCHAR(255) NULL,
            search_vector tsvector NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
        """
    )
    for stmt in [
        "CREATE INDEX IF NOT EXISTS ix_candidate_chat_messages_candidate_id "
        "ON candidate_chat_messages (candidate_id)",
        "CREATE INDEX IF NOT EXISTS ix_candidate_chat_messages_author_id "
        "ON candidate_chat_messages (author_id)",
        "CREATE INDEX IF NOT EXISTS ix_candidate_chat_messages_is_deleted "
        "ON candidate_chat_messages (is_deleted)",
        "CREATE INDEX IF NOT EXISTS ix_candidate_chat_messages_candidate_created "
        "ON candidate_chat_messages (candidate_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_candidate_chat_messages_search "
        "ON candidate_chat_messages USING gin (search_vector)",
        "CREATE INDEX IF NOT EXISTS ix_candidate_chat_messages_pinned "
        "ON candidate_chat_messages (candidate_id, pinned_at) "
        "WHERE pinned = TRUE AND is_deleted = FALSE",
    ]:
        op.execute(stmt)

    # FTS trigger (reuse function name pattern)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION candidate_chat_messages_search_trigger()
        RETURNS trigger AS $$
        BEGIN
            NEW.search_vector := to_tsvector('simple', COALESCE(NEW.content, ''));
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS candidate_chat_messages_search_update "
        "ON candidate_chat_messages"
    )
    op.execute(
        """
        CREATE TRIGGER candidate_chat_messages_search_update
        BEFORE INSERT OR UPDATE OF content
        ON candidate_chat_messages
        FOR EACH ROW EXECUTE FUNCTION candidate_chat_messages_search_trigger()
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION candidate_chat_messages_touch_updated_at()
        RETURNS trigger AS $$
        BEGIN
            NEW.updated_at := NOW();
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS candidate_chat_messages_touch_updated_at "
        "ON candidate_chat_messages"
    )
    op.execute(
        """
        CREATE TRIGGER candidate_chat_messages_touch_updated_at
        BEFORE UPDATE ON candidate_chat_messages
        FOR EACH ROW EXECUTE FUNCTION candidate_chat_messages_touch_updated_at()
        """
    )

    # 2) candidate_chat_mentions
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_chat_mentions (
            id SERIAL PRIMARY KEY,
            message_id INTEGER NOT NULL
                REFERENCES candidate_chat_messages(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_candidate_chat_mentions_msg_user
                UNIQUE (message_id, user_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_chat_mentions_message_id "
        "ON candidate_chat_mentions (message_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_chat_mentions_user "
        "ON candidate_chat_mentions (user_id)"
    )

    # 3) candidate_chat_read_state
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_chat_read_state (
            id SERIAL PRIMARY KEY,
            candidate_id INTEGER NOT NULL
                REFERENCES candidates(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            last_read_message_id INTEGER NULL
                REFERENCES candidate_chat_messages(id) ON DELETE SET NULL,
            last_read_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_candidate_chat_read_state_candidate_user
                UNIQUE (candidate_id, user_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_chat_read_state_candidate_id "
        "ON candidate_chat_read_state (candidate_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_chat_read_state_user_id "
        "ON candidate_chat_read_state (user_id)"
    )

    # 4) job_chat_message_reactions
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS job_chat_message_reactions (
            id SERIAL PRIMARY KEY,
            message_id INTEGER NOT NULL
                REFERENCES job_chat_messages(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            emoji VARCHAR(16) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_job_chat_msg_reaction
                UNIQUE (message_id, user_id, emoji)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_chat_msg_reactions_message "
        "ON job_chat_message_reactions (message_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_chat_msg_reactions_user_id "
        "ON job_chat_message_reactions (user_id)"
    )

    # 5) candidate_chat_message_reactions
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_chat_message_reactions (
            id SERIAL PRIMARY KEY,
            message_id INTEGER NOT NULL
                REFERENCES candidate_chat_messages(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            emoji VARCHAR(16) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_candidate_chat_msg_reaction
                UNIQUE (message_id, user_id, emoji)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_chat_msg_reactions_message "
        "ON candidate_chat_message_reactions (message_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_chat_msg_reactions_user_id "
        "ON candidate_chat_message_reactions (user_id)"
    )

    # 6) users.last_seen_at + index
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_last_seen_at ON users (last_seen_at)"
    )

    # 7) notifications.email_sent_at
    op.execute(
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS email_sent_at TIMESTAMPTZ NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE notifications DROP COLUMN IF EXISTS email_sent_at")
    op.execute("DROP INDEX IF EXISTS ix_users_last_seen_at")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS last_seen_at")
    op.execute("DROP TABLE IF EXISTS candidate_chat_message_reactions")
    op.execute("DROP TABLE IF EXISTS job_chat_message_reactions")
    op.execute("DROP TABLE IF EXISTS candidate_chat_read_state")
    op.execute("DROP TABLE IF EXISTS candidate_chat_mentions")
    op.execute(
        "DROP TRIGGER IF EXISTS candidate_chat_messages_touch_updated_at "
        "ON candidate_chat_messages"
    )
    op.execute("DROP FUNCTION IF EXISTS candidate_chat_messages_touch_updated_at()")
    op.execute(
        "DROP TRIGGER IF EXISTS candidate_chat_messages_search_update "
        "ON candidate_chat_messages"
    )
    op.execute("DROP FUNCTION IF EXISTS candidate_chat_messages_search_trigger()")
    op.execute("DROP TABLE IF EXISTS candidate_chat_messages")
