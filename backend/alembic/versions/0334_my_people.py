"""„Moi ludzie": ręczne decyzje rekrutera i dopasowania do nowych rekrutacji.

Revision ID: 0334_my_people
Revises: 0333_job_proposals

Lista „Moi ludzie" wylicza się z ``candidate_stages`` (pierwszy weryfikator
pary, która doszła do „CV Wysłane"). Ta migracja dokłada tylko to, czego nie da
się wyliczyć: uśpienia/przypięcia (``my_people_overrides``) i dopasowania
policzone przy publikacji rekrutacji (``my_people_job_matches``), typ
powiadomienia ``my_people_match`` oraz indeks ``(moved_by, stage)`` — bez niego
lista jednej osoby czytałaby całą tabelę etapów.

Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony).
"""

import sqlalchemy as sa
from alembic import op

revision = "0334_my_people"
down_revision = "0333_job_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'my_people_match'"
        )

    op.create_table(
        "my_people_overrides",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(32), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "user_id", "candidate_id", name="uq_my_people_overrides_user_candidate"
        ),
        sa.CheckConstraint(
            "kind IN ('snoozed', 'pinned')", name="ck_my_people_overrides_kind"
        ),
        sa.CheckConstraint(
            "kind <> 'snoozed' OR reason IS NOT NULL",
            name="ck_my_people_overrides_snooze_reason",
        ),
    )
    op.create_index(
        "ix_my_people_overrides_user_id", "my_people_overrides", ["user_id"]
    )
    op.create_index(
        "ix_my_people_overrides_candidate_id", "my_people_overrides", ["candidate_id"]
    )

    op.create_table(
        "my_people_job_matches",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "user_id",
            "job_id",
            "candidate_id",
            name="uq_my_people_job_matches_user_job_candidate",
        ),
    )
    op.create_index(
        "ix_my_people_job_matches_user_seen",
        "my_people_job_matches",
        ["user_id", "seen_at"],
    )
    op.create_index("ix_my_people_job_matches_job", "my_people_job_matches", ["job_id"])

    op.create_index(
        "ix_candidate_stages_moved_by_stage",
        "candidate_stages",
        ["moved_by", "stage"],
    )


def downgrade() -> None:
    op.drop_index("ix_candidate_stages_moved_by_stage", table_name="candidate_stages")
    op.drop_table("my_people_job_matches")
    op.drop_table("my_people_overrides")
    # Wartości enuma nie da się usunąć bez przebudowy typu — no-op.
