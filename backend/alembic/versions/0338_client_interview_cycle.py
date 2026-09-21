"""Cykl rozmowy u klienta: sloty od DL, typ wydarzenia, debrief.

Revision ID: 0338_client_interview_cycle
Revises: 0337_user_dashboards

Kalendarz przestaje być kopią Outlooka i prowadzi jeden cykl per para
(kandydat, rekrutacja): DL wpisuje terminy od klienta → rekruter ustala termin
z kandydatem → DL potwierdza klientowi → prep, prep 2 → rozmowa u klienta →
telefon do kandydata ≤30 min po → debrief.

- ``eventtype`` + ``client_interview`` — rozmowa kandydata U KLIENTA (rekruter
  jej nie prowadzi, tylko musi znać termin i zadzwonić po niej).
- ``client_interview_slot_requests`` — terminy od klienta i wybór kandydata.
- ``interview_feedback`` + ``offer_acceptance`` / ``acceptance_condition``
  — debrief: „czy przyjmie ofertę”.
- ``interviewquestionsource`` + ``client_debrief`` — pytania klienta z
  debriefów, zasilają prep następnych kandydatów.
- cztery typy powiadomień dla przekazań DL ↔ rekruter (w tym debrief).

Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony). Postgres nie usuwa
wartości enuma, więc downgrade zdejmuje tylko tabelę i kolumny.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0338_client_interview_cycle"
down_revision = "0337_user_dashboards"
branch_labels = None
depends_on = None

_ENUM_VALUES = (
    ("eventtype", "client_interview"),
    ("interviewquestionsource", "client_debrief"),
    ("notificationtype", "interview_slots_requested"),
    ("notificationtype", "interview_slot_chosen"),
    ("notificationtype", "interview_slot_confirmed"),
    ("notificationtype", "interview_debrief_saved"),
)


def upgrade() -> None:
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        for enum_name, value in _ENUM_VALUES:
            op.execute(f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS '{value}'")

    op.create_table(
        "client_interview_slot_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "recruiter_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("slots", JSONB(), nullable=False),
        sa.Column(
            "duration_minutes", sa.Integer(), nullable=False, server_default="60"
        ),
        sa.Column("respond_by", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(1000), nullable=True),
        sa.Column(
            "status",
            sa.String(24),
            nullable=False,
            server_default="awaiting_recruiter",
        ),
        sa.Column("chosen_index", sa.Integer(), nullable=True),
        sa.Column("chosen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "chosen_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "confirmed_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("calendar_events.id", ondelete="SET NULL"),
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
        sa.CheckConstraint(
            "status IN ('awaiting_recruiter', 'awaiting_dl', 'confirmed', 'cancelled')",
            name="ck_interview_slot_requests_status",
        ),
        sa.CheckConstraint(
            "duration_minutes BETWEEN 15 AND 480",
            name="ck_interview_slot_requests_duration",
        ),
    )
    op.create_index(
        "ix_interview_slot_requests_candidate_job",
        "client_interview_slot_requests",
        ["candidate_id", "job_id"],
    )
    op.create_index(
        "ix_interview_slot_requests_status",
        "client_interview_slot_requests",
        ["status"],
    )
    op.create_index(
        "ix_interview_slot_requests_recruiter",
        "client_interview_slot_requests",
        ["recruiter_id"],
    )
    op.create_index(
        "uq_interview_slot_requests_open_pair",
        "client_interview_slot_requests",
        ["candidate_id", "job_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('awaiting_recruiter', 'awaiting_dl')"),
    )

    op.add_column(
        "interview_feedback",
        sa.Column("offer_acceptance", sa.String(16), nullable=True),
    )
    op.add_column(
        "interview_feedback",
        sa.Column("acceptance_condition", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_interview_feedback_offer_acceptance",
        "interview_feedback",
        "offer_acceptance IS NULL OR offer_acceptance IN ('yes', 'likely', 'no', 'unknown')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_interview_feedback_offer_acceptance", "interview_feedback", type_="check"
    )
    op.drop_column("interview_feedback", "acceptance_condition")
    op.drop_column("interview_feedback", "offer_acceptance")
    op.drop_index(
        "uq_interview_slot_requests_open_pair",
        table_name="client_interview_slot_requests",
    )
    op.drop_index(
        "ix_interview_slot_requests_recruiter",
        table_name="client_interview_slot_requests",
    )
    op.drop_index(
        "ix_interview_slot_requests_status",
        table_name="client_interview_slot_requests",
    )
    op.drop_index(
        "ix_interview_slot_requests_candidate_job",
        table_name="client_interview_slot_requests",
    )
    op.drop_table("client_interview_slot_requests")
