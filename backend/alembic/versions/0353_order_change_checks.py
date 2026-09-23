"""Finanse: odhaczenia zmian w zamówieniach i pobrania PDF-ów per osoba.

Revision ID: 0353_order_change_checks
Revises: 0352_pipeline_v4

* ``order_change_checks`` — dopisywany audyt „Zrobione" / „Cofnięto"
  pozycji z Finanse → Zmiany w zamówieniach. Stan pozycji = ostatni wpis jej
  klucza; bez FK, żeby ślad przeżył usunięcie zamówienia i konta.
* ``order_pdf_downloads`` — kto pobrał który PDF zamówienia (status
  „Nowy / Pobrane przez Ciebie" osobny dla każdej osoby).

Lustro w ``entrypoint.sh`` (alembic na prodzie bywa osierocony).
"""

from alembic import op

revision = "0353_order_change_checks"
down_revision = "0352_pipeline_v4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS order_change_checks (
            id SERIAL PRIMARY KEY,
            item_key VARCHAR(160) NOT NULL,
            tab VARCHAR(16) NOT NULL,
            period_year INTEGER NOT NULL,
            period_month INTEGER NOT NULL,
            order_id INTEGER,
            order_group_id INTEGER,
            client_id INTEGER,
            summary VARCHAR(400) NOT NULL DEFAULT '',
            action VARCHAR(10) NOT NULL,
            user_id INTEGER,
            user_name VARCHAR(255) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_order_change_checks_action
                CHECK (action IN ('checked', 'unchecked')),
            CONSTRAINT ck_order_change_checks_tab
                CHECK (tab IN ('changes', 'entries', 'exits', 'ending', 'gaps')),
            CONSTRAINT ck_order_change_checks_month
                CHECK (period_month BETWEEN 1 AND 12)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_order_change_checks_key "
        "ON order_change_checks (item_key, id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_order_change_checks_period "
        "ON order_change_checks (period_year, period_month)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_order_change_checks_order "
        "ON order_change_checks (order_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_order_change_checks_group "
        "ON order_change_checks (order_group_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS order_pdf_downloads (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            file_kind VARCHAR(16) NOT NULL,
            file_id INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            downloaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, file_kind, file_id),
            CONSTRAINT ck_order_pdf_downloads_kind
                CHECK (file_kind IN ('order', 'group', 'amendment'))
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS order_pdf_downloads")
    op.execute("DROP TABLE IF EXISTS order_change_checks")
