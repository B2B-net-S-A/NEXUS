"""Księga NEXUSA (K1): SQL migracji ``0700_ledger_core`` i lustra entrypointu.

Jedno źródło instrukcji dla ``alembic/versions/0700_ledger_core.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``); każda
instrukcja idempotentna. Plan: https://claude.ai/artifact/U9Z3unvSK62Ff5U36hkaar.

* ``ledger_years`` — rok obrotowy: daty, tryb (``symfonia`` — księgą urzędową
  jest Symfonia FK, NEXUS robi paczki; ``parallel`` — paczki i księga NEXUSA do
  porównań; ``nexus`` — NEXUS jest księgą), stan i licznik pozycji dziennika
  (``next_journal_no``): numeracja zapisów ciągła w roku obrotowym (art. 14
  ust. 1 i art. 23 ust. 2 ustawy o rachunkowości).
* ``ledger_periods`` — miesiące roku: ``open`` | ``closed``. Zamknięty okres nie
  przyjmuje dokumentów ani zatwierdzeń; ponownie otwiera tylko administrator
  z powodem.
* ``ledger_documents`` — dokument księgowy: typ, numer własny, data operacji
  i dokumentu, opis, kontrahent, źródło (typ + id — jedno nieodwrócone na
  źródło), waluta i kurs, stan (``draft`` = bufor, ``approved`` = zapis
  w dzienniku z pozycją ``journal_no``), sumy Wn/Ma, wrażliwość (``payroll`` —
  szczegóły tylko dla Płac i admina), storno (``reverses_id`` /
  ``reversed_by_id``).
* ``ledger_lines`` — pozycje dekretu: konto, strona, kwota w groszach (≠ 0;
  storno czerwone ma kwoty ujemne po tej samej stronie), waluta i kwota
  w walucie, kontrahent, MPK, opis. Kontrahenta z zapisami w księdze nie
  można skasować (``RESTRICT``) — zapis musi wskazywać, kogo dotyczył.
* ``ledger_events`` — ślad: kto, kiedy i co (utworzenie, zmiana, zatwierdzenie,
  storno, usunięcie szkicu, zamknięcie i otwarcie okresu, zmiana trybu roku).
* ``finance_accounts`` (plan kont z E2) — dochodzi konto nadrzędne, typ konta
  (bilansowe aktywne/pasywne/aktywno-pasywne, wynikowe, pozabilansowe), słownik
  analityki (np. konta kontrahentów ``201-2-NNN``) i pozycja sprawozdania;
  rodzaj ``other`` dla kont spoza dekretu faktur (0xx, 1xx, 8xx…).

**Trwałość zapisów** pilnuje baza, nie tylko serwis: wyzwalacze nie pozwalają
zmienić ani usunąć zatwierdzonego dokumentu i jego pozycji. Wolno tylko raz
oznaczyć storno (``reversed_by_id`` na dokument, który odwraca ten) i wyczyścić
autora albo zatwierdzającego, gdy jego konto znika (``ON DELETE SET NULL``).
Pozycji nie przenosi się z zatwierdzonego dokumentu ani do niego. Jednorazowe
sprzątanie (testy, naprawy w ``scripts/repairs``) ustawia
``SET LOCAL nexus.ledger_purge = 'on'`` w swojej transakcji.
"""

from __future__ import annotations

from app.services import finance_posting_schema as posting
from app.services.consultant_portal_schema import quoted

YEAR_MODES: tuple[str, ...] = ("symfonia", "parallel", "nexus")
YEAR_STATUSES: tuple[str, ...] = ("open", "closed")
PERIOD_STATUSES: tuple[str, ...] = ("open", "closed")
#: Typy dokumentów: faktury sprzedaży i zakupu, wyciąg bankowy, lista płac,
#: amortyzacja, rozliczenie RMK, rozliczenie VAT, polecenie księgowania,
#: bilans otwarcia, storno.
DOC_TYPES: tuple[str, ...] = (
    "FVS",
    "FVZ",
    "WB",
    "LP",
    "AM",
    "RMK",
    "VAT",
    "PK",
    "BO",
    "ST",
)
DOC_STATUSES: tuple[str, ...] = ("draft", "approved")
SIDES: tuple[str, ...] = ("debit", "credit")
SENSITIVITIES: tuple[str, ...] = ("payroll",)
EVENT_ACTIONS: tuple[str, ...] = (
    "create",
    "update",
    "approve",
    "reverse",
    "delete",
    "close",
    "reopen",
    "mode",
)
#: Rodzaje kont: cztery z dekretu E2 i ``other`` dla reszty planu.
ACCOUNT_KINDS: tuple[str, ...] = (*posting.ACCOUNT_KINDS, "other")
ACCOUNT_TYPES: tuple[str, ...] = ("active", "passive", "mixed", "result", "off_balance")
ACCOUNT_DICTIONARIES: tuple[str, ...] = ("counterparty", "mpk", "tax_office", "bank")

