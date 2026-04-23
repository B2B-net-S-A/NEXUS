"""Pending verification flow — verified stage + approval gate on candidate_stages

Revision ID: 0056_pending_verification
Revises: 0055_job_train_name
Create Date: 2026-04-23 23:00:00.000000

Context:
    Delivery lead potrzebuje "bramki" akceptacji kiedy recruiter wrzuca
    kandydata na stage "Zweryfikowany" ze stawką poza widełkami projektu
    (`expected_rate > Job.salary_max`). Dziś każdy ruch po pipeline jest
    natychmiastowy — brak sygnału biznesowego "ten rate jest poza budżetem,
    ktoś musi to potwierdzić".

What this migration does:
    1. Dodaje `verified` do enum `pipelinestage` (PG-safe ADD VALUE).
    2. Dodaje `pending_verification` do enum `notificationtype`.
    3. Tworzy nowy enum `verificationstatus` (active/pending/rejected).
    4. Dodaje 9 kolumn do `candidate_stages` opisujących stan weryfikacji
       i audit trail (kto/kiedy zaakceptował lub odrzucił, snapshot rate
       i budżetu w momencie ruchu).
    5. Partial index po `(job_id, verification_status)` ograniczony do
       wierszy `verification_status = 'pending'` — dla szybkiej listy
       "Weryfikacje czekające na akceptację" w sidebar/page.

Safety net:
    PG nie pozwala ADD VALUE w transakcji → autocommit_block (wzorzec
    z 0029/0034/0054). Wszystko idempotentne (`IF NOT EXISTS`).
    Downgrade nie usuwa wartości enum (PG ich nie wspiera bez rekreacji).
"""

from alembic import op
import sqlalchemy as sa


revision = "0056_pending_verification"
down_revision = "0055_job_train_name"
branch_labels = None
depends_on = None


PARTIAL_INDEX = "ix_candidate_stages_pending_verification"


