"""Archiwum historii rekrutacji usuniętej korekcyjnie.

``DELETE /api/candidates/{id}/recruitments/{job_id}`` kasuje WSZYSTKIE
``CandidateStage`` pary, a kaskadą snapshoty CV, share-tokeny i zaplanowane
maile odrzucenia. Po takiej korekcie nie dało się odtworzyć, przez jakie etapy
kandydat przeszedł ani kto go przesuwał — zostawało zbiorcze ``Activity`` bez
treści decyzji.

Ta tabela trzyma pełne wiersze sprzed skasowania. Korekta nadal usuwa kandydata
z pipeline'u (to jej cel), ale dowód przebiegu procesu zostaje.

Archiwum, a nie flaga ``voided`` na ``candidate_stages``: flagę trzeba by
filtrować w 132 zapytaniach w 64 plikach, a pierwsze pominięte pokazywałoby
skasowaną rekrutację jako żywą.

Bez FK do ``candidates``/``jobs`` — archiwum ma przeżyć skasowanie kandydata
albo oferty; kaskada zabrałaby dokładnie ten dowód, dla którego istnieje.

Czysto addytywne: nowa tabela, zero zmian w istniejących.

Revision ID: 0199_candidate_stage_removals
Revises: 0198_notification_email_send_started_at
"""

from alembic import op


revision = "0199_candidate_stage_removals"
down_revision = "0198_notification_email_send_started_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Produkcja bootstrapuje ten sam DDL w entrypoint.sh — alembic_version na
    # prodzie jest osierocony, więc każda nowa tabela musi mieć tam lustro.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_stage_removals (
            id BIGSERIAL PRIMARY KEY,
            candidate_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            removed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            removed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            reason TEXT,
            last_stage VARCHAR(64),
            stage_count INTEGER NOT NULL DEFAULT 0,
            stages_snapshot JSONB NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_stage_removals_pair "
        "ON candidate_stage_removals (candidate_id, job_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_stage_removals_removed_at "
        "ON candidate_stage_removals (removed_at)"
    )


def downgrade() -> None:
    # Świadomie no-op: down-migracja skasowałaby jedyny ślad po usuniętych
    # rekrutacjach, czyli zrobiła dokładnie to, czemu ta tabela zapobiega.
    pass
