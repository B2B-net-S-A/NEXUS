"""Informacja zwrotna o wadach rozliczenia: SQL migracji ``0774_settlement_feedback``
i lustra entrypointu (przez ``app/services/hr_schema_bundle.py``).

Próba IX–X 2026 (powtórka 7, 24.11.2026): uwaga NEXUS-a o wadzie RCP była
prawdziwa, ale nie docierała do osoby, która ma ją poprawić (konsultant,
akceptujący po stronie klienta, opiekun). Tabela ``client_settlement_feedback``
to jeden wiersz na (kontrakt, miesiąc, wada):

* ``code``: klucz wady z katalogu ``client_settlements/feedback.CATALOG``,
* ``audience``: kto poprawia — ``consultant``, ``client`` (akceptujący
  u klienta) albo ``owner`` (opiekun kontraktu, opiekun klienta, DL klienta),
* ``first_seen_on`` / ``last_seen_on`` / ``resolved_on``: kiedy NEXUS widział
  wadę i kiedy zniknęła (nowy plik bez uwagi, przyjęcie przez Finanse),
* ``last_sent_on`` i ``send_count``: rezerwacja przed wysyłką i licznik,
* ``sends``: dziennik „wysłałbym / wysłałem: komu, co, kiedy” (JSONB, lista),
  także w trybie na sucho — z niego powtórka próby liczy komunikaty.

Unikat (kontrakt, miesiąc, wada) to „jeden komunikat na wadę i miesiąc”:
wada, która wraca po poprawce, otwiera ten sam wiersz z powrotem.
"""

from __future__ import annotations

from app.services.consultant_portal_schema import quoted

AUDIENCES: tuple[str, ...] = ("consultant", "client", "owner")

#: Dzwonek opiekuna: wada do przekazania konsultantowi albo do poprawy przez niego.
NOTIFICATION_TYPE = "settlement_feedback"

CK_AUDIENCE = f"audience IN ({quoted(AUDIENCES)})"
CK_SENDS_ARRAY = "jsonb_typeof(sends) = 'array'"
CK_SEND_COUNT = "send_count >= 0"
#: Kod wady z katalogu, np. ``proof.signed_pdf`` albo ``amount.protocol``.
CODE_MAX = 40
DETAIL_MAX = 500

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS client_settlement_feedback (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    client_id INTEGER NULL REFERENCES clients(id) ON DELETE SET NULL,
    period_month VARCHAR(7) NOT NULL,
    code VARCHAR({CODE_MAX}) NOT NULL,
    audience VARCHAR(12) NOT NULL,
    detail VARCHAR({DETAIL_MAX}) NULL,
    first_seen_on DATE NOT NULL,
    last_seen_on DATE NOT NULL,
    resolved_on DATE NULL,
    last_sent_on DATE NULL,
    send_count INTEGER NOT NULL DEFAULT 0,
    sends JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_client_settlement_feedback_defect
        UNIQUE (contract_id, period_month, code),
    CONSTRAINT ck_client_settlement_feedback_audience CHECK ({CK_AUDIENCE}),
    CONSTRAINT ck_client_settlement_feedback_sends CHECK ({CK_SENDS_ARRAY}),
    CONSTRAINT ck_client_settlement_feedback_count CHECK ({CK_SEND_COUNT})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_client_settlement_feedback_month "
    "ON client_settlement_feedback (period_month, client_id)",
)

CONSTRAINT_DDL: tuple[str, ...] = ()
DATA_DDL: tuple[str, ...] = ()

ENUM_DDL: tuple[str, ...] = (
    f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{NOTIFICATION_TYPE}'",
)

TABLES: tuple[str, ...] = ("client_settlement_feedback",)

ALL_DDL: tuple[str, ...] = (*TABLE_DDL, *COLUMN_DDL, *INDEX_DDL)
