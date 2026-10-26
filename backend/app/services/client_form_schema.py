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
