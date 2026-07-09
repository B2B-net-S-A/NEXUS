"""AI match-justification cache for the candidate "Dopasowanie" tab.

Revision ID: 0156_candidate_match_justifications
Revises: 0155_contract_status_coherence_backfill
Create Date: 2026-07-09

``candidate_match_justifications`` — jeden wiersz na parę (kandydat, oferta) z
prozą uzasadnienia punktacji AI: ``summary`` ("Podsumowanie"), ``pros`` ("Może
być dobrym wyborem, ponieważ"), ``watchouts`` ("Do weryfikacji") + snapshot
``score`` i ``input_hash`` (odcisk wejść → auto-regeneracja gdy CV/wymagania/
champion/wynik się zmienią). ``rating``/``rating_comment`` = feedback „Oceń ten
scoring" (kciuk w górę/dół, wzorzec z champion_profile_suggestions).

Seeduje też wiersz ``ai_features`` dla capability ``scoring`` (Traffit-parytet:
„Scoring kandydatów" w Ustawieniach → AI), żeby feature był widoczny i miał
licznik zużycia. Serwis i tak toleruje brak wiersza (domyślnie enabled).

Idempotent: CREATE TABLE/INDEX z IF NOT EXISTS + seed pod ``WHERE NOT EXISTS`` —
współgra z entrypoint ``alembic upgrade heads`` oraz ``Base.metadata.create_all``.
"""

from alembic import op

revision = "0156_candidate_match_justifications"
down_revision = "0155_contract_status_coherence_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_match_justifications (
            id              SERIAL PRIMARY KEY,
            candidate_id    INTEGER NOT NULL
                                REFERENCES candidates(id) ON DELETE CASCADE,
            job_id          INTEGER NOT NULL
                                REFERENCES jobs(id) ON DELETE CASCADE,
            score           INTEGER NOT NULL,
            summary         TEXT NOT NULL,
            pros            JSONB NOT NULL DEFAULT '[]'::jsonb,
            watchouts       JSONB NOT NULL DEFAULT '[]'::jsonb,
            model           VARCHAR(64) NULL,
            input_hash      VARCHAR(64) NOT NULL,
            rating          SMALLINT NULL,
            rating_comment  TEXT NULL,
            rated_by        INTEGER NULL
                                REFERENCES users(id) ON DELETE SET NULL,
            rated_at        TIMESTAMPTZ NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_candidate_match_justification
                UNIQUE (candidate_id, job_id),
            CONSTRAINT chk_candidate_match_justification_rating
                CHECK (rating IS NULL OR rating IN (-1, 0, 1))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_match_justifications_candidate_id "
        "ON candidate_match_justifications (candidate_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_match_justifications_job_id "
        "ON candidate_match_justifications (job_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_match_justifications_input_hash "
        "ON candidate_match_justifications (input_hash)"
    )

    # Seed the reserved `scoring` AI feature so it shows in Settings → AI with a
    # usage counter. Guarded on table existence + row absence → safe no-op on a
    # multi-head prod where `ai_features` may or may not exist yet.
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.ai_features') IS NOT NULL THEN
                INSERT INTO ai_features (feature, enabled, monthly_limit,
                                         created_at, updated_at)
                SELECT 'scoring', TRUE, 0, now(), now()
                WHERE NOT EXISTS (
                    SELECT 1 FROM ai_features WHERE feature = 'scoring'
                );
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS candidate_match_justifications")
