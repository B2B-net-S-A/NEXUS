"""Interview Questions Bank + Prep fallback

Revision ID: 0042_interview_questions
Revises: 0041_ai_cc_matching
Create Date: 2026-04-22 23:59:00.000000

Adds centralną bazę pytań rekrutacyjnych ("feature Prepy"):

1. `interview_questions` — tagowalna (CC, skills, seniority, type) z tenant
   isolation przez `client_id`. Pytania client-scoped NIE wyciekają do
   prep-kitów innych klientów (hard filter w `question_suggestions`).
2. `job_questions` — m2m pin pytania do joba, fractional `order_index` do
   drag-drop bez kolizji.
3. `interview_question_ratings` — audit trail thumb up/down (faza 1: bez
   wpływu na ranking, tylko zbieramy sygnał).

Seed z istniejących `jobs.champion_profile->'screening_questions'`:
- Każde pytanie → row w `interview_questions` (source=imported_from_champion,
  client_id = job.client_id jako najbezpieczniejszy default).
- Exact-hash dedup po sha256 znormalizowanego tekstu (lowercase + trim +
  collapse whitespace) w obrębie klienta (a nie semantic merge).
- Auto-pin w `job_questions` z `is_pinned=true, added_by_source=manual`.

Idempotent + reversible.
"""

import hashlib
import re

from alembic import op
import sqlalchemy as sa


