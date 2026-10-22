"""„Ludzie w NEXUSIE” — tablica opieki i popyt dla Delivery Leada: SQL migracji ``0509_care_board`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0509_care_board.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Kontrakt
modułu jak w pozostałych ``*_schema.py``; każda instrukcja idempotentna.

Decyzje Artura z 22.10.2026 (przebudowa „Opieki nad konsultantami”):

* **„Do zrobienia” = kanban** — karty opieki (rozmowy, opinie menedżerów,
  decyzje o przepięciu, popyt) liczone przy odczycie, a ich miejsce na
  tablicy (W toku z terminem, Czeka na kogoś z datą ponowienia, notatka)
  pamięta ``care_board_states``: jeden wiersz na klucz karty
  (``contact:plan:<id>``, ``feedback:<kontakt>``, ``decision:<id>``,
  ``demand:<klient>:<rozmowa>``). Karta w „Nowa” nie ma wiersza —
  przeniesienie do „Nowa” kasuje wiersz. Rozstrzygnięty popyt
  (``outcome``) stoi w kolumnie ``done`` albo, przy „nie teraz”, w ``waiting``
  z datą powrotu. Kolumna w bazie nazywa się ``board_column`` (``column`` to
  słowo zastrzeżone SQL); w JSON tras to ``column``.
* **Okno „Rozmowa”** zapisuje kartę technologiczną z rozmowy —
  ``tech_cards.care_conversation_id`` mówi, z której rozmowy powstała karta
  (Karta konsultanta pokazuje źródło wiedzy o projekcie: rozmowa albo karta).
* **Popyt → Delivery Lead** (nie ATLAS): dzwonek ``care_demand_signal``
  (sekcja Delivery) do aktywnych DL klienta, gdy opiekun zapisze rozmowę
  z „klient zatrudnia”. Najwyżej jeden na (DL, klient, dział) w 7 dni.
"""

from __future__ import annotations

#: Dzwonek do Delivery Leadów klienta. Do ``DELIVERY_TYPES`` modułu
#: powiadomień dopina go ``hr_notification_schema``.
NOTIFICATION_TYPES: tuple[str, ...] = ("care_demand_signal",)
ENUM_DDL: tuple[str, ...] = tuple(
    f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'"
    for value in NOTIFICATION_TYPES
)

BOARD_KINDS: tuple[str, ...] = ("contact", "feedback", "decision", "demand")
#: ``done`` tylko dla rozstrzygniętego popytu; „Nowa” = brak wiersza.
BOARD_COLUMNS: tuple[str, ...] = ("in_progress", "waiting", "done")
DEMAND_OUTCOMES: tuple[str, ...] = ("confirmed", "not_now", "stale")
KEY_MAX = 120
BOARD_NOTE_MAX = 500


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


CK_BOARD_KIND = f"kind IN ({quoted(BOARD_KINDS)})"
CK_BOARD_COLUMN = f"board_column IN ({quoted(BOARD_COLUMNS)})"
CK_BOARD_OUTCOME = f"outcome IS NULL OR outcome IN ({quoted(DEMAND_OUTCOMES)})"
CK_BOARD_NOTE = f"note IS NULL OR char_length(note) <= {BOARD_NOTE_MAX}"
#: „W toku” wymaga terminu albo rozstrzygnięcia, „Czeka” — daty ponowienia.
CK_BOARD_WAITING = "board_column <> 'waiting' OR retry_on IS NOT NULL"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS care_board_states (
    id SERIAL PRIMARY KEY,
    key VARCHAR({KEY_MAX}) NOT NULL,
    kind VARCHAR(16) NOT NULL,
    board_column VARCHAR(16) NOT NULL,
    scheduled_at TIMESTAMPTZ NULL,
    retry_on DATE NULL,
    outcome VARCHAR(16) NULL,
    job_id INTEGER NULL,
    note VARCHAR({BOARD_NOTE_MAX}) NULL,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_care_board_states_kind CHECK ({CK_BOARD_KIND}),
    CONSTRAINT ck_care_board_states_column CHECK ({CK_BOARD_COLUMN}),
    CONSTRAINT ck_care_board_states_outcome CHECK ({CK_BOARD_OUTCOME}),
    CONSTRAINT ck_care_board_states_note CHECK ({CK_BOARD_NOTE}),
    CONSTRAINT ck_care_board_states_waiting CHECK ({CK_BOARD_WAITING})
)""",
)

#: Źródła informacji o popycie (jak ``tech_cards.hiring_source``).
HIRING_SOURCES: tuple[str, ...] = ("widzial", "slyszal", "plotka")
CK_CONVERSATION_HIRING_SOURCE = (
    "client_hiring_source IS NULL OR client_hiring_source IN "
    f"({quoted(HIRING_SOURCES)})"
)

COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE tech_cards ADD COLUMN IF NOT EXISTS care_conversation_id "
    "INTEGER NULL REFERENCES care_conversations(id) ON DELETE SET NULL",
    # „Klient zatrudnia” bez „Co u klienta” (bez karty): role i źródło
    # zostają przy rozmowie, popyt czyta je, gdy rozmowa nie ma karty.
    "ALTER TABLE care_conversations ADD COLUMN IF NOT EXISTS client_hiring_roles "
    "JSONB NULL",
    "ALTER TABLE care_conversations ADD COLUMN IF NOT EXISTS client_hiring_source "
    "VARCHAR(16) NULL",
)

INDEX_DDL: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_care_board_states_key "
    "ON care_board_states (key)",
    "CREATE INDEX IF NOT EXISTS ix_care_board_states_kind "
    "ON care_board_states (kind, board_column)",
    "CREATE INDEX IF NOT EXISTS ix_tech_cards_care_conversation "
    "ON tech_cards (care_conversation_id) WHERE care_conversation_id IS NOT NULL",
)

CONSTRAINT_DDL: tuple[str, ...] = (
    "DO $$ BEGIN "
    "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'ck_care_conversations_hiring_source') THEN "
    "ALTER TABLE care_conversations ADD CONSTRAINT ck_care_conversations_hiring_source "
    f"CHECK ({CK_CONVERSATION_HIRING_SOURCE}); "
    "END IF; END $$",
)
DATA_DDL: tuple[str, ...] = ()
TABLES: tuple[str, ...] = ("care_board_states",)
DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP INDEX IF EXISTS ix_tech_cards_care_conversation",
    "ALTER TABLE tech_cards DROP COLUMN IF EXISTS care_conversation_id",
    "ALTER TABLE care_conversations DROP CONSTRAINT IF EXISTS "
    "ck_care_conversations_hiring_source",
    "ALTER TABLE care_conversations DROP COLUMN IF EXISTS client_hiring_source",
    "ALTER TABLE care_conversations DROP COLUMN IF EXISTS client_hiring_roles",
)

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
