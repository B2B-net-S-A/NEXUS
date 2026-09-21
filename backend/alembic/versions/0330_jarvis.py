"""Jarvis — asystent-agent w shellu aplikacji (zastępuje MINDY).

Revision ID: 0330_jarvis
Revises: 0329_candidate_search_completed_notif

- kubełek AI ``jarvis`` (wartość enuma + seed ``ai_features``) — kalka 0327:
  ADD VALUE w autocommicie, seed poza blokiem i idempotentny;
- ``users.jarvis_prefs`` — wygląd maskotki per osoba;
- cztery tabele rozmów (opis w ``app/models/jarvis.py``).

Zdublowane w safety-necie ``entrypoint.sh`` — prod alembic bywa orphaned.
Każda instrukcja z ``DDL_STATEMENTS`` musi mieć tam lustro; pilnuje tego
``tests/test_jarvis_migration_mirror.py``.
"""

import sqlalchemy as sa
from alembic import op

from app.data.procedures import JARVIS_PROCEDURE

revision = "0330_jarvis"
down_revision = "0329_candidate_search_completed_notif"
branch_labels = None
depends_on = None


ADD_JARVIS_PREFS = "ALTER TABLE users ADD COLUMN IF NOT EXISTS jarvis_prefs JSONB NOT NULL DEFAULT '{}'::jsonb"

CREATE_CONVERSATIONS = """CREATE TABLE IF NOT EXISTS jarvis_conversations (
    id UUID PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(200) NOT NULL DEFAULT 'Nowa rozmowa',
    last_context JSONB NULL,
    busy_until TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)"""

INDEX_CONVERSATIONS = (
    "CREATE INDEX IF NOT EXISTS ix_jarvis_conversations_user_updated "
    "ON jarvis_conversations (user_id, updated_at)"
)

CREATE_MESSAGES = """CREATE TABLE IF NOT EXISTS jarvis_messages (
    id BIGSERIAL PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES jarvis_conversations(id) ON DELETE CASCADE,
    role VARCHAR(16) NOT NULL,
    content JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_jarvis_messages_role CHECK (role IN ('user', 'assistant'))
)"""

INDEX_MESSAGES = (
    "CREATE INDEX IF NOT EXISTS ix_jarvis_messages_conversation "
    "ON jarvis_messages (conversation_id, id)"
)

CREATE_ACTIONS = """CREATE TABLE IF NOT EXISTS jarvis_actions (
    id UUID PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES jarvis_conversations(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tool_use_id VARCHAR(100) NOT NULL,
    tool_name VARCHAR(64) NOT NULL,
    args JSONB NOT NULL,
    preview JSONB NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'proposed',
    result JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at TIMESTAMPTZ NULL,
    CONSTRAINT ck_jarvis_actions_status CHECK (
        status IN ('proposed', 'confirmed', 'rejected', 'executed', 'failed', 'expired')
    )
)"""

INDEX_ACTIONS_CONVERSATION = (
    "CREATE INDEX IF NOT EXISTS ix_jarvis_actions_conversation "
    "ON jarvis_actions (conversation_id)"
)

INDEX_ACTIONS_STATUS = (
    "CREATE INDEX IF NOT EXISTS ix_jarvis_actions_status_created "
    "ON jarvis_actions (status, created_at)"
)

CREATE_ENTITIES = """CREATE TABLE IF NOT EXISTS jarvis_conversation_entities (
    conversation_id UUID NOT NULL REFERENCES jarvis_conversations(id) ON DELETE CASCADE,
    entity_type VARCHAR(32) NOT NULL,
    entity_id INTEGER NOT NULL,
    PRIMARY KEY (conversation_id, entity_type, entity_id)
)"""

INDEX_ENTITIES = (
    "CREATE INDEX IF NOT EXISTS ix_jarvis_conversation_entities_entity "
    "ON jarvis_conversation_entities (entity_type, entity_id)"
)

DDL_STATEMENTS = (
    ADD_JARVIS_PREFS,
    CREATE_CONVERSATIONS,
    INDEX_CONVERSATIONS,
    CREATE_MESSAGES,
    INDEX_MESSAGES,
    CREATE_ACTIONS,
    INDEX_ACTIONS_CONVERSATION,
    INDEX_ACTIONS_STATUS,
    CREATE_ENTITIES,
    INDEX_ENTITIES,
)


def upgrade() -> None:
    # ADD VALUE musi biec w autocommicie: Postgres nie pozwala użyć nowej
    # etykiety enuma w tej samej transakcji, w której ją dodano.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'jarvis'")

    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        "SELECT 'jarvis', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS (SELECT 1 FROM ai_features WHERE feature = 'jarvis')"
    )

    for statement in DDL_STATEMENTS:
        op.execute(statement)

    # Procedura w Pomocy „co Jarvis umie” — ten sam plik czyta entrypoint.
    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO procedures
                (title, slug, content, sort_order, is_published, created_at, updated_at)
            VALUES (:title, :slug, :content, :sort_order, TRUE, now(), now())
            ON CONFLICT (slug) DO UPDATE
                SET title = EXCLUDED.title,
                    content = EXCLUDED.content,
                    sort_order = EXCLUDED.sort_order,
                    updated_at = now()
                WHERE procedures.updated_by IS NULL
            """
        ),
        {
            "title": JARVIS_PROCEDURE.title,
            "slug": JARVIS_PROCEDURE.slug,
            "content": JARVIS_PROCEDURE.read(),
            "sort_order": JARVIS_PROCEDURE.sort_order,
        },
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM procedures WHERE slug = 'jarvis-asystent' AND updated_by IS NULL"
    )
    op.execute("DROP TABLE IF EXISTS jarvis_conversation_entities")
    op.execute("DROP TABLE IF EXISTS jarvis_actions")
    op.execute("DROP TABLE IF EXISTS jarvis_messages")
    op.execute("DROP TABLE IF EXISTS jarvis_conversations")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS jarvis_prefs")
    # Wartości enuma w Postgresie nie da się usunąć bez przepisania typu.
    op.execute("DELETE FROM ai_features WHERE feature = 'jarvis'")
