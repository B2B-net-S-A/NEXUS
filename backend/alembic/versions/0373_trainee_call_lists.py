"""Praktykant: rola, codzienna lista telefonów i fakty z rozmowy w profilu.

Revision ID: 0373_trainee_call_lists
Revises: 0372_candidate_followups

Decyzje Artura 24.09.2026: nowi sourcerzy/rekruterzy przez pierwsze 40 dni
roboczych dzwonią tylko do kandydatów z codziennej listy i zapisują fakty,
bez których rekruter dzwoni na próżno (B2B, minimalna stawka B2B netto i zgoda
na telefon poniżej niej, dni w biurze i zgoda na więcej, full-time/part-time).
Minimum trafia do ``candidates.expected_rate_hourly`` (jedna stawka profilu,
którą czytają bramki budżetu), reszta do nowych kolumn ``candidates``.

Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony) — pilnuje
``test_trainee_migration_mirror.py``.
"""

from alembic import op

revision = "0373_trainee_call_lists"
down_revision = "0372_candidate_followups"
branch_labels = None
depends_on = None

ROLE_VALUES = (
    "'admin', 'head_of_recruitment', 'delivery_lead', "
    "'talent_community_manager', 'finance', 'tac', 'recruiter', 'sourcer', "
    "'user', 'trainee'"
)
EXCLUSIVE_ROLES_CHECK = """
    CASE
        WHEN role::text IN ('finance', 'user', 'trainee')
            THEN roles = jsonb_build_array(role::text)
        ELSE NOT (roles ?| ARRAY['finance', 'user', 'trainee']::text[])
    END
"""
PROPOSAL_SOURCES = (
    "'full_base', 'new_cv', 'similar_projects', 'recommendation', "
    "'marketplace', 'reassign', 'trainee'"
)

CANDIDATE_COLUMNS = (
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS b2b_willingness VARCHAR(20)",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS accepts_below_min_rate BOOLEAN",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS accepts_more_office_days BOOLEAN",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS work_time_preference VARCHAR(20)",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS call_facts_verified_at TIMESTAMPTZ",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS call_facts_verified_by_user_id "
    "INTEGER REFERENCES users(id) ON DELETE SET NULL",
)
CANDIDATE_CHECKS = (
    (
        "ck_candidates_b2b_willingness",
        "b2b_willingness IS NULL OR b2b_willingness IN "
        "('b2b', 'would_switch', 'employment_only')",
    ),
    (
        "ck_candidates_work_time_preference",
        "work_time_preference IS NULL OR work_time_preference IN "
        "('full_time_only', 'also_part_time', 'part_time_only')",
    ),
)

CREATE_PROGRAMS = """CREATE TABLE IF NOT EXISTS trainee_programs (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    start_date DATE NOT NULL,
    workdays INTEGER NOT NULL DEFAULT 40,
    extended_days INTEGER NOT NULL DEFAULT 0,
    daily_list_size INTEGER NOT NULL DEFAULT 70,
    status VARCHAR(12) NOT NULL DEFAULT 'active',
    decision_notified_at TIMESTAMPTZ NULL,
    decided_at TIMESTAMPTZ NULL,
    decided_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    decision VARCHAR(12) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_trainee_programs_status
        CHECK (status IN ('active', 'completed', 'ended')),
    CONSTRAINT ck_trainee_programs_decision
        CHECK (decision IS NULL OR decision IN ('promoted', 'extended', 'ended')),
    CONSTRAINT ck_trainee_programs_numbers
        CHECK (workdays BETWEEN 1 AND 250 AND extended_days BETWEEN 0 AND 250
               AND daily_list_size BETWEEN 1 AND 300)
)"""
CREATE_LISTS = """CREATE TABLE IF NOT EXISTS trainee_call_lists (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    list_date DATE NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    size INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT uq_trainee_call_lists_user_date UNIQUE (user_id, list_date)
)"""
CREATE_ITEMS = """CREATE TABLE IF NOT EXISTS trainee_call_items (
    id BIGSERIAL PRIMARY KEY,
    list_id BIGINT NOT NULL REFERENCES trainee_call_lists(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    list_date DATE NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    reasons JSONB NOT NULL DEFAULT '{}',
    attempts SMALLINT NOT NULL DEFAULT 0,
    last_attempt_at TIMESTAMPTZ NULL,
    retry_after TIMESTAMPTZ NULL,
    outcome VARCHAR(12) NULL,
    later_date DATE NULL,
    closed_at TIMESTAMPTZ NULL,
    phone_snapshot VARCHAR(30) NULL,
    call_id INTEGER NULL REFERENCES calls(id) ON DELETE SET NULL,
    note_id INTEGER NULL REFERENCES notes(id) ON DELETE SET NULL,
    quality_verdict VARCHAR(8) NULL,
    quality_note TEXT NULL,
    quality_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    quality_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_trainee_call_items_list_candidate UNIQUE (list_id, candidate_id),
    CONSTRAINT ck_trainee_call_items_outcome CHECK (
        outcome IS NULL OR outcome IN ('call', 'noanswer', 'later', 'wrong', 'declined')),
    CONSTRAINT ck_trainee_call_items_closed CHECK ((outcome IS NULL) = (closed_at IS NULL)),
    CONSTRAINT ck_trainee_call_items_later CHECK (
        (outcome = 'later') = (later_date IS NOT NULL)),
    CONSTRAINT ck_trainee_call_items_quality CHECK (
        quality_verdict IS NULL OR quality_verdict IN ('ok', 'issue'))
)"""
INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_trainee_call_items_candidate_date "
    "ON trainee_call_items (candidate_id, list_date)",
    "CREATE INDEX IF NOT EXISTS ix_trainee_call_items_user_date "
    "ON trainee_call_items (user_id, list_date)",
    "CREATE INDEX IF NOT EXISTS ix_trainee_call_items_later "
    "ON trainee_call_items (user_id, later_date) WHERE outcome = 'later'",
)


