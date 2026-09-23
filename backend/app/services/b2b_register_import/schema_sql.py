"""DDL importu rejestru umów z Excela — JEDNO źródło dla migracji 0363 i ``entrypoint.sh``.

Produkcyjny alembic bywa osierocony, więc siatka bezpieczeństwa w
``entrypoint.sh`` jest wdrożeniem równorzędnym z migracją — obie strony
importują listy stąd (wzór: ``services/b2b_documents/schema_sql.py``).

Kolejność jest load-bearing: tabela przebiegów powstaje PRZED kolumną
``b2b_generated_contracts.import_run_id``, która na nią wskazuje.
"""

from __future__ import annotations

TABLE_DDL: list[str] = [
    """CREATE TABLE IF NOT EXISTS b2b_register_import_runs (
           id SERIAL PRIMARY KEY,
           source_filename VARCHAR(255) NOT NULL,
           source_sha256 VARCHAR(64) NOT NULL,
           mode VARCHAR(16) NOT NULL,
           counters JSONB NOT NULL DEFAULT '{}'::jsonb,
           missing_marked_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
           created_by INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           rolled_back_at TIMESTAMPTZ NULL,
           rolled_back_by INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           CONSTRAINT ck_b2b_register_import_runs_mode
               CHECK (mode IN ('dry_run', 'applied', 'rolled_back')),
           CONSTRAINT ck_b2b_register_import_runs_sha256
               CHECK (char_length(source_sha256) = 64)
       )""",
    """CREATE INDEX IF NOT EXISTS ix_b2b_register_import_runs_sha256
       ON b2b_register_import_runs (source_sha256)""",
    """CREATE TABLE IF NOT EXISTS b2b_register_import_rows (
           id SERIAL PRIMARY KEY,
           run_id INTEGER NOT NULL
               REFERENCES b2b_register_import_runs (id) ON DELETE CASCADE,
           sheet VARCHAR(64) NOT NULL,
           row_number INTEGER NOT NULL,
           raw JSONB NOT NULL DEFAULT '{}'::jsonb,
           parsed JSONB NULL,
           matches JSONB NULL,
           decision VARCHAR(32) NOT NULL,
           generated_contract_id INTEGER NULL
               REFERENCES b2b_generated_contracts (id) ON DELETE SET NULL,
           snapshot_before JSONB NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
       )""",
    """CREATE INDEX IF NOT EXISTS ix_b2b_register_import_rows_run_id
       ON b2b_register_import_rows (run_id)""",
    """CREATE INDEX IF NOT EXISTS ix_b2b_register_import_rows_generated_contract_id
       ON b2b_register_import_rows (generated_contract_id)""",
    # ── Nowe kolumny rejestru ──────────────────────────────────────────────
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS source VARCHAR(16) NOT NULL DEFAULT 'generator'
       CONSTRAINT ck_b2b_generated_contracts_source
       CHECK (source IN ('generator', 'excel'))""",
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS source_key VARCHAR(64) NULL""",
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS raw_contract_number VARCHAR(64) NULL""",
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS contract_kind VARCHAR(16) NULL
       CONSTRAINT ck_b2b_generated_contracts_contract_kind
       CHECK (contract_kind IS NULL OR
              contract_kind IN ('b2b', 'mandate', 'work', 'employment'))""",
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS start_date_mode VARCHAR(16) NULL
       CONSTRAINT ck_b2b_generated_contracts_start_date_mode
       CHECK (start_date_mode IS NULL OR
              start_date_mode IN ('exact', 'not_later', 'not_earlier'))""",
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS position VARCHAR(255) NULL""",
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS recruiter_user_id INTEGER NULL
       REFERENCES users (id) ON DELETE SET NULL""",
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS legacy_data JSONB NULL""",
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS needs_business_data_annex BOOLEAN NOT NULL
       DEFAULT false""",
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS business_data_annex_done_at DATE NULL""",
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS import_run_id INTEGER NULL
       REFERENCES b2b_register_import_runs (id) ON DELETE SET NULL""",
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS excel_missing_since TIMESTAMPTZ NULL""",
    # Numer spoza formatu („264A”, „bez numeru”) nie ma `seq`, a wiersz bez
    # daty podpisania — roku.
    "ALTER TABLE b2b_generated_contracts ALTER COLUMN seq DROP NOT NULL",
    "ALTER TABLE b2b_generated_contracts ALTER COLUMN year DROP NOT NULL",
    # UNIQUE(year, seq) z 0128 → częściowy (tylko numery kanoniczne).
    # Idempotentnie: indeks bez predykatu zdejmujemy tylko raz.
    """DO $$
       BEGIN
         IF EXISTS (
           SELECT 1 FROM pg_indexes
           WHERE indexname = 'uq_b2b_generated_contracts_year_seq'
             AND indexdef NOT ILIKE '%WHERE%'
         ) THEN
           DROP INDEX uq_b2b_generated_contracts_year_seq;
         END IF;
       END $$""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_b2b_generated_contracts_year_seq
       ON b2b_generated_contracts (year, seq) WHERE seq IS NOT NULL""",
    """CREATE UNIQUE INDEX IF NOT EXISTS ux_b2b_generated_contracts_excel_source_key
       ON b2b_generated_contracts (source_key) WHERE source = 'excel'""",
    """CREATE INDEX IF NOT EXISTS ix_b2b_generated_contracts_source
       ON b2b_generated_contracts (source)""",
]
