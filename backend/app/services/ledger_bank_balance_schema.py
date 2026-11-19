"""Salda wyciągów w księdze — SQL migracji ``0741_ledger_bank_balances``.

Jedno źródło DDL dla ``alembic/versions/0741_ledger_bank_balances.py`` i lustra
``entrypoint.sh`` (``app/services/hr_schema_bundle.py``, po K4c); każda
instrukcja idempotentna. Po co: „po terminie” faktury do klienta liczy się
tylko z ciągłych wyciągów rachunku odbioru (``ledger/bank_continuity.py``,
``client_invoicing/payment_proof.py``, 19.11.2026).

* ``opening_balance`` / ``opening_day`` / ``closing_balance`` / ``closing_day``
  — saldo otwarcia i zamknięcia pliku w groszach ze znakiem i daty tych sald
  (MT940 ``:60F:`` → ``:62F:``, CAMT.053 ``OPBD`` → ``CLBD``); puste, gdy plik
  ich nie dowodzi (``file_span``) albo wszedł przed tą migracją (ponowne
  wgranie tego samego pliku je uzupełnia),
* ``first_number`` / ``last_number`` — numer wyciągu banku pierwszej
  i ostatniej części pliku (``:28C:``, ``LglSeqNb``), mostek nad dniami bez
  wyciągu,
* ``credits_matched`` — uznania z pliku przeszły przez E8 przy imporcie
  (moduł faktur do klientów włączony, bez błędu w ścieżce Płac). Wyciąg, którego
  uznań E8 nie sprawdziło, nie dowodzi braku wpłaty.

Wyciągi sprzed migracji: ``credits_matched`` jednorazowo (znacznik
w ``app_settings``) z dowodu w bazie — plik bez uznań albo z zapisem E8.
"""

from __future__ import annotations

CK_BALANCES = (
    "(opening_balance IS NULL AND opening_day IS NULL AND closing_balance IS NULL "
    "AND closing_day IS NULL) OR (opening_balance IS NOT NULL AND opening_day IS "
    "NOT NULL AND closing_balance IS NOT NULL AND closing_day IS NOT NULL AND "
    "closing_day >= opening_day)"
)
BACKFILL_MARKER = "ledger_bank_credits_matched_backfill"

TABLE_DDL: tuple[str, ...] = ()

COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE ledger_bank_statements ADD COLUMN IF NOT EXISTS opening_balance "
    "BIGINT NULL",
    "ALTER TABLE ledger_bank_statements ADD COLUMN IF NOT EXISTS opening_day DATE NULL",
    "ALTER TABLE ledger_bank_statements ADD COLUMN IF NOT EXISTS closing_balance "
    "BIGINT NULL",
    "ALTER TABLE ledger_bank_statements ADD COLUMN IF NOT EXISTS closing_day DATE NULL",
    "ALTER TABLE ledger_bank_statements ADD COLUMN IF NOT EXISTS first_number "
    "BIGINT NULL",
    "ALTER TABLE ledger_bank_statements ADD COLUMN IF NOT EXISTS last_number "
    "BIGINT NULL",
    "ALTER TABLE ledger_bank_statements ADD COLUMN IF NOT EXISTS credits_matched "
    "BOOLEAN NOT NULL DEFAULT false",
)

INDEX_DDL: tuple[str, ...] = ()

CONSTRAINT_DDL: tuple[str, ...] = (
    f"""DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_ledger_bank_statements_balances'
    ) THEN
        ALTER TABLE ledger_bank_statements
            ADD CONSTRAINT ck_ledger_bank_statements_balances CHECK ({CK_BALANCES});
    END IF;
END $$""",
)

#: Raz: E8 sprawdziło uznania pliku, gdy plik ich nie ma albo E8 coś z niego
#: zapisało (dopasowane, do sprawdzenia, duplikat). Plik z samymi uznaniami
#: spoza faktur zostaje ``false`` — nie wiemy, czy E8 przy nim działało.
DATA_DDL: tuple[str, ...] = (
    "WITH marker AS ("
    "INSERT INTO app_settings (key, value) "
    f"VALUES ('{BACKFILL_MARKER}', 'true'::jsonb) "
    "ON CONFLICT (key) DO NOTHING RETURNING key) "
    "UPDATE ledger_bank_statements s SET credits_matched = true "
    "WHERE EXISTS (SELECT 1 FROM marker) AND NOT s.credits_matched "
    "AND (s.credit_total = 0 OR EXISTS (SELECT 1 FROM client_sales_invoice_payments p "
    "WHERE p.statement_sha256 = s.sha256))",
)

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)

DOWNGRADE_DDL: tuple[str, ...] = (
    "ALTER TABLE ledger_bank_statements DROP CONSTRAINT IF EXISTS "
    "ck_ledger_bank_statements_balances",
    "ALTER TABLE ledger_bank_statements DROP COLUMN IF EXISTS credits_matched",
    "ALTER TABLE ledger_bank_statements DROP COLUMN IF EXISTS last_number",
    "ALTER TABLE ledger_bank_statements DROP COLUMN IF EXISTS first_number",
    "ALTER TABLE ledger_bank_statements DROP COLUMN IF EXISTS closing_day",
    "ALTER TABLE ledger_bank_statements DROP COLUMN IF EXISTS closing_balance",
    "ALTER TABLE ledger_bank_statements DROP COLUMN IF EXISTS opening_day",
    "ALTER TABLE ledger_bank_statements DROP COLUMN IF EXISTS opening_balance",
    f"DELETE FROM app_settings WHERE key = '{BACKFILL_MARKER}'",
)
