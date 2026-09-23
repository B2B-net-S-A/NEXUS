"""Mail potwierdzenia aplikacji: tabela dedupu (adres, link) na 24 h.

Revision ID: 0357_application_confirmation
Revises: 0356_kpi_targets_editor_reports

* ``application_confirmation_sends`` — HMAC adresu kandydata + nie-sekretny
  klucz linku aplikacyjnego; ``sent_at`` = ostatnia wysyłka. Bez jawnego
  e-maila i bez FK (wiersze żyją najwyżej dwie doby).

Rodzaj „Potwierdzenie aplikacji” w polityce powiadomień nie wymaga zmian
schematu — polityka żyje w ``app_settings`` i brak wpisu = wyłączony.
Lustro w ``entrypoint.sh`` (alembic na prodzie bywa osierocony).
"""

from alembic import op

revision = "0357_application_confirmation"
down_revision = "0356_kpi_targets_editor_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS application_confirmation_sends (
            id SERIAL PRIMARY KEY,
            email_key VARCHAR(64) NOT NULL,
            link_key VARCHAR(64) NOT NULL,
            sent_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_application_confirmation_sends_pair
                UNIQUE (email_key, link_key)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS application_confirmation_sends")
