"""Wejście trenera z rynku do panelu (0807) — JEDNO źródło dla migracji i siatki
w ``entrypoint.sh`` (produkcyjny alembic bywa osierocony).

Decyzje Artura z 28.11.2026: trener z rynku (``market_trainer_applications``
w stanie „w bazie trenerów”) dostaje osobne wejście do panelu ``/konsultant``
— link z maila jak konsultant, ale widzi tylko „Szkolenia” i „Trener”; dane firmy
do umowy szkoleniowej wpisuje TCM z Białej Listy; wejście ma własny włącznik
(``app_settings['market_trainer_portal']``), niezależny od panelu konsultanta.

* kolumny panelu w ``market_trainer_applications``: dane firmy (nazwa, NIP, REGON,
  adres), adres logowania i kto/kiedy otworzył albo zamknął panel;
* ``trainings.trainer_market_id`` — szkolenie trenera z rynku. Obieg jak trenera
  B2B (``trainer_kind = 'consultant'``: umowa, zapłata, biblioteka po zapłacie),
  tylko bez kontraktu, co ``ck_trainings_trainer`` już dopuszcza;
* ``training_files.uploaded_by_market_id`` — plik od trenera z rynku;
* ``mt_portal_links`` i ``mt_portal_sessions`` — link z maila i sesja trenera,
  osobno od ``cp_links``/``cp_sessions`` konsultanta (tamte wymagają kontraktu,
  a sesja trenera nie może otworzyć żadnej trasy konsultanta).

Same dodania; stary kod działa na nowym schemacie.
"""

from __future__ import annotations

from app.services.website_intake_schema import EMAIL_MAX, TRAINERS

COMPANY_MAX = 300
NIP_MAX = 10
REGON_MAX = 14
ADDRESS_MAX = 500

LINKS = "mt_portal_links"
SESSIONS = "mt_portal_sessions"

CK_TRAINER_MARKET = (
    "trainer_market_id IS NULL "
    "OR (trainer_kind = 'consultant' AND trainer_contract_id IS NULL)"
)

COLUMN_DDL: tuple[str, ...] = (
    f"ALTER TABLE {TRAINERS} ADD COLUMN IF NOT EXISTS company_name "
    f"VARCHAR({COMPANY_MAX}) NOT NULL DEFAULT ''",
    f"ALTER TABLE {TRAINERS} ADD COLUMN IF NOT EXISTS nip VARCHAR({NIP_MAX}) NULL",
    f"ALTER TABLE {TRAINERS} ADD COLUMN IF NOT EXISTS regon "
    f"VARCHAR({REGON_MAX}) NOT NULL DEFAULT ''",
    f"ALTER TABLE {TRAINERS} ADD COLUMN IF NOT EXISTS company_address "
    f"VARCHAR({ADDRESS_MAX}) NOT NULL DEFAULT ''",
    f"ALTER TABLE {TRAINERS} ADD COLUMN IF NOT EXISTS panel_email "
    f"VARCHAR({EMAIL_MAX}) NULL",
    f"ALTER TABLE {TRAINERS} ADD COLUMN IF NOT EXISTS panel_opened_by "
    "INTEGER NULL REFERENCES users(id) ON DELETE SET NULL",
    f"ALTER TABLE {TRAINERS} ADD COLUMN IF NOT EXISTS panel_opened_at "
    "TIMESTAMPTZ NULL",
    f"ALTER TABLE {TRAINERS} ADD COLUMN IF NOT EXISTS panel_closed_at "
    "TIMESTAMPTZ NULL",
    "ALTER TABLE trainings ADD COLUMN IF NOT EXISTS trainer_market_id "
    f"INTEGER NULL REFERENCES {TRAINERS}(id) ON DELETE SET NULL",
    "ALTER TABLE training_files ADD COLUMN IF NOT EXISTS uploaded_by_market_id "
    f"INTEGER NULL REFERENCES {TRAINERS}(id) ON DELETE SET NULL",
)

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS {LINKS} (
    id SERIAL PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES {TRAINERS}(id) ON DELETE CASCADE,
    email VARCHAR({EMAIL_MAX}) NOT NULL,
    token_hash VARCHAR(64) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_{LINKS}_token UNIQUE (token_hash)
)""",
    f"""CREATE TABLE IF NOT EXISTS {SESSIONS} (
    id SERIAL PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES {TRAINERS}(id) ON DELETE CASCADE,
    email VARCHAR({EMAIL_MAX}) NOT NULL,
    token_hash VARCHAR(64) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_{SESSIONS}_token UNIQUE (token_hash)
)""",
)

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_trainings_trainer_market "
    "ON trainings (trainer_market_id) WHERE trainer_market_id IS NOT NULL",
    f"CREATE INDEX IF NOT EXISTS ix_{LINKS}_application "
    f"ON {LINKS} (application_id, created_at)",
    f"CREATE INDEX IF NOT EXISTS ix_{SESSIONS}_application "
    f"ON {SESSIONS} (application_id)",
)

CONSTRAINT_DDL: tuple[str, ...] = (
    "DO $$ BEGIN "
    "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'ck_trainings_trainer_market') THEN "
    "ALTER TABLE trainings ADD CONSTRAINT ck_trainings_trainer_market "
    f"CHECK ({CK_TRAINER_MARKET}); "
    "END IF; END $$",
)

TABLES: tuple[str, ...] = (LINKS, SESSIONS)

ALL_DDL: tuple[str, ...] = (*COLUMN_DDL, *TABLE_DDL, *INDEX_DDL, *CONSTRAINT_DDL)

DOWNGRADE_DDL: tuple[str, ...] = (
    *(f"DROP TABLE IF EXISTS {table}" for table in reversed(TABLES)),
    "ALTER TABLE trainings DROP CONSTRAINT IF EXISTS ck_trainings_trainer_market",
    "DROP INDEX IF EXISTS ix_trainings_trainer_market",
    "ALTER TABLE training_files DROP COLUMN IF EXISTS uploaded_by_market_id",
    "ALTER TABLE trainings DROP COLUMN IF EXISTS trainer_market_id",
    *(
        f"ALTER TABLE {TRAINERS} DROP COLUMN IF EXISTS {column}"
        for column in (
            "panel_closed_at",
            "panel_opened_at",
            "panel_opened_by",
            "panel_email",
            "company_address",
            "regon",
            "nip",
            "company_name",
        )
    ),
)
