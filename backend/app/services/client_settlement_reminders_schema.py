"""Przypomnienia o brakującym raporcie godzin: SQL migracji ``0763_settlement_reminders``
i lustra entrypointu (przez ``app/services/hr_schema_bundle.py``).

Rekomendacja 4 z makiet panelu Finansów (23.11.2026): w powtórce października
52 kontrakty nie miały raportu w poczcie rozliczeń, a Finanse nie miały akcji
„przypomnij”. Dziennik ``client_settlement_reminders`` to jeden wiersz na
(kontrakt, miesiąc, kanał, dzień wysyłki):

* ``channel``: ``consultant`` (mail do konsultanta przez ``portal_mail.send``,
  opiekun w kopii od 5. dnia roboczego) albo ``owner`` (dzwonek opiekuna
  kontraktu albo Delivery Leada klienta),
* ``step``: ``day3``, ``day5``, ``day7`` (dzień roboczy miesiąca po rozliczanym)
  albo ``manual`` (przycisk „Przypomnij” Finansów),
* ``outcome``: ``pending`` (rezerwacja przed wysyłką), ``sent``, ``simulated``
  (``HR_M365_MODE=simulate``), ``failed`` (transport odmówił albo wynik niepewny),
  ``blocked`` (wyłącznik portalu albo brak nadawcy w chwili wysyłki).

Unikat na dzień to bezpiecznik „bez powtórek tego samego dnia”: wiersz
powstaje przed wysyłką, a drugi przebieg (restart, drugi proces, klik Finansów
po automacie) odbija się od konfliktu i niczego nie wysyła.
"""

from __future__ import annotations

from app.services.consultant_portal_schema import quoted

STEPS: tuple[str, ...] = ("day3", "day5", "day7", "manual")
CHANNELS: tuple[str, ...] = ("consultant", "owner")
OUTCOMES: tuple[str, ...] = ("pending", "sent", "simulated", "failed", "blocked")

#: Dzwonek opiekuna z listą brakujących raportów (7. dzień roboczy i przycisk).
NOTIFICATION_TYPE = "settlement_report_missing"

CK_STEP = f"step IN ({quoted(STEPS)})"
CK_CHANNEL = f"channel IN ({quoted(CHANNELS)})"
CK_OUTCOME = f"outcome IN ({quoted(OUTCOMES)})"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS client_settlement_reminders (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    client_id INTEGER NULL REFERENCES clients(id) ON DELETE SET NULL,
    period_month VARCHAR(7) NOT NULL,
    step VARCHAR(8) NOT NULL,
    channel VARCHAR(12) NOT NULL,
    owner_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    outcome VARCHAR(12) NOT NULL DEFAULT 'pending',
    sent_on DATE NOT NULL,
    sent_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_client_settlement_reminders_day
        UNIQUE (contract_id, period_month, channel, sent_on),
    CONSTRAINT ck_client_settlement_reminders_step CHECK ({CK_STEP}),
    CONSTRAINT ck_client_settlement_reminders_channel CHECK ({CK_CHANNEL}),
    CONSTRAINT ck_client_settlement_reminders_outcome CHECK ({CK_OUTCOME})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_client_settlement_reminders_month "
    "ON client_settlement_reminders (period_month, client_id)",
)

CONSTRAINT_DDL: tuple[str, ...] = ()
DATA_DDL: tuple[str, ...] = ()

ENUM_DDL: tuple[str, ...] = (
    f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{NOTIFICATION_TYPE}'",
)

TABLES: tuple[str, ...] = ("client_settlement_reminders",)

ALL_DDL: tuple[str, ...] = (*TABLE_DDL, *COLUMN_DDL, *INDEX_DDL)