ACCOUNT_MAX = posting.ACCOUNT_MAX
NUMBER_MAX = 80
DESCRIPTION_MAX = 300
LINE_TEXT_MAX = 200
MPK_MAX = 16
SOURCE_TYPE_MAX = 24
SOURCE_ID_MAX = 64
REASON_MAX = 500
REPORT_LINE_MAX = 32
LINES_MAX = 500

CK_YEAR_MODE = f"mode IN ({quoted(YEAR_MODES)})"
CK_YEAR_STATUS = f"status IN ({quoted(YEAR_STATUSES)})"
CK_YEAR_DATES = "ends_on > starts_on"
CK_YEAR_NEXT = "next_journal_no >= 1"
CK_PERIOD_MONTH = "month BETWEEN 1 AND 12"
CK_PERIOD_STATUS = f"status IN ({quoted(PERIOD_STATUSES)})"
CK_DOC_TYPE = f"doc_type IN ({quoted(DOC_TYPES)})"
CK_DOC_STATUS = f"status IN ({quoted(DOC_STATUSES)})"
CK_DOC_JOURNAL = "(status = 'approved') = (journal_no IS NOT NULL)"
CK_DOC_BALANCE = "status = 'draft' OR debit_total = credit_total"
CK_DOC_SENSITIVITY = f"sensitivity IS NULL OR sensitivity IN ({quoted(SENSITIVITIES)})"
CK_DOC_SOURCE = "(source_type IS NULL) = (source_id IS NULL)"
CK_DOC_FX = "currency = 'PLN' OR (fx_rate IS NOT NULL AND fx_date IS NOT NULL)"
CK_LINE_SIDE = f"side IN ({quoted(SIDES)})"
CK_LINE_AMOUNT = "amount <> 0"
CK_EVENT_ACTION = f"action IN ({quoted(EVENT_ACTIONS)})"
CK_ACCOUNT_KIND = f"kind IN ({quoted(ACCOUNT_KINDS)})"
CK_ACCOUNT_TYPE = f"account_type IS NULL OR account_type IN ({quoted(ACCOUNT_TYPES)})"
CK_ACCOUNT_DICTIONARY = (
    f"dictionary IS NULL OR dictionary IN ({quoted(ACCOUNT_DICTIONARIES)})"
)

