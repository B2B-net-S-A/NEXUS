"""Akademia (Akademia Rekrutera i kolejne programy) — szybki przepływ naboru.

Revision ID: 0369_academy
Revises: 0368_contract_termination_reversal

Decyzje Artura 23–24.09.2026: nabór do akademii to OSOBNY, krótki przepływ,
nie rekrutacja pod klienta — ogłoszenia → sortowanie Luny → dwuminutowy
telefon (warunki z ogłoszenia + zapis na termin w biurze) → spotkanie
w biurze → zadanie → umowa → start z edycją 1. dnia miesiąca.

Tabele:

- ``academy_programs`` — program (np. „Akademia Rekrutera") z kryteriami
  sortowania i pytaniami na telefon.
- ``academy_program_sources`` — ogłoszenia (rekrutacje z NEXUSA/Traffita),
  z których ludzie wpadają sami; ``since`` odcina historię sprzed naboru.
- ``academy_sessions`` — terminy spotkań w biurze z limitem miejsc.
- ``academy_applications`` — jedna osoba w jednym programie (UNIQUE), więc
  odrzucenie („nie” klika człowiek) jest PAMIĘCIĄ na zawsze: kolejna
  aplikacja tej osoby nie wraca do kolejki telefonów, tylko stempluje
  ``reapplied_at``.

Kandydat CASCADE — twarde usunięcie osoby (art. 17 RODO) zabiera też jej
ślady w akademii, w tym cytaty z CV w ``screening``.

Lustro w ``entrypoint.sh`` (alembic na prodzie bywa osierocony) — pilnuje
``tests/test_academy_migration_mirror.py``.
"""

from alembic import op

revision = "0369_academy"
down_revision = "0368_contract_termination_reversal"
branch_labels = None
depends_on = None

APPLICATION_STATUSES = (
    "new",
    "to_call",
    "scheduled",
    "task_given",
    "task_passed",
    "contract_sent",
    "signed",
    "rejected",
    "withdrew",
)

CREATE_PROGRAMS = """CREATE TABLE IF NOT EXISTS academy_programs (
        id SERIAL PRIMARY KEY,
        name VARCHAR(200) NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT true,
        max_experience_years INTEGER NOT NULL DEFAULT 6,
        require_polish BOOLEAN NOT NULL DEFAULT true,
        luna_enabled BOOLEAN NOT NULL DEFAULT true,
        conditions JSONB NOT NULL DEFAULT '[]'::jsonb,
        session_capacity INTEGER NOT NULL DEFAULT 8,
        task_due_days INTEGER NOT NULL DEFAULT 5,
        created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ck_academy_programs_experience
            CHECK (max_experience_years BETWEEN 0 AND 40),
        CONSTRAINT ck_academy_programs_capacity
            CHECK (session_capacity BETWEEN 1 AND 200),
        CONSTRAINT ck_academy_programs_task_days
            CHECK (task_due_days BETWEEN 1 AND 60)
    )"""

CREATE_SOURCES = """CREATE TABLE IF NOT EXISTS academy_program_sources (
        program_id INTEGER NOT NULL REFERENCES academy_programs(id) ON DELETE CASCADE,
        job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        since DATE NULL,
        added_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (program_id, job_id)
    )"""

CREATE_SESSIONS = """CREATE TABLE IF NOT EXISTS academy_sessions (
        id SERIAL PRIMARY KEY,
        program_id INTEGER NOT NULL REFERENCES academy_programs(id) ON DELETE CASCADE,
        starts_at TIMESTAMPTZ NOT NULL,
        location VARCHAR(255) NULL,
        capacity INTEGER NOT NULL DEFAULT 8,
        cancelled_at TIMESTAMPTZ NULL,
        created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ck_academy_sessions_capacity CHECK (capacity BETWEEN 1 AND 200)
    )"""

INDEX_SESSIONS = (
    "CREATE INDEX IF NOT EXISTS ix_academy_sessions_program_starts "
    "ON academy_sessions (program_id, starts_at)"
)

