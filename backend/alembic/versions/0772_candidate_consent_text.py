"""Dosłowna treść zgody przy wierszu ``candidate_consents`` (strona WWW).

Revision ID: 0772_candidate_consent_text
Revises: 0771_cv_preview_reads

Zgody z formularzy strony B2B Network (``POST /api/public/website-applications``)
mają treść zapisaną na stronie, nie w ``services/career_consent.py``, więc
``text_version`` nie wskazuje na nic w NEXUSIE. Dowód zgody (RODO art. 7 ust. 1)
to wtedy treść w samym wierszu, obok ``given_at`` i ``text_sha256``.
Stare wiersze zostają z ``NULL`` (treść wskazuje ich wersja).

Samo dodanie kolumny NULL — stary kod jej nie zna. Lustro w ``entrypoint.sh``
(pilnuje ``tests/test_public_website_applications.py``).
"""

from alembic import op

revision = "0772_candidate_consent_text"
down_revision = "0771_cv_preview_reads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE candidate_consents ADD COLUMN IF NOT EXISTS consent_text TEXT NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE candidate_consents DROP COLUMN IF EXISTS consent_text")
