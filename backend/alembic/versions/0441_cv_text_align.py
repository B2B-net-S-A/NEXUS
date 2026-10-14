"""client_cv_rules.cv_text_align — wyrównanie treści CV (decyzja J1, 14.10.2026).

Revision ID: 0441_cv_text_align
Revises: 0440_cv_ready_notification

Zespół prosił o justowanie CV. Nowe CV są domyślnie wyjustowane, reguła klienta
może przełączyć na „do lewej”. Wartość jest zamrażana w `client_rule_snapshot`
przy generacji i czytana przez oba renderery Worda (`services/cv_text_align.py`).
Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony).
"""

from alembic import op

revision = "0441_cv_text_align"
down_revision = "0440_cv_ready_notification"
branch_labels = None
depends_on = None

ADD_COLUMN = (
    "ALTER TABLE client_cv_rules ADD COLUMN IF NOT EXISTS cv_text_align "
    "VARCHAR(8) NOT NULL DEFAULT 'justify'"
)
ADD_CHECK = """DO $$ BEGIN
    ALTER TABLE client_cv_rules ADD CONSTRAINT ck_client_cv_rules_text_align
        CHECK (cv_text_align IN ('justify', 'left'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$"""


def upgrade() -> None:
    op.execute(ADD_COLUMN)
    op.execute(ADD_CHECK)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE client_cv_rules DROP CONSTRAINT IF EXISTS ck_client_cv_rules_text_align"
    )
    op.execute("ALTER TABLE client_cv_rules DROP COLUMN IF EXISTS cv_text_align")
