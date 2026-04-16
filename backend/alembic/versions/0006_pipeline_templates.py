"""Pipeline templates: PipelineTemplate, PipelineStageDef, RejectionReason + seed

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-16 12:00:00.000000

Introduces the elastic pipeline model. Seeds a single "Default B2B" template
that mirrors the 12 legacy PipelineStage enum values, and backfills every
existing job + candidate_stages row to point at it.

Idempotent: safe to re-run against a DB already advanced by 0001's
Base.metadata.create_all (uses IF NOT EXISTS for DDL and ON CONFLICT for seeds).
"""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


DEFAULT_TEMPLATE_NAME = "Default B2B"

STAGES_SEED = [
    # (name, order, category, is_terminal, terminal_type, legacy_enum_value)
    ("Nowi / Analiza CV", 0, "internal", False, None, "new"),
    ("Preparation Call", 1, "internal", False, None, "prep_call"),
    ("Screening", 2, "internal", False, None, "screening"),
    ("Interview Wewnętrzny", 3, "internal", False, None, "interview"),
    ("CV Wysłane", 4, "internal", False, None, "cv_sent"),
    ("Interview Klient", 5, "external", False, None, "client_interview"),
    ("Akceptacja", 6, "external", False, None, "acceptance"),
    ("Negocjacje", 7, "external", False, None, "negotiation"),
    ("Onboarding", 8, "external", False, None, "onboarding"),
    ("Zatrudniony", 9, "terminal", True, "hired", "hired"),
    ("Odrzucony", 10, "terminal", True, "rejected", "rejected"),
    ("Wycofany", 11, "terminal", True, "withdrawn", "withdrawn"),
]

REJECTION_REASONS_SEED = [
    ("Brak doświadczenia", "rejected"),
    ("Za wysokie oczekiwania finansowe", "rejected"),
    ("Nie spełnia wymagań technicznych", "rejected"),
    ("Nie pasuje kulturowo", "rejected"),
    ("Zatrudniony gdzie indziej", "rejected"),
    ("Inne (rejected)", "rejected"),
    ("Kandydat się wycofał", "withdrawn"),
    ("Brak odpowiedzi", "withdrawn"),
    ("Kandydat nieosiągalny", "withdrawn"),
    ("Inne (withdrawn)", "withdrawn"),
]


