"""Role dashboards, session cutover and relationship reconciliation.

Revision ID: 0210_role_dashboard_rbac_cutover
Revises: 0210_fix_nordea_display_name
Create Date: 2026-08-03

This is the expand/reconcile half of the relationship migration.  The legacy
``client_tac_assignments.is_primary`` column remains available to old pods and
to existing ``client_primary_tac`` notification rules.  The new
``is_first_priority_for_tac`` column has the opposite cardinality: at most one
preferred client per TAC, while any client may have many equal TACs.

Ambiguous legacy priorities are never guessed.  They are written to
``rbac_relationship_reconciliation`` and stay NULL until an authorised user
chooses the TAC's priority client through the new API.

The role/session cutover is intentionally one-way at the data level: all
current sessions and SSO exchange codes are invalidated.  The audit snapshot
retains the pre-cutover role/profile state, but sanitised Finance relationships
and notification payloads are not automatically restored by downgrade.
"""

from alembic import op


revision = "0210_role_dashboard_rbac_cutover"
down_revision = "0210_fix_nordea_display_name"
branch_labels = None
depends_on = None


def _add_constraint(table: str, name: str, definition: str) -> None:
    op.execute(
        f"""
        DO $$ BEGIN
            ALTER TABLE {table} ADD CONSTRAINT {name} {definition};
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )


def upgrade() -> None:
    # PostgreSQL requires a newly added enum value to commit before statements
    # in the migration transaction can use it.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'finance'")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS role_session_migration_audit (
            id              BIGSERIAL PRIMARY KEY,
            migration_key   VARCHAR(80) NOT NULL,
            user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            original_state  JSONB NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT uq_role_session_migration_audit UNIQUE (migration_key, user_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rbac_relationship_reconciliation (
            id              BIGSERIAL PRIMARY KEY,
            migration_key   VARCHAR(80) NOT NULL,
            issue_kind      VARCHAR(80) NOT NULL,
            user_id         INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            details         JSONB NOT NULL DEFAULT '{}'::jsonb,
            resolved_at     TIMESTAMPTZ NULL,
            resolved_by     INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_rbac_reconciliation_open "
        "ON rbac_relationship_reconciliation (issue_kind, created_at) "
        "WHERE resolved_at IS NULL"
    )

    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
        "authorization_version BIGINT NOT NULL DEFAULT 1"
    )
    op.execute(
        "ALTER TABLE auth_exchange_codes ADD COLUMN IF NOT EXISTS "
        "issued_authorization_version BIGINT NOT NULL DEFAULT 1"
    )

    # Snapshot every account before role/profile/session changes.  No email or
    # recruitment PII is duplicated here.
    op.execute(
        """
        INSERT INTO role_session_migration_audit (
            migration_key, user_id, original_state
        )
        SELECT
            '0210_role_dashboard_rbac_cutover',
            id,
            jsonb_build_object(
                'role', role::text,
                'roles', roles,
                'profile_completed', profile_completed,
                'profile_completed_at', profile_completed_at,
                'allowed_sections', allowed_sections,
                'kpi_coach_enabled', kpi_coach_enabled,
                'cloudtalk_agent_id', cloudtalk_agent_id,
                'authorization_version', authorization_version,
                'tokens_valid_after', tokens_valid_after,
                'finance_requested',
                    role::text = 'finance'
                    OR (
                        jsonb_typeof(roles) = 'array'
                        AND roles ? 'finance'
                    )
            )
        FROM users
        ON CONFLICT (migration_key, user_id) DO NOTHING
        """
    )

    # Repair malformed JSON arrays first.  Raw imports historically relied on
    # the [] default and did not always call User.ensure_roles_invariant().
    op.execute(
        """
        UPDATE users
        SET roles = jsonb_build_array(role::text)
        WHERE roles IS NULL OR jsonb_typeof(roles) <> 'array'
        """
    )

    # A pre-existing JSON-only Finance mapping becomes the exclusive Finance
    # persona.  Finance has no recruitment onboarding and no Dyna grants.
    op.execute(
        """
        UPDATE users
        SET role = 'finance'::userrole,
            roles = '["finance"]'::jsonb,
            allowed_sections = '[]'::jsonb,
            profile_completed = TRUE,
            profile_completed_at = COALESCE(profile_completed_at, clock_timestamp()),
            kpi_coach_enabled = FALSE,
            cloudtalk_agent_id = NULL
        WHERE role::text = 'finance' OR roles ? 'finance'
        """
    )

    # Every legacy viewer becomes a Recruiter behind mandatory onboarding.
    op.execute(
        """
        UPDATE users
        SET role = 'recruiter'::userrole,
            roles = '["recruiter"]'::jsonb,
            allowed_sections = '[]'::jsonb,
            profile_completed = FALSE,
            profile_completed_at = NULL
        WHERE role::text = 'user'
        """
    )

    # A stale secondary viewer must not demote a valid primary persona.  Strip
    # deprecated/unknown labels, preserve valid hybrids and keep primary first.
    op.execute(
        """
        WITH cleaned AS (
            SELECT
                u.id,
                COALESCE(
                    jsonb_agg(e.value ORDER BY e.ordinality)
                        FILTER (
                            WHERE e.value IN (
                                'admin', 'head_of_recruitment', 'delivery_lead',
                                'tac', 'recruiter', 'sourcer'
                            )
                        ),
                    '[]'::jsonb
                ) AS roles
            FROM users AS u
            LEFT JOIN LATERAL jsonb_array_elements_text(u.roles)
                WITH ORDINALITY AS e(value, ordinality) ON TRUE
            WHERE u.role::text <> 'finance'
            GROUP BY u.id
        )
        UPDATE users AS u
        SET roles = cleaned.roles
        FROM cleaned
        WHERE u.id = cleaned.id
        """
    )
    op.execute(
        """
        UPDATE users
        SET roles = jsonb_build_array(role::text) || roles
        WHERE role::text <> 'finance' AND NOT (roles ? role::text)
        """
    )

    # Record current Finance assignment IDs before removing live access paths.
    op.execute(
        """
        INSERT INTO rbac_relationship_reconciliation (
            migration_key, issue_kind, user_id, details
        )
        SELECT
            '0210_role_dashboard_rbac_cutover',
            'finance_relationships_sanitised',
            u.id,
            jsonb_build_object(
                'delivery_lead_client_assignment_ids', COALESCE((
                    SELECT jsonb_agg(a.id ORDER BY a.id)
                    FROM delivery_lead_client_assignments a
                    WHERE a.delivery_lead_user_id = u.id
                ), '[]'::jsonb),
                'client_tac_assignment_ids', COALESCE((
                    SELECT jsonb_agg(a.id ORDER BY a.id)
                    FROM client_tac_assignments a
                    WHERE a.tac_user_id = u.id
                ), '[]'::jsonb),
                'tac_delivery_lead_assignment_ids', COALESCE((
                    SELECT jsonb_agg(a.id ORDER BY a.id)
                    FROM tac_delivery_lead_assignments a
                    WHERE a.tac_user_id = u.id OR a.delivery_lead_user_id = u.id
                ), '[]'::jsonb),
                'competence_assignment_ids', COALESCE((
                    SELECT jsonb_agg(a.id ORDER BY a.id)
                    FROM user_competence_categories a
                    WHERE a.user_id = u.id
                ), '[]'::jsonb)
            )
        FROM users u
        WHERE u.role::text = 'finance'
          AND NOT EXISTS (
              SELECT 1
              FROM rbac_relationship_reconciliation r
              WHERE r.migration_key = '0210_role_dashboard_rbac_cutover'
                AND r.issue_kind = 'finance_relationships_sanitised'
                AND r.user_id = u.id
          )
        """
    )
    op.execute(
        "DELETE FROM delivery_lead_client_assignments a USING users u "
        "WHERE a.delivery_lead_user_id = u.id AND u.role::text = 'finance'"
    )
    op.execute(
        "DELETE FROM client_tac_assignments a USING users u "
        "WHERE a.tac_user_id = u.id AND u.role::text = 'finance'"
    )
    op.execute(
        "DELETE FROM tac_delivery_lead_assignments a USING users u "
        "WHERE u.role::text = 'finance' AND "
        "(a.tac_user_id = u.id OR a.delivery_lead_user_id = u.id)"
    )
    op.execute(
        "DELETE FROM tac_linkedin_farming a USING users u "
        "WHERE a.tac_user_id = u.id AND u.role::text = 'finance'"
    )
    op.execute(
        "DELETE FROM user_competence_categories a USING users u "
        "WHERE a.user_id = u.id AND u.role::text = 'finance'"
    )
    op.execute(
        "DELETE FROM job_collaborators a USING users u "
        "WHERE a.user_id = u.id AND u.role::text = 'finance'"
    )
    # The legacy DynaReporter tables are optional on historically stamped
    # databases.  Guard them exactly like the production entrypoint mirror so
    # a missing legacy table cannot abort the canonical Alembic migration.
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.dr_tac_delivery_lead_assignments') IS NOT NULL THEN
                DELETE FROM dr_tac_delivery_lead_assignments a USING users u
                WHERE u.role::text = 'finance'
                  AND (a.tac_user_id = u.id OR a.delivery_lead_user_id = u.id);
            END IF;
            IF to_regclass('public.dr_sourcer_category_assignments') IS NOT NULL THEN
                DELETE FROM dr_sourcer_category_assignments a USING users u
                WHERE a.user_id = u.id AND u.role::text = 'finance';
            END IF;
        END $$
        """
    )
    op.execute(
        """
        UPDATE jobs j SET recruiter_id = NULL
        FROM users u WHERE j.recruiter_id = u.id AND u.role::text = 'finance'
        """
    )
    op.execute(
        """
        UPDATE jobs j SET delivery_lead_id = NULL
        FROM users u WHERE j.delivery_lead_id = u.id AND u.role::text = 'finance'
        """
    )
    op.execute(
        """
        UPDATE jobs j SET tac_id = NULL
        FROM users u WHERE j.tac_id = u.id AND u.role::text = 'finance'
        """
    )
    op.execute(
        """
        UPDATE contacts c SET key_relationship_owner_id = NULL
        FROM users u
        WHERE c.key_relationship_owner_id = u.id AND u.role::text = 'finance'
        """
    )
    op.execute(
        """
        UPDATE saved_searches s
        SET notify_new_matches = FALSE, unseen_count = 0
        FROM users u
        WHERE s.user_id = u.id AND u.role::text = 'finance'
        """
    )
    op.execute(
        """
        DELETE FROM notifications n USING users u
        WHERE n.user_id = u.id
          AND u.role::text = 'finance'
          AND n.notification_type::text NOT IN (
              'password_reset_requested', 'password_changed_by_admin'
          )
        """
    )
    op.execute(
        """
        UPDATE notifications n
        SET link = NULL,
            related_entity_type = NULL,
            related_entity_id = NULL,
            email_send_started_at = NULL
        FROM users u
        WHERE n.user_id = u.id AND u.role::text = 'finance'
        """
    )

    # One global cutover: all access/refresh/WS tokens and every pending SSO
    # handoff become stale.  The marker is written only after the full migration
    # succeeds, so the entrypoint mirror does not repeat this on every restart.
    op.execute(
        """
        UPDATE users
        SET authorization_version = GREATEST(authorization_version, 1) + 1,
            tokens_valid_after = clock_timestamp()
        WHERE NOT EXISTS (
            SELECT 1 FROM app_settings
            WHERE key = '0210_role_dashboard_rbac_cutover'
        )
        """
    )
    op.execute(
        """
        DELETE FROM auth_exchange_codes
        WHERE NOT EXISTS (
            SELECT 1 FROM app_settings
            WHERE key = '0210_role_dashboard_rbac_cutover'
        )
        """
    )

    _add_constraint(
        "users",
        "ck_users_authorization_version_positive",
        "CHECK (authorization_version > 0) NOT VALID",
    )
    _add_constraint(
        "users",
        "ck_users_roles_array",
        "CHECK (jsonb_typeof(roles) = 'array') NOT VALID",
    )
    _add_constraint(
        "users",
        "ck_users_exclusive_finance_viewer_roles",
        """CHECK (
            CASE
                WHEN role::text IN ('finance', 'user')
                    THEN roles = jsonb_build_array(role::text)
                ELSE NOT (roles ?| ARRAY['finance', 'user']::text[])
            END
        ) NOT VALID""",
    )
    op.execute(
        "ALTER TABLE users VALIDATE CONSTRAINT ck_users_authorization_version_positive"
    )
    op.execute("ALTER TABLE users VALIDATE CONSTRAINT ck_users_roles_array")
    op.execute(
        "ALTER TABLE users VALIDATE CONSTRAINT ck_users_exclusive_finance_viewer_roles"
    )

    # Client↔TAC expand.  Only a TAC with exactly one client has an
    # unambiguous first priority.  Multi-client portfolios are queued for an
    # explicit choice regardless of the old per-client leader flag.
    op.execute(
        "ALTER TABLE client_tac_assignments ADD COLUMN IF NOT EXISTS "
        "is_first_priority_for_tac BOOLEAN NULL"
    )
    op.execute(
        """
        INSERT INTO rbac_relationship_reconciliation (
            migration_key, issue_kind, user_id, details
        )
        SELECT
            '0210_role_dashboard_rbac_cutover',
            'client_tac_first_priority_required',
            tac_user_id,
            jsonb_build_object(
                'assignment_count', count(*),
                'client_ids', jsonb_agg(client_id ORDER BY client_id),
                'legacy_primary_client_ids',
                    COALESCE(
                        jsonb_agg(client_id ORDER BY client_id)
                            FILTER (WHERE is_primary IS TRUE),
                        '[]'::jsonb
                    )
            )
        FROM client_tac_assignments AS assignment
        GROUP BY assignment.tac_user_id
        HAVING count(*) > 1
           AND count(*) FILTER (
                   WHERE assignment.is_first_priority_for_tac IS TRUE
               ) <> 1
           AND NOT EXISTS (
               SELECT 1
               FROM rbac_relationship_reconciliation AS existing
               WHERE existing.migration_key = '0210_role_dashboard_rbac_cutover'
                 AND existing.issue_kind = 'client_tac_first_priority_required'
                 AND existing.user_id = assignment.tac_user_id
           )
        """
    )
    op.execute(
        """
        WITH single_client_tacs AS (
            SELECT tac_user_id
            FROM client_tac_assignments
            GROUP BY tac_user_id
            HAVING count(*) = 1
        )
        UPDATE client_tac_assignments a
        SET is_first_priority_for_tac = TRUE
        FROM single_client_tacs s
        WHERE a.tac_user_id = s.tac_user_id
          AND a.is_first_priority_for_tac IS NULL
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "ux_client_tac_one_first_priority_client "
        "ON client_tac_assignments (tac_user_id) "
        "WHERE is_first_priority_for_tac IS TRUE"
    )

    # Competence priority becomes canonical.  Multiple legacy primary signals
    # are demoted to secondary and recorded for an explicit re-selection; no
    # category assignment row is deleted.
    op.execute(
        """
        INSERT INTO rbac_relationship_reconciliation (
            migration_key, issue_kind, user_id, details
        )
        SELECT
            '0210_role_dashboard_rbac_cutover',
            'competence_primary_required',
            user_id,
            jsonb_build_object(
                'signalled_assignment_ids',
                    jsonb_agg(id ORDER BY id)
                        FILTER (WHERE is_primary IS TRUE OR priority = 1),
                'all_assignment_ids', jsonb_agg(id ORDER BY id)
            )
        FROM user_competence_categories AS assignment
        GROUP BY assignment.user_id
        HAVING count(*) FILTER (
                   WHERE assignment.is_primary IS TRUE OR assignment.priority = 1
               ) > 1
           AND NOT EXISTS (
               SELECT 1
               FROM rbac_relationship_reconciliation AS existing
               WHERE existing.migration_key = '0210_role_dashboard_rbac_cutover'
                 AND existing.issue_kind = 'competence_primary_required'
                 AND existing.user_id = assignment.user_id
           )
        """
    )
    op.execute(
        """
        WITH ambiguous AS (
            SELECT user_id
            FROM user_competence_categories
            GROUP BY user_id
            HAVING count(*) FILTER (WHERE is_primary IS TRUE OR priority = 1) > 1
        )
        UPDATE user_competence_categories a
        SET priority = 2, is_primary = FALSE
        FROM ambiguous x
        WHERE a.user_id = x.user_id
        """
    )
    op.execute(
        """
        WITH signal AS (
            SELECT user_id, min(id) AS assignment_id
            FROM user_competence_categories
            WHERE is_primary IS TRUE OR priority = 1
            GROUP BY user_id
            HAVING count(*) = 1
        )
        UPDATE user_competence_categories a
        SET priority = CASE WHEN a.id = signal.assignment_id THEN 1 ELSE 2 END,
            is_primary = (a.id = signal.assignment_id)
        FROM signal
        WHERE a.user_id = signal.user_id
        """
    )
    op.execute(
        """
        UPDATE user_competence_categories
        SET priority = COALESCE(priority, 2),
            is_primary = (COALESCE(priority, 2) = 1)
        """
    )
    op.execute(
        "ALTER TABLE user_competence_categories ALTER COLUMN priority SET DEFAULT 2"
    )
    op.execute(
        "ALTER TABLE user_competence_categories ALTER COLUMN priority SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE user_competence_categories "
        "DROP CONSTRAINT IF EXISTS ck_user_cc_priority"
    )
    _add_constraint(
        "user_competence_categories",
        "ck_user_cc_priority",
        "CHECK (priority IN (1, 2)) NOT VALID",
    )
    _add_constraint(
        "user_competence_categories",
        "ck_user_cc_primary_priority",
        "CHECK (is_primary = (priority = 1)) NOT VALID",
    )
    op.execute(
        "ALTER TABLE user_competence_categories VALIDATE CONSTRAINT ck_user_cc_priority"
    )
    op.execute(
        "ALTER TABLE user_competence_categories "
        "VALIDATE CONSTRAINT ck_user_cc_primary_priority"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_user_cc_one_primary "
        "ON user_competence_categories (user_id) WHERE priority = 1"
    )

    # Marker written last.  The production safety net uses the same key for
    # its one-time data/session cutover and therefore cannot log everyone out
    # again after a normal restart.
    op.execute(
        """
        INSERT INTO app_settings (key, value)
        VALUES (
            '0210_role_dashboard_rbac_cutover',
            jsonb_build_object(
                'revision', '0210_role_dashboard_rbac_cutover',
                'completed_at', clock_timestamp()
            )
        )
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    # Structural rollback only.  Session invalidation and sanitised Finance
    # relationships are not recreated; production rollback requires a restore
    # or an explicit forward repair using the audit/reconciliation records.
    op.execute("DELETE FROM kpi_role_defaults WHERE role::text = 'finance'")
    op.execute(
        """
        UPDATE users
        SET role = 'user'::userrole,
            roles = '["user"]'::jsonb,
            allowed_sections = '[]'::jsonb,
            profile_completed = TRUE,
            profile_completed_at = COALESCE(profile_completed_at, clock_timestamp())
        WHERE role::text = 'finance'
        """
    )

    op.execute("DROP INDEX IF EXISTS ux_user_cc_one_primary")
    op.execute(
        "ALTER TABLE user_competence_categories "
        "DROP CONSTRAINT IF EXISTS ck_user_cc_primary_priority"
    )
    op.execute(
        "ALTER TABLE user_competence_categories "
        "DROP CONSTRAINT IF EXISTS ck_user_cc_priority"
    )
    op.execute(
        "ALTER TABLE user_competence_categories ALTER COLUMN priority DROP NOT NULL"
    )
    op.execute(
        "ALTER TABLE user_competence_categories ALTER COLUMN priority DROP DEFAULT"
    )
    _add_constraint(
        "user_competence_categories",
        "ck_user_cc_priority",
        "CHECK (priority IS NULL OR priority IN (1, 2))",
    )

    op.execute("DROP INDEX IF EXISTS ux_client_tac_one_first_priority_client")
    op.execute(
        "ALTER TABLE client_tac_assignments "
        "DROP COLUMN IF EXISTS is_first_priority_for_tac"
    )

    op.execute(
        "ALTER TABLE users DROP CONSTRAINT IF EXISTS "
        "ck_users_exclusive_finance_viewer_roles"
    )
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_roles_array")
    op.execute(
        "ALTER TABLE users DROP CONSTRAINT IF EXISTS "
        "ck_users_authorization_version_positive"
    )
    op.execute(
        "ALTER TABLE auth_exchange_codes "
        "DROP COLUMN IF EXISTS issued_authorization_version"
    )
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS authorization_version")
    # A later forward upgrade must perform a fresh cutover and invalidate any
    # sessions issued while the downgraded application was active.  The audit
    # and reconciliation rows intentionally remain as historical evidence.
    op.execute(
        "DELETE FROM app_settings WHERE key = '0210_role_dashboard_rbac_cutover'"
    )
