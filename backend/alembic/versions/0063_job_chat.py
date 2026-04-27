"""Job Chat — wiadomości, mentions, read state, FTS

Revision ID: 0063_job_chat
Revises: 0062_engagement_declaration_tokens
Create Date: 2026-04-27 12:00:00.000000

Context:
    Brak wewnętrznego czatu zespołu per rekrutacja. DL + collaborators dyskutują
    poza systemem (Teams/Slack/WhatsApp) → utrata kontekstu, brak audytu.

What this migration does:
    1. Rozszerza enum `notificationtype` o dwie wartości:
       `job_chat_message` i `job_chat_mention` (PG-safe ADD VALUE).
    2. Tworzy 3 tabele: `job_chat_messages`, `job_chat_mentions`,
       `job_chat_read_state`.
    3. Buduje GIN index po `search_vector` (Postgres FTS) + trigger
       który aktualizuje wektor na każdym INSERT/UPDATE OF content.
    4. Partial index po pinned wiadomościach — listę pinów uciągnie tanio
       nawet przy milionach wierszy.

Safety net:
    - `ALTER TYPE ... ADD VALUE` w autocommit_block (PG limitation).
    - `CREATE TABLE/INDEX` z idempotentnymi `IF NOT EXISTS`.
    - Trigger function `job_chat_messages_search_trigger` — `CREATE OR REPLACE`.
    - Downgrade dropuje tabele + funkcję; enum values pozostają (PG nie wspiera
      ich usuwania bez rekreacji typu).
"""

from alembic import op
import sqlalchemy as sa


revision = "0063_job_chat"
down_revision = "0062_engagement_declaration_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Rozszerz enum NotificationType + UserActionType (PG: ADD VALUE
    #    wymaga autocommit).
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notificationtype "
            "ADD VALUE IF NOT EXISTS 'job_chat_message'"
        )
        op.execute(
            "ALTER TYPE notificationtype "
            "ADD VALUE IF NOT EXISTS 'job_chat_mention'"
        )
        op.execute(
            "ALTER TYPE useractiontype "
            "ADD VALUE IF NOT EXISTS 'chat_message_added'"
        )

    # 2) job_chat_messages
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS job_chat_messages (
            id SERIAL PRIMARY KEY,
            job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            author_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            content TEXT NOT NULL,
            reply_to_message_id INTEGER NULL
                REFERENCES job_chat_messages(id) ON DELETE SET NULL,
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
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_chat_messages_job_id "
        "ON job_chat_messages (job_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_chat_messages_author_id "
        "ON job_chat_messages (author_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_chat_messages_is_deleted "
        "ON job_chat_messages (is_deleted)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_chat_messages_job_created "
        "ON job_chat_messages (job_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_chat_messages_search "
        "ON job_chat_messages USING gin (search_vector)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_chat_messages_pinned "
        "ON job_chat_messages (job_id, pinned_at) "
        "WHERE pinned = TRUE AND is_deleted = FALSE"
    )

    # 3) FTS trigger — aktualizuje search_vector na INSERT i UPDATE OF content.
    #    'simple' config = bez stemming (PL/EN mieszanka, działa poprawnie dla
    #    obu języków bez instalacji dodatkowych słowników).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION job_chat_messages_search_trigger()
        RETURNS trigger AS $$
        BEGIN
            NEW.search_vector := to_tsvector('simple', COALESCE(NEW.content, ''));
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS job_chat_messages_search_update
        ON job_chat_messages
        """
    )
    op.execute(
        """
        CREATE TRIGGER job_chat_messages_search_update
        BEFORE INSERT OR UPDATE OF content
        ON job_chat_messages
        FOR EACH ROW EXECUTE FUNCTION job_chat_messages_search_trigger()
        """
    )

    # 4) updated_at auto-touch (TimestampMixin używa onupdate=func.now() ale
    #    surowy SQL UPDATE go nie wywoła; dodajmy trigger dla bezpieczeństwa).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION job_chat_messages_touch_updated_at()
        RETURNS trigger AS $$
        BEGIN
            NEW.updated_at := NOW();
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS job_chat_messages_touch_updated_at
        ON job_chat_messages
        """
    )
    op.execute(
        """
        CREATE TRIGGER job_chat_messages_touch_updated_at
        BEFORE UPDATE ON job_chat_messages
        FOR EACH ROW EXECUTE FUNCTION job_chat_messages_touch_updated_at()
        """
    )

    # 5) job_chat_mentions
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS job_chat_mentions (
            id SERIAL PRIMARY KEY,
            message_id INTEGER NOT NULL
                REFERENCES job_chat_messages(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_job_chat_mentions_msg_user
                UNIQUE (message_id, user_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_chat_mentions_message_id "
        "ON job_chat_mentions (message_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_chat_mentions_user "
        "ON job_chat_mentions (user_id)"
    )

    # 6) job_chat_read_state
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS job_chat_read_state (
            id SERIAL PRIMARY KEY,
            job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            last_read_message_id INTEGER NULL
                REFERENCES job_chat_messages(id) ON DELETE SET NULL,
            last_read_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_job_chat_read_state_job_user
                UNIQUE (job_id, user_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_chat_read_state_job_id "
        "ON job_chat_read_state (job_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_chat_read_state_user_id "
        "ON job_chat_read_state (user_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS job_chat_read_state")
    op.execute("DROP TABLE IF EXISTS job_chat_mentions")
    op.execute(
        "DROP TRIGGER IF EXISTS job_chat_messages_touch_updated_at "
        "ON job_chat_messages"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS job_chat_messages_touch_updated_at()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS job_chat_messages_search_update "
        "ON job_chat_messages"
    )
    op.execute("DROP FUNCTION IF EXISTS job_chat_messages_search_trigger()")
    op.execute("DROP TABLE IF EXISTS job_chat_messages")
    # Enum values 'job_chat_message', 'job_chat_mention' pozostają — PG nie
    # pozwala ich usunąć bez rekreacji typu (i tak były idempotentnie dodane).
