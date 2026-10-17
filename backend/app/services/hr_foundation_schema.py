"""„Ludzie w NEXUSIE” — fundament modułu kadrowego: SQL migracji i lustra.

JEDNO źródło instrukcji dla ``alembic/versions/0452_hr_foundation.py``
i ``entrypoint.sh`` (przez ``hr_schema_bundle``; alembic na produkcji bywa
osierocony, więc entrypoint jest wdrożeniem schematu).

Tabele:

* ``employee_profiles`` — kartoteka pracownika 1:1 z kontem (przełożony,
  forma zatrudnienia, status, daty, domyślne miejsce pracy, obowiązek
  timesheetu). Konsultanci B2B u klientów NIE mają tu wierszy — ich świat to
  kontrakty i zamówienia.
* ``leave_entitlements`` — pula urlopowa per osoba i rok (przeniesienie jawne
  w wierszu kolejnego roku; Compass nie przenosił niczego sam).
* ``company_days_off`` — dni wolne firmy poza świętami ustawowymi
  (te liczy biblioteka ``holidays`` w ``app/core/scheduling.py``).
* ``hr_audit_events`` — ślad zmian z poziomem wrażliwości (zdrowie, płace);
  ``critical_events`` dostaje tylko zdanie bez kwot.
* ``hr_job_runs`` — rezerwacje zadań okresowych (restart przy nocnym
  wdrożeniu nie powtarza wysyłki ani zamknięcia miesiąca).
* ``hr_import_batches`` / ``hr_import_id_map`` — import z Compassa:
  na sucho → raport (same liczby) → zapis; mapa id czyni import idempotentnym.
* ``hr_import_uploads`` — paczka wgrana z ekranu „Import z Compassa”: surowy
  plik leży tu najwyżej do zapisu albo 24 h (potem ``bundle`` = NULL, zostają
  SHA-256 i liczby); ``batch_ids`` wskazuje partie modułów z przebiegu na sucho.

Przełączniki modułów: ``app_settings['hr_modules']`` (domyślnie wszystko
wyłączone; admin włącza przy przełączeniu, bez wdrożenia).
"""

from __future__ import annotations

HR_MODULES_SETTING = "hr_modules"
HR_MODULE_KEYS: tuple[str, ...] = (
    "people",
    "leave",
    "time",
    "payroll",
    "lifecycle",
    "care",
    "cases",
    "equipment",
)

EMPLOYMENT_TYPES: tuple[str, ...] = ("uop", "b2b", "zlecenie")
EMPLOYMENT_STATUSES: tuple[str, ...] = (
    "pending",
    "onboarding",
    "active",
    "offboarding",
    "exited",
)
LOCATIONS: tuple[str, ...] = ("onsite", "remote")
DAY_OFF_KINDS: tuple[str, ...] = ("company", "bridge")
SENSITIVITIES: tuple[str, ...] = ("general", "health", "payroll")
JOB_RUN_STATUSES: tuple[str, ...] = ("claimed", "done", "skipped", "failed")
IMPORT_STATUSES: tuple[str, ...] = ("uploaded", "dry_run", "applied", "failed")
IMPORT_DECISIONS: tuple[str, ...] = ("auto", "manual", "skipped")
UPLOAD_STATUSES: tuple[str, ...] = ("dry_run", "applied", "expired", "superseded")


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