def upgrade() -> None:
    # ── enums (idempotent) ─────────────────────────────────────────────────────
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'stagecategoryenum') THEN
                    CREATE TYPE stagecategoryenum AS ENUM ('internal', 'external', 'terminal');
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'terminaltype') THEN
                    CREATE TYPE terminaltype AS ENUM ('hired', 'rejected', 'withdrawn');
                END IF;
            END $$;
            """
        )
    )

    # ── pipeline_templates ────────────────────────────────────────────────────
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS pipeline_templates (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL UNIQUE,
                description TEXT,
                is_default BOOLEAN NOT NULL DEFAULT false,
                archived BOOLEAN NOT NULL DEFAULT false,
                created_by INTEGER REFERENCES users(id),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
    )

    # ── pipeline_stage_defs ────────────────────────────────────────────────────
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS pipeline_stage_defs (
                id SERIAL PRIMARY KEY,
                template_id INTEGER NOT NULL REFERENCES pipeline_templates(id) ON DELETE CASCADE,
                name VARCHAR(100) NOT NULL,
                "order" INTEGER NOT NULL,
                category stagecategoryenum NOT NULL,
                is_terminal BOOLEAN NOT NULL DEFAULT false,
                terminal_type terminaltype,
                tracker_enabled BOOLEAN NOT NULL DEFAULT false,
                tracker_public_name VARCHAR(100),
                sla_max_days INTEGER,
                scorecard_schema JSONB DEFAULT '{}'::jsonb,
                legacy_enum_value VARCHAR(50),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_stage_order_in_template UNIQUE (template_id, "order"),
                CONSTRAINT uq_stage_name_in_template UNIQUE (template_id, name)
            );
            """
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_stage_defs_template ON pipeline_stage_defs (template_id)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_stage_defs_legacy_enum ON pipeline_stage_defs (legacy_enum_value)"
        )
    )

    # ── rejection_reasons ─────────────────────────────────────────────────────
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS rejection_reasons (
                id SERIAL PRIMARY KEY,
                template_id INTEGER NOT NULL REFERENCES pipeline_templates(id) ON DELETE CASCADE,
                stage_def_id INTEGER REFERENCES pipeline_stage_defs(id),
                name VARCHAR(100) NOT NULL,
                "order" INTEGER NOT NULL DEFAULT 0,
                category terminaltype NOT NULL,
                active BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_rejection_reason UNIQUE (template_id, name, category)
            );
            """
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_reject_reason_template ON rejection_reasons (template_id)"
        )
    )

    # ── FKs on existing tables (idempotent) ───────────────────────────────────
    op.execute(
        sa.text(
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS pipeline_template_id INTEGER"
        )
    )
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'fk_jobs_pipeline_template_id'
                ) THEN
                    ALTER TABLE jobs
                    ADD CONSTRAINT fk_jobs_pipeline_template_id
                    FOREIGN KEY (pipeline_template_id) REFERENCES pipeline_templates(id);
                END IF;
            END $$;
            """
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_jobs_pipeline_template_id ON jobs (pipeline_template_id)"
        )
    )

    op.execute(
        sa.text(
            "ALTER TABLE candidate_stages ADD COLUMN IF NOT EXISTS stage_def_id INTEGER"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE candidate_stages ADD COLUMN IF NOT EXISTS rejection_reason_id INTEGER"
        )
    )
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'fk_cs_stage_def_id'
                ) THEN
                    ALTER TABLE candidate_stages
                    ADD CONSTRAINT fk_cs_stage_def_id
                    FOREIGN KEY (stage_def_id) REFERENCES pipeline_stage_defs(id);
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'fk_cs_rejection_reason_id'
                ) THEN
                    ALTER TABLE candidate_stages
                    ADD CONSTRAINT fk_cs_rejection_reason_id
                    FOREIGN KEY (rejection_reason_id) REFERENCES rejection_reasons(id);
                END IF;
            END $$;
            """
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_cs_stage_def_id ON candidate_stages (stage_def_id)"
        )
    )

    # ── Seed Default B2B template ─────────────────────────────────────────────
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO pipeline_templates (name, description, is_default, created_at, updated_at)
            VALUES (:name, :desc, true, NOW(), NOW())
            ON CONFLICT (name) DO NOTHING
            """
        ),
        {
            "name": DEFAULT_TEMPLATE_NAME,
            "desc": "Domyślny proces rekrutacyjny B2B.net (seedowany z legacy enum PipelineStage).",
        },
    )
    template_id = conn.execute(
        sa.text("SELECT id FROM pipeline_templates WHERE name = :name"),
        {"name": DEFAULT_TEMPLATE_NAME},
    ).scalar()

    # Seed stages
    for name, order, category, is_term, term_type, legacy in STAGES_SEED:
        conn.execute(
            sa.text(
                """
                INSERT INTO pipeline_stage_defs
                  (template_id, name, "order", category, is_terminal, terminal_type,
                   legacy_enum_value, tracker_enabled, scorecard_schema, created_at, updated_at)
                VALUES (:tid, :name, :ord, :cat, :is_term, :term_type,
                        :legacy, false, '{}'::jsonb, NOW(), NOW())
                ON CONFLICT (template_id, name) DO NOTHING
                """
            ),
            {
                "tid": template_id,
                "name": name,
                "ord": order,
                "cat": category,
                "is_term": is_term,
                "term_type": term_type,
                "legacy": legacy,
            },
        )

    # Seed rejection reasons
    for i, (name, category) in enumerate(REJECTION_REASONS_SEED):
        conn.execute(
            sa.text(
                """
                INSERT INTO rejection_reasons
                  (template_id, name, "order", category, active, created_at, updated_at)
                VALUES (:tid, :name, :ord, :cat, true, NOW(), NOW())
                ON CONFLICT (template_id, name, category) DO NOTHING
                """
            ),
            {"tid": template_id, "name": name, "ord": i, "cat": category},
        )

    # ── Backfill existing jobs with default template ──────────────────────────
    conn.execute(
        sa.text(
            "UPDATE jobs SET pipeline_template_id = :tid WHERE pipeline_template_id IS NULL"
        ),
        {"tid": template_id},
    )

    # ── Backfill candidate_stages.stage_def_id via legacy enum mapping ────────
    conn.execute(
        sa.text(
            """
            UPDATE candidate_stages cs
            SET stage_def_id = sd.id
            FROM pipeline_stage_defs sd
            WHERE sd.template_id = :tid
              AND sd.legacy_enum_value = cs.stage::text
              AND cs.stage_def_id IS NULL
            """
        ),
        {"tid": template_id},
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_cs_stage_def_id"))
    op.execute(
        sa.text(
            "ALTER TABLE candidate_stages DROP CONSTRAINT IF EXISTS fk_cs_rejection_reason_id"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE candidate_stages DROP CONSTRAINT IF EXISTS fk_cs_stage_def_id"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE candidate_stages DROP COLUMN IF EXISTS rejection_reason_id"
        )
    )
    op.execute(
        sa.text("ALTER TABLE candidate_stages DROP COLUMN IF EXISTS stage_def_id")
    )

    op.execute(sa.text("DROP INDEX IF EXISTS ix_jobs_pipeline_template_id"))
    op.execute(
        sa.text(
            "ALTER TABLE jobs DROP CONSTRAINT IF EXISTS fk_jobs_pipeline_template_id"
        )
    )
    op.execute(sa.text("ALTER TABLE jobs DROP COLUMN IF EXISTS pipeline_template_id"))

    op.execute(sa.text("DROP TABLE IF EXISTS rejection_reasons"))
    op.execute(sa.text("DROP TABLE IF EXISTS pipeline_stage_defs"))
    op.execute(sa.text("DROP TABLE IF EXISTS pipeline_templates"))
    op.execute(sa.text("DROP TYPE IF EXISTS terminaltype"))
    op.execute(sa.text("DROP TYPE IF EXISTS stagecategoryenum"))
