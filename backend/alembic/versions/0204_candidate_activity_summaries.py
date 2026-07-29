"""AI activity-summary cache for the candidate "Podsumowanie aktywności" card.

Revision ID: 0204_candidate_activity_summaries
Revises: 0203_b2b_generated_contract_status
Create Date: 2026-07-29

``candidate_activity_summaries`` — jeden wiersz na kandydata z krótką notatką
AI podsumowującą całą historię aktywności (wysyłki na projekty, feedbacki po
interview, preferencje/ograniczenia, stawki, dostępność, powody odrzuceń).
``input_hash`` = odcisk zebranej historii + wersji promptu → przycisk
„Aktualizuj notatkę" płaci za nowe wywołanie LLM tylko gdy historia faktycznie
się zmieniła.

Seeduje też wiersz ``ai_features`` dla zarezerwowanego capability
``candidate_summary`` („Podsumowanie kandydata" w Ustawieniach → AI), żeby
feature był widoczny i miał licznik zużycia. Serwis i tak toleruje brak
wiersza (domyślnie enabled). Wartość ``candidate_summary`` istnieje w enumie
``aifeaturekey`` od migracji 0085.

Idempotent: CREATE TABLE/INDEX z IF NOT EXISTS + seed pod ``WHERE NOT EXISTS`` —
współgra z entrypoint ``alembic upgrade heads`` oraz ``Base.metadata.create_all``.
"""

from alembic import op

revision = "0204_candidate_activity_summaries"
down_revision = "0203_b2b_generated_contract_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_activity_summaries (
            id              SERIAL PRIMARY KEY,
            candidate_id    INTEGER NOT NULL
                                REFERENCES candidates(id) ON DELETE CASCADE,
            summary         TEXT NOT NULL,
            model           VARCHAR(64) NULL,
            input_hash      VARCHAR(64) NOT NULL,
            generated_by    INTEGER NULL
                                REFERENCES users(id) ON DELETE SET NULL,
            generated_at    TIMESTAMPTZ NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_candidate_activity_summary UNIQUE (candidate_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_activity_summaries_candidate_id "
        "ON candidate_activity_summaries (candidate_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_activity_summaries_input_hash "
        "ON candidate_activity_summaries (input_hash)"
    )

    # Seed the reserved `candidate_summary` AI feature so it shows in
    # Settings → AI with a usage counter. Guarded on table existence + row
    # absence → safe no-op wherever `ai_features` may not exist yet.
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.ai_features') IS NOT NULL THEN
                INSERT INTO ai_features (feature, enabled, monthly_limit,
                                         created_at, updated_at)
                SELECT 'candidate_summary', TRUE, 0, now(), now()
                WHERE NOT EXISTS (
                    SELECT 1 FROM ai_features WHERE feature = 'candidate_summary'
                );
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS candidate_activity_summaries")
    # Remove the seeded feature row so downgrade doesn't leave an orphan
    # `candidate_summary` entry in Settings → AI (usage log rows stay — they
    # are historical audit data, same policy as other feature removals).
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.ai_features') IS NOT NULL THEN
                DELETE FROM ai_features WHERE feature = 'candidate_summary';
            END IF;
        END $$;
        """
    )
