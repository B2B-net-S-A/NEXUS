"""„Ludzie w NEXUSIE” — zgody na wydatki i premie poza umową: SQL migracji ``0483_hr_approvals`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0483_hr_approvals.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Kontrakt
modułu jak w pozostałych ``*_schema.py``; każda instrukcja idempotentna.

Decyzja Artura 20.10.2026: wydatki i premie, które dziś zatwierdza mailem
(„approved”) — premia poza umową, subskrypcja, delegacja, prezent, szkolenie,
inny wydatek — idą przez NEXUS. Premie z umowy (placementy, ligi, reguły
Płac) nie przechodzą przez zgody, liczą się same.

* ``approval_requests`` — jedna zgoda: rodzaj, kwota (raz / co miesiąc /
  co rok), po co, autor; przy premii osoba i miesiąc wypłaty. Stan:
  ``pending_supervisor`` (decyduje przełożony autora), ``pending_final``
  (decyduje zatwierdzający z Ustawień), ``approved``, ``rejected``,
  ``returned`` (pytanie do autora — poprawia i wysyła znowu), ``withdrawn``.
  Nikt nie decyduje we własnej sprawie ani o premii dla siebie (CHECK).
  Zatwierdzona premia staje się przyznaną premią w Płacach (``bonus_id``).

Dzwonki ``hr_approval_requested`` (do decydującego — mail z kwotą
i przyciskami) i ``hr_approval_decided`` (do autora).
"""

from __future__ import annotations

KINDS: tuple[str, ...] = (
    "bonus",
    "subscription",
    "trip",
    "gift",
    "training",
    "other",
)
STATUSES: tuple[str, ...] = (
    "pending_supervisor",
    "pending_final",
    "approved",
    "rejected",
    "returned",
    "withdrawn",
)
PENDING_STATUSES: tuple[str, ...] = ("pending_supervisor", "pending_final")
RECURRENCES: tuple[str, ...] = ("once", "monthly", "yearly")
AMOUNT_BASES: tuple[str, ...] = ("gross", "net")
PAYERS: tuple[str, ...] = ("company_invoice", "company_card", "reimbursement")
CURRENCIES: tuple[str, ...] = ("PLN", "EUR", "USD")
#: Kanał decyzji — ślad, skąd przyszło „tak” (odpowiedź mailem: kolejny etap).
DECISION_CHANNELS: tuple[str, ...] = ("app", "mail_reply")

TITLE_MAX_LENGTH = 200
PURPOSE_MAX_LENGTH = 2000
NOTE_MAX_LENGTH = 1000
LINK_MAX_LENGTH = 500
AMOUNT_MAX = "10000000"

#: Ustawienia zasad (próg przełożonego per rodzaj, zatwierdzający).
RULES_SETTING = "hr_approval_rules"

NOTIFICATION_TYPES: tuple[str, ...] = ("hr_approval_requested", "hr_approval_decided")
ENUM_DDL: tuple[str, ...] = tuple(
    f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'"
    for value in NOTIFICATION_TYPES
)


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


