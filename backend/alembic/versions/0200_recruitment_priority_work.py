"""Recruitment Priority Lock persistence foundation.

Additive only:
* versioned plans, Delivery Lead demands, member assignments and blockers,
* one-shot exceptions, cohort modes and persisted worker/alert state,
* append-only privileged-action audit,
* nullable Priority Work provenance on the canonical RecruitmentProcess.

No historical process is classified in this migration.  A resumable
reconciliation job owns that backfill so deploy/startup remains bounded.

Revision ID: 0200_recruitment_priority_work
Revises: 0199_candidate_stage_removals
"""

import re

from alembic import op
import sqlalchemy as sa


revision = "0200_recruitment_priority_work"
down_revision = "0199_candidate_stage_removals"
branch_labels = None
depends_on = None


ENUM_STATEMENTS = [
    """DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'prioritymode') THEN
            CREATE TYPE prioritymode AS ENUM ('off', 'shadow', 'enforce');
        END IF;
    END $$""",
    """DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_type WHERE typname = 'priorityplanstatus'
        ) THEN
            CREATE TYPE priorityplanstatus AS ENUM (
                'draft', 'published', 'superseded'
            );
        END IF;
    END $$""",
    """DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_type WHERE typname = 'prioritymemberstatus'
        ) THEN
            CREATE TYPE prioritymemberstatus AS ENUM ('active', 'paused');
        END IF;
    END $$""",
    """DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_type WHERE typname = 'prioritydemandstatus'
        ) THEN
            CREATE TYPE prioritydemandstatus AS ENUM (
                'open', 'covered', 'fulfilled', 'paused', 'cancelled'
            );
        END IF;
    END $$""",
    """DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'priorityrank') THEN
            CREATE TYPE priorityrank AS ENUM ('A', 'B', 'C', 'D', 'E');
        END IF;
    END $$""",
    """DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_type WHERE typname = 'prioritychannel'
        ) THEN
            CREATE TYPE prioritychannel AS ENUM (
                'database', 'linkedin', 'mixed'
            );
        END IF;
    END $$""",
    """DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_type WHERE typname = 'priorityblockercategory'
        ) THEN
            CREATE TYPE priorityblockercategory AS ENUM (
                'brief', 'client_feedback', 'rate', 'market', 'competence',
                'capacity', 'access', 'other'
            );
        END IF;
    END $$""",
    """DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_type WHERE typname = 'priorityblockerstatus'
        ) THEN
            CREATE TYPE priorityblockerstatus AS ENUM (
                'pending', 'accepted', 'rejected', 'resolved'
            );
        END IF;
    END $$""",
    """DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_type WHERE typname = 'priorityexceptionstatus'
        ) THEN
            CREATE TYPE priorityexceptionstatus AS ENUM (
                'approved', 'consumed', 'revoked', 'expired'
            );
        END IF;
    END $$""",
    """DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_type WHERE typname = 'priorityoriginkind'
        ) THEN
            CREATE TYPE priorityoriginkind AS ENUM (
                'legacy', 'assigned', 'shadow_violation', 'external_inbound',
                'external_observed', 'manager_inbound', 'approved_exception'
            );
        END IF;
    END $$""",
    """DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_type WHERE typname = 'priorityalertseverity'
        ) THEN
            CREATE TYPE priorityalertseverity AS ENUM (
                'info', 'warning', 'critical'
            );
        END IF;
    END $$""",
]

ENUM_VALUES = {
    "prioritymode": ("off", "shadow", "enforce"),
    "priorityplanstatus": ("draft", "published", "superseded"),
    "prioritymemberstatus": ("active", "paused"),
    "prioritydemandstatus": (
        "open",
        "covered",
        "fulfilled",
        "paused",
        "cancelled",
    ),
    "priorityrank": ("A", "B", "C", "D", "E"),
    "prioritychannel": ("database", "linkedin", "mixed"),
    "priorityblockercategory": (
        "brief",
        "client_feedback",
        "rate",
        "market",
        "competence",
        "capacity",
        "access",
        "other",
    ),
    "priorityblockerstatus": ("pending", "accepted", "rejected", "resolved"),
    "priorityexceptionstatus": ("approved", "consumed", "revoked", "expired"),
    "priorityoriginkind": (
        "legacy",
        "assigned",
        "shadow_violation",
        "external_inbound",
        "external_observed",
        "manager_inbound",
        "approved_exception",
    ),
    "priorityalertseverity": ("info", "warning", "critical"),
}