DOC_JOURNAL_WHERE = "journal_no IS NOT NULL"
DOC_SOURCE_WHERE = "source_type IS NOT NULL AND reversed_by_id IS NULL"
DOC_COUNTERPARTY_WHERE = "counterparty_id IS NOT NULL"
PURGE_SETTING = "nexus.ledger_purge"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS ledger_years (
    id SERIAL PRIMARY KEY,
    year SMALLINT NOT NULL,
    starts_on DATE NOT NULL,
    ends_on DATE NOT NULL,
    mode VARCHAR(10) NOT NULL DEFAULT 'symfonia',
    status VARCHAR(8) NOT NULL DEFAULT 'open',
    next_journal_no INTEGER NOT NULL DEFAULT 1,
    closed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    closed_at TIMESTAMPTZ NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_ledger_years_year UNIQUE (year),
    CONSTRAINT ck_ledger_years_mode CHECK ({CK_YEAR_MODE}),
    CONSTRAINT ck_ledger_years_status CHECK ({CK_YEAR_STATUS}),
    CONSTRAINT ck_ledger_years_dates CHECK ({CK_YEAR_DATES}),
    CONSTRAINT ck_ledger_years_next CHECK ({CK_YEAR_NEXT})
)""",
    f"""CREATE TABLE IF NOT EXISTS ledger_periods (
    id SERIAL PRIMARY KEY,
    year_id INTEGER NOT NULL REFERENCES ledger_years(id) ON DELETE CASCADE,
    month SMALLINT NOT NULL,
    starts_on DATE NOT NULL,
    ends_on DATE NOT NULL,
    status VARCHAR(8) NOT NULL DEFAULT 'open',
    closed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    closed_at TIMESTAMPTZ NULL,
    reopened_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    reopened_at TIMESTAMPTZ NULL,
    reopen_reason VARCHAR({REASON_MAX}) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_ledger_periods_month UNIQUE (year_id, month),
    CONSTRAINT ck_ledger_periods_month CHECK ({CK_PERIOD_MONTH}),
    CONSTRAINT ck_ledger_periods_status CHECK ({CK_PERIOD_STATUS})
)""",
    f"""CREATE TABLE IF NOT EXISTS ledger_documents (
    id SERIAL PRIMARY KEY,
    year_id INTEGER NOT NULL REFERENCES ledger_years(id) ON DELETE RESTRICT,
    period_id INTEGER NOT NULL REFERENCES ledger_periods(id) ON DELETE RESTRICT,
    doc_type VARCHAR(4) NOT NULL,
    number VARCHAR({NUMBER_MAX}) NOT NULL,
    op_date DATE NOT NULL,
    doc_date DATE NOT NULL,
    description VARCHAR({DESCRIPTION_MAX}) NOT NULL DEFAULT '',
    counterparty_id INTEGER NULL REFERENCES finance_counterparties(id) ON DELETE RESTRICT,
    source_type VARCHAR({SOURCE_TYPE_MAX}) NULL,
    source_id VARCHAR({SOURCE_ID_MAX}) NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'PLN',
    fx_rate NUMERIC(12, 6) NULL,
    fx_date DATE NULL,
    status VARCHAR(10) NOT NULL DEFAULT 'draft',
    journal_no INTEGER NULL,
    debit_total BIGINT NOT NULL DEFAULT 0,
    credit_total BIGINT NOT NULL DEFAULT 0,
    sensitivity VARCHAR(8) NULL,
    reverses_id INTEGER NULL REFERENCES ledger_documents(id) ON DELETE RESTRICT,
    reversed_by_id INTEGER NULL REFERENCES ledger_documents(id) ON DELETE SET NULL,
    meta JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    approved_at TIMESTAMPTZ NULL,
    CONSTRAINT ck_ledger_documents_type CHECK ({CK_DOC_TYPE}),
    CONSTRAINT ck_ledger_documents_status CHECK ({CK_DOC_STATUS}),
    CONSTRAINT ck_ledger_documents_journal CHECK ({CK_DOC_JOURNAL}),
    CONSTRAINT ck_ledger_documents_balance CHECK ({CK_DOC_BALANCE}),
    CONSTRAINT ck_ledger_documents_sensitivity CHECK ({CK_DOC_SENSITIVITY}),
    CONSTRAINT ck_ledger_documents_source CHECK ({CK_DOC_SOURCE}),
    CONSTRAINT ck_ledger_documents_fx CHECK ({CK_DOC_FX})
)""",
    f"""CREATE TABLE IF NOT EXISTS ledger_lines (
    id BIGSERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES ledger_documents(id) ON DELETE CASCADE,
    line_no SMALLINT NOT NULL,
    side VARCHAR(6) NOT NULL,
    account VARCHAR({ACCOUNT_MAX}) NOT NULL,
    amount BIGINT NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'PLN',
    amount_cur BIGINT NULL,
    counterparty_id INTEGER NULL REFERENCES finance_counterparties(id) ON DELETE RESTRICT,
    mpk VARCHAR({MPK_MAX}) NULL,
    description VARCHAR({LINE_TEXT_MAX}) NOT NULL DEFAULT '',
    CONSTRAINT uq_ledger_lines_no UNIQUE (document_id, line_no),
    CONSTRAINT ck_ledger_lines_side CHECK ({CK_LINE_SIDE}),
    CONSTRAINT ck_ledger_lines_amount CHECK ({CK_LINE_AMOUNT})
)""",
    f"""CREATE TABLE IF NOT EXISTS ledger_events (
    id BIGSERIAL PRIMARY KEY,
    document_id INTEGER NULL REFERENCES ledger_documents(id) ON DELETE SET NULL,
    period_id INTEGER NULL REFERENCES ledger_periods(id) ON DELETE SET NULL,
    action VARCHAR(16) NOT NULL,
    detail JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    actor_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_ledger_events_action CHECK ({CK_EVENT_ACTION})
)""",
)

COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE finance_accounts ADD COLUMN IF NOT EXISTS parent_number "
    f"VARCHAR({ACCOUNT_MAX}) NULL",
    "ALTER TABLE finance_accounts ADD COLUMN IF NOT EXISTS account_type VARCHAR(12) NULL",
    "ALTER TABLE finance_accounts ADD COLUMN IF NOT EXISTS dictionary VARCHAR(16) NULL",
    "ALTER TABLE finance_accounts ADD COLUMN IF NOT EXISTS report_line "
    f"VARCHAR({REPORT_LINE_MAX}) NULL",
)

INDEX_DDL: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_ledger_documents_journal "
    f"ON ledger_documents (year_id, journal_no) WHERE {DOC_JOURNAL_WHERE}",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_ledger_documents_source "
    f"ON ledger_documents (source_type, source_id) WHERE {DOC_SOURCE_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_ledger_documents_period "
    "ON ledger_documents (period_id, doc_type, status)",
    "CREATE INDEX IF NOT EXISTS ix_ledger_documents_counterparty "
    f"ON ledger_documents (counterparty_id) WHERE {DOC_COUNTERPARTY_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_ledger_lines_account "
    "ON ledger_lines (account, document_id)",
    "CREATE INDEX IF NOT EXISTS ix_ledger_events_document "
    "ON ledger_events (document_id, id)",
)

_GUARD_FUNCTION = f"""CREATE OR REPLACE FUNCTION ledger_guard_approved() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    doc_status VARCHAR(10);
BEGIN
    IF current_setting('{PURGE_SETTING}', true) = 'on' THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    IF TG_TABLE_NAME = 'ledger_documents' THEN
        IF OLD.status = 'approved' THEN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Zatwierdzonego dokumentu nie usuwa się (dokument %).', OLD.id
                    USING ERRCODE = 'check_violation';
            END IF;
            IF (NEW.doc_type, NEW.number, NEW.op_date, NEW.doc_date, NEW.description,
                NEW.year_id, NEW.period_id, NEW.status, NEW.journal_no,
                NEW.debit_total, NEW.credit_total, NEW.currency, NEW.fx_rate,
                NEW.fx_date, NEW.reverses_id, NEW.sensitivity, NEW.counterparty_id,
                NEW.source_type, NEW.source_id, NEW.meta, NEW.created_at,
                NEW.approved_at)
               IS DISTINCT FROM
               (OLD.doc_type, OLD.number, OLD.op_date, OLD.doc_date, OLD.description,
                OLD.year_id, OLD.period_id, OLD.status, OLD.journal_no,
                OLD.debit_total, OLD.credit_total, OLD.currency, OLD.fx_rate,
                OLD.fx_date, OLD.reverses_id, OLD.sensitivity, OLD.counterparty_id,
                OLD.source_type, OLD.source_id, OLD.meta, OLD.created_at,
                OLD.approved_at)
               OR (NEW.created_by IS DISTINCT FROM OLD.created_by
                   AND NEW.created_by IS NOT NULL)
               OR (NEW.approved_by IS DISTINCT FROM OLD.approved_by
                   AND NEW.approved_by IS NOT NULL)
               OR (OLD.reversed_by_id IS NOT NULL
                   AND NEW.reversed_by_id IS DISTINCT FROM OLD.reversed_by_id)
               OR (OLD.reversed_by_id IS NULL AND NEW.reversed_by_id IS NOT NULL
                   AND NOT EXISTS (
                       SELECT 1 FROM ledger_documents AS storno
                       WHERE storno.id = NEW.reversed_by_id
                         AND storno.reverses_id = OLD.id)) THEN
                RAISE EXCEPTION 'Zatwierdzony dokument jest trwały — popraw go stornem (dokument %).', OLD.id
                    USING ERRCODE = 'check_violation';
            END IF;
        END IF;
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    IF TG_OP <> 'INSERT' THEN
        SELECT status INTO doc_status FROM ledger_documents WHERE id = OLD.document_id;
        IF doc_status = 'approved' THEN
            RAISE EXCEPTION 'Pozycje zatwierdzonego dokumentu są trwałe (dokument %).',
                OLD.document_id USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        SELECT status INTO doc_status FROM ledger_documents WHERE id = NEW.document_id;
        IF doc_status = 'approved' THEN
            RAISE EXCEPTION 'Pozycje zatwierdzonego dokumentu są trwałe (dokument %).',
                NEW.document_id USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    RETURN OLD;
