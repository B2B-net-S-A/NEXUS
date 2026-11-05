"""Panel konsultanta, pierwsza wersja (decyzje Artura 04–05.11.2026): SQL migracji ``0648_consultant_panel`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0648_consultant_panel.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``).

Tabele:

* ``cp_activations`` — panel powstaje ręcznie po podpisaniu umowy. Bez aktywnego
  wiersza kontrakt nie wejdzie do panelu w żadnym stanie wyłącznika. Wyłączenie
  zostawia wiersz, żeby było widać kto i kiedy.
* ``client_onboarding_materials`` — pliki i linki na start: klienta albo wspólne
  (``client_id`` puste). Pakiet klienta nie przechowuje plików do pobrania.
* ``cp_activation_materials`` — co z propozycji dostała ta konkretna osoba.
* ``client_settlement_rules`` — sposób rozliczenia klienta, ustawiają Finanse.
  Tabela-siostra, bo ``client_playbooks`` ma bramkę Delivery.
* ``cp_trainer_applications`` — zgłoszenie „Zostań trenerem”: dane w polach, żeby dało
  się z nich później zrobić rejestr, a obsługa idzie sprawą (``case_id``).
"""

from __future__ import annotations

from app.services.consultant_portal_schema import quoted

MATERIAL_KINDS: tuple[str, ...] = ("file", "link")
#: A: raport przysyła klient, B: raport i akceptacja klienta od konsultanta,
#: C: raport od konsultanta akceptują Finanse.
SETTLEMENT_MODES: tuple[str, ...] = (
    "client_report",
    "report_with_approval",
    "own_report",
)
TRAINER_FORMS: tuple[str, ...] = ("online_or_onsite", "online", "onsite")

MATERIAL_TITLE_MAX = 200
MATERIAL_URL_MAX = 1_000
FILE_NAME_MAX = 255
INSTRUCTIONS_MAX = 5_000
TRAINER_TEXT_MAX = 3_000
TRAINER_SHORT_MAX = 200

CK_MATERIAL_KIND = f"kind IN ({quoted(MATERIAL_KINDS)})"
CK_MATERIAL_TITLE = "btrim(title) <> ''"
CK_MATERIAL_SOURCE = (
    "(kind = 'link' AND url IS NOT NULL AND file_path IS NULL) "
    "OR (kind = 'file' AND file_path IS NOT NULL AND url IS NULL)"
)
CK_SETTLEMENT_MODE = f"mode IN ({quoted(SETTLEMENT_MODES)})"
CK_TRAINER_FORM = f"form IN ({quoted(TRAINER_FORMS)})"
CK_TRAINER_TOPICS = "jsonb_typeof(topics) = 'array'"

TABLE_DDL: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS cp_activations (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    activated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    activated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deactivated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    deactivated_at TIMESTAMPTZ NULL,
    CONSTRAINT uq_cp_activations_contract UNIQUE (contract_id)
)""",
    f"""CREATE TABLE IF NOT EXISTS client_onboarding_materials (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NULL REFERENCES clients(id) ON DELETE CASCADE,
    title VARCHAR({MATERIAL_TITLE_MAX}) NOT NULL,
    kind VARCHAR(8) NOT NULL,
    url VARCHAR({MATERIAL_URL_MAX}) NULL,
    file_path VARCHAR(500) NULL,
    file_name VARCHAR({FILE_NAME_MAX}) NULL,
    mime VARCHAR(120) NULL,
    size_bytes INTEGER NULL,
    position SMALLINT NOT NULL DEFAULT 0,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_client_onboarding_materials_kind CHECK ({CK_MATERIAL_KIND}),
    CONSTRAINT ck_client_onboarding_materials_title CHECK ({CK_MATERIAL_TITLE}),
    CONSTRAINT ck_client_onboarding_materials_source CHECK ({CK_MATERIAL_SOURCE})
)""",
    """CREATE TABLE IF NOT EXISTS cp_activation_materials (
    activation_id INTEGER NOT NULL REFERENCES cp_activations(id) ON DELETE CASCADE,
    material_id INTEGER NOT NULL REFERENCES client_onboarding_materials(id) ON DELETE CASCADE,
    PRIMARY KEY (activation_id, material_id)
)""",
    f"""CREATE TABLE IF NOT EXISTS client_settlement_rules (
    client_id INTEGER PRIMARY KEY REFERENCES clients(id) ON DELETE CASCADE,
    mode VARCHAR(24) NOT NULL,
    instructions VARCHAR({INSTRUCTIONS_MAX}) NOT NULL DEFAULT '',
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_client_settlement_rules_mode CHECK ({CK_SETTLEMENT_MODE})
)""",
    f"""CREATE TABLE IF NOT EXISTS cp_trainer_applications (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    case_id INTEGER NULL REFERENCES admin_cases(id) ON DELETE SET NULL,
    topics JSONB NOT NULL DEFAULT '[]'::jsonb,
    experience VARCHAR({TRAINER_TEXT_MAX}) NOT NULL DEFAULT '',
    form VARCHAR(20) NOT NULL DEFAULT 'online_or_onsite',
    day_rate VARCHAR({TRAINER_SHORT_MAX}) NOT NULL DEFAULT '',
    availability VARCHAR({TRAINER_SHORT_MAX}) NOT NULL DEFAULT '',
    materials VARCHAR({MATERIAL_URL_MAX}) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_cp_trainer_applications_contract UNIQUE (contract_id),
    CONSTRAINT ck_cp_trainer_applications_form CHECK ({CK_TRAINER_FORM}),
    CONSTRAINT ck_cp_trainer_applications_topics CHECK ({CK_TRAINER_TOPICS})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_cp_activations_active "
    "ON cp_activations (contract_id) WHERE deactivated_at IS NULL",
    "CREATE INDEX IF NOT EXISTS ix_client_onboarding_materials_client "
    "ON client_onboarding_materials (client_id, position)",
    "CREATE INDEX IF NOT EXISTS ix_cp_activation_materials_material "
    "ON cp_activation_materials (material_id)",
)

CONSTRAINT_DDL: tuple[str, ...] = ()
DATA_DDL: tuple[str, ...] = ()
DOWNGRADE_DDL: tuple[str, ...] = ()

TABLES: tuple[str, ...] = (
    "cp_activations",
    "client_onboarding_materials",
    "cp_activation_materials",
    "client_settlement_rules",
    "cp_trainer_applications",
)

ALL_DDL: tuple[str, ...] = (*TABLE_DDL, *COLUMN_DDL, *INDEX_DDL)
