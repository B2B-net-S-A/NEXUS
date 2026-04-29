"""Initial schema - explicit DDL pinned to 2026-03-18 (commit 38bd32f)

Revision ID: 0001
Revises:
Create Date: 2026-03-18 00:00:00.000000

Refactored 2026-04-29: replaced ``Base.metadata.create_all()`` with explicit
DDL that pins the schema at 2026-03-18 (commit ``38bd32f`` — "Initial Nexus
import"), so subsequent migrations get a stable starting point regardless of
how the ORM evolves.

Why: the previous create_all-based 0001 generated all tables from the *current*
ORM, which by 2026-04-21 included tables added in 0034_kpi_coach
(``kpi_role_defaults``, ``user_kpi_targets``) that depend on the new 6-value
``userrole`` enum. On a fresh DB this caused 0011_consolidate_user_roles to
fail with ``DependentObjectsStillExistError`` when trying to drop ``userrole``
because tables from the future were already pointing at it. Migrations 0001
through 0034+ now run cleanly on an empty Postgres.

The 20 tables created here mirror the contents of ``backend/app/models/`` at
commit 38bd32f:

    activities, calendar_events, calls, candidates, candidate_stages, clients,
    client_knowledge, contacts, contracts, email_templates, jobs, job_postings,
    notes, notifications, sales_opportunities, screening_notes, talent_pools,
    talent_pool_memberships, users, user_activities

``sales_opportunities`` is intentionally created here even though 0003 drops
it, because we are reproducing the historical schema at the boundary between
0001 and 0002.

Idempotent: every CREATE TABLE / CREATE INDEX uses ``IF NOT EXISTS`` and every
CREATE TYPE is wrapped in a ``DO $$ … EXCEPTION WHEN duplicate_object`` block,
so re-running the migration on a partially-bootstrapped DB is safe.
"""
from alembic import op


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


# Enum types created at the 2026-03-18 schema boundary. Names match what
# SQLAlchemy would have generated via ``Enum(<Class>)`` (lowercased class name)
# or via the explicit ``name=`` parameter on the column.
_ENUMS: list[tuple[str, list[str]]] = [
    ("userrole", ["admin", "recruiter", "manager", "client"]),
    (
        "recruiterrole",
        ["recruiter", "sourcer", "tac", "delivery_lead", "quality_control", "admin"],
    ),
    ("candidatestatus", ["active", "passive", "blacklisted"]),
    (
        "candidatesource",
        ["linkedin", "pracuj", "jjit", "referral", "database", "manual"],
    ),
    ("clientstatus", ["active", "inactive", "prospect"]),
    (
        "knowledgecategory",
        ["selling_points", "interview_questions", "tech_stack", "culture", "general"],
    ),
    ("contracttype", ["b2b", "uop", "uzlecenie"]),
    ("contractstatus", ["draft", "active", "ending", "ended"]),
    (
        "emailcategory",
        [
            "application_received",
            "screening_invite",
            "interview_invite",
            "rejection",
            "offer",
            "general",
        ],
    ),
    ("remotepolicy", ["onsite", "hybrid", "remote"]),
    ("jobstatus", ["draft", "published", "closed"]),
    ("jobpriority", ["low", "medium", "high", "urgent"]),
    ("recruitmenttype", ["body_leasing", "sales_project", "tender"]),
    (
        "portal",
        ["pracuj_pl", "justjoinit", "linkedin", "nofluffjobs", "bulldogjob"],
    ),
    ("postingstatus", ["draft", "published", "expired", "removed"]),
    ("notetype", ["call", "meeting", "email", "general", "interview"]),
    (
        "notificationtype",
        [
            "contract_ending",
            "interview_scheduled",
            "candidate_added",
            "stage_changed",
            "new_application",
        ],
    ),
    (
        "pipelinestage",
        [
            "new",
            "prep_call",
            "screening",
            "interview",
            "cv_sent",
            "client_interview",
            "acceptance",
            "negotiation",
            "onboarding",
            "hired",
            "rejected",
            "withdrawn",
        ],
    ),
    (
        "salesstage",
        ["lead", "qualification", "proposal", "negotiation", "won", "lost"],
    ),
    ("screeningtype", ["initial_screening", "prep_call", "follow_up"]),
    (
        "motivationtype",
        [
            "money",
            "growth",
            "project",
            "team",
            "work_mode",
            "stability",
            "technology",
            "location",
        ],
    ),
    ("counterofferrisk", ["low", "medium", "high"]),
    ("calldirection", ["inbound", "outbound"]),
    ("callstatus", ["completed", "missed", "voicemail", "failed"]),
    ("eventtype", ["interview", "screening", "prep_call", "meeting", "deadline"]),
    ("eventstatus", ["scheduled", "completed", "cancelled"]),
    (
        "useractiontype",
        [
            "candidate_added",
            "stage_changed",
            "call_made",
            "screening_done",
            "interview_scheduled",
            "placement_closed",
            "note_added",
            "cv_uploaded",
        ],
    ),
]