END $$"""

#: Rodzaj ``other`` w CHECK-u planu kont z E2. Warunek w DO, żeby entrypoint
#: nie przebudowywał CHECK-a przy każdym starcie (pełny skan pod blokadą).
CONSTRAINT_DDL: tuple[str, ...] = (
    f"""DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_finance_accounts_kind'
          AND pg_get_constraintdef(oid) LIKE '%other%'
    ) THEN
        ALTER TABLE finance_accounts DROP CONSTRAINT IF EXISTS ck_finance_accounts_kind;
        ALTER TABLE finance_accounts
            ADD CONSTRAINT ck_finance_accounts_kind CHECK ({CK_ACCOUNT_KIND});
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_finance_accounts_type'
    ) THEN
        ALTER TABLE finance_accounts
            ADD CONSTRAINT ck_finance_accounts_type CHECK ({CK_ACCOUNT_TYPE});
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_finance_accounts_dictionary'
    ) THEN
        ALTER TABLE finance_accounts
            ADD CONSTRAINT ck_finance_accounts_dictionary CHECK ({CK_ACCOUNT_DICTIONARY});
    END IF;
END $$""",
    _GUARD_FUNCTION,
    "CREATE OR REPLACE TRIGGER trg_ledger_documents_guard "
    "BEFORE UPDATE OR DELETE ON ledger_documents "
    "FOR EACH ROW EXECUTE FUNCTION ledger_guard_approved()",
    "CREATE OR REPLACE TRIGGER trg_ledger_lines_guard "
    "BEFORE INSERT OR UPDATE OR DELETE ON ledger_lines "
    "FOR EACH ROW EXECUTE FUNCTION ledger_guard_approved()",
)

DATA_DDL: tuple[str, ...] = ()

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)

DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP TRIGGER IF EXISTS trg_ledger_lines_guard ON ledger_lines",
    "DROP TRIGGER IF EXISTS trg_ledger_documents_guard ON ledger_documents",
    "DROP FUNCTION IF EXISTS ledger_guard_approved()",
    "DROP TABLE IF EXISTS ledger_events",
    "DROP TABLE IF EXISTS ledger_lines",
    "DROP TABLE IF EXISTS ledger_documents",
    "DROP TABLE IF EXISTS ledger_periods",
    "DROP TABLE IF EXISTS ledger_years",
    "ALTER TABLE finance_accounts DROP CONSTRAINT IF EXISTS ck_finance_accounts_dictionary",
    "ALTER TABLE finance_accounts DROP CONSTRAINT IF EXISTS ck_finance_accounts_type",
    "UPDATE finance_accounts SET kind = 'cost' WHERE kind = 'other'",
    "ALTER TABLE finance_accounts DROP CONSTRAINT IF EXISTS ck_finance_accounts_kind",
    "ALTER TABLE finance_accounts "
    f"ADD CONSTRAINT ck_finance_accounts_kind CHECK ({posting.CK_ACCOUNT_KIND})",
    "ALTER TABLE finance_accounts DROP COLUMN IF EXISTS report_line",
    "ALTER TABLE finance_accounts DROP COLUMN IF EXISTS dictionary",
    "ALTER TABLE finance_accounts DROP COLUMN IF EXISTS account_type",
    "ALTER TABLE finance_accounts DROP COLUMN IF EXISTS parent_number",
)
