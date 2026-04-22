"""Reporting matrices + gamification tables (port z InfraReportera)

Revision ID: 0038_reporting_matrices
Revises: 0037_contracts_expansion
Create Date: 2026-04-22 20:00:00.000000

Scope:
  1. jobs.delivery_lead_id FK NULLABLE — który DL odpowiada za dany Job
  2. user_competence_categories.priority SMALLINT NULL — 1=1st priority,
     2=2nd priority (dla sourcerów w kategorii kompetencji)
  3. Nowa tabela `tac_delivery_lead_assignments` — jeden TAC → jeden DL
  4. Nowa tabela `tac_linkedin_farming` — TAC farmuje wiele kategorii
     kompetencji na LinkedIn
  5. Nowa tabela `delivery_lead_client_assignments` — DL → klienci (z flagą
     `is_head` = główny opiekun klienta)
  6. Nowa tabela `competition_winners` — snapshot Liga Mistrzów Q +
     Wyścigów Miesięcznych (zamrażane na koniec okresu, żeby historia się
     nie zmieniała)

Pattern: idempotentne `IF NOT EXISTS` / `DO $$ BEGIN ... END$$` — safe pod
`entrypoint.sh` re-runs i Base.metadata.create_all() w DEV.
"""

from alembic import op


revision = "0038_reporting_matrices"
down_revision = "0037_contracts_expansion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. jobs.delivery_lead_id ──────────────────────────────────────────
    op.execute(
        "ALTER TABLE jobs "
        "ADD COLUMN IF NOT EXISTS delivery_lead_id INTEGER "
        "REFERENCES users(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_delivery_lead_id "
        "ON jobs (delivery_lead_id)"
    )

    # ── 2. user_competence_categories.priority ────────────────────────────
    # 1 = 1st priority (główna kategoria sourcera)
    # 2 = 2nd priority (druga kategoria)
    # NULL = brak ustalenia (backward-compat z istniejącymi wierszami)
    op.execute(
        "ALTER TABLE user_competence_categories "
        "ADD COLUMN IF NOT EXISTS priority SMALLINT"
    )
    # PostgreSQL nie wspiera `ADD CONSTRAINT IF NOT EXISTS` — używamy
    # idempotentnego bloku DO.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_user_cc_priority'
            ) THEN
                ALTER TABLE user_competence_categories
                    ADD CONSTRAINT ck_user_cc_priority
                    CHECK (priority IS NULL OR priority IN (1, 2));
            END IF;
        END$$;
        """
    )

    # ── 3. tac_delivery_lead_assignments ──────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tac_delivery_lead_assignments (
            id SERIAL PRIMARY KEY,
            tac_user_id INTEGER NOT NULL UNIQUE
                REFERENCES users(id) ON DELETE CASCADE,
            delivery_lead_user_id INTEGER NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tac_dl_assignments_dl "
        "ON tac_delivery_lead_assignments (delivery_lead_user_id)"
    )

    # ── 4. tac_linkedin_farming ───────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tac_linkedin_farming (
            id SERIAL PRIMARY KEY,
            tac_user_id INTEGER NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            competence_category_id INTEGER NOT NULL
                REFERENCES competence_categories(id) ON DELETE CASCADE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT uq_tac_linkedin_farming UNIQUE (tac_user_id, competence_category_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tac_linkedin_farming_tac "
        "ON tac_linkedin_farming (tac_user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tac_linkedin_farming_cc "
        "ON tac_linkedin_farming (competence_category_id)"
    )

    # ── 5. delivery_lead_client_assignments ───────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS delivery_lead_client_assignments (
            id SERIAL PRIMARY KEY,
            delivery_lead_user_id INTEGER NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            client_id INTEGER NOT NULL
                REFERENCES clients(id) ON DELETE CASCADE,
            is_head BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT uq_dl_client UNIQUE (delivery_lead_user_id, client_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_dl_client_client "
        "ON delivery_lead_client_assignments (client_id)"
    )
    # Tylko jeden is_head=true per client.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_dl_client_head "
        "ON delivery_lead_client_assignments (client_id) WHERE is_head = true"
    )

    # ── 6. competition_winners ────────────────────────────────────────────
    # Zamrożone wyniki Liga Mistrzów Q + Wyścigów Miesięcznych.
    # `frozen_snapshot` (JSONB) trzyma pełne dane z momentu zamknięcia,
    # żeby późniejsze zmiany w candidate_stages nie zmieniały historii.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS competition_winners (
            id SERIAL PRIMARY KEY,
            competition_type VARCHAR(50) NOT NULL,
            period VARCHAR(20) NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            rank SMALLINT NOT NULL,
            points INTEGER NOT NULL DEFAULT 0,
            metric_value INTEGER NOT NULL DEFAULT 0,
            prize_pln INTEGER NOT NULL DEFAULT 0,
            frozen_snapshot JSONB,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT ck_competition_rank CHECK (rank IN (1, 2, 3)),
            CONSTRAINT uq_competition UNIQUE (competition_type, period, rank)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_competition_winners_user "
        "ON competition_winners (user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_competition_winners_type_period "
        "ON competition_winners (competition_type, period)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS competition_winners")
    op.execute("DROP TABLE IF EXISTS delivery_lead_client_assignments")
    op.execute("DROP TABLE IF EXISTS tac_linkedin_farming")
    op.execute("DROP TABLE IF EXISTS tac_delivery_lead_assignments")

    op.execute(
        "ALTER TABLE user_competence_categories "
        "DROP CONSTRAINT IF EXISTS ck_user_cc_priority"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='user_competence_categories'
                  AND column_name='priority'
            ) THEN
                ALTER TABLE user_competence_categories DROP COLUMN priority;
            END IF;
        END$$;
        """
    )

    op.execute("DROP INDEX IF EXISTS ix_jobs_delivery_lead_id")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='jobs' AND column_name='delivery_lead_id'
            ) THEN
                ALTER TABLE jobs DROP COLUMN delivery_lead_id;
            END IF;
        END$$;
        """
    )