def _create_enum_sql(name: str, values: list[str]) -> str:
    vals = ", ".join(f"'{v}'" for v in values)
    return (
        "DO $$ BEGIN "
        f"CREATE TYPE {name} AS ENUM ({vals}); "
        "EXCEPTION WHEN duplicate_object THEN null; "
        "END $$;"
    )


def upgrade() -> None:
    # ── alembic_version column widening ─────────────────────────────────
    # Alembic 1.14 creates `alembic_version.version_num` as VARCHAR(32),
    # but several later revisions use IDs longer than 32 chars (e.g.
    # ``0031_champion_profile_notification_type`` = 39 chars). On a fresh
    # DB those revisions fail to record completion. Prod was bootstrapped
    # with a wider column; reproduce that here so the chain runs end-to-end.
    # Idempotent: PG ALTER COLUMN TYPE to a wider VARCHAR is a no-op when the
    # column is already at least that wide.
    op.execute(
        "ALTER TABLE alembic_version "
        "ALTER COLUMN version_num TYPE VARCHAR(255)"
    )

    # ── Enum types ──────────────────────────────────────────────────────
    for name, values in _ENUMS:
        op.execute(_create_enum_sql(name, values))

    # ── users ───────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id              SERIAL PRIMARY KEY,
            email           VARCHAR(255) NOT NULL UNIQUE,
            password_hash   VARCHAR(255) NOT NULL,
            name            VARCHAR(255) NOT NULL,
            role            userrole NOT NULL DEFAULT 'recruiter',
            recruiter_role  recruiterrole,
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_id ON users (id)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)")

    # ── clients ─────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS clients (
            id              SERIAL PRIMARY KEY,
            name            VARCHAR(255) NOT NULL,
            industry        VARCHAR(100),
            website         VARCHAR(500),
            address         VARCHAR(500),
            contact_person  VARCHAR(255),
            contact_email   VARCHAR(255),
            contact_phone   VARCHAR(30),
            status          clientstatus NOT NULL DEFAULT 'prospect',
            nda_signed      BOOLEAN DEFAULT FALSE,
            contract_type   VARCHAR(100),
            notes           TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_clients_id ON clients (id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_clients_name ON clients (name)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_clients_status ON clients (status)")

    # ── candidates ──────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS candidates (
            id                    SERIAL PRIMARY KEY,
            name                  VARCHAR(100) NOT NULL,
            lastname              VARCHAR(100) NOT NULL,
            email                 VARCHAR(255) UNIQUE,
            phone                 VARCHAR(30),
            location              VARCHAR(255),
            linkedin              VARCHAR(500),
            avatar_url            VARCHAR(1000),
            salary_expectation    INTEGER,
            salary_currency       VARCHAR(3) DEFAULT 'PLN',
            availability_date     DATE,
            notice_period         INTEGER,
            source                VARCHAR(100),
            source_enum           candidatesource,
            competence_category   VARCHAR(100),
            ai_summary            TEXT,
            status                candidatestatus NOT NULL DEFAULT 'active',
            tags                  JSONB DEFAULT '[]'::jsonb,
            skills                JSONB DEFAULT '[]'::jsonb,
            experience            JSONB DEFAULT '[]'::jsonb,
            education             JSONB DEFAULT '[]'::jsonb,
            languages             JSONB DEFAULT '[]'::jsonb,
            raw_cv_text           TEXT,
            cv_filename           VARCHAR(500),
            cv_parsed_at          TIMESTAMPTZ,
            notes_count           INTEGER NOT NULL DEFAULT 0,
            last_contacted_at     TIMESTAMPTZ,
            embedding_id          VARCHAR(100),
            created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_candidates_id ON candidates (id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_candidates_name ON candidates (name)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidates_lastname ON candidates (lastname)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_candidates_email ON candidates (email)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_candidates_source ON candidates (source)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidates_competence_category "
        "ON candidates (competence_category)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_candidates_status ON candidates (status)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidates_embedding_id "
        "ON candidates (embedding_id)"
    )

    # ── jobs ────────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id                SERIAL PRIMARY KEY,
            title             VARCHAR(255) NOT NULL,
            description       TEXT,
            requirements      TEXT,
            location          VARCHAR(255),
            salary_min        INTEGER,
            salary_max        INTEGER,
            remote_policy     remotepolicy NOT NULL DEFAULT 'hybrid',
            status            jobstatus NOT NULL DEFAULT 'draft',
            priority          jobpriority NOT NULL DEFAULT 'medium',
            recruitment_type  recruitmenttype NOT NULL DEFAULT 'body_leasing',
            deadline          DATE,
            portals           JSONB DEFAULT '{}'::jsonb,
            client_id         INTEGER REFERENCES clients(id),
            recruiter_id      INTEGER REFERENCES users(id),
            created_by        INTEGER REFERENCES users(id),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_jobs_id ON jobs (id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_jobs_title ON jobs (title)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs (status)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_recruitment_type "
        "ON jobs (recruitment_type)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_jobs_client_id ON jobs (client_id)")

    # ── contacts ────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS contacts (
            id                  SERIAL PRIMARY KEY,
            client_id           INTEGER NOT NULL REFERENCES clients(id),
            name                VARCHAR(255) NOT NULL,
            email               VARCHAR(255),
            phone               VARCHAR(50),
            position            VARCHAR(255),
            department          VARCHAR(255),
            is_decision_maker   BOOLEAN DEFAULT FALSE,
            notes               TEXT,
            last_contacted_at   TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_contacts_id ON contacts (id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_contacts_client_id ON contacts (client_id)")

    # ── client_knowledge ────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS client_knowledge (
            id          SERIAL PRIMARY KEY,
            client_id   INTEGER NOT NULL REFERENCES clients(id),
            category    knowledgecategory NOT NULL,
            content     TEXT NOT NULL,
            added_by    INTEGER REFERENCES users(id),
            source      VARCHAR(255),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_knowledge_id ON client_knowledge (id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_knowledge_client_id "
        "ON client_knowledge (client_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_knowledge_category "
        "ON client_knowledge (category)"
    )

    # ── contracts ───────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS contracts (
            id              SERIAL PRIMARY KEY,
            candidate_id    INTEGER NOT NULL REFERENCES candidates(id),
            client_id       INTEGER NOT NULL REFERENCES clients(id),
            job_id          INTEGER REFERENCES jobs(id),
            start_date      DATE NOT NULL,
            end_date        DATE,
            rate_candidate  INTEGER,
            rate_client     INTEGER,
            currency        VARCHAR(3) DEFAULT 'PLN',
            margin          INTEGER,
            contract_type   contracttype NOT NULL DEFAULT 'b2b',
            status          contractstatus NOT NULL DEFAULT 'draft',
            documents       JSONB DEFAULT '[]'::jsonb,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_contracts_id ON contracts (id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contracts_candidate_id "
        "ON contracts (candidate_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contracts_client_id ON contracts (client_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_contracts_job_id ON contracts (job_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_contracts_status ON contracts (status)")

    # ── email_templates ─────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS email_templates (
            id          SERIAL PRIMARY KEY,
            name        VARCHAR(200) NOT NULL,
            subject     VARCHAR(500) NOT NULL,
            body        TEXT NOT NULL,
            category    emailcategory NOT NULL DEFAULT 'general',
            created_by  INTEGER REFERENCES users(id),
            is_default  BOOLEAN NOT NULL DEFAULT FALSE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_email_templates_id ON email_templates (id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_email_templates_category "
        "ON email_templates (category)"
    )

    # ── job_postings ────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS job_postings (
            id            SERIAL PRIMARY KEY,
            job_id        INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            portal        portal NOT NULL,
            external_id   VARCHAR(255),
            status        postingstatus NOT NULL DEFAULT 'draft',
            published_at  TIMESTAMPTZ,
            expires_at    TIMESTAMPTZ,
            url           VARCHAR(1024),
            views         INTEGER NOT NULL DEFAULT 0,
            applications  INTEGER NOT NULL DEFAULT 0,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_job_postings_id ON job_postings (id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_postings_job_id ON job_postings (job_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_postings_status ON job_postings (status)"
    )

    # ── notes ───────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS notes (
            id            SERIAL PRIMARY KEY,
            content       TEXT NOT NULL,
            note_type     notetype NOT NULL DEFAULT 'general',
            candidate_id  INTEGER REFERENCES candidates(id),
            job_id        INTEGER REFERENCES jobs(id),
            author_id     INTEGER REFERENCES users(id),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_notes_id ON notes (id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notes_candidate_id ON notes (candidate_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_notes_job_id ON notes (job_id)")

    # ── notifications ───────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id                 SERIAL PRIMARY KEY,
            user_id            INTEGER NOT NULL REFERENCES users(id),
            title              VARCHAR(255) NOT NULL,
            message            TEXT NOT NULL,
            link               VARCHAR(1000),
            notification_type  notificationtype NOT NULL,
            is_read            BOOLEAN NOT NULL DEFAULT FALSE,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_notifications_id ON notifications (id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notifications_user_id "
        "ON notifications (user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notifications_notification_type "
        "ON notifications (notification_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notifications_is_read "
        "ON notifications (is_read)"
    )

    # ── candidate_stages ────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_stages (
            id            SERIAL PRIMARY KEY,
            candidate_id  INTEGER NOT NULL REFERENCES candidates(id),
            job_id        INTEGER NOT NULL REFERENCES jobs(id),
            stage         pipelinestage NOT NULL DEFAULT 'new',
            moved_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            moved_by      INTEGER REFERENCES users(id),
            notes         TEXT,
            rating        INTEGER,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_stages_id ON candidate_stages (id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_stages_candidate_id "
        "ON candidate_stages (candidate_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_stages_job_id "
        "ON candidate_stages (job_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_stages_stage "
        "ON candidate_stages (stage)"
    )

    # ── screening_notes ─────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS screening_notes (
            id                    SERIAL PRIMARY KEY,
            candidate_id          INTEGER NOT NULL REFERENCES candidates(id),
            job_id                INTEGER REFERENCES jobs(id),
            author_id             INTEGER NOT NULL REFERENCES users(id),
            screening_type        screeningtype NOT NULL DEFAULT 'initial_screening',
            motivation_primary    motivationtype,
            motivation_secondary  motivationtype,
            salary_expectation    INTEGER,
            salary_currency       VARCHAR(10) DEFAULT 'PLN',
            salary_negotiable     BOOLEAN DEFAULT FALSE,
            verified_skills       JSONB DEFAULT '[]'::jsonb,
            red_flags             TEXT,
            personality_notes     TEXT,
            readiness_to_change   INTEGER,
            counteroffer_risk     counterofferrisk,
            closing_strategy      TEXT,
            overall_impression    INTEGER,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_screening_notes_id ON screening_notes (id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_screening_notes_candidate_id "
        "ON screening_notes (candidate_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_screening_notes_job_id "
        "ON screening_notes (job_id)"
    )

    # ── calls ───────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS calls (
            id                  SERIAL PRIMARY KEY,
            candidate_id        INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
            user_id             INTEGER REFERENCES users(id) ON DELETE SET NULL,
            direction           calldirection NOT NULL DEFAULT 'outbound',
            duration_seconds    INTEGER,
            status              callstatus NOT NULL DEFAULT 'completed',
            transcript          TEXT,
            summary             TEXT,
            recording_url       VARCHAR(1000),
            cloudtalk_call_id   VARCHAR(255) UNIQUE,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_calls_id ON calls (id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_calls_candidate_id ON calls (candidate_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_calls_user_id ON calls (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_calls_status ON calls (status)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_calls_cloudtalk_call_id "
        "ON calls (cloudtalk_call_id)"
    )

    # ── calendar_events ─────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS calendar_events (
            id                SERIAL PRIMARY KEY,
            title             VARCHAR(255) NOT NULL,
            description       TEXT,
            event_type        eventtype NOT NULL DEFAULT 'meeting',
            start_time        TIMESTAMPTZ NOT NULL,
            end_time          TIMESTAMPTZ,
            all_day           BOOLEAN NOT NULL DEFAULT FALSE,
            candidate_id      INTEGER REFERENCES candidates(id),
            job_id            INTEGER REFERENCES jobs(id),
            client_id         INTEGER REFERENCES clients(id),
            attendees         JSONB DEFAULT '[]'::jsonb,
            location          VARCHAR(500),
            teams_link        VARCHAR(1000),
            created_by        INTEGER REFERENCES users(id),
            reminder_minutes  INTEGER NOT NULL DEFAULT 15,
            status            eventstatus NOT NULL DEFAULT 'scheduled',
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_calendar_events_id ON calendar_events (id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_calendar_events_start_time "
        "ON calendar_events (start_time)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_calendar_events_candidate_id "
        "ON calendar_events (candidate_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_calendar_events_job_id "
        "ON calendar_events (job_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_calendar_events_client_id "
        "ON calendar_events (client_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_calendar_events_status "
        "ON calendar_events (status)"
    )

    # ── sales_opportunities ─────────────────────────────────────────────
    # Created here for fidelity with the 2026-03-18 schema; 0003 drops it.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sales_opportunities (
            id                   SERIAL PRIMARY KEY,
            client_id            INTEGER NOT NULL REFERENCES clients(id),
            contact_person       VARCHAR(255),
            title                VARCHAR(255) NOT NULL,
            description          TEXT,
            stage                salesstage NOT NULL DEFAULT 'lead',
            value                NUMERIC(12, 2),
            currency             VARCHAR(10) NOT NULL DEFAULT 'PLN',
            probability          INTEGER NOT NULL DEFAULT 50,
            expected_close_date  DATE,
            assigned_to          INTEGER REFERENCES users(id),
            lost_reason          TEXT,
            converted_job_id     INTEGER REFERENCES jobs(id),
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sales_opportunities_id "
        "ON sales_opportunities (id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sales_opportunities_client_id "
        "ON sales_opportunities (client_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sales_opportunities_stage "
        "ON sales_opportunities (stage)"
    )

    # ── talent_pools ────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS talent_pools (
            id          SERIAL PRIMARY KEY,
            name        VARCHAR(255) NOT NULL,
            description TEXT,
            criteria    JSONB DEFAULT '{}'::jsonb,
            created_by  INTEGER REFERENCES users(id),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_talent_pools_id ON talent_pools (id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_talent_pools_name ON talent_pools (name)")

    # ── talent_pool_memberships ─────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS talent_pool_memberships (
            id              SERIAL PRIMARY KEY,
            talent_pool_id  INTEGER NOT NULL REFERENCES talent_pools(id),
            candidate_id    INTEGER NOT NULL REFERENCES candidates(id),
            added_by        INTEGER REFERENCES users(id),
            added_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_pool_candidate UNIQUE (talent_pool_id, candidate_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_talent_pool_memberships_id "
        "ON talent_pool_memberships (id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_talent_pool_memberships_talent_pool_id "
        "ON talent_pool_memberships (talent_pool_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_talent_pool_memberships_candidate_id "
        "ON talent_pool_memberships (candidate_id)"
    )

    # ── activities ──────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS activities (
            id           SERIAL PRIMARY KEY,
            entity_type  VARCHAR(50) NOT NULL,
            entity_id    INTEGER NOT NULL,
            action       VARCHAR(100) NOT NULL,
            details      JSONB DEFAULT '{}'::jsonb,
            user_id      INTEGER REFERENCES users(id),
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_activities_id ON activities (id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_activities_entity_type "
        "ON activities (entity_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_activities_entity_id ON activities (entity_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_activities_user_id ON activities (user_id)"
    )

    # ── user_activities ─────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_activities (
            id           SERIAL PRIMARY KEY,
            user_id      INTEGER NOT NULL REFERENCES users(id),
            action_type  useractiontype NOT NULL,
            entity_type  VARCHAR(50) NOT NULL,
            entity_id    INTEGER NOT NULL,
            details      JSONB DEFAULT '{}'::jsonb,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_activities_id ON user_activities (id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_activities_user_id "
        "ON user_activities (user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_activities_action_type "
        "ON user_activities (action_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_activities_entity_type "
        "ON user_activities (entity_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_activities_entity_id "
        "ON user_activities (entity_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_activities_created_at "
        "ON user_activities (created_at)"
    )


def downgrade() -> None:
    # Drop in reverse dependency order. Use IF EXISTS for idempotency.
    op.execute("DROP TABLE IF EXISTS user_activities CASCADE")
    op.execute("DROP TABLE IF EXISTS activities CASCADE")
    op.execute("DROP TABLE IF EXISTS talent_pool_memberships CASCADE")
    op.execute("DROP TABLE IF EXISTS talent_pools CASCADE")
    op.execute("DROP TABLE IF EXISTS sales_opportunities CASCADE")
    op.execute("DROP TABLE IF EXISTS calendar_events CASCADE")
    op.execute("DROP TABLE IF EXISTS calls CASCADE")
    op.execute("DROP TABLE IF EXISTS screening_notes CASCADE")
    op.execute("DROP TABLE IF EXISTS candidate_stages CASCADE")
    op.execute("DROP TABLE IF EXISTS notifications CASCADE")
    op.execute("DROP TABLE IF EXISTS notes CASCADE")
    op.execute("DROP TABLE IF EXISTS job_postings CASCADE")
    op.execute("DROP TABLE IF EXISTS email_templates CASCADE")
    op.execute("DROP TABLE IF EXISTS contracts CASCADE")
    op.execute("DROP TABLE IF EXISTS client_knowledge CASCADE")
    op.execute("DROP TABLE IF EXISTS contacts CASCADE")
    op.execute("DROP TABLE IF EXISTS jobs CASCADE")
    op.execute("DROP TABLE IF EXISTS candidates CASCADE")
    op.execute("DROP TABLE IF EXISTS clients CASCADE")
    op.execute("DROP TABLE IF EXISTS users CASCADE")

    for name, _ in reversed(_ENUMS):
        op.execute(f"DROP TYPE IF EXISTS {name} CASCADE")
