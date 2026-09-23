"""Jarvis: telemetria pomocy na ekranie (dymki, przewodniki, podświetlenia).

Revision ID: 0355_jarvis_ui_events
Revises: 0354_order_change_checks

Po wdrożeniu przewodników ekranów decydujemy liczbami, które dymki
i przewodniki zostają: typ z kliknięciami poniżej 25% po dwóch tygodniach
jest do wyłączenia. Wiersz niesie wyłącznie klucz ekranu i kod (id kotwicy
albo kod odmowy) — nigdy dane rekordu. Retencja 90 dni (pętla
``jarvis_retention``).

Lustro w ``entrypoint.sh`` (alembic na prodzie bywa osierocony) — pilnuje
``tests/test_jarvis_migration_mirror.py``.
"""

from alembic import op

revision = "0355_jarvis_ui_events"
down_revision = "0354_order_change_checks"
branch_labels = None
depends_on = None

UI_EVENT_NAMES = (
    "bubble_shown",
    "bubble_clicked",
    "bubble_dismissed",
    "guide_opened",
    "guide_task",
    "highlight_shown",
    "highlight_missing",
    "stuck_shown",
    "stuck_clicked",
)

CREATE_UI_EVENTS = """CREATE TABLE IF NOT EXISTS jarvis_ui_events (
        id BIGSERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        event VARCHAR(40) NOT NULL,
        screen_key VARCHAR(60) NULL,
        detail VARCHAR(60) NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ck_jarvis_ui_events_event CHECK (
            event IN ('bubble_shown', 'bubble_clicked', 'bubble_dismissed', 'guide_opened', 'guide_task', 'highlight_shown', 'highlight_missing', 'stuck_shown', 'stuck_clicked')
        )
    )"""

INDEX_UI_EVENTS = (
    "CREATE INDEX IF NOT EXISTS ix_jarvis_ui_events_event_created "
    "ON jarvis_ui_events (event, created_at)"
)

DDL_STATEMENTS = (CREATE_UI_EVENTS, INDEX_UI_EVENTS)


def upgrade() -> None:
    for statement in DDL_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS jarvis_ui_events")
