"""Strona kariery: linki bez rekrutacji, slug, opis publiczny, zgody.

Revision ID: 0339_career_links
Revises: 0338_client_interview_cycle

- ``candidate_invite_links``: ``kind`` (``job`` | ``recruiter``), czytelny
  ``slug``, licznik wejść ``visit_count``; ``job_id`` i ``expires_at``
  NULL-owalne (stały link rekrutera nie ma rekrutacji ani terminu, link
  rekrutacji domyślnie żyje do jej zamknięcia). Jeden nieodwołany link
  ``recruiter`` na osobę.
- ``job_public_profiles``: publiczny opis rekrutacji (1:1), zatwierdzany.
- ``candidate_consents``: zgoda z formularza, CASCADE z kandydatem (RODO).
- klucz AI ``job_public_description`` (enum + seed ``ai_features``).

Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony) — pilnuje
``tests/test_career_migration_mirror.py``.
"""

from alembic import op

revision = "0339_career_links"
down_revision = "0338_client_interview_cycle"
branch_labels = None
depends_on = None


INVITE_LINK_COLUMNS = (
    "ALTER TABLE candidate_invite_links "
    "ADD COLUMN IF NOT EXISTS kind VARCHAR(16) NOT NULL DEFAULT 'job'",
    "ALTER TABLE candidate_invite_links ADD COLUMN IF NOT EXISTS slug VARCHAR(64) NULL",
    "ALTER TABLE candidate_invite_links "
    "ADD COLUMN IF NOT EXISTS visit_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE candidate_invite_links ALTER COLUMN job_id DROP NOT NULL",
    "ALTER TABLE candidate_invite_links ALTER COLUMN expires_at DROP NOT NULL",
)

INVITE_LINK_CONSTRAINTS = (
    """DO $$ BEGIN
        ALTER TABLE candidate_invite_links
            DROP CONSTRAINT IF EXISTS ck_candidate_invite_links_kind;
        ALTER TABLE candidate_invite_links
            ADD CONSTRAINT ck_candidate_invite_links_kind
            CHECK (kind IN ('job', 'recruiter'));
        ALTER TABLE candidate_invite_links
            DROP CONSTRAINT IF EXISTS ck_candidate_invite_links_kind_shape;
        ALTER TABLE candidate_invite_links
            ADD CONSTRAINT ck_candidate_invite_links_kind_shape
            CHECK ((kind = 'job' AND job_id IS NOT NULL) OR
                   (kind = 'recruiter' AND job_id IS NULL AND slug IS NOT NULL));
    END $$""",
)

INVITE_LINK_INDEXES = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_candidate_invite_links_slug "
    "ON candidate_invite_links (slug) WHERE slug IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_candidate_invite_links_one_recruiter_link "
    "ON candidate_invite_links (created_by) "
    "WHERE kind = 'recruiter' AND revoked = false",
)

CREATE_JOB_PUBLIC_PROFILES = """CREATE TABLE IF NOT EXISTS job_public_profiles (
        job_id INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
        subtitle TEXT NULL,
        about TEXT NULL,
        sections JSONB NOT NULL
            DEFAULT '{"must": true, "nice": true, "params": true, "process": true}'::jsonb,
        show_on_recruiter_page BOOLEAN NOT NULL DEFAULT true,
        approved_at TIMESTAMPTZ NULL,
        approved_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        approved_hash VARCHAR(64) NULL,
        updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )"""

CREATE_CANDIDATE_CONSENTS = """CREATE TABLE IF NOT EXISTS candidate_consents (
        id BIGSERIAL PRIMARY KEY,
        candidate_id INTEGER NULL REFERENCES candidates(id) ON DELETE CASCADE,
        application_submission_id INTEGER NULL
            REFERENCES application_submissions(id) ON DELETE CASCADE,
        kind VARCHAR(40) NOT NULL,
        text_version VARCHAR(20) NOT NULL,
        text_sha256 VARCHAR(64) NOT NULL,
        given_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        invite_link_key VARCHAR(64) NULL,
        CONSTRAINT ck_candidate_consents_one_subject
            CHECK ((candidate_id IS NOT NULL) <> (application_submission_id IS NOT NULL)),
        CONSTRAINT ck_candidate_consents_kind
            CHECK (kind IN ('recruitment_current_future'))
    )"""

CONSENT_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_candidate_consents_candidate_id "
    "ON candidate_consents (candidate_id)",
    "CREATE INDEX IF NOT EXISTS ix_candidate_consents_application_submission_id "
    "ON candidate_consents (application_submission_id)",
)

DDL_STATEMENTS = (
    *INVITE_LINK_COLUMNS,
    *INVITE_LINK_CONSTRAINTS,
    *INVITE_LINK_INDEXES,
    CREATE_JOB_PUBLIC_PROFILES,
    CREATE_CANDIDATE_CONSENTS,
    *CONSENT_INDEXES,
)


def upgrade() -> None:
    # ADD VALUE musi biec w autocommicie (nowej etykiety nie da się użyć w tej
    # samej transakcji, w której ją dodano).
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'job_public_description'"
        )

    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        "SELECT 'job_public_description', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS "
        "(SELECT 1 FROM ai_features WHERE feature = 'job_public_description')"
    )

    for statement in DDL_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS candidate_consents")
    op.execute("DROP TABLE IF EXISTS job_public_profiles")
    op.execute("DROP INDEX IF EXISTS ux_candidate_invite_links_one_recruiter_link")
    op.execute("DROP INDEX IF EXISTS ux_candidate_invite_links_slug")
    op.execute(
        "ALTER TABLE candidate_invite_links "
        "DROP CONSTRAINT IF EXISTS ck_candidate_invite_links_kind_shape"
    )
    op.execute(
        "ALTER TABLE candidate_invite_links "
        "DROP CONSTRAINT IF EXISTS ck_candidate_invite_links_kind"
    )
    # Linki stałe rekrutera nie mają rekrutacji — bez usunięcia ich NOT NULL
    # nie wróci. Linki rekrutacji bez terminu dostają termin „teraz + 30 dni".
    op.execute("DELETE FROM candidate_invite_links WHERE job_id IS NULL")
    op.execute(
        "UPDATE candidate_invite_links SET expires_at = now() + interval '30 days' "
        "WHERE expires_at IS NULL"
    )
    op.execute("ALTER TABLE candidate_invite_links ALTER COLUMN job_id SET NOT NULL")
    op.execute(
        "ALTER TABLE candidate_invite_links ALTER COLUMN expires_at SET NOT NULL"
    )
    op.execute("ALTER TABLE candidate_invite_links DROP COLUMN IF EXISTS visit_count")
    op.execute("ALTER TABLE candidate_invite_links DROP COLUMN IF EXISTS slug")
    op.execute("ALTER TABLE candidate_invite_links DROP COLUMN IF EXISTS kind")
    op.execute("DELETE FROM ai_features WHERE feature = 'job_public_description'")