def upgrade() -> None:
    # 1) Enum extensions — must run outside transaction (PG limitation).
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE pipelinestage ADD VALUE IF NOT EXISTS 'verified'")
        op.execute(
            "ALTER TYPE notificationtype "
            "ADD VALUE IF NOT EXISTS 'pending_verification'"
        )

    # 2) New enum for verification status.
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE verificationstatus AS ENUM ('active', 'pending', 'rejected');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    # 3) Reuse existing rateunit enum from contracts module — no new type.
    #    Columns are added one-by-one with IF NOT EXISTS for idempotency.
    op.execute(
        """
        ALTER TABLE candidate_stages
            ADD COLUMN IF NOT EXISTS verification_status verificationstatus
                NOT NULL DEFAULT 'active'
        """
    )
    op.execute(
        """
        ALTER TABLE candidate_stages
            ADD COLUMN IF NOT EXISTS expected_rate_value NUMERIC(10, 2) NULL
        """
    )
    op.execute(
        """
        ALTER TABLE candidate_stages
            ADD COLUMN IF NOT EXISTS expected_rate_unit rateunit NULL
        """
    )
    op.execute(
        """
        ALTER TABLE candidate_stages
            ADD COLUMN IF NOT EXISTS expected_rate_currency VARCHAR(3) NULL
        """
    )
    op.execute(
        """
        ALTER TABLE candidate_stages
            ADD COLUMN IF NOT EXISTS budget_max_at_move INTEGER NULL
        """
    )
    op.execute(
        """
        ALTER TABLE candidate_stages
            ADD COLUMN IF NOT EXISTS approved_by INTEGER NULL
                REFERENCES users(id)
        """
    )
    op.execute(
        """
        ALTER TABLE candidate_stages
            ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP WITH TIME ZONE NULL
        """
    )
    op.execute(
        """
        ALTER TABLE candidate_stages
            ADD COLUMN IF NOT EXISTS rejected_by INTEGER NULL
                REFERENCES users(id)
        """
    )
    op.execute(
        """
        ALTER TABLE candidate_stages
            ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMP WITH TIME ZONE NULL
        """
    )
    op.execute(
        """
        ALTER TABLE candidate_stages
            ADD COLUMN IF NOT EXISTS rejection_note TEXT NULL
        """
    )

    # 4) Partial index — keeps the "pending" lookup tiny even when the
    #    table grows to millions of rows (most are 'active').
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {PARTIAL_INDEX} "
        "ON candidate_stages (job_id, verification_status) "
        "WHERE verification_status = 'pending'"
    )

    # 5) Upsert nowy stage 'Zweryfikowany' do KAŻDEGO istniejącego templatu,
    #    żeby kanban (template-driven) miał dedykowaną kolumnę między
    #    Screening (order=2) i Interview Wewnętrzny (oryginalnie order=3).
    #
    #    Tabela ma `uq_stage_order_in_template` UNIQUE (template_id, order)
    #    bez DEFERRABLE — proste UPDATE +1 by raise duplicate key. Trick:
    #    najpierw shiftujemy o +1000 (poza pasmo), wstawiamy nowy, potem
    #    normalizujemy przez -999. Idempotent.
    op.execute(
        """
        DO $$
        DECLARE
            tpl_id INTEGER;
        BEGIN
            FOR tpl_id IN SELECT id FROM pipeline_templates LOOP
                IF NOT EXISTS (
                    SELECT 1 FROM pipeline_stage_defs
                    WHERE template_id = tpl_id
                      AND legacy_enum_value = 'verified'
                ) THEN
                    -- Step 1: shift "order" >= 3 do wysokich liczb (>=1003)
                    UPDATE pipeline_stage_defs
                       SET "order" = "order" + 1000
                     WHERE template_id = tpl_id
                       AND "order" >= 3;
                    -- Step 2: wstaw nowy stage na pozycji 3
                    INSERT INTO pipeline_stage_defs (
                        template_id, name, "order", category,
                        is_terminal, terminal_type, legacy_enum_value
                    ) VALUES (
                        tpl_id, 'Zweryfikowany', 3, 'internal',
                        FALSE, NULL, 'verified'
                    );
                    -- Step 3: znormalizuj shift (-999) — kolejne stage'y
                    -- dostają teraz wartości 4, 5, 6, ...
                    UPDATE pipeline_stage_defs
                       SET "order" = "order" - 999
                     WHERE template_id = tpl_id
                       AND "order" >= 1003;
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    # Drop only what we can safely drop — enum values stay (PG cannot remove
    # them without recreating the type, and rows might already reference them).
    # Best-effort: usuwamy stage_def 'verified' z templatów, ale nie shiftujemy
    # z powrotem (nie wiemy bezpiecznie kogo bumpnięto przy upgrade).
    op.execute(
        "DELETE FROM pipeline_stage_defs WHERE legacy_enum_value = 'verified'"
    )
    op.execute(f"DROP INDEX IF EXISTS {PARTIAL_INDEX}")
    op.execute("ALTER TABLE candidate_stages DROP COLUMN IF EXISTS rejection_note")
    op.execute("ALTER TABLE candidate_stages DROP COLUMN IF EXISTS rejected_at")
    op.execute("ALTER TABLE candidate_stages DROP COLUMN IF EXISTS rejected_by")
    op.execute("ALTER TABLE candidate_stages DROP COLUMN IF EXISTS approved_at")
    op.execute("ALTER TABLE candidate_stages DROP COLUMN IF EXISTS approved_by")
    op.execute("ALTER TABLE candidate_stages DROP COLUMN IF EXISTS budget_max_at_move")
    op.execute(
        "ALTER TABLE candidate_stages DROP COLUMN IF EXISTS expected_rate_currency"
    )
    op.execute(
        "ALTER TABLE candidate_stages DROP COLUMN IF EXISTS expected_rate_unit"
    )
    op.execute(
        "ALTER TABLE candidate_stages DROP COLUMN IF EXISTS expected_rate_value"
    )
    op.execute(
        "ALTER TABLE candidate_stages DROP COLUMN IF EXISTS verification_status"
    )
    op.execute("DROP TYPE IF EXISTS verificationstatus")
