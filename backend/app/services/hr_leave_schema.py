"""„Ludzie w NEXUSIE” — Urlopy i zastępstwa: SQL migracji ``0457_hr_leave`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0457_hr_leave.py`` i ``entrypoint.sh``
(przez ``app/services/hr_schema_bundle.py``). Zakres: wnioski urlopowe (dzień per wiersz), akceptacje, zastępstwa, kolejka operacji Microsoft 365, stan skrzynek.

Kontrakt modułu (czyta go agregator i test łańcucha):

* ``TABLE_DDL`` — ``CREATE TABLE IF NOT EXISTS`` nowych tabel (VARCHAR + CHECK,
  bez nowych typów enum),
* ``COLUMN_DDL`` — ``ALTER TABLE … ADD COLUMN IF NOT EXISTS`` w istniejących tabelach,
* ``INDEX_DDL`` — ``CREATE [UNIQUE] INDEX IF NOT EXISTS``,
* ``CONSTRAINT_DDL`` — ograniczenia dokładane do ISTNIEJĄCYCH tabel (idempotentne bloki ``DO``),
* ``DATA_DDL`` — zasiewy i znaczniki jednorazowe (idempotentne),
* ``TABLES`` — nowe tabele w kolejności tworzenia (downgrade kasuje odwrotnie),
* ``DOWNGRADE_DDL`` — sprzątanie kolumn/ograniczeń w istniejących tabelach.

Każda instrukcja musi być idempotentna: entrypoint wykonuje je przy każdym starcie.

Tabele:

* ``leave_requests`` — wniosek (id UUID zachowany z Compassa przy imporcie).
  Naprawy błędów Compassa siedzą w CHECK-ach: nikt nie decyduje o własnym
  wniosku (``decided_by <> user_id``), zgoda na przekierowanie poczty istnieje
  tylko z zastępcą (ustawia ją wyłącznie sama osoba — pilnuje serwis).
* ``leave_request_days`` — dzień roboczy wniosku per wiersz. ``active`` =
  wniosek oczekuje albo jest zatwierdzony; częściowy UNIQUE ``(user_id, day)
  WHERE active`` kończy nakładki wniosków. ``paid`` = dzień z puli płatnej
  (tylko rodzaje puli: urlop wypoczynkowy i na żądanie) — zużycie puli liczy
  się po ``paid`` i po roku KALENDARZOWYM dnia (urlop przez Nowy Rok dzieli
  się na dwa lata; dni bezpłatne B2B nie zjadają puli).
* ``hr_m365_operations`` — kolejka operacji Microsoft Graph (autoodpowiedź,
  wydarzenie w kalendarzu, reguła przekierowania). Ten etap tylko zapisuje
  operacje (``dedupe_key`` = jedna operacja logiczna raz); wykonuje je pętla
  z kolejnego etapu, lokalnie w trybie symulacji (``simulated_request``).
* ``hr_m365_mailbox_state`` — stan skrzynki osoby (własna autoodpowiedź,
  ostatnie uzgodnienie, błąd).
"""

from __future__ import annotations

LEAVE_TYPES: tuple[str, ...] = (
    "vacation",
    "on_demand",
    "occasional",
    "childcare",
    "care_leave",
    "force_majeure",
    "sick_leave",
    "maternity",
    "paternity",
    "parental_leave",
    "childrearing",
    "unpaid_leave",
    "blood_donation",
    "training",
    "holiday_in_lieu",
    "other",
)
LEAVE_STATUSES: tuple[str, ...] = ("pending", "approved", "rejected", "cancelled")
ACTIVE_STATUSES: tuple[str, ...] = ("pending", "approved")
HALF_DAYS: tuple[str, ...] = ("morning", "afternoon")
LEAVE_SOURCES: tuple[str, ...] = ("self", "on_behalf", "outlook_oof", "compass_import")

M365_OPERATION_KINDS: tuple[str, ...] = (
    "set_oof",
    "clear_oof",
    "calendar_event_upsert",
    "calendar_event_delete",
    "forward_rule_open",
    "forward_rule_close",
)
M365_OPERATION_STATUSES: tuple[str, ...] = (
    "pending",
    "running",
    "done",
    "failed",
    "skipped",
    "simulated",
)


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


CK_LEAVE_TYPE = f"leave_type IN ({quoted(LEAVE_TYPES)})"
CK_LEAVE_STATUS = f"status IN ({quoted(LEAVE_STATUSES)})"
CK_LEAVE_DATES = "end_date >= start_date"
CK_LEAVE_HALF_DAY = (
    f"half_day IS NULL OR (half_day IN ({quoted(HALF_DAYS)}) AND start_date = end_date)"
)
CK_LEAVE_SUBSTITUTE = "substitute_user_id IS NULL OR substitute_user_id <> user_id"
CK_LEAVE_FORWARD_CONSENT = (
    "forward_mail_consent = false OR substitute_user_id IS NOT NULL"
)
CK_LEAVE_NO_SELF_DECISION = "decided_by IS NULL OR decided_by <> user_id"
CK_LEAVE_DAYS = "paid_days >= 0 AND unpaid_days >= 0"
CK_LEAVE_SOURCE = f"source IN ({quoted(LEAVE_SOURCES)})"
CK_DAY_FRACTION = "fraction IN (0.5, 1.0)"
CK_M365_KIND = f"kind IN ({quoted(M365_OPERATION_KINDS)})"
CK_M365_STATUS = f"status IN ({quoted(M365_OPERATION_STATUSES)})"
CK_M365_ATTEMPTS = "attempts >= 0"