def _replace_check(
    table: str, name: str, expression: str, *, not_valid: bool = False
) -> None:
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
    suffix = " NOT VALID" if not_valid else ""
    op.execute(
        f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expression}){suffix}"
    )
    if not_valid:
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'trainee'")
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS "
            "'trainee_program_decision'"
        )

    for table in ("rbac_role_section_permissions", "rbac_role_action_permissions"):
        _replace_check(table, f"ck_{table}_role", f"role IN ({ROLE_VALUES})")
    _replace_check(
        "users",
        "ck_users_exclusive_finance_viewer_roles",
        EXCLUSIVE_ROLES_CHECK,
        not_valid=True,
    )
    _replace_check(
        "job_proposals", "ck_job_proposals_source", f"source IN ({PROPOSAL_SOURCES})"
    )

    # Praktykant nie ma żadnej sekcji ani akcji — jego ekran stoi poza sekcjami.
    op.execute("""
        INSERT INTO rbac_role_section_permissions (role, section, access)
        SELECT 'trainee', section, 'none'
        FROM (VALUES ('sourcing'), ('pipeline'), ('delivery'), ('insights'),
                     ('finance'), ('system_admin')) AS s(section)
        ON CONFLICT (role, section) DO NOTHING
    """)
    op.execute("""
        INSERT INTO rbac_role_action_permissions (role, action, access)
        SELECT DISTINCT 'trainee', action, 'none'
        FROM rbac_role_action_permissions
        ON CONFLICT (role, action) DO NOTHING
    """)
    op.execute(
        "UPDATE rbac_policy_state SET revision = revision + 1, updated_at = now() WHERE id = 1"
    )

    for statement in CANDIDATE_COLUMNS:
        op.execute(statement)
    for name, expression in CANDIDATE_CHECKS:
        _replace_check("candidates", name, expression, not_valid=True)

    op.execute(CREATE_PROGRAMS)
    op.execute(CREATE_LISTS)
    op.execute(CREATE_ITEMS)
    for statement in INDEXES:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS trainee_call_items")
    op.execute("DROP TABLE IF EXISTS trainee_call_lists")
    op.execute("DROP TABLE IF EXISTS trainee_programs")
    for name, _ in CANDIDATE_CHECKS:
        op.execute(f"ALTER TABLE candidates DROP CONSTRAINT IF EXISTS {name}")
    for column in (
        "call_facts_verified_by_user_id",
        "call_facts_verified_at",
        "work_time_preference",
        "accepts_more_office_days",
        "accepts_below_min_rate",
        "b2b_willingness",
    ):
        op.execute(f"ALTER TABLE candidates DROP COLUMN IF EXISTS {column}")
    op.execute("DELETE FROM rbac_role_section_permissions WHERE role = 'trainee'")
    op.execute("DELETE FROM rbac_role_action_permissions WHERE role = 'trainee'")
    op.execute("DELETE FROM job_proposals WHERE source = 'trainee'")
    # Wartości enumów zostają — Postgres nie ma `ALTER TYPE … DROP VALUE`;
    # CHECK-i ról zostają szersze (nieszkodliwe bez kont `trainee`).