revision = "0042_interview_questions"
down_revision = "0041_ai_cc_matching"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Enumy ─────────────────────────────────────────────────────────────
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE interviewquestionsource AS ENUM ('manual', 'auto_generated', 'imported_from_champion');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE interviewquestiontype AS ENUM ('technical', 'behavioral', 'motivation', 'experience');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE interviewquestionseniority AS ENUM ('junior', 'mid', 'senior', 'lead', 'architect');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE jobquestionaddedbysource AS ENUM ('manual', 'auto_from_similar', 'auto_generated');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE questionratingvalue AS ENUM ('up', 'down');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """
    )

    # ── 2. interview_questions ──────────────────────────────────────────────
    op.create_table(
        "interview_questions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("ideal_answer", sa.Text, nullable=True),
        sa.Column(
            "deal_breaker",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "competence_category_id",
            sa.Integer,
            sa.ForeignKey("competence_categories.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "skill_tags",
            sa.dialects.postgresql.JSONB,
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "seniority",
            sa.Enum(
                "junior",
                "mid",
                "senior",
                "lead",
                "architect",
                name="interviewquestionseniority",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "question_type",
            sa.Enum(
                "technical",
                "behavioral",
                "motivation",
                "experience",
                name="interviewquestiontype",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "source",
            sa.Enum(
                "manual",
                "auto_generated",
                "imported_from_champion",
                name="interviewquestionsource",
                create_type=False,
            ),
            nullable=False,
            server_default="manual",
        ),
        sa.Column(
            "client_id",
            sa.Integer,
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "canonical_question_id",
            sa.Integer,
            sa.ForeignKey("interview_questions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("normalized_text_hash", sa.String(64), nullable=False, index=True),
        sa.Column(
            "created_by",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Partial unique indexes dla tenant-isolated dedup
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_iq_client_hash
            ON interview_questions (client_id, normalized_text_hash)
            WHERE client_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_iq_global_hash
            ON interview_questions (normalized_text_hash)
            WHERE client_id IS NULL
        """
    )

    # ── 3. job_questions (m2m pin) ──────────────────────────────────────────
    op.create_table(
        "job_questions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer,
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "question_id",
            sa.Integer,
            sa.ForeignKey("interview_questions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "is_pinned",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "added_by_source",
            sa.Enum(
                "manual",
                "auto_from_similar",
                "auto_generated",
                name="jobquestionaddedbysource",
                create_type=False,
            ),
            nullable=False,
            server_default="manual",
        ),
        sa.Column(
            "added_by_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "order_index",
            sa.Float,
            nullable=False,
            server_default=sa.text("1000.0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("job_id", "question_id", name="uq_job_question"),
    )
    op.create_index(
        "ix_job_questions_job_order",
        "job_questions",
        ["job_id", "order_index"],
    )

    # ── 4. interview_question_ratings ───────────────────────────────────────
    op.create_table(
        "interview_question_ratings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "question_id",
            sa.Integer,
            sa.ForeignKey("interview_questions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Integer,
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "candidate_id",
            sa.Integer,
            sa.ForeignKey("candidates.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "rating",
            sa.Enum("up", "down", name="questionratingvalue", create_type=False),
            nullable=False,
        ),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_iqr_question_created",
        "interview_question_ratings",
        ["question_id", "created_at"],
    )

    # ── 5. Seed z champion_profile.screening_questions ──────────────────────
    # Każde pytanie → interview_questions (imported_from_champion, client_id =
    # job.client_id). Auto-pin do job_questions (manual, order_index seq*1000).
    # Idempotent: (client_id, normalized_text_hash) uniq partial index zapobiega
    # duplikatom per-klient; (job_id, question_id) uniq constraint chroni piny.
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT id, client_id, champion_profile->'screening_questions' AS qs
              FROM jobs
             WHERE champion_profile IS NOT NULL
               AND jsonb_typeof(champion_profile->'screening_questions') = 'array'
            """
        )
    ).fetchall()

    whitespace_re = re.compile(r"\s+")

    for job_id, client_id, qs in rows:
        if not isinstance(qs, list):
            continue
        for seq, q in enumerate(qs, start=1):
            if not isinstance(q, dict):
                continue
            text = (q.get("question") or "").strip()
            if not text:
                continue
            ideal = (q.get("ideal_answer") or "").strip() or None
            deal = bool((q.get("deal_breaker") or "").strip())
            norm = whitespace_re.sub(" ", text.lower()).strip()
            q_hash = hashlib.sha256(norm.encode("utf-8")).hexdigest()

            # Upsert pytania (partial unique index obsługuje dedup)
            if client_id is None:
                existing = conn.execute(
                    sa.text(
                        "SELECT id FROM interview_questions "
                        "WHERE client_id IS NULL AND normalized_text_hash = :h"
                    ),
                    {"h": q_hash},
                ).fetchone()
            else:
                existing = conn.execute(
                    sa.text(
                        "SELECT id FROM interview_questions "
                        "WHERE client_id = :c AND normalized_text_hash = :h"
                    ),
                    {"c": client_id, "h": q_hash},
                ).fetchone()

            if existing:
                question_id = existing[0]
            else:
                question_id = conn.execute(
                    sa.text(
                        """
                        INSERT INTO interview_questions
                            (text, ideal_answer, deal_breaker, source, client_id,
                             normalized_text_hash, skill_tags, created_at, updated_at)
                        VALUES
                            (:text, :ideal, :deal,
                             'imported_from_champion'::interviewquestionsource,
                             :client_id, :hash, '[]'::jsonb, NOW(), NOW())
                        RETURNING id
                        """
                    ),
                    {
                        "text": text,
                        "ideal": ideal,
                        "deal": deal,
                        "client_id": client_id,
                        "hash": q_hash,
                    },
                ).scalar()

            # Pin do joba (UNIQUE (job_id, question_id) chroni przed duplikacją
            # przy re-run migracji)
            conn.execute(
                sa.text(
                    """
                    INSERT INTO job_questions
                        (job_id, question_id, is_pinned, added_by_source,
                         order_index, created_at)
                    VALUES
                        (:job_id, :question_id, true,
                         'manual'::jobquestionaddedbysource,
                         :order_index, NOW())
                    ON CONFLICT (job_id, question_id) DO NOTHING
                    """
                ),
                {
                    "job_id": job_id,
                    "question_id": question_id,
                    "order_index": float(seq * 1000),
                },
            )


def downgrade() -> None:
    op.drop_index("ix_iqr_question_created", table_name="interview_question_ratings")
    op.drop_table("interview_question_ratings")
    op.drop_index("ix_job_questions_job_order", table_name="job_questions")
    op.drop_table("job_questions")
    op.execute("DROP INDEX IF EXISTS uq_iq_global_hash")
    op.execute("DROP INDEX IF EXISTS uq_iq_client_hash")
    op.drop_table("interview_questions")
    op.execute("DROP TYPE IF EXISTS questionratingvalue")
    op.execute("DROP TYPE IF EXISTS jobquestionaddedbysource")
    op.execute("DROP TYPE IF EXISTS interviewquestionseniority")
    op.execute("DROP TYPE IF EXISTS interviewquestiontype")
    op.execute("DROP TYPE IF EXISTS interviewquestionsource")
