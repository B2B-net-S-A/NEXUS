"""AI retrieval outbox and versioned scoring cache.

Revision ID: 0165_ai_retrieval_foundation
Revises: 0164_analytics_v1_kpi_defaults
"""

from alembic import op
import sqlalchemy as sa


revision = "0165_ai_retrieval_foundation"
down_revision = "0164_analytics_v1_kpi_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "embedding_index_queue",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(10), nullable=False, server_default="upsert"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_hash", sa.String(64), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "entity_type", "entity_id", name="uq_embedding_index_entity"
        ),
        sa.CheckConstraint(
            "entity_type IN ('candidate', 'job')", name="ck_embedding_index_entity_type"
        ),
        sa.CheckConstraint(
            "operation IN ('upsert', 'delete')", name="ck_embedding_index_operation"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'retry', 'done', 'dead')",
            name="ck_embedding_index_status",
        ),
    )
    op.create_index(
        "ix_embedding_index_queue_status", "embedding_index_queue", ["status"]
    )
    op.create_index(
        "ix_embedding_index_queue_available_at",
        "embedding_index_queue",
        ["available_at"],
    )
    op.create_index(
        "ix_embedding_index_queue_entity_type", "embedding_index_queue", ["entity_type"]
    )

    op.add_column(
        "scoring_weight_profiles",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    # Resolve legacy ambiguous scopes deterministically (user wins), then keep
    # only the newest active row in every scope before adding unique indexes.
    op.execute(
        "UPDATE scoring_weight_profiles SET client_id = NULL "
        "WHERE user_id IS NOT NULL AND client_id IS NOT NULL"
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY
                           CASE
                               WHEN user_id IS NOT NULL THEN 'user:' || user_id::text
                               WHEN client_id IS NOT NULL THEN 'client:' || client_id::text
                               ELSE 'global'
                           END
                       ORDER BY updated_at DESC, id DESC
                   ) AS rn
            FROM scoring_weight_profiles
            WHERE active
        )
        UPDATE scoring_weight_profiles p
        SET active = false
        FROM ranked r
        WHERE p.id = r.id AND r.rn > 1
        """
    )
    op.create_check_constraint(
        "ck_scoring_profile_single_scope",
        "scoring_weight_profiles",
        "NOT (user_id IS NOT NULL AND client_id IS NOT NULL)",
    )
    op.create_index(
        "uq_scoring_profile_active_user",
        "scoring_weight_profiles",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("active AND user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_scoring_profile_active_client",
        "scoring_weight_profiles",
        ["client_id"],
        unique=True,
        postgresql_where=sa.text("active AND client_id IS NOT NULL"),
    )
    op.create_index(
        "uq_scoring_profile_active_global",
        "scoring_weight_profiles",
        [sa.text("(1)")],
        unique=True,
        postgresql_where=sa.text("active AND user_id IS NULL AND client_id IS NULL"),
    )
    op.execute(
        """
        UPDATE scoring_weight_profiles
        SET weights = jsonb_build_object(
            'semantic', round(COALESCE((weights->>'semantic')::numeric, 35) * 0.9, 2),
            'skills', round(COALESCE((weights->>'skills')::numeric, 30) * 0.9, 2),
            'salary', round(COALESCE((weights->>'salary')::numeric, 12) * 0.9, 2),
            'location', round(COALESCE((weights->>'location')::numeric, 8) * 0.9, 2),
            'availability', 90 - (
                round(COALESCE((weights->>'semantic')::numeric, 35) * 0.9, 2) +
                round(COALESCE((weights->>'skills')::numeric, 30) * 0.9, 2) +
                round(COALESCE((weights->>'salary')::numeric, 12) * 0.9, 2) +
                round(COALESCE((weights->>'location')::numeric, 8) * 0.9, 2)
            ),
            'champion_fit', 10
        ), version = version + 1
        WHERE NOT (weights ? 'champion_fit')
        """
    )

    for name, type_ in (
        ("profile_version", sa.Integer()),
        ("scoring_algorithm_version", sa.String(40)),
        ("index_version", sa.String(255)),
        ("candidate_source_hash", sa.String(64)),
        ("job_source_hash", sa.String(64)),
    ):
        op.add_column(
            "candidate_job_match_scores",
            sa.Column(
                name,
                type_,
                nullable=False,
                server_default="1" if name == "profile_version" else "legacy",
            ),
        )
    op.execute("UPDATE candidate_job_match_scores SET stale = true")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION nexus_enqueue_embedding_index()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            target_id integer;
            target_operation varchar(10);
        BEGIN
            target_id := COALESCE(NEW.id, OLD.id);
            target_operation := CASE WHEN TG_OP = 'DELETE' THEN 'delete' ELSE 'upsert' END;
            INSERT INTO embedding_index_queue (
                entity_type, entity_id, operation, status, attempts,
                available_at, locked_at, last_error, created_at, updated_at
            ) VALUES (
                TG_ARGV[0], target_id, target_operation, 'pending', 0,
                now(), NULL, NULL, now(), now()
            )
            ON CONFLICT (entity_type, entity_id) DO UPDATE SET
                operation = EXCLUDED.operation,
                status = 'pending',
                attempts = 0,
                available_at = now(),
                locked_at = NULL,
                last_error = NULL,
                updated_at = now();
            RETURN COALESCE(NEW, OLD);
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_candidates_embedding_index
        AFTER INSERT OR DELETE OR UPDATE OF
            name, lastname, competence_category, competence_category_id,
            years_it_experience, skills, verified_tech, experience, tags,
            preferences, ai_summary, raw_cv_text, languages
        ON candidates FOR EACH ROW
        EXECUTE FUNCTION nexus_enqueue_embedding_index('candidate')
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_jobs_embedding_index
        AFTER INSERT OR DELETE OR UPDATE OF
            title, description, requirements, seniority, subcategory, industry,
            train_name, champion_profile, must_skills, nice_skills,
            competence_category_id, work_mode
        ON jobs FOR EACH ROW
        EXECUTE FUNCTION nexus_enqueue_embedding_index('job')
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_jobs_embedding_index ON jobs")
    op.execute("DROP TRIGGER IF EXISTS trg_candidates_embedding_index ON candidates")
    op.execute("DROP FUNCTION IF EXISTS nexus_enqueue_embedding_index()")
    for name in (
        "job_source_hash",
        "candidate_source_hash",
        "index_version",
        "scoring_algorithm_version",
        "profile_version",
    ):
        op.drop_column("candidate_job_match_scores", name)
    op.drop_index(
        "uq_scoring_profile_active_global", table_name="scoring_weight_profiles"
    )
    op.drop_index(
        "uq_scoring_profile_active_client", table_name="scoring_weight_profiles"
    )
    op.drop_index(
        "uq_scoring_profile_active_user", table_name="scoring_weight_profiles"
    )
    op.drop_constraint(
        "ck_scoring_profile_single_scope", "scoring_weight_profiles", type_="check"
    )
    op.drop_column("scoring_weight_profiles", "version")
    op.drop_table("embedding_index_queue")
