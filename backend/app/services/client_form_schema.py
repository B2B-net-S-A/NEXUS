"""Formularz CV klienta zamiast CV firmowego — SQL migracji 0521 i lustra w ``entrypoint.sh``.

JEDNO źródło instrukcji dla ``alembic/versions/0521_client_form_documents.py``
i ``entrypoint.sh`` (alembic na prodzie bywa osierocony); test
``test_client_form_migration_mirror.py`` sprawdza, że każda stoi w entrypoincie
dosłownie — kolumny po tabeli ``job_files``, włączenie dla CEZ w danych.

* ``clients.cv_client_document`` — co idzie do klienta: ``company_cv`` (CV
  firmowe z generatora, jak dotąd) albo ``client_form`` (formularz klienta
  wypełniany przez NEXUS). Flaga klienta prowadzona z edytora reguły CV, tak
  jak ``cv_interactive_enabled``.
* ``job_files.client_form`` — ten plik rekrutacji jest wzorem formularza;
  najwyżej jeden na rekrutację. ``client_form_structure`` to odczytane pola
  (``client_form_structure.read_structure``), żeby nie czytać DOCX przy każdej
  liście plików.

Decyzje Artura 26.10.2026: wzór wyłącznie z Plików rekrutacji, na start tylko
Centrum e-Zdrowia. Włączenie dla CEZ biegnie RAZ (znacznik w ``app_settings``),
żeby restart nie cofał późniejszej zmiany w edytorze reguły.
"""

from __future__ import annotations

from app.services.ezdrowie import EZDROWIE_CLIENT_ID

COMPANY_CV = "company_cv"
CLIENT_FORM = "client_form"
CLIENT_DOCUMENTS = (COMPANY_CV, CLIENT_FORM)

SEED_MARKER = "0521_ezdrowie_client_form"

CLIENT_COLUMN_DDL = (
    "ALTER TABLE clients ADD COLUMN IF NOT EXISTS cv_client_document "
    "VARCHAR(16) NOT NULL DEFAULT 'company_cv'"
)

JOB_FILE_DDL = (
    "ALTER TABLE job_files ADD COLUMN IF NOT EXISTS client_form "
    "BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE job_files ADD COLUMN IF NOT EXISTS client_form_structure JSONB NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_job_files_client_form ON job_files (job_id) "
    "WHERE client_form AND job_id IS NOT NULL",
)

SEED_DDL = (
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM app_settings WHERE key = "
    f"'{SEED_MARKER}') THEN UPDATE clients SET cv_client_document = "
    f"'{CLIENT_FORM}' WHERE id = {EZDROWIE_CLIENT_ID}; "
    "INSERT INTO app_settings (key, value) VALUES "
    f"('{SEED_MARKER}', jsonb_build_object('completed_at', clock_timestamp())) "
    "ON CONFLICT (key) DO NOTHING; END IF; END $$"
)

ALL_DDL = (CLIENT_COLUMN_DDL, *JOB_FILE_DDL, SEED_DDL)

DOWNGRADE_DDL = (
    "DROP INDEX IF EXISTS ux_job_files_client_form",
    "ALTER TABLE job_files DROP COLUMN IF EXISTS client_form_structure",
    "ALTER TABLE job_files DROP COLUMN IF EXISTS client_form",
    "ALTER TABLE clients DROP COLUMN IF EXISTS cv_client_document",
    f"DELETE FROM app_settings WHERE key = '{SEED_MARKER}'",
)


# ── 0522: wypełniony formularz pary osoba × rekrutacja ────────────────────
# Jeden wiersz na parę (nie na wiersz etapu — etap ma kilka wierszy historii).
# ``fields`` = {id pola: {"value", "source", "quote"}}; plik DOCX powstaje
# przy pobraniu z wzoru ``job_file_id`` — edycja rekrutera nie rozjedzie się
# z zapisanym plikiem. ``template_sha256`` mówi, że DL podmienił wzór.
FILL_TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS candidate_client_forms ("
    "id SERIAL PRIMARY KEY, "
    "candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE, "
    "job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE, "
    "job_file_id INTEGER NULL REFERENCES job_files(id) ON DELETE SET NULL, "
    "template_sha256 VARCHAR(64) NULL, "
    "fields JSONB NOT NULL DEFAULT '{}'::jsonb, "
    "extra_rows JSONB NOT NULL DEFAULT '[]'::jsonb, "
    "missing_count INTEGER NOT NULL DEFAULT 0, "
    "model VARCHAR(80) NULL, "
    "filled_at TIMESTAMPTZ NULL, "
    "filled_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "CONSTRAINT uq_candidate_client_forms_pair UNIQUE (candidate_id, job_id))"
)

FILL_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS ix_candidate_client_forms_job "
    "ON candidate_client_forms (job_id)",
)

FILL_DDL = (FILL_TABLE_DDL, *FILL_INDEX_DDL)

FILL_DOWNGRADE_DDL = ("DROP TABLE IF EXISTS candidate_client_forms",)


# ── 0525: tabela punktowa klienta (Excel) obok formularza (Word) ─────────────
# Decyzja Artura 27.10.2026: CEZ do formularza CV dokłada Excel z punktacją
# (zał. 5 SWZ) — jeden na osobę, wypełniany przez NEXUS jak formularz. Rodzaj
# wzoru wynika z pliku: Word = „form”, Excel = „score”; każdy rodzaj ma
# najwyżej jeden wzór na rekrutację i jeden wypełniony dokument na parę.
KIND_FORM = "form"
KIND_SCORE = "score"
KINDS = (KIND_FORM, KIND_SCORE)

# Indeks „jeden wzór na rekrutację” z 0521 zastępuje „jeden wzór każdego
# rodzaju” — nie może stać w entrypoincie, bo dwa wzory (Word i Excel)
# wywróciłyby jego ponowne założenie przy starcie.
SUPERSEDED_DDL = (JOB_FILE_DDL[2],)

SCORE_DDL = (
    "ALTER TABLE job_files ADD COLUMN IF NOT EXISTS client_form_kind VARCHAR(8) NULL",
    "UPDATE job_files SET client_form_kind = 'form' "
    "WHERE client_form AND client_form_kind IS NULL",
    "DROP INDEX IF EXISTS ux_job_files_client_form",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_job_files_client_form_kind "
    "ON job_files (job_id, client_form_kind) WHERE client_form AND job_id IS NOT NULL",
    "ALTER TABLE candidate_client_forms ADD COLUMN IF NOT EXISTS kind "
    "VARCHAR(8) NOT NULL DEFAULT 'form'",
    "ALTER TABLE candidate_client_forms DROP CONSTRAINT IF EXISTS "
    "uq_candidate_client_forms_pair",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_candidate_client_forms_pair_kind "
    "ON candidate_client_forms (candidate_id, job_id, kind)",
)

SCORE_DOWNGRADE_DDL = (
    "DROP INDEX IF EXISTS ux_candidate_client_forms_pair_kind",
    "DELETE FROM candidate_client_forms WHERE kind <> 'form'",
    "ALTER TABLE candidate_client_forms DROP COLUMN IF EXISTS kind",
    "ALTER TABLE candidate_client_forms ADD CONSTRAINT uq_candidate_client_forms_pair "
    "UNIQUE (candidate_id, job_id)",
    "DROP INDEX IF EXISTS ux_job_files_client_form_kind",
    "UPDATE job_files SET client_form = false, client_form_structure = NULL "
    "WHERE client_form_kind = 'score'",
    "ALTER TABLE job_files DROP COLUMN IF EXISTS client_form_kind",
    JOB_FILE_DDL[2],
)
