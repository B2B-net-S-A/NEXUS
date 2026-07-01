"""Generator CV: status generacji w tle (processing/ready/failed).

Revision ID: 0152_cv_generated_async_status
Revises: 0151_contract_client_rate_schedule
Create Date: 2026-07-01

Generacja CV leci teraz w tle (FastAPI BackgroundTasks), więc wynik nie ginie,
gdy rekruter zamknie/opuści kartę przeglądarki w trakcie tych 60-90 s — kiedyś
zamknięcie karty przerywało synchroniczny request i gubiło CV bez śladu.

Dokłada do ``cv_generated_documents`` trzy kolumny obsługujące ten flow:
  * ``status``        — VARCHAR(20) NOT NULL DEFAULT 'ready'
                        ('processing' | 'ready' | 'failed'). Istniejące wiersze
                        były zawsze ukończone → 'ready'.
  * ``error_message`` — VARCHAR(1000), powód gdy status='failed'.
  * ``warnings``      — JSONB, uwagi Claude + seatbelt (wcześniej tylko nagłówek
                        X-Generator-Warnings; przy async-generacji utrwalane).

Indeks częściowy WHERE status='processing' wspiera reaper na starcie aplikacji
(orphaned „processing" po restarcie serwera → 'failed').

Idempotent: ADD COLUMN / CREATE INDEX IF NOT EXISTS — współgra z DEBUG
``Base.metadata.create_all`` oraz z entrypoint safety-net (entrypoint.sh).
"""

from alembic import op

revision = "0152_cv_generated_async_status"
down_revision = "0151_contract_client_rate_schedule"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cv_generated_documents "
        "ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'ready'"
    )
    op.execute(
        "ALTER TABLE cv_generated_documents "
        "ADD COLUMN IF NOT EXISTS error_message VARCHAR(1000)"
    )
    op.execute(
        "ALTER TABLE cv_generated_documents "
        "ADD COLUMN IF NOT EXISTS warnings JSONB"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cv_generated_documents_status "
        "ON cv_generated_documents (status) "
        "WHERE status = 'processing'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_cv_generated_documents_status")
    op.execute("ALTER TABLE cv_generated_documents DROP COLUMN IF EXISTS warnings")
    op.execute(
        "ALTER TABLE cv_generated_documents DROP COLUMN IF EXISTS error_message"
    )
    op.execute("ALTER TABLE cv_generated_documents DROP COLUMN IF EXISTS status")
