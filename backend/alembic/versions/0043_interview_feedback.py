"""Phase 14 — Post-interview feedback + 4 nowe typy powiadomień

Revision ID: 0043_interview_feedback
Revises: 0042_interview_questions
Create Date: 2026-04-22 23:59:30.000000

Feature "zadzwoń i zbierz feedback po interview":

1. Nowa tabela `interview_feedback` — strukturalne zbieranie feedbacku po każdym
   interview. Dwa warianty per CalendarEvent (UNIQUE (event_id, source)):
   - `candidate_side` (recruiter pyta kandydata): impression, interest, pytania
     kandydata, concerns, next step preference
   - `client_side` (recruiter/DL pyta klienta): technical/soft/overall fit,
     decision (advance/reject/on_hold), pytania klienta, summary

2. Rozszerzenie `notificationtype` enum o 4 nowe wartości:
   - post_interview_t15, post_interview_t45, post_interview_t2h_escalation
   - suggest_next_step (użyte w Wave 5 auto-actions)

3. `calendar_events.needs_attention BOOLEAN` — czerwona flaga gdy T+2h eskalacja
   bez feedbacku. Setowany przez trigger, czyszczony przy zapisaniu feedbacku.

Idempotent + reversible (z wyjątkiem enum values — Postgres limitation).
"""

from alembic import op
import sqlalchemy as sa


revision = "0043_interview_feedback"
down_revision = "0042_interview_questions"
branch_labels = None
depends_on = None


_NEW_NOTIF_TYPES = (
    "post_interview_t15",
    "post_interview_t45",
    "post_interview_t2h_escalation",
    "suggest_next_step",
)


def upgrade() -> None:
    # 1) Enum extensions — poza transakcją (PG wymóg dla ADD VALUE).
    with op.get_context().autocommit_block():
        for value in _NEW_NOTIF_TYPES:
            op.execute(
                f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'"
            )

    # 2) Dedykowane enumy dla interview_feedback.
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE feedbacksource AS ENUM ('candidate_side', 'client_side');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE interestlevel AS ENUM ('hot', 'warm', 'cold', 'dead');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE nextsteppreference AS ENUM ('ready_for_next', 'need_info', 'pass');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE interviewdecision AS ENUM ('advance', 'reject', 'on_hold');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """
    )

    # 3) Tabela interview_feedback
    op.create_table(
        "interview_feedback",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "calendar_event_id",
            sa.Integer,
            sa.ForeignKey("calendar_events.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "candidate_id",
            sa.Integer,
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "job_id",
            sa.Integer,
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "author_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "feedback_source",
            sa.Enum(
                "candidate_side",
                "client_side",
                name="feedbacksource",
                create_type=False,
            ),
            nullable=False,
        ),
        # ── candidate_side fields (nullable when source=client_side) ──
        sa.Column("overall_impression", sa.SmallInteger, nullable=True),
        sa.Column(
            "interest_level",
            sa.Enum(
                "hot",
                "warm",
                "cold",
                "dead",
                name="interestlevel",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("candidate_questions", sa.Text, nullable=True),
        sa.Column("concerns", sa.Text, nullable=True),
        sa.Column(
            "next_step_preference",
            sa.Enum(
                "ready_for_next",
                "need_info",
                "pass",
                name="nextsteppreference",
                create_type=False,
            ),
            nullable=True,
        ),
        # ── client_side fields (nullable when source=candidate_side) ──
        sa.Column("technical_fit", sa.SmallInteger, nullable=True),
        sa.Column("soft_fit", sa.SmallInteger, nullable=True),
        sa.Column("overall_fit", sa.SmallInteger, nullable=True),
        sa.Column(
            "decision",
            sa.Enum(
                "advance",
                "reject",
                "on_hold",
                name="interviewdecision",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("client_questions", sa.Text, nullable=True),
        sa.Column("feedback_summary", sa.Text, nullable=True),
        # ── timestamps ──
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
        # ── constraints ──
        sa.UniqueConstraint(
            "calendar_event_id",
            "feedback_source",
            name="uq_interview_feedback_event_source",
        ),
        sa.CheckConstraint(
            "overall_impression IS NULL OR (overall_impression BETWEEN 1 AND 5)",
            name="ck_interview_feedback_overall_impression_range",
        ),
        sa.CheckConstraint(
            "technical_fit IS NULL OR (technical_fit BETWEEN 1 AND 5)",
            name="ck_interview_feedback_technical_fit_range",
        ),
        sa.CheckConstraint(
            "soft_fit IS NULL OR (soft_fit BETWEEN 1 AND 5)",
            name="ck_interview_feedback_soft_fit_range",
        ),
        sa.CheckConstraint(
            "overall_fit IS NULL OR (overall_fit BETWEEN 1 AND 5)",
            name="ck_interview_feedback_overall_fit_range",
        ),
    )

    # 4) needs_attention na calendar_events (czerwona flaga po T+2h eskalacji)
    op.execute(
        "ALTER TABLE calendar_events "
        "ADD COLUMN IF NOT EXISTS needs_attention BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_calendar_events_needs_attention "
        "ON calendar_events (needs_attention) WHERE needs_attention = true"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_calendar_events_needs_attention")
    op.execute("ALTER TABLE calendar_events DROP COLUMN IF EXISTS needs_attention")
    op.drop_table("interview_feedback")
    op.execute("DROP TYPE IF EXISTS interviewdecision")
    op.execute("DROP TYPE IF EXISTS nextsteppreference")
    op.execute("DROP TYPE IF EXISTS interestlevel")
    op.execute("DROP TYPE IF EXISTS feedbacksource")
    # Nie usuwamy notificationtype values — PG nie wspiera DROP VALUE bez
    # recreacji typu. Akceptowalny trade-off (zgodnie z 0029_notifications_triggers).