CREATE_APPLICATIONS = """CREATE TABLE IF NOT EXISTS academy_applications (
        id BIGSERIAL PRIMARY KEY,
        program_id INTEGER NOT NULL REFERENCES academy_programs(id) ON DELETE CASCADE,
        candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
        source_job_id INTEGER NULL REFERENCES jobs(id) ON DELETE SET NULL,
        applied_at TIMESTAMPTZ NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'new',
        screening_verdict VARCHAR(10) NULL,
        screening JSONB NULL,
        screened_at TIMESTAMPTZ NULL,
        experience_years NUMERIC(4, 1) NULL,
        call_attempts INTEGER NOT NULL DEFAULT 0,
        last_call_at TIMESTAMPTZ NULL,
        session_id INTEGER NULL REFERENCES academy_sessions(id) ON DELETE SET NULL,
        attended BOOLEAN NULL,
        task_due DATE NULL,
        task_result VARCHAR(10) NULL,
        contract_sent_at TIMESTAMPTZ NULL,
        signed_at TIMESTAMPTZ NULL,
        cohort_month DATE NULL,
        closed_stage VARCHAR(20) NULL,
        closed_reason VARCHAR(500) NULL,
        closed_at TIMESTAMPTZ NULL,
        closed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        reapplied_at TIMESTAMPTZ NULL,
        note VARCHAR(2000) NULL,
        updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_academy_applications_program_candidate
            UNIQUE (program_id, candidate_id),
        CONSTRAINT ck_academy_applications_status CHECK (
            status IN ('new', 'to_call', 'scheduled', 'task_given', 'task_passed', 'contract_sent', 'signed', 'rejected', 'withdrew')
        ),
        CONSTRAINT ck_academy_applications_verdict CHECK (
            screening_verdict IS NULL OR screening_verdict IN ('call', 'review', 'skip')
        ),
        CONSTRAINT ck_academy_applications_task_result CHECK (
            task_result IS NULL OR task_result IN ('passed', 'failed')
        ),
        CONSTRAINT ck_academy_applications_rejected_reason CHECK (
            status <> 'rejected' OR closed_reason IS NOT NULL
        )
    )"""

INDEX_APPLICATIONS_STATUS = (
    "CREATE INDEX IF NOT EXISTS ix_academy_applications_program_status "
    "ON academy_applications (program_id, status)"
)
INDEX_APPLICATIONS_CANDIDATE = (
    "CREATE INDEX IF NOT EXISTS ix_academy_applications_candidate "
    "ON academy_applications (candidate_id)"
)
INDEX_APPLICATIONS_SESSION = (
    "CREATE INDEX IF NOT EXISTS ix_academy_applications_session "
    "ON academy_applications (session_id)"
)

ENUM_AI_FEATURE = "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'academy_screening'"
SEED_AI_FEATURE = (
    "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
    "SELECT 'academy_screening', TRUE, 0, NOW(), NOW() "
    "WHERE NOT EXISTS "
    "(SELECT 1 FROM ai_features WHERE feature = 'academy_screening')"
)

DDL_STATEMENTS = (
    CREATE_PROGRAMS,
    CREATE_SOURCES,
    CREATE_SESSIONS,
    INDEX_SESSIONS,
    CREATE_APPLICATIONS,
    INDEX_APPLICATIONS_STATUS,
    INDEX_APPLICATIONS_CANDIDATE,
    INDEX_APPLICATIONS_SESSION,
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(ENUM_AI_FEATURE)
    op.execute(SEED_AI_FEATURE)
    for statement in DDL_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS academy_applications")
    op.execute("DROP TABLE IF EXISTS academy_sessions")
    op.execute("DROP TABLE IF EXISTS academy_program_sources")
    op.execute("DROP TABLE IF EXISTS academy_programs")
    op.execute("DELETE FROM ai_features WHERE feature = 'academy_screening'")
