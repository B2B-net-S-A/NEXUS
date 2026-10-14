"""Migawki szkicu CV etapu przed „Napisz od nowa” (Edytor CV 3, PR 5).

Revision ID: 0444_cv_stage_draft_snapshots
Revises: 0443_integrations_v1

Nowa generacja nadpisywała niezatwierdzony szkic CV etapu bez śladu.
``cv_stage_draft_snapshots`` trzyma szkic sprzed podmiany: „Wróć do
poprzedniej” wraca do niego, a następne „Napisz od nowa” porównuje szkic
z generacją, z której powstał, i zostawia ręcznie poprawione części.

Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony).
"""

from alembic import op

revision = "0444_cv_stage_draft_snapshots"
down_revision = "0443_integrations_v1"
branch_labels = None
depends_on = None

UPGRADE = [
    """CREATE TABLE IF NOT EXISTS cv_stage_draft_snapshots (
    id SERIAL PRIMARY KEY,
    candidate_stage_cv_id INTEGER NOT NULL
        REFERENCES candidate_stage_cvs(id) ON DELETE CASCADE,
    content_html TEXT NOT NULL,
    generated_document_id INTEGER NULL
        REFERENCES cv_generated_documents(id) ON DELETE SET NULL,
    branded_from_generator BOOLEAN NOT NULL DEFAULT false,
    render_metadata JSON NULL,
    branded_template VARCHAR(20) NULL,
    branded_language VARCHAR(10) NULL,
    edit_revision INTEGER NOT NULL,
    reason VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    restored_at TIMESTAMPTZ NULL,
    restored_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT ck_cv_stage_draft_snapshots_reason
        CHECK (reason IN ('replaced', 'restore'))
)""",
    "CREATE INDEX IF NOT EXISTS ix_cv_stage_draft_snapshots_cv "
    "ON cv_stage_draft_snapshots (candidate_stage_cv_id, id DESC)",
]

# Migawka to jedyna kopia szkicu sprzed podmiany — downgrade jej nie skasuje.
REFUSE_WITH_ROWS = """DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM cv_stage_draft_snapshots) THEN
        RAISE EXCEPTION 'Downgrade 0444 odmawia: cv_stage_draft_snapshots ma migawki szkiców CV, których nie ma nigdzie indziej.';
    END IF;
END $$"""


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    op.execute(REFUSE_WITH_ROWS)
    op.execute("DROP TABLE IF EXISTS cv_stage_draft_snapshots")
