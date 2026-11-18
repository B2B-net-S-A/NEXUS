"""Posiedzenia Rady (R5): SQL migracji ``0735_board_meetings`` i lustra entrypointu.

``board_meetings`` — posiedzenie Rady nadzorczej: data, tryb (posiedzenie,
zdalnie — art. 388 § 3 KSH, pisemnie / obiegiem), porządek obrad z
dokumentami, protokół (wiersz z ``board_documents``) i **pakiet**: zamrożony
w chwili wysłania obraz liczb (pulpit, budżet, analiza, dokumenty i wpisy
KRS od poprzedniego posiedzenia) — informacja Zarządu dla Rady (art. 380¹
KSH), której nie zmienia późniejszy import faktur.

Admin (Zarząd) prowadzi rejestr i zamraża pakiet; Rada czyta.
"""

from __future__ import annotations

KINDS: tuple[str, ...] = ("meeting", "remote", "circular")
STATUSES: tuple[str, ...] = ("planned", "held", "cancelled")
TITLE_MAX = 255
PLACE_MAX = 255
AGENDA_MAX = 30


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


CK_KIND = f"kind IN ({_quoted(KINDS)})"
CK_STATUS = f"status IN ({_quoted(STATUSES)})"
CK_AGENDA = "jsonb_typeof(agenda) = 'array'"
CK_PACK = "pack IS NULL OR jsonb_typeof(pack) = 'object'"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS board_meetings (
    id SERIAL PRIMARY KEY,
    held_on DATE NOT NULL,
    kind VARCHAR(12) NOT NULL DEFAULT 'meeting',
    status VARCHAR(12) NOT NULL DEFAULT 'planned',
    title VARCHAR({TITLE_MAX}) NOT NULL,
    place VARCHAR({PLACE_MAX}) NULL,
    agenda JSONB NOT NULL DEFAULT '[]'::jsonb,
    note TEXT NULL,
    minutes_document_id INTEGER NULL REFERENCES board_documents(id) ON DELETE SET NULL,
    pack JSONB NULL,
    pack_frozen_at TIMESTAMPTZ NULL,
    pack_frozen_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_board_meetings_kind CHECK ({CK_KIND}),
    CONSTRAINT ck_board_meetings_status CHECK ({CK_STATUS}),
    CONSTRAINT ck_board_meetings_agenda CHECK ({CK_AGENDA}),
    CONSTRAINT ck_board_meetings_pack CHECK ({CK_PACK})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_board_meetings_held_on "
    "ON board_meetings (held_on DESC)",
)

CONSTRAINT_DDL: tuple[str, ...] = ()
DATA_DDL: tuple[str, ...] = ()

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)

TABLES: tuple[str, ...] = ("board_meetings",)

DOWNGRADE_DDL: tuple[str, ...] = ("DROP TABLE IF EXISTS board_meetings",)
