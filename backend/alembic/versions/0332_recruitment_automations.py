"""Automaty rekrutacji v3: digest propozycji + pochodzenie wygenerowanego CV.

Revision ID: 0332_recruitment_automations
Revises: 0331_job_proposals

* ``notificationtype.auto_match_proposals`` — JEDEN dzienny digest na
  (rekrutacja, odbiorca): „N nowych propozycji z nowych CV” (auto-match
  w trybie ``propose`` — nic nie wchodzi do pipeline'u).
* ``notificationtype.automation_failing`` — ten sam automat padł 3 razy z rzędu;
  jedno powiadomienie na serię, tylko dla adminów.
* ``cv_generated_documents.origin`` (``manual`` | ``auto``), ``stage_id``,
  ``source_cv_revision`` — auto-CV po ruchu na „Zweryfikowany”. Częściowy
  UNIQUE ``(stage_id, source_cv_revision) WHERE origin = 'auto'`` jest kluczem
  idempotencji: ten sam etap z tą samą wersją CV nie wygeneruje (i nie naliczy)
  drugiego dokumentu, także przy dwóch równoległych ruchach.

``stage_id`` celowo BEZ klucza obcego: dokument ma przeżyć usunięcie etapu
(tak jak ``job_id``/``candidate_id`` mają SET NULL), a klucz idempotencji ma
zostać stabilny. Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony).
"""

import sqlalchemy as sa
from alembic import op

revision = "0332_recruitment_automations"
down_revision = "0331_job_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'auto_match_proposals'"
        )
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'automation_failing'"
        )
    op.add_column(
        "cv_generated_documents",
        sa.Column("origin", sa.String(16), nullable=False, server_default="manual"),
    )
    op.add_column(
        "cv_generated_documents", sa.Column("stage_id", sa.Integer(), nullable=True)
    )
    op.add_column(
        "cv_generated_documents",
        sa.Column("source_cv_revision", sa.String(64), nullable=True),
    )
    op.create_check_constraint(
        "ck_cv_generated_documents_origin",
        "cv_generated_documents",
        "origin IN ('manual', 'auto')",
    )
    op.create_index(
        "ux_cv_generated_documents_auto_stage_revision",
        "cv_generated_documents",
        ["stage_id", "source_cv_revision"],
        unique=True,
        postgresql_where=sa.text("origin = 'auto'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ux_cv_generated_documents_auto_stage_revision",
        table_name="cv_generated_documents",
    )
    op.drop_constraint(
        "ck_cv_generated_documents_origin", "cv_generated_documents", type_="check"
    )
    op.drop_column("cv_generated_documents", "source_cv_revision")
    op.drop_column("cv_generated_documents", "stage_id")
    op.drop_column("cv_generated_documents", "origin")
    # Wartości enuma nie da się usunąć bez przebudowy typu — no-op.
