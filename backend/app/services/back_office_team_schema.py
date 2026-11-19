"""Jeden zespół back office'u (decyzje Artura 10.11 i 19.11.2026): SQL migracji ``0743``.

JEDNO źródło instrukcji dla ``alembic/versions/0743_back_office_one_team.py``
i lustra entrypointu (przez ``app/services/hr_schema_bundle.py``). Każda
instrukcja idempotentna.

Zastępuje cztery zespoły po typie pracy (Opieka, Finanse, Umowy, Zamówienia
z 02.11): back office to jeden zespół, sprawę bierze pierwsza wolna osoba,
a dawne kolumny zespołów zostają na kartach jako etykiety (``bo_cards.team``
i ``lane`` się nie zmieniają).

* ``bo_members`` — skład zespołu z rolą (zastępca Heada, recepcja, księgowa,
  zespół) i przełącznikiem „przyjmuje rozmowy z portalu”. Head zostaje
  w ``app_settings['hr_divisions']``. Stara ``bo_team_members`` zostaje bez
  DROP-u, nikt jej już nie czyta.
* ``bo_cards.outside_team`` — sprawa przekazana do działu poza back office'em
  (kolumna „Na zewnątrz”, gdy stan karty to ``waiting``).
* ``bo_client_notes`` — ściąga klienta: jak u niego robimy rozliczenia, wejście
  nowej osoby, zamówienia i kontakty.
"""

from __future__ import annotations

from app.services.back_office_schema import quoted

#: Role w zespole (decyzja 10.11): zastępca to back-up Heada i kierownik kolejki.
MEMBER_ROLES: tuple[str, ...] = ("deputy", "reception", "accountant", "member")
#: Działy, do których back office wysyła sprawę, gdy sam nie da rady (10.11).
OUTSIDE_TEAMS: tuple[str, ...] = (
    "recruitment",
    "sales",
    "it",
    "hr",
    "accounting",
    "legal",
)
CLIENT_NOTE_BLOCKS: tuple[str, ...] = ("settlement", "onboarding", "orders", "contacts")
CLIENT_NOTE_MAX = 4_000

CK_MEMBER_ROLE = f"role IN ({quoted(MEMBER_ROLES)})"
# Bez warunku na stan: każda ścieżka zamknięcia (synchronizacja, krok, „Nie
# dotyczy”) musiałaby pamiętać o wyczyszczeniu działu. Tablica pokazuje „Na
# zewnątrz” tylko przy stanie ``waiting``.
CK_CARD_OUTSIDE = f"outside_team IS NULL OR outside_team IN ({quoted(OUTSIDE_TEAMS)})"
CK_NOTE_BLOCK = f"block IN ({quoted(CLIENT_NOTE_BLOCKS)})"
CK_NOTE_BODY = f"char_length(body) <= {CLIENT_NOTE_MAX}"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS bo_members (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(12) NOT NULL DEFAULT 'member',
    takes_calls BOOLEAN NOT NULL DEFAULT TRUE,
    added_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_bo_members_role CHECK ({CK_MEMBER_ROLE})
)""",
    f"""CREATE TABLE IF NOT EXISTS bo_client_notes (
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    block VARCHAR(12) NOT NULL,
    body TEXT NOT NULL,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (client_id, block),
    CONSTRAINT ck_bo_client_notes_block CHECK ({CK_NOTE_BLOCK}),
    CONSTRAINT ck_bo_client_notes_body CHECK ({CK_NOTE_BODY})
)""",
)
COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE bo_cards ADD COLUMN IF NOT EXISTS outside_team VARCHAR(16) NULL",
)
INDEX_DDL: tuple[str, ...] = (
    # Jeden zastępca naraz: drugi zapis „deputy” to błąd, nie cicha podmiana.
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_bo_members_deputy "
    "ON bo_members (role) WHERE role = 'deputy'",
)
CONSTRAINT_DDL: tuple[str, ...] = (
    f"""DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_bo_cards_outside_team'
    ) THEN
        ALTER TABLE bo_cards
        ADD CONSTRAINT ck_bo_cards_outside_team CHECK ({CK_CARD_OUTSIDE});
    END IF;
END $$""",
)
DATA_DDL: tuple[str, ...] = ()

TABLES: tuple[str, ...] = ("bo_members", "bo_client_notes")
DOWNGRADE_DDL: tuple[str, ...] = (
    "ALTER TABLE bo_cards DROP CONSTRAINT IF EXISTS ck_bo_cards_outside_team",
    "ALTER TABLE bo_cards DROP COLUMN IF EXISTS outside_team",
    "DROP TABLE IF EXISTS bo_client_notes",
    "DROP TABLE IF EXISTS bo_members",
)

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