TABLE_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS recruitment_priority_plans (
        id SERIAL PRIMARY KEY,
        version INTEGER NOT NULL UNIQUE,
        status priorityplanstatus NOT NULL DEFAULT 'draft',
        previous_plan_id INTEGER NULL
            REFERENCES recruitment_priority_plans(id) ON DELETE SET NULL,
        effective_from TIMESTAMPTZ NULL,
        review_due_at TIMESTAMPTZ NULL,
        published_at TIMESTAMPTZ NULL,
        superseded_at TIMESTAMPTZ NULL,
        created_by_user_id INTEGER NULL
            REFERENCES users(id) ON DELETE SET NULL,
        published_by_user_id INTEGER NULL
            REFERENCES users(id) ON DELETE SET NULL,
        notes TEXT NULL,
        row_version INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT ck_priority_plan_version_positive CHECK (version > 0),
        CONSTRAINT ck_priority_plan_row_version_positive
            CHECK (row_version > 0)
    )""",
    """CREATE TABLE IF NOT EXISTS recruitment_priority_demands (
        id SERIAL PRIMARY KEY,
        job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
        requested_by_user_id INTEGER NULL
            REFERENCES users(id) ON DELETE SET NULL,
        status prioritydemandstatus NOT NULL DEFAULT 'open',
        proposed_rank priorityrank NULL,
        expected_recommendations INTEGER NOT NULL DEFAULT 3,
        due_at TIMESTAMPTZ NULL,
        required_channel prioritychannel NULL,
        rationale TEXT NOT NULL,
        brief_ready BOOLEAN NOT NULL DEFAULT false,
        row_version INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT ck_priority_demand_recommendations_minimum
            CHECK (expected_recommendations >= 3),
        CONSTRAINT ck_priority_demand_row_version_positive
            CHECK (row_version > 0)
    )""",
    """CREATE TABLE IF NOT EXISTS recruitment_priority_plan_members (
        id SERIAL PRIMARY KEY,
        plan_id INTEGER NOT NULL
            REFERENCES recruitment_priority_plans(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        status prioritymemberstatus NOT NULL DEFAULT 'active',
        verification_capacity INTEGER NOT NULL DEFAULT 12,
        capacity_reason TEXT NULL,
        paused_reason TEXT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_priority_plan_member_user UNIQUE (plan_id, user_id),
        CONSTRAINT ck_priority_member_capacity_nonnegative
            CHECK (verification_capacity >= 0),
        CONSTRAINT ck_priority_member_paused_reason CHECK (
            status <> 'paused'
            OR NULLIF(btrim(paused_reason), '') IS NOT NULL
        )
    )""",
    """CREATE TABLE IF NOT EXISTS recruitment_priority_assignments (
        id SERIAL PRIMARY KEY,
        plan_member_id INTEGER NOT NULL
            REFERENCES recruitment_priority_plan_members(id) ON DELETE CASCADE,
        demand_id INTEGER NOT NULL
            REFERENCES recruitment_priority_demands(id) ON DELETE RESTRICT,
        job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
        rank priorityrank NOT NULL,
        channel prioritychannel NOT NULL,
        verification_target INTEGER NOT NULL DEFAULT 0,
        recommendation_target INTEGER NOT NULL DEFAULT 0,
        competence_category_id INTEGER NULL
            REFERENCES competence_categories(id) ON DELETE SET NULL,
        competence_matches BOOLEAN NOT NULL DEFAULT true,
        cc_exception_reason TEXT NULL,
        extra_slot_reason TEXT NULL,
        suggestion_source VARCHAR(30) NOT NULL DEFAULT 'manual',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_priority_assignment_member_rank
            UNIQUE (plan_member_id, rank),
        CONSTRAINT uq_priority_assignment_member_job
            UNIQUE (plan_member_id, job_id),
        CONSTRAINT ck_priority_assignment_verifications_nonnegative
            CHECK (verification_target >= 0),
        CONSTRAINT ck_priority_assignment_recommendations_nonnegative
            CHECK (recommendation_target >= 0),
        CONSTRAINT ck_priority_assignment_extra_slot_reason CHECK (
            rank NOT IN ('D', 'E')
            OR NULLIF(btrim(extra_slot_reason), '') IS NOT NULL
        ),
        CONSTRAINT ck_priority_assignment_cc_exception_reason CHECK (
            competence_matches
            OR NULLIF(btrim(cc_exception_reason), '') IS NOT NULL
        )
    )""",
    """CREATE TABLE IF NOT EXISTS recruitment_priority_blockers (
        id SERIAL PRIMARY KEY,
        assignment_id INTEGER NOT NULL
            REFERENCES recruitment_priority_assignments(id) ON DELETE CASCADE,
        reported_by_user_id INTEGER NULL
            REFERENCES users(id) ON DELETE SET NULL,
        category priorityblockercategory NOT NULL,
        description TEXT NOT NULL,
        evidence JSONB NULL,
        status priorityblockerstatus NOT NULL DEFAULT 'pending',
        decided_by_user_id INTEGER NULL
            REFERENCES users(id) ON DELETE SET NULL,
        decided_at TIMESTAMPTZ NULL,
        decision_reason TEXT NULL,
        resolved_by_user_id INTEGER NULL
            REFERENCES users(id) ON DELETE SET NULL,
        resolved_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT ck_priority_blocker_decision_timestamp
            CHECK (
                status NOT IN ('accepted', 'rejected')
                OR decided_at IS NOT NULL
            ),
        CONSTRAINT ck_priority_blocker_resolved_at
            CHECK (status <> 'resolved' OR resolved_at IS NOT NULL)
    )""",
    """CREATE TABLE IF NOT EXISTS recruitment_priority_exceptions (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
        granted_by_user_id INTEGER NULL
            REFERENCES users(id) ON DELETE SET NULL,
        origin_assignment_id INTEGER NULL
            REFERENCES recruitment_priority_assignments(id) ON DELETE SET NULL,
        status priorityexceptionstatus NOT NULL DEFAULT 'approved',
        reason TEXT NOT NULL,
        valid_from TIMESTAMPTZ NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        consumed_at TIMESTAMPTZ NULL,
        consumed_candidate_id INTEGER NULL
            REFERENCES candidates(id) ON DELETE SET NULL,
        consumed_process_id INTEGER NULL UNIQUE
            REFERENCES recruitment_processes(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT ck_priority_exception_valid_window
            CHECK (expires_at > valid_from),
        CONSTRAINT ck_priority_exception_consumed_at
            CHECK (status <> 'consumed' OR consumed_at IS NOT NULL)
    )""",
    """CREATE TABLE IF NOT EXISTS recruitment_priority_state (
        id SMALLINT PRIMARY KEY DEFAULT 1,
        current_plan_id INTEGER NULL UNIQUE
            REFERENCES recruitment_priority_plans(id) ON DELETE SET NULL,
        row_version INTEGER NOT NULL DEFAULT 1,
        worker_heartbeat_at TIMESTAMPTZ NULL,
        last_reconciled_at TIMESTAMPTZ NULL,
        last_alert_sweep_at TIMESTAMPTZ NULL,
        last_error TEXT NULL,
        metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT ck_recruitment_priority_state_singleton CHECK (id = 1),
        CONSTRAINT ck_priority_state_row_version_positive
            CHECK (row_version > 0)
    )""",
    """CREATE TABLE IF NOT EXISTS recruitment_priority_user_modes (
        user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        mode prioritymode NOT NULL DEFAULT 'off',
        set_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        reason TEXT NULL,
        effective_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS recruitment_priority_alerts (
        id BIGSERIAL PRIMARY KEY,
        dedupe_key VARCHAR(255) NOT NULL UNIQUE,
        kind VARCHAR(80) NOT NULL,
        severity priorityalertseverity NOT NULL DEFAULT 'warning',
        user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        job_id INTEGER NULL REFERENCES jobs(id) ON DELETE SET NULL,
        assignment_id INTEGER NULL
            REFERENCES recruitment_priority_assignments(id) ON DELETE SET NULL,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        occurrence_count INTEGER NOT NULL DEFAULT 1,
        first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        resolved_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT ck_priority_alert_occurrence_count_positive
            CHECK (occurrence_count > 0),
        CONSTRAINT ck_priority_alert_seen_window
            CHECK (last_seen_at >= first_seen_at)
    )""",
    """CREATE TABLE IF NOT EXISTS recruitment_priority_audit_events (
        id BIGSERIAL PRIMARY KEY,
        event_type VARCHAR(80) NOT NULL,
        actor_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        plan_id INTEGER NULL
            REFERENCES recruitment_priority_plans(id) ON DELETE SET NULL,
        subject_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        job_id INTEGER NULL REFERENCES jobs(id) ON DELETE SET NULL,
        assignment_id INTEGER NULL
            REFERENCES recruitment_priority_assignments(id) ON DELETE SET NULL,
        process_id INTEGER NULL
            REFERENCES recruitment_processes(id) ON DELETE SET NULL,
        exception_id INTEGER NULL
            REFERENCES recruitment_priority_exceptions(id) ON DELETE SET NULL,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        correlation_id VARCHAR(100) NULL
    )""",
]


INDEX_STATEMENTS = [
    """CREATE UNIQUE INDEX IF NOT EXISTS
        ux_recruitment_priority_one_published
        ON recruitment_priority_plans (status)
        WHERE status = 'published'""",
    """CREATE INDEX IF NOT EXISTS ix_recruitment_priority_plans_status
        ON recruitment_priority_plans (status)""",
    """CREATE INDEX IF NOT EXISTS ix_recruitment_priority_plans_review_due_at
        ON recruitment_priority_plans (review_due_at)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS
        ux_recruitment_priority_one_active_demand_per_job
        ON recruitment_priority_demands (job_id)
        WHERE status IN ('open', 'covered', 'paused')""",
    """CREATE INDEX IF NOT EXISTS ix_recruitment_priority_demands_job_id
        ON recruitment_priority_demands (job_id)""",
    """CREATE INDEX IF NOT EXISTS
        ix_recruitment_priority_demands_requested_by_user_id
        ON recruitment_priority_demands (requested_by_user_id)""",
    """CREATE INDEX IF NOT EXISTS ix_recruitment_priority_demands_status
        ON recruitment_priority_demands (status)""",
    """CREATE INDEX IF NOT EXISTS ix_recruitment_priority_demands_due_at
        ON recruitment_priority_demands (due_at)""",
    """CREATE INDEX IF NOT EXISTS ix_recruitment_priority_plan_members_plan_id
        ON recruitment_priority_plan_members (plan_id)""",
    """CREATE INDEX IF NOT EXISTS ix_recruitment_priority_plan_members_user_id
        ON recruitment_priority_plan_members (user_id)""",
    """CREATE INDEX IF NOT EXISTS
        ix_recruitment_priority_assignments_plan_member_id
        ON recruitment_priority_assignments (plan_member_id)""",
    """CREATE INDEX IF NOT EXISTS ix_priority_assignment_job
        ON recruitment_priority_assignments (job_id)""",
    """CREATE INDEX IF NOT EXISTS ix_priority_assignment_demand
        ON recruitment_priority_assignments (demand_id)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS
        ux_priority_blocker_assignment_active
        ON recruitment_priority_blockers (assignment_id)
        WHERE status IN ('pending', 'accepted') AND resolved_at IS NULL""",
    """CREATE INDEX IF NOT EXISTS ix_recruitment_priority_blockers_assignment_id
        ON recruitment_priority_blockers (assignment_id)""",
    """CREATE INDEX IF NOT EXISTS ix_recruitment_priority_blockers_status
        ON recruitment_priority_blockers (status)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS
        ux_priority_exception_one_approved_per_user_job
        ON recruitment_priority_exceptions (user_id, job_id)
        WHERE status = 'approved'""",
    """CREATE INDEX IF NOT EXISTS ix_priority_exception_expiry
        ON recruitment_priority_exceptions (status, expires_at)""",
    """CREATE INDEX IF NOT EXISTS ix_recruitment_priority_exceptions_user_id
        ON recruitment_priority_exceptions (user_id)""",
    """CREATE INDEX IF NOT EXISTS ix_recruitment_priority_exceptions_job_id
        ON recruitment_priority_exceptions (job_id)""",
    """CREATE INDEX IF NOT EXISTS ix_recruitment_priority_exceptions_status
        ON recruitment_priority_exceptions (status)""",
    """CREATE INDEX IF NOT EXISTS ix_priority_alert_unresolved
        ON recruitment_priority_alerts (severity, last_seen_at)
        WHERE resolved_at IS NULL""",
    """CREATE INDEX IF NOT EXISTS ix_recruitment_priority_alerts_kind
        ON recruitment_priority_alerts (kind)""",
    """CREATE INDEX IF NOT EXISTS ix_recruitment_priority_alerts_user_id
        ON recruitment_priority_alerts (user_id)""",
    """CREATE INDEX IF NOT EXISTS ix_recruitment_priority_alerts_job_id
        ON recruitment_priority_alerts (job_id)""",
    """CREATE INDEX IF NOT EXISTS ix_recruitment_priority_alerts_assignment_id
        ON recruitment_priority_alerts (assignment_id)""",
    """CREATE INDEX IF NOT EXISTS ix_priority_audit_event_type_occurred
        ON recruitment_priority_audit_events (event_type, occurred_at)""",
    """CREATE INDEX IF NOT EXISTS ix_priority_audit_plan_occurred
        ON recruitment_priority_audit_events (plan_id, occurred_at)""",
    """CREATE INDEX IF NOT EXISTS
        ix_recruitment_priority_audit_events_correlation_id
        ON recruitment_priority_audit_events (correlation_id)""",
]


PROCESS_COLUMNS = [
    """ALTER TABLE recruitment_processes
        ADD COLUMN IF NOT EXISTS origin_assignment_id INTEGER NULL""",
    """ALTER TABLE recruitment_processes
        ADD COLUMN IF NOT EXISTS eligibility_assignment_id INTEGER NULL""",
    """ALTER TABLE recruitment_processes
        ADD COLUMN IF NOT EXISTS opened_by_user_id INTEGER NULL""",
    """ALTER TABLE recruitment_processes
        ADD COLUMN IF NOT EXISTS credit_user_id INTEGER NULL""",
    """ALTER TABLE recruitment_processes
        ADD COLUMN IF NOT EXISTS origin_kind priorityoriginkind NULL""",
    """ALTER TABLE recruitment_processes
        ADD COLUMN IF NOT EXISTS priority_compliant_at_open BOOLEAN NULL""",
    """ALTER TABLE recruitment_processes
        ADD COLUMN IF NOT EXISTS kpi_eligible BOOLEAN NULL""",
    """ALTER TABLE recruitment_processes
        ADD COLUMN IF NOT EXISTS kpi_eligibility_reason VARCHAR(255) NULL""",
    """ALTER TABLE recruitment_processes
        ADD COLUMN IF NOT EXISTS kpi_eligibility_decided_at TIMESTAMPTZ NULL""",
    """ALTER TABLE recruitment_processes
        ADD COLUMN IF NOT EXISTS ownership_confirmed_at TIMESTAMPTZ NULL""",
    """ALTER TABLE recruitment_processes
        ADD COLUMN IF NOT EXISTS ownership_confirmed_by_user_id INTEGER NULL""",
]

INVITE_LINK_COLUMNS = [
    """ALTER TABLE candidate_invite_links
        ADD COLUMN IF NOT EXISTS origin_assignment_id INTEGER NULL""",
    """ALTER TABLE candidate_invite_links
        ADD COLUMN IF NOT EXISTS priority_compliant_at_create BOOLEAN NULL""",
]


PROCESS_FOREIGN_KEYS = [
    (
        "fk_process_origin_priority_assignment",
        "origin_assignment_id",
        "recruitment_priority_assignments",
    ),
    (
        "fk_process_eligibility_priority_assignment",
        "eligibility_assignment_id",
        "recruitment_priority_assignments",
    ),
    ("fk_process_opened_by_user", "opened_by_user_id", "users"),
    ("fk_process_credit_user", "credit_user_id", "users"),
    (
        "fk_process_ownership_confirmed_by_user",
        "ownership_confirmed_by_user_id",
        "users",
    ),
]

REQUIRED_COLUMNS = {
    "recruitment_priority_plans": {
        "id",
        "version",
        "status",
        "previous_plan_id",
        "effective_from",
        "review_due_at",
        "published_at",
        "superseded_at",
        "created_by_user_id",
        "published_by_user_id",
        "notes",
        "row_version",
        "created_at",
        "updated_at",
    },
    "recruitment_priority_plan_members": {
        "id",
        "plan_id",
        "user_id",
        "status",
        "verification_capacity",
        "capacity_reason",
        "paused_reason",
        "created_at",
        "updated_at",
    },
    "recruitment_priority_demands": {
        "id",
        "job_id",
        "requested_by_user_id",
        "status",
        "proposed_rank",
        "expected_recommendations",
        "due_at",
        "required_channel",
        "rationale",
        "brief_ready",
        "row_version",
        "created_at",
        "updated_at",
    },
    "recruitment_priority_assignments": {
        "id",
        "plan_member_id",
        "demand_id",
        "job_id",
        "rank",
        "channel",
        "verification_target",
        "recommendation_target",
        "competence_category_id",
        "competence_matches",
        "cc_exception_reason",
        "extra_slot_reason",
        "suggestion_source",
        "created_at",
        "updated_at",
    },
    "recruitment_priority_blockers": {
        "id",
        "assignment_id",
        "reported_by_user_id",
        "category",
        "description",
        "evidence",
        "status",
        "decided_by_user_id",
        "decided_at",
        "decision_reason",
        "resolved_by_user_id",
        "resolved_at",
        "created_at",
        "updated_at",
    },
    "recruitment_priority_exceptions": {
        "id",
        "user_id",
        "job_id",
        "granted_by_user_id",
        "origin_assignment_id",
        "status",
        "reason",
        "valid_from",
        "expires_at",
        "consumed_at",
        "consumed_candidate_id",
        "consumed_process_id",
        "created_at",
        "updated_at",
    },
    "recruitment_priority_state": {
        "id",
        "current_plan_id",
        "row_version",
        "worker_heartbeat_at",
        "last_reconciled_at",
        "last_alert_sweep_at",
        "last_error",
        "metrics",
        "created_at",
        "updated_at",
    },
    "recruitment_priority_user_modes": {
        "user_id",
        "mode",
        "set_by_user_id",
        "reason",
        "effective_at",
        "created_at",
        "updated_at",
    },
    "recruitment_priority_alerts": {
        "id",
        "dedupe_key",
        "kind",
        "severity",
        "user_id",
        "job_id",
        "assignment_id",
        "payload",
        "occurrence_count",
        "first_seen_at",
        "last_seen_at",
        "resolved_at",
        "created_at",
        "updated_at",
    },
    "recruitment_priority_audit_events": {
        "id",
        "event_type",
        "actor_user_id",
        "plan_id",
        "subject_user_id",
        "job_id",
        "assignment_id",
        "process_id",
        "exception_id",
        "payload",
        "occurred_at",
        "correlation_id",
    },
    "recruitment_processes": {
        "origin_assignment_id",
        "eligibility_assignment_id",
        "opened_by_user_id",
        "credit_user_id",
        "origin_kind",
        "priority_compliant_at_open",
        "kpi_eligible",
        "kpi_eligibility_reason",
        "kpi_eligibility_decided_at",
        "ownership_confirmed_at",
        "ownership_confirmed_by_user_id",
    },
    "candidate_invite_links": {
        "origin_assignment_id",
        "priority_compliant_at_create",
    },
}

REQUIRED_INDEXES = (
    (
        "recruitment_priority_plans",
        "ux_recruitment_priority_one_published",
        True,
        True,
        ("status",),
        "status='published'",
    ),
    (
        "recruitment_priority_plans",
        "ix_recruitment_priority_plans_status",
        False,
        False,
        ("status",),
        "",
    ),
    (
        "recruitment_priority_plans",
        "ix_recruitment_priority_plans_review_due_at",
        False,
        False,
        ("review_due_at",),
        "",
    ),
    (
        "recruitment_priority_demands",
        "ux_recruitment_priority_one_active_demand_per_job",
        True,
        True,
        ("job_id",),
        "status=anyarray['open','covered','paused']",
    ),
    (
        "recruitment_priority_blockers",
        "ux_priority_blocker_assignment_active",
        True,
        True,
        ("assignment_id",),
        "status=anyarray['pending','accepted']andresolved_atisnull",
    ),
    (
        "recruitment_priority_exceptions",
        "ux_priority_exception_one_approved_per_user_job",
        True,
        True,
        ("user_id", "job_id"),
        "status='approved'",
    ),
    (
        "recruitment_priority_alerts",
        "ix_priority_alert_unresolved",
        False,
        True,
        ("severity", "last_seen_at"),
        "resolved_atisnull",
    ),
    (
        "recruitment_processes",
        "ix_recruitment_processes_origin_assignment_id",
        False,
        False,
        ("origin_assignment_id",),
        "",
    ),
    (
        "recruitment_processes",
        "ix_recruitment_processes_eligibility_assignment_id",
        False,
        False,
        ("eligibility_assignment_id",),
        "",
    ),
    (
        "recruitment_processes",
        "ix_recruitment_processes_credit_user_id",
        False,
        False,
        ("credit_user_id",),
        "",
    ),
    (
        "recruitment_processes",
        "ix_recruitment_processes_origin_kind",
        False,
        False,
        ("origin_kind",),
        "",
    ),
    (
        "candidate_invite_links",
        "ix_candidate_invite_links_origin_assignment_id",
        False,
        False,
        ("origin_assignment_id",),
        "",
    ),
)

REQUIRED_CHECKS = (
    (
        "recruitment_priority_demands",
        "ck_priority_demand_recommendations_minimum",
        "expected_recommendations >= 3",
    ),
)

REQUIRED_NAMED_CONSTRAINTS = (
    ("recruitment_priority_plans", "recruitment_priority_plans_pkey", "p"),
    (
        "recruitment_priority_plans",
        "recruitment_priority_plans_version_key",
        "u",
    ),
    ("recruitment_priority_plans", "ck_priority_plan_version_positive", "c"),
    ("recruitment_priority_plans", "ck_priority_plan_row_version_positive", "c"),
    (
        "recruitment_priority_demands",
        "recruitment_priority_demands_pkey",
        "p",
    ),
    (
        "recruitment_priority_demands",
        "ck_priority_demand_recommendations_minimum",
        "c",
    ),
    (
        "recruitment_priority_demands",
        "ck_priority_demand_row_version_positive",
        "c",
    ),
    (
        "recruitment_priority_plan_members",
        "recruitment_priority_plan_members_pkey",
        "p",
    ),
    (
        "recruitment_priority_plan_members",
        "uq_priority_plan_member_user",
        "u",
    ),
    (
        "recruitment_priority_plan_members",
        "ck_priority_member_capacity_nonnegative",
        "c",
    ),
    (
        "recruitment_priority_plan_members",
        "ck_priority_member_paused_reason",
        "c",
    ),
    (
        "recruitment_priority_assignments",
        "recruitment_priority_assignments_pkey",
        "p",
    ),
    (
        "recruitment_priority_assignments",
        "uq_priority_assignment_member_rank",
        "u",
    ),
    (
        "recruitment_priority_assignments",
        "uq_priority_assignment_member_job",
        "u",
    ),
    (
        "recruitment_priority_assignments",
        "ck_priority_assignment_verifications_nonnegative",
        "c",
    ),
    (
        "recruitment_priority_assignments",
        "ck_priority_assignment_recommendations_nonnegative",
        "c",
    ),
    (
        "recruitment_priority_assignments",
        "ck_priority_assignment_extra_slot_reason",
        "c",
    ),
    (
        "recruitment_priority_assignments",
        "ck_priority_assignment_cc_exception_reason",
        "c",
    ),
    (
        "recruitment_priority_blockers",
        "recruitment_priority_blockers_pkey",
        "p",
    ),
    (
        "recruitment_priority_blockers",
        "ck_priority_blocker_decision_timestamp",
        "c",
    ),
    (
        "recruitment_priority_blockers",
        "ck_priority_blocker_resolved_at",
        "c",
    ),
    (
        "recruitment_priority_exceptions",
        "recruitment_priority_exceptions_pkey",
        "p",
    ),
    (
        "recruitment_priority_exceptions",
        "recruitment_priority_exceptions_consumed_process_id_key",
        "u",
    ),
    (
        "recruitment_priority_exceptions",
        "ck_priority_exception_valid_window",
        "c",
    ),
    (
        "recruitment_priority_exceptions",
        "ck_priority_exception_consumed_at",
        "c",
    ),
    (
        "recruitment_priority_state",
        "recruitment_priority_state_pkey",
        "p",
    ),
    (
        "recruitment_priority_state",
        "recruitment_priority_state_current_plan_id_key",
        "u",
    ),
    (
        "recruitment_priority_state",
        "ck_recruitment_priority_state_singleton",
        "c",
    ),
    (
        "recruitment_priority_state",
        "ck_priority_state_row_version_positive",
        "c",
    ),
    (
        "recruitment_priority_user_modes",
        "recruitment_priority_user_modes_pkey",
        "p",
    ),
    (
        "recruitment_priority_alerts",
        "recruitment_priority_alerts_pkey",
        "p",
    ),
    (
        "recruitment_priority_alerts",
        "recruitment_priority_alerts_dedupe_key_key",
        "u",
    ),
    (
        "recruitment_priority_alerts",
        "ck_priority_alert_occurrence_count_positive",
        "c",
    ),
    (
        "recruitment_priority_alerts",
        "ck_priority_alert_seen_window",
        "c",
    ),
    (
        "recruitment_priority_audit_events",
        "recruitment_priority_audit_events_pkey",
        "p",
    ),
)

# Core ownership/admission foreign keys and their PostgreSQL delete actions:
# c=cascade, n=set null, r=restrict. These are the links whose drift could
# silently weaken carry-over, plan membership or audit invariants.
REQUIRED_FOREIGN_KEYS = (
    (
        "recruitment_priority_demands",
        "job_id",
        "jobs",
        "r",
    ),
    (
        "recruitment_priority_plan_members",
        "plan_id",
        "recruitment_priority_plans",
        "c",
    ),
    (
        "recruitment_priority_plan_members",
        "user_id",
        "users",
        "r",
    ),
    (
        "recruitment_priority_assignments",
        "plan_member_id",
        "recruitment_priority_plan_members",
        "c",
    ),
    (
        "recruitment_priority_assignments",
        "demand_id",
        "recruitment_priority_demands",
        "r",
    ),
    (
        "recruitment_priority_assignments",
        "job_id",
        "jobs",
        "r",
    ),
    (
        "recruitment_priority_blockers",
        "assignment_id",
        "recruitment_priority_assignments",
        "c",
    ),
    (
        "recruitment_priority_exceptions",
        "user_id",
        "users",
        "r",
    ),
    (
        "recruitment_priority_exceptions",
        "job_id",
        "jobs",
        "r",
    ),
    (
        "recruitment_priority_exceptions",
        "consumed_process_id",
        "recruitment_processes",
        "n",
    ),
    (
        "recruitment_priority_state",
        "current_plan_id",
        "recruitment_priority_plans",
        "n",
    ),
    (
        "recruitment_priority_user_modes",
        "user_id",
        "users",
        "c",
    ),
    (
        "recruitment_processes",
        "origin_assignment_id",
        "recruitment_priority_assignments",
        "n",
    ),
    (
        "recruitment_processes",
        "eligibility_assignment_id",
        "recruitment_priority_assignments",
        "n",
    ),
    ("recruitment_processes", "opened_by_user_id", "users", "n"),
    ("recruitment_processes", "credit_user_id", "users", "n"),
    (
        "recruitment_processes",
        "ownership_confirmed_by_user_id",
        "users",
        "n",
    ),
    (
        "candidate_invite_links",
        "origin_assignment_id",
        "recruitment_priority_assignments",
        "n",
    ),
)


def _add_foreign_key(
    source_table: str,
    constraint_name: str,
    column_name: str,
    target_table: str,
) -> None:
    op.execute(
        f"""DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint AS constraint_row
                JOIN pg_attribute AS source_column
                  ON source_column.attrelid = constraint_row.conrelid
                 AND source_column.attnum = ANY(constraint_row.conkey)
                WHERE constraint_row.contype = 'f'
                  AND constraint_row.conrelid = '{source_table}'::regclass
                  AND constraint_row.confrelid = '{target_table}'::regclass
                  AND source_column.attname = '{column_name}'
            ) THEN
                ALTER TABLE {source_table}
                    ADD CONSTRAINT {constraint_name}
                    FOREIGN KEY ({column_name})
                    REFERENCES {target_table}(id)
                    ON DELETE SET NULL;
            END IF;
        END $$"""
    )


def _canonical_index_predicate(value: object) -> str:
    """Normalize pg_get_expr output while preserving boolean semantics."""

    without_type_casts = re.sub(
        r"::[a-z_][a-z0-9_]*(?:\[\])?",
        "",
        str(value or "").lower(),
    )
    return re.sub(r"[\s()]+", "", without_type_casts)


def _assert_required_schema() -> None:
    """Fail the revision instead of stamping a partial IF-NOT-EXISTS schema."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    missing_columns: list[str] = []
    for table_name, required in REQUIRED_COLUMNS.items():
        try:
            actual = {
                column["name"]
                for column in inspector.get_columns(table_name, schema="public")
            }
        except sa.exc.NoSuchTableError:
            actual = set()
        missing_columns.extend(
            f"{table_name}.{column}" for column in sorted(required - actual)
        )
    if missing_columns:
        raise RuntimeError(
            "Priority Work schema is partial; missing columns: "
            + ", ".join(missing_columns)
        )

    index_query = sa.text(
        """
        SELECT index_row.indisvalid,
               index_row.indisready,
               index_row.indisunique,
               index_row.indpred IS NOT NULL AS is_partial,
               PG_GET_EXPR(index_row.indpred, index_row.indrelid)
                   AS predicate_definition,
               ARRAY(
                   SELECT attribute.attname
                   FROM UNNEST(index_row.indkey)
                        WITH ORDINALITY AS indexed(attnum, position)
                   JOIN pg_attribute AS attribute
                     ON attribute.attrelid = index_row.indrelid
                    AND attribute.attnum = indexed.attnum
                   WHERE indexed.attnum > 0
                   ORDER BY indexed.position
               ) AS column_names
        FROM pg_index AS index_row
        JOIN pg_class AS index_class
          ON index_class.oid = index_row.indexrelid
        WHERE index_row.indrelid = TO_REGCLASS(:table_name)
          AND index_class.relname = :index_name
        """
    )
    invalid_indexes: list[str] = []
    for (
        table_name,
        index_name,
        must_be_unique,
        must_be_partial,
        expected_columns,
        expected_predicate,
    ) in REQUIRED_INDEXES:
        row = (
            bind.execute(
                index_query,
                {
                    "table_name": f"public.{table_name}",
                    "index_name": index_name,
                },
            )
            .mappings()
            .first()
        )
        if (
            row is None
            or not row["indisvalid"]
            or not row["indisready"]
            or bool(row["indisunique"]) != must_be_unique
            or bool(row["is_partial"]) != must_be_partial
            or tuple(row["column_names"] or ()) != expected_columns
            or _canonical_index_predicate(row["predicate_definition"])
            != expected_predicate
        ):
            invalid_indexes.append(f"{table_name}.{index_name}")
    if invalid_indexes:
        raise RuntimeError(
            "Priority Work schema has missing/invalid indexes: "
            + ", ".join(invalid_indexes)
        )

    check_query = sa.text(
        """
        SELECT PG_GET_CONSTRAINTDEF(constraint_row.oid) AS definition
        FROM pg_constraint AS constraint_row
        WHERE constraint_row.conrelid = TO_REGCLASS(:table_name)
          AND constraint_row.conname = :constraint_name
          AND constraint_row.contype = 'c'
        """
    )
    invalid_checks: list[str] = []
    for table_name, constraint_name, required_fragment in REQUIRED_CHECKS:
        definition = bind.execute(
            check_query,
            {
                "table_name": f"public.{table_name}",
                "constraint_name": constraint_name,
            },
        ).scalar_one_or_none()
        normalized = " ".join(
            str(definition or "").replace("(", " ").replace(")", " ").split()
        )
        if required_fragment not in normalized:
            invalid_checks.append(f"{table_name}.{constraint_name}")
    if invalid_checks:
        raise RuntimeError(
            "Priority Work schema has missing/invalid checks: "
            + ", ".join(invalid_checks)
        )

    constraint_query = sa.text(
        """
        SELECT constraint_row.contype::text
        FROM pg_constraint AS constraint_row
        WHERE constraint_row.conrelid = TO_REGCLASS(:table_name)
          AND constraint_row.conname = :constraint_name
        """
    )
    invalid_constraints: list[str] = []
    for table_name, constraint_name, expected_type in REQUIRED_NAMED_CONSTRAINTS:
        actual_type = bind.execute(
            constraint_query,
            {
                "table_name": f"public.{table_name}",
                "constraint_name": constraint_name,
            },
        ).scalar_one_or_none()
        if actual_type != expected_type:
            invalid_constraints.append(f"{table_name}.{constraint_name}")
    if invalid_constraints:
        raise RuntimeError(
            "Priority Work schema has missing/invalid constraints: "
            + ", ".join(invalid_constraints)
        )

    foreign_key_query = sa.text(
        """
        SELECT constraint_row.confdeltype::text
        FROM pg_constraint AS constraint_row
        JOIN pg_attribute AS source_column
          ON source_column.attrelid = constraint_row.conrelid
         AND source_column.attnum = ANY(constraint_row.conkey)
        WHERE constraint_row.contype = 'f'
          AND constraint_row.conrelid = TO_REGCLASS(:table_name)
          AND constraint_row.confrelid = TO_REGCLASS(:target_table)
          AND source_column.attname = :column_name
        """
    )
    invalid_foreign_keys: list[str] = []
    for (
        table_name,
        column_name,
        target_table,
        expected_delete_action,
    ) in REQUIRED_FOREIGN_KEYS:
        actual_delete_action = bind.execute(
            foreign_key_query,
            {
                "table_name": f"public.{table_name}",
                "target_table": f"public.{target_table}",
                "column_name": column_name,
            },
        ).scalar_one_or_none()
        if actual_delete_action != expected_delete_action:
            invalid_foreign_keys.append(f"{table_name}.{column_name}")
    if invalid_foreign_keys:
        raise RuntimeError(
            "Priority Work schema has missing/invalid foreign keys: "
            + ", ".join(invalid_foreign_keys)
        )


def upgrade() -> None:
    for statement in ENUM_STATEMENTS:
        op.execute(statement)
    # An entrypoint safety-net or interrupted manual repair may have created a
    # type with only some labels. Commit type creation first, then make every
    # label idempotently available before table defaults reference it.
    with op.get_context().autocommit_block():
        for enum_name, values in ENUM_VALUES.items():
            for value in values:
                op.execute(f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS '{value}'")
    for statement in TABLE_STATEMENTS:
        op.execute(statement)
    for statement in INDEX_STATEMENTS:
        op.execute(statement)

    op.execute(
        "INSERT INTO recruitment_priority_state (id) VALUES (1) "
        "ON CONFLICT (id) DO NOTHING"
    )

    for statement in PROCESS_COLUMNS:
        op.execute(statement)
    for statement in INVITE_LINK_COLUMNS:
        op.execute(statement)
    for constraint_name, column_name, target_table in PROCESS_FOREIGN_KEYS:
        _add_foreign_key(
            "recruitment_processes",
            constraint_name,
            column_name,
            target_table,
        )
    _add_foreign_key(
        "candidate_invite_links",
        "fk_invite_link_origin_priority_assignment",
        "origin_assignment_id",
        "recruitment_priority_assignments",
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "ix_recruitment_processes_origin_assignment_id "
        "ON recruitment_processes (origin_assignment_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "ix_recruitment_processes_eligibility_assignment_id "
        "ON recruitment_processes (eligibility_assignment_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_recruitment_processes_credit_user_id "
        "ON recruitment_processes (credit_user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_recruitment_processes_origin_kind "
        "ON recruitment_processes (origin_kind)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_invite_links_origin_assignment_id "
        "ON candidate_invite_links (origin_assignment_id)"
    )
    _assert_required_schema()


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_candidate_invite_links_origin_assignment_id")
    op.execute(
        "ALTER TABLE candidate_invite_links "
        "DROP CONSTRAINT IF EXISTS fk_invite_link_origin_priority_assignment"
    )
    for column_name in (
        "priority_compliant_at_create",
        "origin_assignment_id",
    ):
        op.execute(
            f"ALTER TABLE candidate_invite_links DROP COLUMN IF EXISTS {column_name}"
        )
    op.execute("DROP INDEX IF EXISTS ix_recruitment_processes_origin_kind")
    op.execute("DROP INDEX IF EXISTS ix_recruitment_processes_credit_user_id")
    op.execute(
        "DROP INDEX IF EXISTS ix_recruitment_processes_eligibility_assignment_id"
    )
    op.execute("DROP INDEX IF EXISTS ix_recruitment_processes_origin_assignment_id")
    for constraint_name, _, _ in reversed(PROCESS_FOREIGN_KEYS):
        op.execute(
            "ALTER TABLE recruitment_processes "
            f"DROP CONSTRAINT IF EXISTS {constraint_name}"
        )
    for column_name in (
        "ownership_confirmed_by_user_id",
        "ownership_confirmed_at",
        "kpi_eligibility_decided_at",
        "kpi_eligibility_reason",
        "kpi_eligible",
        "priority_compliant_at_open",
        "origin_kind",
        "credit_user_id",
        "opened_by_user_id",
        "eligibility_assignment_id",
        "origin_assignment_id",
    ):
        op.execute(
            f"ALTER TABLE recruitment_processes DROP COLUMN IF EXISTS {column_name}"
        )

    for table_name in (
        "recruitment_priority_audit_events",
        "recruitment_priority_alerts",
        "recruitment_priority_user_modes",
        "recruitment_priority_state",
        "recruitment_priority_blockers",
        "recruitment_priority_exceptions",
        "recruitment_priority_assignments",
        "recruitment_priority_plan_members",
        "recruitment_priority_demands",
        "recruitment_priority_plans",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table_name}")

    for enum_name in (
        "priorityalertseverity",
        "priorityoriginkind",
        "priorityexceptionstatus",
        "priorityblockerstatus",
        "priorityblockercategory",
        "prioritychannel",
        "priorityrank",
        "prioritydemandstatus",
        "prioritymemberstatus",
        "priorityplanstatus",
        "prioritymode",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
