"""Back office na sprawach (decyzje Artura 02.11.2026): SQL migracji ``0637_back_office`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0637_back_office.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Kontrakt
modułu jak w pozostałych ``*_schema.py``; każda instrukcja idempotentna.

Praca całego back office'u (Opieka, Finanse, Umowy, Zamówienia) jest kolejką
kart. Rekord źródłowy (sprawa, raport godzin, premia, zamówienie) zostaje
prawdą: karta nigdy nie zmienia go sama, a akcept na karcie woła istniejącą
ścieżkę. Premia czy mail z zamówieniem nie mają gdzie trzymać osoby i terminu,
stąd osobna tabela (precedens: ``care_board_states``).

Tabele:

* ``bo_cards`` — karta na tablicy. ``source_key`` UNIQUE czyni synchronizację
  idempotentną. Krok wejścia albo wyjścia to karta-dziecko (``parent_card_id``)
  w kolumnie swojego zespołu. Tytuł i ``meta`` nie niosą kwot: kwotę dostaje
  przy odczycie tylko osoba z Płacami.
* ``bo_card_events`` — historia na karcie: kto, co i kiedy.
* ``bo_team_members`` — skład czterech zespołów. Kierownik zostaje
  w ``app_settings['hr_divisions']`` (head back office), zastępca
  w ``app_settings['back_office']``.
"""

from __future__ import annotations

BACK_OFFICE_SETTING = "back_office"

#: Zespoły w kolejności zakładek.
TEAMS: tuple[str, ...] = ("care", "finance", "contracts", "orders")
#: Kolumny zespołu (decyzja: po cztery, po typie pracy).
TEAM_LANES: dict[str, tuple[str, ...]] = {
    "care": ("help", "entry", "bench", "exit"),
    "finance": ("timesheet", "bonus", "invoice", "changes"),
    "contracts": ("draft", "sign", "annex", "ending"),
    "orders": ("mail", "gap", "extend", "md"),
}
#: ``triage`` to „Do rozdzielenia” u kierownika: reguły i AI nie były pewne.
LANES: tuple[str, ...] = (
    *(lane for lanes in TEAM_LANES.values() for lane in lanes),
    "triage",
)
TRIAGE_LANE = "triage"
#: ``done`` to stan końcowy; historia zostaje, karta znika z tablicy.
STATES: tuple[str, ...] = ("new", "in_progress", "waiting", "done")
SOURCE_KINDS: tuple[str, ...] = (
    "case",
    "step",
    "bench",
    "contact",
    "timesheet",
    "bonus",
    "changes",
    "draft",
    "sign",
    "ending",
    "mail",
    "gap",
    "extend",
    "md",
    "document",
)
#: Zbiorczy dzwonek dla kierownika i przydział karty bez sprawy. Do osobistych
#: typów modułu powiadomień dopina je ``hr_notification_schema``.
NOTIFICATION_TYPES: tuple[str, ...] = ("back_office_escalated", "back_office_assigned")
ENUM_DDL: tuple[str, ...] = tuple(
    f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'"
    for value in NOTIFICATION_TYPES
)
SOURCE_KEY_MAX = 160
TITLE_MAX = 200
NOTE_MAX = 2_000


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