CK_EMPLOYMENT_TYPE = f"employment_type IN ({quoted(EMPLOYMENT_TYPES)})"
CK_EMPLOYMENT_STATUS = f"employment_status IN ({quoted(EMPLOYMENT_STATUSES)})"
CK_LOCATION = f"default_location IN ({quoted(LOCATIONS)})"
CK_NO_SELF_MANAGER = "manager_user_id IS NULL OR manager_user_id <> user_id"
CK_ENTITLEMENT_YEAR = "year BETWEEN 2020 AND 2100"
CK_ENTITLEMENT_DAYS = (
    "entitlement_days IS NULL OR (entitlement_days >= 0 AND entitlement_days <= 366)"
)
CK_CARRIED_DAYS = "carried_over_days >= 0 AND carried_over_days <= 366"
CK_USED_INITIAL_DAYS = "used_initial_days >= 0 AND used_initial_days <= 366"
CK_DAY_OFF_KIND = f"kind IN ({quoted(DAY_OFF_KINDS)})"
CK_SENSITIVITY = f"sensitivity IN ({quoted(SENSITIVITIES)})"
CK_JOB_RUN_STATUS = f"status IN ({quoted(JOB_RUN_STATUSES)})"
CK_IMPORT_MODULE = f"module IN ({quoted(('profiles', *HR_MODULE_KEYS))})"
CK_IMPORT_STATUS = f"status IN ({quoted(IMPORT_STATUSES)})"
CK_IMPORT_DECISION = f"decision IN ({quoted(IMPORT_DECISIONS)})"
CK_UPLOAD_STATUS = f"status IN ({quoted(UPLOAD_STATUSES)})"
# Surowa paczka (dane osobowe) żyje tylko w partii czekającej na zapis.
CK_UPLOAD_BUNDLE = "status = 'dry_run' OR bundle IS NULL"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS employee_profiles (
    id SERIAL PRIMARY KEY,
    public_id UUID NOT NULL DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    manager_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    employment_type VARCHAR(16) NOT NULL DEFAULT 'b2b',
    employment_status VARCHAR(16) NOT NULL DEFAULT 'active',
    hired_on DATE NULL,
    work_start_date DATE NULL,
    last_working_day DATE NULL,
    exited_at TIMESTAMPTZ NULL,
    default_location VARCHAR(16) NOT NULL DEFAULT 'onsite',
    timesheet_required BOOLEAN NOT NULL DEFAULT TRUE,
    can_log_overtime BOOLEAN NOT NULL DEFAULT FALSE,
    job_title VARCHAR(200) NULL,
    department VARCHAR(200) NULL,
    phone VARCHAR(64) NULL,
    m365_synced_at TIMESTAMPTZ NULL,
    compass_profile_id UUID NULL,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_employee_profiles_user UNIQUE (user_id),
    CONSTRAINT uq_employee_profiles_public_id UNIQUE (public_id),
    CONSTRAINT uq_employee_profiles_compass UNIQUE (compass_profile_id),
    CONSTRAINT ck_employee_profiles_type CHECK ({CK_EMPLOYMENT_TYPE}),
    CONSTRAINT ck_employee_profiles_status CHECK ({CK_EMPLOYMENT_STATUS}),
    CONSTRAINT ck_employee_profiles_location CHECK ({CK_LOCATION}),
    CONSTRAINT ck_employee_profiles_no_self_manager CHECK ({CK_NO_SELF_MANAGER})
)""",
    f"""CREATE TABLE IF NOT EXISTS leave_entitlements (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    year SMALLINT NOT NULL,
    entitlement_days NUMERIC(5,1) NULL,
    carried_over_days NUMERIC(5,1) NOT NULL DEFAULT 0,
    used_initial_days NUMERIC(5,1) NOT NULL DEFAULT 0,
    reason TEXT NULL,
    set_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_leave_entitlements_user_year UNIQUE (user_id, year),
    CONSTRAINT ck_leave_entitlements_year CHECK ({CK_ENTITLEMENT_YEAR}),
    CONSTRAINT ck_leave_entitlements_days CHECK ({CK_ENTITLEMENT_DAYS}),
    CONSTRAINT ck_leave_entitlements_carried CHECK ({CK_CARRIED_DAYS}),
    CONSTRAINT ck_leave_entitlements_used_initial CHECK ({CK_USED_INITIAL_DAYS})
)""",
    f"""CREATE TABLE IF NOT EXISTS company_days_off (
    id SERIAL PRIMARY KEY,
    day DATE NOT NULL,
    name VARCHAR(120) NOT NULL,
    kind VARCHAR(16) NOT NULL DEFAULT 'company',
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_company_days_off_day UNIQUE (day),
    CONSTRAINT ck_company_days_off_kind CHECK ({CK_DAY_OFF_KIND})
)""",
    f"""CREATE TABLE IF NOT EXISTS hr_audit_events (
    id BIGSERIAL PRIMARY KEY,
    actor_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    subject_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    entity_type VARCHAR(40) NOT NULL,
    entity_id VARCHAR(64) NULL,
    action VARCHAR(60) NOT NULL,
    sensitivity VARCHAR(16) NOT NULL DEFAULT 'general',
    details JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_hr_audit_events_sensitivity CHECK ({CK_SENSITIVITY})
)""",
    f"""CREATE TABLE IF NOT EXISTS hr_job_runs (
    id SERIAL PRIMARY KEY,
    kind VARCHAR(60) NOT NULL,
    period_key VARCHAR(60) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'claimed',
    counts JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    error TEXT NULL,
    claimed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ NULL,
    CONSTRAINT uq_hr_job_runs_kind_period UNIQUE (kind, period_key),
    CONSTRAINT ck_hr_job_runs_status CHECK ({CK_JOB_RUN_STATUS})
)""",
    f"""CREATE TABLE IF NOT EXISTS hr_import_batches (
    id SERIAL PRIMARY KEY,
    module VARCHAR(32) NOT NULL,
    bundle_sha256 VARCHAR(64) NOT NULL,
    schema_version SMALLINT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'uploaded',
    report JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    applied_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    applied_at TIMESTAMPTZ NULL,
    CONSTRAINT ck_hr_import_batches_module CHECK ({CK_IMPORT_MODULE}),
    CONSTRAINT ck_hr_import_batches_status CHECK ({CK_IMPORT_STATUS})
)""",
    f"""CREATE TABLE IF NOT EXISTS hr_import_id_map (
    id SERIAL PRIMARY KEY,
    module VARCHAR(32) NOT NULL,
    source_id VARCHAR(64) NOT NULL,
    target_table VARCHAR(64) NOT NULL,
    target_id VARCHAR(64) NOT NULL,
    decision VARCHAR(16) NOT NULL DEFAULT 'auto',
    batch_id INTEGER NULL REFERENCES hr_import_batches(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_hr_import_id_map_source UNIQUE (module, source_id),
    CONSTRAINT ck_hr_import_id_map_decision CHECK ({CK_IMPORT_DECISION})
)""",
    f"""CREATE TABLE IF NOT EXISTS hr_import_uploads (
    id SERIAL PRIMARY KEY,
    bundle_sha256 VARCHAR(64) NOT NULL,
    size_bytes INTEGER NOT NULL,
    bundle BYTEA NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'dry_run',
    batch_ids JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    report JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    applied_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    applied_at TIMESTAMPTZ NULL,
    CONSTRAINT ck_hr_import_uploads_status CHECK ({CK_UPLOAD_STATUS}),
    CONSTRAINT ck_hr_import_uploads_bundle CHECK ({CK_UPLOAD_BUNDLE})
)""",
)

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_employee_profiles_manager "
    "ON employee_profiles (manager_user_id)",
    "CREATE INDEX IF NOT EXISTS ix_employee_profiles_status "
    "ON employee_profiles (employment_status)",
    "CREATE INDEX IF NOT EXISTS ix_hr_audit_events_subject "
    "ON hr_audit_events (subject_user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_hr_audit_events_entity "
    "ON hr_audit_events (entity_type, entity_id)",
)

DATA_DDL: tuple[str, ...] = (
    # Wszystkie moduły domyślnie wyłączone; admin przełącza przy migracji
    # danych z Compassa. ON CONFLICT: decyzja admina nie jest cofana startem.
    "INSERT INTO app_settings (key, value) VALUES ('"
    + HR_MODULES_SETTING
    + "', jsonb_build_object("
    + ", ".join(f"'{key}', false" for key in HR_MODULE_KEYS)
    + ")) ON CONFLICT (key) DO NOTHING",
)

TABLES: tuple[str, ...] = (
    "employee_profiles",
    "leave_entitlements",
    "company_days_off",
    "hr_audit_events",
    "hr_job_runs",
    "hr_import_batches",
    "hr_import_id_map",
    "hr_import_uploads",
)

ALL_DDL: tuple[str, ...] = TABLE_DDL + INDEX_DDL + DATA_DDL