#: Częściowy UNIQUE — jedna aktywna nieobecność osoby na dzień (koniec nakładek).
ACTIVE_DAY_WHERE = "active"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS leave_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    leave_type VARCHAR(24) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    half_day VARCHAR(16) NULL,
    note TEXT NULL,
    substitute_user_id INTEGER NULL REFERENCES users(id) ON DELETE RESTRICT,
    forward_mail_consent BOOLEAN NOT NULL DEFAULT false,
    oof_internal_message TEXT NULL,
    oof_external_message TEXT NULL,
    paid_days NUMERIC(5,1) NOT NULL DEFAULT 0,
    unpaid_days NUMERIC(5,1) NOT NULL DEFAULT 0,
    decided_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    decided_at TIMESTAMPTZ NULL,
    decision_note TEXT NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    source VARCHAR(16) NOT NULL DEFAULT 'self',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_leave_requests_type CHECK ({CK_LEAVE_TYPE}),
    CONSTRAINT ck_leave_requests_status CHECK ({CK_LEAVE_STATUS}),
    CONSTRAINT ck_leave_requests_dates CHECK ({CK_LEAVE_DATES}),
    CONSTRAINT ck_leave_requests_half_day CHECK ({CK_LEAVE_HALF_DAY}),
    CONSTRAINT ck_leave_requests_substitute CHECK ({CK_LEAVE_SUBSTITUTE}),
    CONSTRAINT ck_leave_requests_forward_consent CHECK ({CK_LEAVE_FORWARD_CONSENT}),
    CONSTRAINT ck_leave_requests_no_self_decision CHECK ({CK_LEAVE_NO_SELF_DECISION}),
    CONSTRAINT ck_leave_requests_days CHECK ({CK_LEAVE_DAYS}),
    CONSTRAINT ck_leave_requests_source CHECK ({CK_LEAVE_SOURCE})
)""",
    f"""CREATE TABLE IF NOT EXISTS leave_request_days (
    id BIGSERIAL PRIMARY KEY,
    leave_request_id UUID NOT NULL REFERENCES leave_requests(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    day DATE NOT NULL,
    fraction NUMERIC(2,1) NOT NULL DEFAULT 1.0,
    paid BOOLEAN NOT NULL DEFAULT false,
    active BOOLEAN NOT NULL DEFAULT true,
    CONSTRAINT uq_leave_request_days_request_day UNIQUE (leave_request_id, day),
    CONSTRAINT ck_leave_request_days_fraction CHECK ({CK_DAY_FRACTION})
)""",
    f"""CREATE TABLE IF NOT EXISTS hr_m365_operations (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    leave_request_id UUID NULL REFERENCES leave_requests(id) ON DELETE SET NULL,
    kind VARCHAR(32) NOT NULL,
    dedupe_key VARCHAR(200) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    attempts SMALLINT NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error TEXT NULL,
    simulated_request JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    done_at TIMESTAMPTZ NULL,
    CONSTRAINT uq_hr_m365_operations_dedupe UNIQUE (dedupe_key),
    CONSTRAINT ck_hr_m365_operations_kind CHECK ({CK_M365_KIND}),
    CONSTRAINT ck_hr_m365_operations_status CHECK ({CK_M365_STATUS}),
    CONSTRAINT ck_hr_m365_operations_attempts CHECK ({CK_M365_ATTEMPTS})
)""",
    """CREATE TABLE IF NOT EXISTS hr_m365_mailbox_state (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    custom_oof_detected BOOLEAN NOT NULL DEFAULT false,
    last_reconciled_at TIMESTAMPTZ NULL,
    last_error TEXT NULL,
    state JSONB NOT NULL DEFAULT '{}'::jsonb
)""",
)
COLUMN_DDL: tuple[str, ...] = ()
INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_leave_requests_user_start "
    "ON leave_requests (user_id, start_date)",
    "CREATE INDEX IF NOT EXISTS ix_leave_requests_status_start "
    "ON leave_requests (status, start_date)",
    "CREATE INDEX IF NOT EXISTS ix_leave_requests_substitute "
    "ON leave_requests (substitute_user_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_leave_request_days_user_day_active "
    f"ON leave_request_days (user_id, day) WHERE {ACTIVE_DAY_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_leave_request_days_day ON leave_request_days (day)",
    "CREATE INDEX IF NOT EXISTS ix_hr_m365_operations_due "
    "ON hr_m365_operations (status, next_attempt_at)",
    "CREATE INDEX IF NOT EXISTS ix_hr_m365_operations_leave "
    "ON hr_m365_operations (leave_request_id)",
)
CONSTRAINT_DDL: tuple[str, ...] = ()
DATA_DDL: tuple[str, ...] = ()
TABLES: tuple[str, ...] = (
    "leave_requests",
    "leave_request_days",
    "hr_m365_operations",
    "hr_m365_mailbox_state",
)
DOWNGRADE_DDL: tuple[str, ...] = ()

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