CK_CARD_TEAM = f"team IN ({quoted(TEAMS)})"
CK_CARD_LANE = f"lane IN ({quoted(LANES)})"
CK_CARD_STATE = f"state IN ({quoted(STATES)})"
CK_CARD_SOURCE_KIND = f"source_kind IN ({quoted(SOURCE_KINDS)})"
CK_CARD_TITLE = "btrim(title) <> ''"
CK_CARD_CLOSED = "(state = 'done') = (closed_at IS NOT NULL)"
CK_CARD_META = "jsonb_typeof(meta) = 'object'"
CK_EVENT_DETAILS = "jsonb_typeof(details) = 'object'"
CK_MEMBER_TEAM = f"team IN ({quoted(TEAMS)})"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS bo_cards (
    id SERIAL PRIMARY KEY,
    team VARCHAR(12) NOT NULL,
    lane VARCHAR(12) NOT NULL,
    lane_locked BOOLEAN NOT NULL DEFAULT FALSE,
    source_kind VARCHAR(12) NOT NULL,
    source_key VARCHAR({SOURCE_KEY_MAX}) NOT NULL,
    parent_card_id INTEGER NULL REFERENCES bo_cards(id) ON DELETE CASCADE,
    step_order SMALLINT NULL,
    case_id INTEGER NULL REFERENCES admin_cases(id) ON DELETE SET NULL,
    contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE SET NULL,
    client_id INTEGER NULL REFERENCES clients(id) ON DELETE SET NULL,
    subject_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    title VARCHAR({TITLE_MAX}) NOT NULL,
    person VARCHAR(200) NULL,
    client_label VARCHAR(200) NULL,
    state VARCHAR(12) NOT NULL DEFAULT 'new',
    waiting_on VARCHAR(200) NULL,
    assignee_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    substituting BOOLEAN NOT NULL DEFAULT FALSE,
    due_on DATE NULL,
    href VARCHAR(300) NULL,
    meta JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    taken_at TIMESTAMPTZ NULL,
    escalated_at TIMESTAMPTZ NULL,
    priority_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    priority_until DATE NULL,
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ NULL,
    CONSTRAINT uq_bo_cards_source_key UNIQUE (source_key),
    CONSTRAINT ck_bo_cards_team CHECK ({CK_CARD_TEAM}),
    CONSTRAINT ck_bo_cards_lane CHECK ({CK_CARD_LANE}),
    CONSTRAINT ck_bo_cards_state CHECK ({CK_CARD_STATE}),
    CONSTRAINT ck_bo_cards_source_kind CHECK ({CK_CARD_SOURCE_KIND}),
    CONSTRAINT ck_bo_cards_title CHECK ({CK_CARD_TITLE}),
    CONSTRAINT ck_bo_cards_closed CHECK ({CK_CARD_CLOSED}),
    CONSTRAINT ck_bo_cards_meta CHECK ({CK_CARD_META})
)""",
    f"""CREATE TABLE IF NOT EXISTS bo_card_events (
    id SERIAL PRIMARY KEY,
    card_id INTEGER NOT NULL REFERENCES bo_cards(id) ON DELETE CASCADE,
    actor_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(40) NOT NULL,
    details JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_bo_card_events_details CHECK ({CK_EVENT_DETAILS})
)""",
    f"""CREATE TABLE IF NOT EXISTS bo_team_members (
    team VARCHAR(12) NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    added_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (team, user_id),
    CONSTRAINT ck_bo_team_members_team CHECK ({CK_MEMBER_TEAM})
)""",
)

#: Kierunek wiadomości w sprawie: odpowiedź ze sprawy to ``out``. Stare wiersze
#: dostają ``in``; własne maile w wątku czytnik zapisuje już jako ``out``.
MESSAGE_DIRECTIONS: tuple[str, ...] = ("in", "out")
CK_MESSAGE_DIRECTION = f"direction IN ({quoted(MESSAGE_DIRECTIONS)})"
COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE admin_case_messages ADD COLUMN IF NOT EXISTS direction "
    "VARCHAR(3) NOT NULL DEFAULT 'in'",
)

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_bo_cards_board "
    "ON bo_cards (team, lane, state) WHERE state <> 'done'",
    "CREATE INDEX IF NOT EXISTS ix_bo_cards_kind ON bo_cards (source_kind, state)",
    "CREATE INDEX IF NOT EXISTS ix_bo_cards_assignee "
    "ON bo_cards (assignee_user_id, state)",
    "CREATE INDEX IF NOT EXISTS ix_bo_cards_parent ON bo_cards (parent_card_id)",
    "CREATE INDEX IF NOT EXISTS ix_bo_cards_case ON bo_cards (case_id)",
    "CREATE INDEX IF NOT EXISTS ix_bo_card_events_card "
    "ON bo_card_events (card_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_bo_team_members_user ON bo_team_members (user_id)",
)

CONSTRAINT_DDL: tuple[str, ...] = (
    f"""DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_admin_case_messages_direction'
    ) THEN
        ALTER TABLE admin_case_messages
        ADD CONSTRAINT ck_admin_case_messages_direction CHECK ({CK_MESSAGE_DIRECTION});
    END IF;
END $$""",
)
DATA_DDL: tuple[str, ...] = ()

TABLES: tuple[str, ...] = ("bo_cards", "bo_card_events", "bo_team_members")
DOWNGRADE_DDL: tuple[str, ...] = (
    "ALTER TABLE admin_case_messages DROP CONSTRAINT IF EXISTS "
    "ck_admin_case_messages_direction",
    "ALTER TABLE admin_case_messages DROP COLUMN IF EXISTS direction",
)

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
