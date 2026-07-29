"""CV content mode (basic/polished/tailored) + per-client ceiling.

Records HOW MUCH presentation work produced each generated CV, and lets a
client cap how far the generator may go for them. The cap is what turns a
commitment made to a client ("we stopped positioning CVs against your job
ad") into something enforced server-side, instead of a UI checkbox any
recruiter can undo.

Historical rows are backfilled to 'tailored' — that is factually what they
were: full positioning against the client's Champion Profile.

Revision ID: 0202_cv_content_mode
Revises: 0201_candidate_contact_coordination
"""

from alembic import op


revision = "0202_cv_content_mode"
down_revision = "0201_candidate_contact_coordination"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Plain VARCHAR + CHECK, matching the codebase convention of avoiding
    # PostgreSQL enum lifecycle churn.
    op.execute(
        """
        ALTER TABLE cv_generated_documents
            ADD COLUMN IF NOT EXISTS content_mode VARCHAR(16)
            NOT NULL DEFAULT 'tailored'
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_cv_generated_documents_content_mode'
            ) THEN
                ALTER TABLE cv_generated_documents
                    ADD CONSTRAINT ck_cv_generated_documents_content_mode
                    CHECK (content_mode IN ('basic', 'polished', 'tailored'));
            END IF;
        END $$;
        """
    )

    # NULL = no ceiling. Deliberately nullable rather than defaulted: only
    # clients we have made an explicit promise to get a cap.
    op.execute(
        """
        ALTER TABLE clients
            ADD COLUMN IF NOT EXISTS cv_content_mode_cap VARCHAR(16)
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_clients_cv_content_mode_cap'
            ) THEN
                ALTER TABLE clients
                    ADD CONSTRAINT ck_clients_cv_content_mode_cap
                    CHECK (
                        cv_content_mode_cap IS NULL
                        OR cv_content_mode_cap IN ('basic', 'polished', 'tailored')
                    );
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE clients DROP CONSTRAINT IF EXISTS ck_clients_cv_content_mode_cap"
    )
    op.execute("ALTER TABLE clients DROP COLUMN IF EXISTS cv_content_mode_cap")
    op.execute(
        "ALTER TABLE cv_generated_documents "
        "DROP CONSTRAINT IF EXISTS ck_cv_generated_documents_content_mode"
    )
    op.execute(
        "ALTER TABLE cv_generated_documents DROP COLUMN IF EXISTS content_mode"
    )
