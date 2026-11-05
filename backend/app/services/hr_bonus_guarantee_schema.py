"""„Ludzie w NEXUSIE” — gwarancja premii DL: SQL migracji ``0653_hr_bonus_guarantee`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0653_hr_bonus_guarantee.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``).

Zasada Artura z 05.11.2026: konsultant, który nie przepracuje 12 miesięcy od
startu kontraktu, odbiera Delivery Leadowi premię za ten placement. DL oddaje
całą kwotę, a potrąca się ona sama z jego kolejnych premii.

Tabele:

* ``hr_bonus_clawbacks`` — dług za jedną przyznaną premię DL: automat przy
  końcu kontraktu przed rocznicą startu albo Płace ręcznie. Jeden otwarty dług
  na premię (indeks częściowy). Anulowanie jest miękkie, jak przy premiach.
  Nikt nie zakłada ani nie zdejmuje długu sobie (CHECK-i). ``deduct_from`` —
  pierwszy dzień miesiąca, od którego dług bierze premie („z kolejnych premii”).
* ``hr_bonus_clawback_offsets`` — potrącenie zamrożone przy zamknięciu
  miesiąca płac (dług × okres). Ponowne otwarcie miesiąca je kasuje, więc
  w otwartym miesiącu potrącenie liczy się z danych, jak cały raport płac.

``payroll_lines.clawback_total`` — potrącenie w zamrożonej linii. ``bonus_total``
jest już po potrąceniu (eksport, Symfonia i rozliczenia biorą kwotę netto),
premie przed potrąceniem to ``bonus_total + clawback_total``.
"""

from __future__ import annotations

from app.services.hr_payroll_schema import BONUS_MAX, CURRENCIES, quoted

CLAWBACK_ORIGINS: tuple[str, ...] = ("automatic", "manual")
CLAWBACK_STATUSES: tuple[str, ...] = ("open", "settled", "cancelled")
NOTE_MAX_LENGTH = 500

CK_CLAWBACK_AMOUNT = f"amount > 0 AND amount <= {BONUS_MAX}"
CK_CLAWBACK_CURRENCY = f"currency IN ({quoted(CURRENCIES)})"
CK_CLAWBACK_ORIGIN = f"origin IN ({quoted(CLAWBACK_ORIGINS)})"
CK_CLAWBACK_STATUS = f"status IN ({quoted(CLAWBACK_STATUSES)})"
CK_CLAWBACK_NOT_SELF_CREATED = "created_by IS NULL OR created_by <> recipient_user_id"
CK_CLAWBACK_NOT_SELF_CANCELLED = (
    "cancelled_by IS NULL OR cancelled_by <> recipient_user_id"
)
CK_CLAWBACK_CANCELLED_AT = "status <> 'cancelled' OR cancelled_at IS NOT NULL"
CK_CLAWBACK_DEDUCT_FROM = "EXTRACT(DAY FROM deduct_from) = 1"
CK_CLAWBACK_NOTE = f"note IS NULL OR char_length(note) <= {NOTE_MAX_LENGTH}"
CK_CLAWBACK_CANCEL_NOTE = (
    f"cancel_note IS NULL OR char_length(cancel_note) <= {NOTE_MAX_LENGTH}"
)
#: Indeks częściowy: jeden żywy dług na premię.
LIVE_CLAWBACK_WHERE = "status <> 'cancelled'"

CK_OFFSET_AMOUNT = "amount > 0"
CK_LINE_CLAWBACK = "clawback_total >= 0"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS hr_bonus_clawbacks (
    id SERIAL PRIMARY KEY,
    bonus_id INTEGER NOT NULL REFERENCES hr_bonuses(id) ON DELETE CASCADE,
    recipient_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE SET NULL,
    amount NUMERIC(12,2) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'PLN',
    origin VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'open',
    contract_start DATE NULL,
    ended_on DATE NULL,
    guarantee_until DATE NULL,
    deduct_from DATE NOT NULL,
    note TEXT NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    cancelled_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    cancelled_at TIMESTAMPTZ NULL,
    cancel_reason VARCHAR(40) NULL,
    cancel_note TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_hr_bonus_clawbacks_amount CHECK ({CK_CLAWBACK_AMOUNT}),
    CONSTRAINT ck_hr_bonus_clawbacks_currency CHECK ({CK_CLAWBACK_CURRENCY}),
    CONSTRAINT ck_hr_bonus_clawbacks_origin CHECK ({CK_CLAWBACK_ORIGIN}),
    CONSTRAINT ck_hr_bonus_clawbacks_status CHECK ({CK_CLAWBACK_STATUS}),
    CONSTRAINT ck_hr_bonus_clawbacks_not_self_created CHECK ({CK_CLAWBACK_NOT_SELF_CREATED}),
    CONSTRAINT ck_hr_bonus_clawbacks_not_self_cancelled CHECK ({CK_CLAWBACK_NOT_SELF_CANCELLED}),
    CONSTRAINT ck_hr_bonus_clawbacks_cancelled_at CHECK ({CK_CLAWBACK_CANCELLED_AT}),
    CONSTRAINT ck_hr_bonus_clawbacks_deduct_from CHECK ({CK_CLAWBACK_DEDUCT_FROM}),
    CONSTRAINT ck_hr_bonus_clawbacks_note CHECK ({CK_CLAWBACK_NOTE}),
    CONSTRAINT ck_hr_bonus_clawbacks_cancel_note CHECK ({CK_CLAWBACK_CANCEL_NOTE})
)""",
    f"""CREATE TABLE IF NOT EXISTS hr_bonus_clawback_offsets (
    id SERIAL PRIMARY KEY,
    clawback_id INTEGER NOT NULL REFERENCES hr_bonus_clawbacks(id) ON DELETE CASCADE,
    period_id INTEGER NOT NULL REFERENCES payroll_periods(id) ON DELETE CASCADE,
    amount NUMERIC(12,2) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_hr_bonus_clawback_offsets_period UNIQUE (clawback_id, period_id),
    CONSTRAINT ck_hr_bonus_clawback_offsets_amount CHECK ({CK_OFFSET_AMOUNT})
)""",
)

COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE payroll_lines ADD COLUMN IF NOT EXISTS "
    "clawback_total NUMERIC(14,2) NOT NULL DEFAULT 0",
)

INDEX_DDL: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_hr_bonus_clawbacks_live "
    f"ON hr_bonus_clawbacks (bonus_id) WHERE {LIVE_CLAWBACK_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_hr_bonus_clawbacks_recipient "
    "ON hr_bonus_clawbacks (recipient_user_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_hr_bonus_clawback_offsets_period "
    "ON hr_bonus_clawback_offsets (period_id)",
)

CONSTRAINT_DDL: tuple[str, ...] = (
    f"""DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'ck_payroll_lines_clawback'
        ) THEN
            ALTER TABLE payroll_lines ADD CONSTRAINT ck_payroll_lines_clawback
                CHECK ({CK_LINE_CLAWBACK});
        END IF;
    END $$""",
)

DATA_DDL: tuple[str, ...] = ()
TABLES: tuple[str, ...] = ("hr_bonus_clawbacks", "hr_bonus_clawback_offsets")
DOWNGRADE_DDL: tuple[str, ...] = (
    "ALTER TABLE payroll_lines DROP CONSTRAINT IF EXISTS ck_payroll_lines_clawback",
    "ALTER TABLE payroll_lines DROP COLUMN IF EXISTS clawback_total",
)

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
