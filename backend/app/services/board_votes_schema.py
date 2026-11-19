"""Uchwały Rady w trybie pisemnym (R6): SQL migracji ``0736_board_votes``
i lustra entrypointu.

Projekt statutu (akt NWZ z 16.09.2025, § 25) — decyzja Artura 18.11.2026,
żeby budować na projekcie, zanim znajdzie się tekst przyjęty 24.11.2025:

* ust. 4 — uchwała pisemna / e-mailem ważna, gdy projekt dostali wszyscy
  członkowie Rady i głosowała co najmniej połowa,
* ust. 1 — zwykła większość głosów oddanych, przy remisie głos
  Przewodniczącego,
* ust. 5 — tryb wyłączony dla wyboru Przewodniczącego i Wiceprzewodniczącego
  Rady oraz powołania, odwołania i zawieszenia członka Zarządu.

``board_votes`` — uchwała: projekt, termin, skład Rady w chwili wysłania
(``member_ids``: „wszyscy dostali projekt”), Przewodniczący, wynik.
``board_vote_ballots`` — głos członka (za / przeciw / wstrzymuję się).
"""

from __future__ import annotations

STATUSES: tuple[str, ...] = ("open", "closed", "withdrawn")
CHOICES: tuple[str, ...] = ("for", "against", "abstain")
TITLE_MAX = 255
NUMBER_MAX = 64


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


CK_STATUS = f"status IN ({_quoted(STATUSES)})"
CK_CHOICE = f"choice IN ({_quoted(CHOICES)})"
CK_MEMBERS = "jsonb_typeof(member_ids) = 'array'"
CK_RESULT = "result IS NULL OR jsonb_typeof(result) = 'object'"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS board_votes (
    id SERIAL PRIMARY KEY,
    number VARCHAR({NUMBER_MAX}) NULL,
    title VARCHAR({TITLE_MAX}) NOT NULL,
    draft TEXT NOT NULL,
    document_id INTEGER NULL REFERENCES board_documents(id) ON DELETE SET NULL,
    meeting_id INTEGER NULL REFERENCES board_meetings(id) ON DELETE SET NULL,
    deadline DATE NOT NULL,
    status VARCHAR(12) NOT NULL DEFAULT 'open',
    member_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    chair_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    result JSONB NULL,
    resolution_document_id INTEGER NULL REFERENCES board_documents(id) ON DELETE SET NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    closed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ NULL,
    CONSTRAINT ck_board_votes_status CHECK ({CK_STATUS}),
    CONSTRAINT ck_board_votes_members CHECK ({CK_MEMBERS}),
    CONSTRAINT ck_board_votes_result CHECK ({CK_RESULT})
)""",
    f"""CREATE TABLE IF NOT EXISTS board_vote_ballots (
    id SERIAL PRIMARY KEY,
    vote_id INTEGER NOT NULL REFERENCES board_votes(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    choice VARCHAR(8) NOT NULL,
    cast_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_board_vote_ballots_choice CHECK ({CK_CHOICE})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_board_votes_status_deadline "
    "ON board_votes (status, deadline)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_board_vote_ballots_vote_user "
    "ON board_vote_ballots (vote_id, user_id)",
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

TABLES: tuple[str, ...] = ("board_votes", "board_vote_ballots")

DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP TABLE IF EXISTS board_vote_ballots",
    "DROP TABLE IF EXISTS board_votes",
)