CK_KIND = f"kind IN ({quoted(KINDS)})"
CK_STATUS = f"status IN ({quoted(STATUSES)})"
CK_RECURRENCE = f"recurrence IN ({quoted(RECURRENCES)})"
CK_BASIS = f"amount_basis IN ({quoted(AMOUNT_BASES)})"
CK_PAYER = f"payer IS NULL OR payer IN ({quoted(PAYERS)})"
CK_CURRENCY = f"currency IN ({quoted(CURRENCIES)})"
CK_AMOUNT = f"amount > 0 AND amount <= {AMOUNT_MAX}"
CK_DECIDED_AMOUNT = (
    f"decided_amount IS NULL OR (decided_amount > 0 AND decided_amount <= {AMOUNT_MAX})"
)
CK_CHANNEL = (
    f"decision_channel IS NULL OR decision_channel IN ({quoted(DECISION_CHANNELS)})"
)
#: Premia ma osobę i miesiąc wypłaty, raz, brutto; reszta ich nie ma.
CK_BONUS_SHAPE = (
    "(kind = 'bonus' AND beneficiary_user_id IS NOT NULL "
    "AND payout_year IS NOT NULL AND payout_month BETWEEN 1 AND 12 "
    "AND recurrence = 'once' AND payer IS NULL) "
    "OR (kind <> 'bonus' AND beneficiary_user_id IS NULL "
    "AND payout_year IS NULL AND payout_month IS NULL)"
)
CK_NOT_FOR_SELF = (
    "beneficiary_user_id IS NULL OR beneficiary_user_id <> requester_user_id"
)
CK_NOT_OWN_DECISION = (
    "decided_by IS NULL OR (decided_by <> requester_user_id "
    "AND decided_by IS DISTINCT FROM beneficiary_user_id)"
)
CK_NOT_OWN_ENDORSEMENT = (
    "endorsed_by IS NULL OR (endorsed_by <> requester_user_id "
    "AND endorsed_by IS DISTINCT FROM beneficiary_user_id)"
)
CK_DECIDED = (
    "status NOT IN ('approved', 'rejected', 'returned') "
    "OR (decided_by IS NOT NULL AND decided_at IS NOT NULL)"
)
CK_SUPERVISOR_STEP = "status <> 'pending_supervisor' OR supervisor_user_id IS NOT NULL"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS approval_requests (
    id SERIAL PRIMARY KEY,
    kind VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL,
    title VARCHAR({TITLE_MAX_LENGTH}) NOT NULL,
    purpose TEXT NOT NULL,
    amount NUMERIC(12, 2) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'PLN',
    amount_basis VARCHAR(5) NOT NULL DEFAULT 'gross',
    recurrence VARCHAR(10) NOT NULL DEFAULT 'once',
    payer VARCHAR(20) NULL,
    link_url VARCHAR({LINK_MAX_LENGTH}) NULL,
    needed_by DATE NULL,
    starts_on DATE NULL,
    ends_on DATE NULL,
    beneficiary_user_id INTEGER NULL REFERENCES users(id) ON DELETE RESTRICT,
    payout_year SMALLINT NULL,
    payout_month SMALLINT NULL,
    requester_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    supervisor_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    needs_final BOOLEAN NOT NULL DEFAULT true,
    endorsed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    endorsed_at TIMESTAMPTZ NULL,
    endorse_note TEXT NULL,
    decided_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    decided_at TIMESTAMPTZ NULL,
    decided_amount NUMERIC(12, 2) NULL,
    decision_note TEXT NULL,
    decision_channel VARCHAR(12) NULL,
    bonus_id INTEGER NULL REFERENCES hr_bonuses(id) ON DELETE SET NULL,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_approval_requests_kind CHECK ({CK_KIND}),
    CONSTRAINT ck_approval_requests_status CHECK ({CK_STATUS}),
    CONSTRAINT ck_approval_requests_recurrence CHECK ({CK_RECURRENCE}),
    CONSTRAINT ck_approval_requests_basis CHECK ({CK_BASIS}),
    CONSTRAINT ck_approval_requests_payer CHECK ({CK_PAYER}),
    CONSTRAINT ck_approval_requests_currency CHECK ({CK_CURRENCY}),
    CONSTRAINT ck_approval_requests_amount CHECK ({CK_AMOUNT}),
    CONSTRAINT ck_approval_requests_decided_amount CHECK ({CK_DECIDED_AMOUNT}),
    CONSTRAINT ck_approval_requests_channel CHECK ({CK_CHANNEL}),
    CONSTRAINT ck_approval_requests_bonus_shape CHECK ({CK_BONUS_SHAPE}),
    CONSTRAINT ck_approval_requests_not_for_self CHECK ({CK_NOT_FOR_SELF}),
    CONSTRAINT ck_approval_requests_not_own_decision CHECK ({CK_NOT_OWN_DECISION}),
    CONSTRAINT ck_approval_requests_not_own_endorsement CHECK ({CK_NOT_OWN_ENDORSEMENT}),
    CONSTRAINT ck_approval_requests_decided CHECK ({CK_DECIDED}),
    CONSTRAINT ck_approval_requests_supervisor_step CHECK ({CK_SUPERVISOR_STEP})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

PENDING_WHERE = f"status IN ({quoted(PENDING_STATUSES)})"
APPROVED_WHERE = "status = 'approved'"

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_approval_requests_requester "
    "ON approval_requests (requester_user_id, submitted_at)",
    "CREATE INDEX IF NOT EXISTS ix_approval_requests_pending "
    f"ON approval_requests (status, supervisor_user_id) WHERE {PENDING_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_approval_requests_decided "
    f"ON approval_requests (kind, decided_at) WHERE {APPROVED_WHERE}",
)

CONSTRAINT_DDL: tuple[str, ...] = ()
DATA_DDL: tuple[str, ...] = ()
TABLES: tuple[str, ...] = ("approval_requests",)
DOWNGRADE_DDL: tuple[str, ...] = ()

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
