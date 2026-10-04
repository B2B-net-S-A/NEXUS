"""Rekrutacja bez szkiców: „Klient nie podał” przy hiring managerze i terminie.

Revision ID: 0414_job_required_decisions
Revises: 0413_recommendation_cards

Decyzja Artura 04.10.2026: rekrutacja nigdy nie jest szkicem — utworzenie,
przekazanie do searchu i publikacja to jedno żądanie. Termin i hiring manager
są wymaganą DECYZJĄ: wartość albo jawne „Klient nie podał”. Dwie flagi
(domyślnie ``false``) niosą tę drugą odpowiedź; zapis wartości je zeruje.

Do tego znacznik startu okna zamykania starych szkiców
(``app_settings['legacy_draft_autoclose:deployed_at']``) — szkice założone
przed tą zmianą zamykają się same po 7 dniach, bez kasowania danych
(``services/legacy_draft_autoclose.py``). Lustro DDL i znacznika
w ``entrypoint.sh``.
"""

from alembic import op

revision = "0414_job_required_decisions"
down_revision = "0413_recommendation_cards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS hiring_manager_not_provided "
        "BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS deadline_not_provided "
        "BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "INSERT INTO app_settings (key, value) "
        "VALUES ('legacy_draft_autoclose:deployed_at', "
        "jsonb_build_object('deployed_at', now())) "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    # Flagi są decyzją człowieka („Klient nie podał”) — po ich zdjęciu bramka
    # przekazania pytałaby o nie od nowa, ale żadna wartość nie przepada.
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS deadline_not_provided")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS hiring_manager_not_provided")
