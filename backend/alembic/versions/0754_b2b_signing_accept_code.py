"""Paczka do podpisu: wymagany podpis per dokument i akceptacja kodem z maila.

Revision ID: 0754_b2b_signing_accept_code
Revises: 0753_cv_layout

Decyzja Artura 22.11.2026: kwalifikowany podpis jest wymagany tylko przy
umowie z przeniesieniem praw autorskich. NDA, oświadczenia i inne dokumenty
kontraktor może podpisać tym samym podpisem albo zaakceptować kodem z maila.
SQL w ``app/services/b2b_esign/documents_schema.py`` (lustro w ``entrypoint.sh``).
Same dodania kolumn z wartością domyślną albo NULL: stary kod działa na nowym
schemacie.
"""

from alembic import op

from app.services.b2b_esign.documents_schema import ACCEPT_CODE_DDL

revision = "0754_b2b_signing_accept_code"
down_revision = "0753_cv_layout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in ACCEPT_CODE_DDL:
        op.execute(statement)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE b2b_signing_requests DROP COLUMN IF EXISTS accept_code_sent_at"
    )
    op.execute(
        "ALTER TABLE b2b_signing_requests DROP COLUMN IF EXISTS accept_code_expires_at"
    )
    op.execute(
        "ALTER TABLE b2b_signing_requests DROP COLUMN IF EXISTS accept_code_hash"
    )
    op.execute("ALTER TABLE b2b_signing_documents DROP COLUMN IF EXISTS signed_via")
    op.execute("ALTER TABLE b2b_signing_documents DROP COLUMN IF EXISTS requirement")
