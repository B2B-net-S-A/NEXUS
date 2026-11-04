"""DDL „Champion po ludzku” — JEDNO źródło dla migracji 0403 i ``entrypoint.sh``.

Produkcyjny alembic bywa osierocony, więc siatka w ``entrypoint.sh`` jest
wdrożeniem równorzędnym z migracją. Obie strony importują listy stąd, żeby
dwie ręczne kopie ``CREATE TABLE`` nie rozjechały się przy pierwszej poprawce.
Wartość enumu AI (``plain_knowledge_research``) i jej wiersz w ``ai_features``
stoją w entrypoincie literalnie — pilnuje ich ``test_ai_feature_enum_entrypoint_mirror``.
"""

from __future__ import annotations

TABLE_DDL: list[str] = [
    """CREATE TABLE IF NOT EXISTS plain_terms (
           id SERIAL PRIMARY KEY,
           term_key VARCHAR(200) NOT NULL,
           display_name VARCHAR(200) NOT NULL,
           summary TEXT,
           does TEXT,
           cv_hints JSONB,
           confused_with TEXT,
           sources JSONB,
           origin VARCHAR(10) NOT NULL DEFAULT 'seed',
           status VARCHAR(12) NOT NULL DEFAULT 'ready',
           claimed_at TIMESTAMPTZ,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
           CONSTRAINT uq_plain_terms_term_key UNIQUE (term_key),
           CONSTRAINT ck_plain_terms_origin CHECK (origin IN ('seed','ai','manual')),
           CONSTRAINT ck_plain_terms_status
               CHECK (status IN ('ready','researching','failed'))
       )""",
    """CREATE TABLE IF NOT EXISTS role_profiles (
           id SERIAL PRIMARY KEY,
           slug VARCHAR(120) NOT NULL,
           name VARCHAR(200) NOT NULL,
           summary TEXT,
           example TEXT,
           day_to_day JSONB,
           candidate_questions JSONB,
           typical_skills JSONB,
           match_rules JSONB,
           sources JSONB,
           origin VARCHAR(10) NOT NULL DEFAULT 'seed',
           status VARCHAR(12) NOT NULL DEFAULT 'ready',
           claimed_at TIMESTAMPTZ,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
           CONSTRAINT uq_role_profiles_slug UNIQUE (slug),
           CONSTRAINT ck_role_profiles_origin CHECK (origin IN ('seed','ai','manual')),
           CONSTRAINT ck_role_profiles_status
               CHECK (status IN ('ready','researching','failed'))
       )""",
    """CREATE TABLE IF NOT EXISTS job_plain_briefs (
           job_id INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
           status VARCHAR(10) NOT NULL DEFAULT 'none',
           inputs_hash VARCHAR(64),
           generated_at TIMESTAMPTZ,
           model VARCHAR(80),
           one_liner TEXT,
           example TEXT,
           day_to_day JSONB,
           pitch TEXT,
           candidate_qa JSONB,
           screening_plain JSONB,
           term_notes JSONB,
           message TEXT,
           updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           CONSTRAINT ck_job_plain_briefs_status
               CHECK (status IN ('none','ready','failed'))
       )""",
    """CREATE TABLE IF NOT EXISTS plain_knowledge_events (
           id SERIAL PRIMARY KEY,
           entity_type VARCHAR(10) NOT NULL,
           entity_id INTEGER NOT NULL,
           action VARCHAR(20) NOT NULL,
           changes JSONB,
           user_id INTEGER,
           user_name VARCHAR(200),
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           CONSTRAINT ck_plain_knowledge_events_type
               CHECK (entity_type IN ('term','role'))
       )""",
    "CREATE INDEX IF NOT EXISTS ix_plain_knowledge_events_entity_id "
    "ON plain_knowledge_events (entity_id)",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS role_profile_id INTEGER "
    "REFERENCES role_profiles(id) ON DELETE SET NULL",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS role_profile_source VARCHAR(10)",
    "CREATE INDEX IF NOT EXISTS ix_jobs_role_profile_id ON jobs (role_profile_id)",
    "ALTER TABLE client_playbooks "
    "ADD COLUMN IF NOT EXISTS about_for_candidate_origin VARCHAR(10)",
    "ALTER TABLE client_playbooks "
    "ADD COLUMN IF NOT EXISTS about_for_candidate_sources JSONB",
]

DROP_DDL: list[str] = [
    "ALTER TABLE client_playbooks DROP COLUMN IF EXISTS about_for_candidate_sources",
    "ALTER TABLE client_playbooks DROP COLUMN IF EXISTS about_for_candidate_origin",
    "DROP INDEX IF EXISTS ix_jobs_role_profile_id",
    "ALTER TABLE jobs DROP COLUMN IF EXISTS role_profile_source",
    "ALTER TABLE jobs DROP COLUMN IF EXISTS role_profile_id",
    "DROP TABLE IF EXISTS plain_knowledge_events",
    "DROP TABLE IF EXISTS job_plain_briefs",
    "DROP TABLE IF EXISTS role_profiles",
    "DROP TABLE IF EXISTS plain_terms",
]
