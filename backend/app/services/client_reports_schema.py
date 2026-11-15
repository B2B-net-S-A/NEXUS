"""Katalog raportów klienta (decyzje Artura 15.11.2026): SQL migracji
``0710_client_reports`` i lustra entrypointu.

Jedno źródło instrukcji dla ``alembic/versions/0710_client_reports.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``).

Tabele:

* ``client_report_definitions`` — raport, którego wymaga klient: wiersz danych
  przy kliencie, nie kod. Skąd wymóg (umowa i fragment albo Delivery Lead),
  rodzina, generator z rejestru (``services/client_reports/registry.py``;
  pusty = plik spoza NEXUSA), parametry szablonu, rytm i reguła terminu,
  odbiorca, kto przygotowuje. ``status``: ``proposal`` (odczyt z umowy albo
  wpis osoby bez prawa zatwierdzenia) → ``active`` po potwierdzeniu DL-a
  klienta; ``rejected`` nie wraca jako propozycja; ``archived`` znika
  z katalogu i kalendarza, historia zostaje.
* ``client_report_runs`` — historia: wygenerowany plik albo wysyłka za okres.
  Wysyłkę robi DL ze swojej poczty (decyzja 15.11), a NEXUS zapisuje datę,
  adresata i plik.

Kalendarz liczy się przy odczycie z definicji × okresów
(``client_reports/schedule.py``), więc tabeli wystąpień nie ma.
"""

from __future__ import annotations

from app.services.consultant_portal_schema import quoted

FAMILIES: tuple[str, ...] = ("settlement", "management", "compliance", "on_request")
RHYTHMS: tuple[str, ...] = (
    "weekly",
    "monthly",
    "quarterly",
    "semiannual",
    "annual",
    "contract_year",
    "event",
    "on_request",
)
PREPARERS: tuple[str, ...] = ("dl", "finance", "board", "iod", "consultant", "client")
SOURCE_KINDS: tuple[str, ...] = ("contract", "amendment", "dl", "manual")
DEFINITION_STATUSES: tuple[str, ...] = ("proposal", "active", "rejected", "archived")
RUN_STATUSES: tuple[str, ...] = ("generated", "sent")

NAME_MAX = 200
GENERATOR_MAX = 48
RECIPIENT_MAX = 255
CHANNEL_MAX = 32
FORMAT_MAX = 16
SOURCE_REF_MAX = 255
PERIOD_KEY_MAX = 16
FILE_NAME_MAX = 255
FILE_PATH_MAX = 512
SENT_TO_MAX = 255

CK_FAMILY = f"family IN ({quoted(FAMILIES)})"
CK_RHYTHM = f"rhythm IN ({quoted(RHYTHMS)})"
CK_PREPARER = f"preparer IN ({quoted(PREPARERS)})"
CK_SOURCE_KIND = f"source_kind IN ({quoted(SOURCE_KINDS)})"
CK_DEFINITION_STATUS = f"status IN ({quoted(DEFINITION_STATUSES)})"
CK_RUN_STATUS = f"status IN ({quoted(RUN_STATUSES)})"
CK_SHA = "sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'"
CK_SENT = "status <> 'sent' OR sent_at IS NOT NULL"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS client_report_definitions (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    name VARCHAR({NAME_MAX}) NOT NULL,
    family VARCHAR(12) NOT NULL,
    generator_key VARCHAR({GENERATOR_MAX}) NULL,
    params JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    rhythm VARCHAR(16) NOT NULL,
    due_rule JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    recipient VARCHAR({RECIPIENT_MAX}) NULL,
    channel VARCHAR({CHANNEL_MAX}) NULL,
    file_format VARCHAR({FORMAT_MAX}) NULL,
    preparer VARCHAR(12) NOT NULL,
    preparer_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    source_kind VARCHAR(12) NOT NULL,
    source_contract_id INTEGER NULL REFERENCES client_framework_contracts(id) ON DELETE SET NULL,
    source_chunk_id BIGINT NULL,
    source_ref VARCHAR({SOURCE_REF_MAX}) NULL,
    status VARCHAR(10) NOT NULL,
    valid_from DATE NULL,
    valid_to DATE NULL,
    notes TEXT NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    confirmed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    confirmed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_client_report_definitions_family CHECK ({CK_FAMILY}),
    CONSTRAINT ck_client_report_definitions_rhythm CHECK ({CK_RHYTHM}),
    CONSTRAINT ck_client_report_definitions_preparer CHECK ({CK_PREPARER}),
    CONSTRAINT ck_client_report_definitions_source CHECK ({CK_SOURCE_KIND}),
    CONSTRAINT ck_client_report_definitions_status CHECK ({CK_DEFINITION_STATUS})
)""",
    f"""CREATE TABLE IF NOT EXISTS client_report_runs (
    id SERIAL PRIMARY KEY,
    definition_id INTEGER NOT NULL REFERENCES client_report_definitions(id) ON DELETE CASCADE,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    period_key VARCHAR({PERIOD_KEY_MAX}) NOT NULL,
    period_start DATE NULL,
    period_end DATE NULL,
    status VARCHAR(10) NOT NULL,
    file_name VARCHAR({FILE_NAME_MAX}) NULL,
    file_path VARCHAR({FILE_PATH_MAX}) NULL,
    content_type VARCHAR(128) NULL,
    size_bytes INTEGER NULL,
    sha256 VARCHAR(64) NULL,
    generated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    sent_at TIMESTAMPTZ NULL,
    sent_to VARCHAR({SENT_TO_MAX}) NULL,
    sent_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    note TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_client_report_runs_status CHECK ({CK_RUN_STATUS}),
    CONSTRAINT ck_client_report_runs_sha CHECK ({CK_SHA}),
    CONSTRAINT ck_client_report_runs_sent CHECK ({CK_SENT})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_client_report_definitions_client "
    "ON client_report_definitions (client_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_client_report_runs_definition_period "
    "ON client_report_runs (definition_id, period_key)",
)

CONSTRAINT_DDL: tuple[str, ...] = ()

#: Raport miesięczny rekrutacji BNP (#3265) był przyciskiem dla klienta 12
#: zaszytego w kodzie. Od katalogu przycisk pokazuje się klientowi, który ma
#: tę definicję — wiersz dla dotychczasowego klienta zakłada zasiew, raz.
DATA_DDL: tuple[str, ...] = (
    """INSERT INTO client_report_definitions
    (client_id, name, family, generator_key, rhythm, due_rule, preparer,
     source_kind, status, confirmed_at, notes)
SELECT 12, 'Raport miesięczny rekrutacji', 'management', 'bnp_recruitment_monthly',
       'monthly', '{"type": "none"}'::jsonb, 'dl', 'dl', 'active', now(),
       'Przeniesione z przycisku w zakładce Projekty (#3265).'
WHERE EXISTS (SELECT 1 FROM clients WHERE id = 12)
  AND NOT EXISTS (
    SELECT 1 FROM client_report_definitions
    WHERE generator_key = 'bnp_recruitment_monthly'
)""",
)

TABLES: tuple[str, ...] = ("client_report_definitions", "client_report_runs")

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
