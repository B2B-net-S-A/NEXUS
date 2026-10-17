"""„Ludzie w NEXUSIE” — Sprzęt i protokoły: SQL migracji ``0463_equipment`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0463_equipment.py`` i ``entrypoint.sh``
(przez ``app/services/hr_schema_bundle.py``). Zakres: modele i egzemplarze, osoby zewnętrzne, wydania, protokoły z linkiem do podpisu, zadania, import plików recepcji.

Kontrakt modułu (czyta go agregator i test łańcucha):

* ``TABLE_DDL`` — ``CREATE TABLE IF NOT EXISTS`` nowych tabel (VARCHAR + CHECK,
  bez nowych typów enum),
* ``COLUMN_DDL`` — ``ALTER TABLE … ADD COLUMN IF NOT EXISTS`` w istniejących tabelach,
* ``INDEX_DDL`` — ``CREATE [UNIQUE] INDEX IF NOT EXISTS``,
* ``CONSTRAINT_DDL`` — ograniczenia dokładane do ISTNIEJĄCYCH tabel (idempotentne bloki ``DO``),
* ``DATA_DDL`` — zasiewy i znaczniki jednorazowe (idempotentne),
* ``TABLES`` — nowe tabele w kolejności tworzenia (downgrade kasuje odwrotnie),
* ``DOWNGRADE_DDL`` — sprzątanie kolumn/ograniczeń w istniejących tabelach.

Każda instrukcja musi być idempotentna: entrypoint wykonuje je przy każdym starcie.

Tabele (propozycja recepcji z 15.10, decyzje D2–D10):

* ``equipment_models`` — cennik: model w kategorii z ceną (D5),
* ``equipment_items`` — egzemplarz z numerem ewidencyjnym, S/N, IMEI, ICCID,
  numerem telefonu SIM i numerem karty dostępu (każdy unikalny, gdy niepusty).
  NIE ma kolumn na PUK, klucz BitLocker, PESEL ani prywatny e-mail (D10),
* ``equipment_external_people`` — osoby bez konta NEXUSA (np. Akademia),
* ``equipment_assignments`` — wydanie egzemplarza dokładnie jednemu
  posiadaczowi (konto, kontrakt albo osoba zewnętrzna); jedno aktywne na egzemplarz,
* ``equipment_protocols`` / ``_lines`` / ``_links`` — protokół wydania lub
  zwrotu z migawką pozycji, podpisem (link, papier, profil zaufany)
  potwierdzanym przez człowieka (D4) i jednorazowym linkiem (hash tokenu, D8),
* ``equipment_tasks`` — „Do zrobienia” recepcji (``source_key`` unikalny:
  zadania z kontraktów i odejść zakładają się raz),
* ``equipment_import_batches`` / ``_rows`` — import plików recepcji przez
  arkusz kontrolny (zapis dopiero po zatwierdzeniu partii),
* ``contract_equipment.item_id`` / ``assignment_id`` — pozycja zakładki
  „Sprzęt” kontraktu wskazuje egzemplarz z rejestru,
* ``clients.equipment_provider`` — kto daje sprzęt konsultantom klienta (D7).

Etap 3 (17.10.2026, decyzje O2, O3, O6):

* ``equipment_protocol_templates`` — wzory protokołów wgrane przez recepcję
  (DOCX z polami, treść pliku w bazie); wbudowany standard nie ma wiersza,
* ``equipment_protocols.template_id`` — z którego wgranego wzoru powstał
  protokół (``NULL`` = wbudowany standard),
* ``client_onboarding_packs`` / ``_items`` — pakiet klienta („Wejście
  u klienta”): wzory protokołów, pierwszy dzień, rzeczy od nas i od klienta,
  dokumenty od konsultanta i dostępy,
* ``consultant_welcome_mails`` — mail powitalny wysłany konsultantowi
  (treść taka, jaką opiekun wysłał). Jeden na kontrakt pilnuje blokada
  doradcza wysyłki, nie UNIQUE: scalenie duplikatów kontraktu przenosi ślady
  obu maili na zachowany kontrakt bez kasowania (``contract_merge``).
"""

from __future__ import annotations

from app.services.hr_lifecycle_schema import (
    MAX_OFFSET_AFTER,
    MAX_OFFSET_BEFORE,
    TASK_ASSIGNEES,
)

CATEGORIES: tuple[str, ...] = (
    "laptop",
    "telefon",
    "monitor",
    "karta_sim",
    "karta_dostepu",
    "akcesorium",
    "inne",
)
#: Kategorie bez wartości w protokole (D6): numer karty to nie mienie z cennika.
NO_VALUE_CATEGORIES: tuple[str, ...] = ("karta_sim", "karta_dostepu")
ITEM_STATUSES: tuple[str, ...] = (
    "na_stanie",
    "wydany",
    "serwis",
    "wycofany",
    "zgubiony",
)
OWNERSHIPS: tuple[str, ...] = ("nasz", "klienta")
PROVIDERS: tuple[str, ...] = ("nasz", "klienta", "nieznany")
RETURN_CONDITIONS: tuple[str, ...] = (
    "sprawny",
    "uszkodzony",
    "niekompletny",
    "zgubiony",
)
PROTOCOL_KINDS: tuple[str, ...] = ("wydanie", "zwrot")
PROTOCOL_STATUSES: tuple[str, ...] = (
    "oczekuje",
    "podpisany",
    "potwierdzony",
    "anulowany",
)
SIGNATURE_METHODS: tuple[str, ...] = ("brak", "link", "papier", "profil_zaufany")
TASK_KINDS: tuple[str, ...] = ("wydanie", "zwrot", "podpis", "zakup")
TASK_STATUSES: tuple[str, ...] = ("otwarte", "zrobione", "anulowane")
IMPORT_BATCH_STATUSES: tuple[str, ...] = ("nowa", "zatwierdzona")
IMPORT_DECISIONS: tuple[str, ...] = ("przyjmij", "pomin", "konflikt", "do_wyjasnienia")
#: Części pakietu klienta: rzeczy od nas, rzeczy od klienta, dokumenty od
#: konsultanta, dostępy u klienta.
PACK_SECTIONS: tuple[str, ...] = (
    "equipment_ours",
    "equipment_client",
    "document",
    "access",
)


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


CK_MODEL_CATEGORY = f"category IN ({quoted(CATEGORIES)})"
CK_MODEL_NAME = "btrim(name) <> ''"
CK_MODEL_PRICE = "price_pln IS NULL OR price_pln >= 0"
CK_ITEM_STATUS = f"status IN ({quoted(ITEM_STATUSES)})"
CK_ITEM_OWNERSHIP = f"ownership IN ({quoted(OWNERSHIPS)})"
CK_EXTERNAL_NAME = "btrim(full_name) <> ''"
CK_ASSIGNMENT_ONE_HOLDER = "num_nonnulls(user_id, contract_id, external_person_id) = 1"
CK_ASSIGNMENT_CONDITION = (
    f"return_condition IS NULL OR return_condition IN ({quoted(RETURN_CONDITIONS)})"
)
CK_ASSIGNMENT_RETURN_ORDER = "returned_at IS NULL OR returned_at >= issued_at"
CK_ASSIGNMENT_RETURN_COMPLETE = "(returned_at IS NULL) = (return_condition IS NULL)"
CK_PROTOCOL_KIND = f"kind IN ({quoted(PROTOCOL_KINDS)})"
CK_PROTOCOL_STATUS = f"status IN ({quoted(PROTOCOL_STATUSES)})"
CK_PROTOCOL_METHOD = f"signature_method IN ({quoted(SIGNATURE_METHODS)})"
CK_PROTOCOL_YEAR = "year BETWEEN 2020 AND 2100"
CK_PROTOCOL_SEQ = "seq > 0"
CK_PROTOCOL_SIGNED = (
    "status NOT IN ('podpisany', 'potwierdzony') OR signed_at IS NOT NULL"
)
CK_PROTOCOL_CONFIRMED = "status <> 'potwierdzony' OR confirmed_at IS NOT NULL"
CK_LINE_CATEGORY = f"category IN ({quoted(CATEGORIES)})"
CK_LINE_QUANTITY = "quantity > 0"
CK_LINE_VALUE = "unit_value IS NULL OR unit_value >= 0"
CK_LINE_CONDITION = f"condition IS NULL OR condition IN ({quoted(RETURN_CONDITIONS)})"
CK_TASK_KIND = f"kind IN ({quoted(TASK_KINDS)})"
CK_TASK_STATUS = f"status IN ({quoted(TASK_STATUSES)})"
CK_IMPORT_BATCH_STATUS = f"status IN ({quoted(IMPORT_BATCH_STATUSES)})"
CK_IMPORT_DECISION = f"decision IN ({quoted(IMPORT_DECISIONS)})"
CK_CLIENT_PROVIDER = f"equipment_provider IN ({quoted(PROVIDERS)})"
CK_TEMPLATE_KIND = f"kind IN ({quoted(PROTOCOL_KINDS)})"
CK_TEMPLATE_NAME = "btrim(name) <> ''"
CK_TEMPLATE_SIZE = "file_size > 0"
CK_PACK_TIME = (
    "first_day_time IS NULL OR first_day_time ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'"
)
CK_PACK_VERSION = "version > 0"
CK_PACK_ITEM_SECTION = f"section IN ({quoted(PACK_SECTIONS)})"
CK_PACK_ITEM_NAME = "btrim(name) <> ''"
CK_PACK_ITEM_ASSIGNEE = f"assignee IS NULL OR assignee IN ({quoted(TASK_ASSIGNEES)})"
CK_PACK_ITEM_OFFSET = (
    f"offset_days IS NULL OR offset_days BETWEEN -{MAX_OFFSET_BEFORE} "
    f"AND {MAX_OFFSET_AFTER}"
)
CK_WELCOME_BODY = "btrim(body) <> ''"
#: Wynik wysyłki maila powitalnego: przyjęty przez Graph, tryb symulacji
#: (``HR_M365_MODE=simulate`` — nic nie wyszło) albo niepewny (brama Graph
#: odpowiedziała błędem po przyjęciu żądania — bez ponowienia).
WELCOME_DELIVERIES: tuple[str, ...] = ("sent", "simulated", "uncertain")
CK_WELCOME_DELIVERY = f"delivery IN ({quoted(WELCOME_DELIVERIES)})"
#: Jeden aktywny wzór o tej nazwie na rodzaj (wycofany nie blokuje nazwy).
TEMPLATE_ACTIVE_WHERE = "is_active"

#: Unikalne identyfikatory egzemplarza (indeks częściowy: tylko niepuste).
ITEM_UNIQUE_COLUMNS: tuple[str, ...] = (
    "inventory_number",
    "serial_number",
    "imei",
    "iccid",
    "phone_number",
    "access_card_number",
)

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS equipment_models (
    id SERIAL PRIMARY KEY,
    category VARCHAR(24) NOT NULL,
    name VARCHAR(200) NOT NULL,
    manufacturer VARCHAR(120) NULL,
    price_pln NUMERIC(12,2) NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_equipment_models_category_name UNIQUE (category, name),
    CONSTRAINT ck_equipment_models_category CHECK ({CK_MODEL_CATEGORY}),
    CONSTRAINT ck_equipment_models_name CHECK ({CK_MODEL_NAME}),
    CONSTRAINT ck_equipment_models_price CHECK ({CK_MODEL_PRICE})
)""",
    f"""CREATE TABLE IF NOT EXISTS equipment_items (
    id SERIAL PRIMARY KEY,
    model_id INTEGER NOT NULL REFERENCES equipment_models(id) ON DELETE RESTRICT,
    inventory_number VARCHAR(40) NULL,
    serial_number VARCHAR(120) NULL,
    imei VARCHAR(20) NULL,
    iccid VARCHAR(24) NULL,
    phone_number VARCHAR(20) NULL,
    access_card_number VARCHAR(40) NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'na_stanie',
    ownership VARCHAR(16) NOT NULL DEFAULT 'nasz',
    purchase_date DATE NULL,
    location VARCHAR(120) NULL,
    notes TEXT NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_equipment_items_status CHECK ({CK_ITEM_STATUS}),
    CONSTRAINT ck_equipment_items_ownership CHECK ({CK_ITEM_OWNERSHIP})
)""",
    f"""CREATE TABLE IF NOT EXISTS equipment_external_people (
    id SERIAL PRIMARY KEY,
    full_name VARCHAR(200) NOT NULL,
    work_email VARCHAR(255) NULL,
    note VARCHAR(200) NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_equipment_external_people_name CHECK ({CK_EXTERNAL_NAME})
)""",
    f"""CREATE TABLE IF NOT EXISTS equipment_protocols (
    id SERIAL PRIMARY KEY,
    kind VARCHAR(16) NOT NULL,
    year SMALLINT NOT NULL,
    seq INTEGER NOT NULL,
    number VARCHAR(32) NOT NULL,
    protocol_date DATE NOT NULL,
    user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE SET NULL,
    external_person_id INTEGER NULL
        REFERENCES equipment_external_people(id) ON DELETE SET NULL,
    holder_name VARCHAR(200) NOT NULL,
    holder_email VARCHAR(255) NULL,
    issuer_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    issuer_name VARCHAR(200) NOT NULL,
    total_value NUMERIC(12,2) NOT NULL DEFAULT 0,
    template_version VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'oczekuje',
    signature_method VARCHAR(16) NOT NULL DEFAULT 'brak',
    signed_at TIMESTAMPTZ NULL,
    signer_name VARCHAR(200) NULL,
    signed_file_path TEXT NULL,
    confirmed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    confirmed_at TIMESTAMPTZ NULL,
    notes TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_equipment_protocols_year_seq UNIQUE (year, seq),
    CONSTRAINT uq_equipment_protocols_number UNIQUE (number),
    CONSTRAINT ck_equipment_protocols_kind CHECK ({CK_PROTOCOL_KIND}),
    CONSTRAINT ck_equipment_protocols_status CHECK ({CK_PROTOCOL_STATUS}),
    CONSTRAINT ck_equipment_protocols_method CHECK ({CK_PROTOCOL_METHOD}),
    CONSTRAINT ck_equipment_protocols_year CHECK ({CK_PROTOCOL_YEAR}),
    CONSTRAINT ck_equipment_protocols_seq CHECK ({CK_PROTOCOL_SEQ}),
    CONSTRAINT ck_equipment_protocols_signed CHECK ({CK_PROTOCOL_SIGNED}),
    CONSTRAINT ck_equipment_protocols_confirmed CHECK ({CK_PROTOCOL_CONFIRMED})
)""",
    f"""CREATE TABLE IF NOT EXISTS equipment_assignments (
    id SERIAL PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES equipment_items(id) ON DELETE RESTRICT,
    user_id INTEGER NULL REFERENCES users(id) ON DELETE RESTRICT,
    contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE CASCADE,
    external_person_id INTEGER NULL
        REFERENCES equipment_external_people(id) ON DELETE RESTRICT,
    issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    returned_at TIMESTAMPTZ NULL,
    return_condition VARCHAR(16) NULL,
    return_notes TEXT NULL,
    issue_protocol_id INTEGER NULL
        REFERENCES equipment_protocols(id) ON DELETE SET NULL,
    return_protocol_id INTEGER NULL
        REFERENCES equipment_protocols(id) ON DELETE SET NULL,
    issued_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    returned_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_equipment_assignments_one_holder CHECK ({CK_ASSIGNMENT_ONE_HOLDER}),
    CONSTRAINT ck_equipment_assignments_condition CHECK ({CK_ASSIGNMENT_CONDITION}),
    CONSTRAINT ck_equipment_assignments_return_order
        CHECK ({CK_ASSIGNMENT_RETURN_ORDER}),
    CONSTRAINT ck_equipment_assignments_return_complete
        CHECK ({CK_ASSIGNMENT_RETURN_COMPLETE})
)""",
    f"""CREATE TABLE IF NOT EXISTS equipment_protocol_lines (
    id SERIAL PRIMARY KEY,
    protocol_id INTEGER NOT NULL REFERENCES equipment_protocols(id) ON DELETE CASCADE,
    position SMALLINT NOT NULL,
    item_id INTEGER NULL REFERENCES equipment_items(id) ON DELETE SET NULL,
    assignment_id INTEGER NULL
        REFERENCES equipment_assignments(id) ON DELETE SET NULL,
    category VARCHAR(24) NOT NULL,
    name VARCHAR(300) NOT NULL,
    identifier VARCHAR(200) NULL,
    quantity SMALLINT NOT NULL DEFAULT 1,
    unit_value NUMERIC(12,2) NULL,
    condition VARCHAR(16) NULL,
    notes TEXT NULL,
    CONSTRAINT uq_equipment_protocol_lines_position UNIQUE (protocol_id, position),
    CONSTRAINT ck_equipment_protocol_lines_category CHECK ({CK_LINE_CATEGORY}),
    CONSTRAINT ck_equipment_protocol_lines_quantity CHECK ({CK_LINE_QUANTITY}),
    CONSTRAINT ck_equipment_protocol_lines_value CHECK ({CK_LINE_VALUE}),
    CONSTRAINT ck_equipment_protocol_lines_condition CHECK ({CK_LINE_CONDITION})
)""",
    """CREATE TABLE IF NOT EXISTS equipment_protocol_links (
    id SERIAL PRIMARY KEY,
    protocol_id INTEGER NOT NULL REFERENCES equipment_protocols(id) ON DELETE CASCADE,
    token_sha256 VARCHAR(64) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ NULL,
    revoked_at TIMESTAMPTZ NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_equipment_protocol_links_token UNIQUE (token_sha256)
)""",
    f"""CREATE TABLE IF NOT EXISTS equipment_tasks (
    id SERIAL PRIMARY KEY,
    kind VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'otwarte',
    title VARCHAR(300) NOT NULL,
    due_on DATE NULL,
    contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE CASCADE,
    user_id INTEGER NULL REFERENCES users(id) ON DELETE CASCADE,
    external_person_id INTEGER NULL
        REFERENCES equipment_external_people(id) ON DELETE CASCADE,
    protocol_id INTEGER NULL REFERENCES equipment_protocols(id) ON DELETE CASCADE,
    source_key VARCHAR(120) NOT NULL,
    details JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    done_at TIMESTAMPTZ NULL,
    done_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    last_reminded_on DATE NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_equipment_tasks_source_key UNIQUE (source_key),
    CONSTRAINT ck_equipment_tasks_kind CHECK ({CK_TASK_KIND}),
    CONSTRAINT ck_equipment_tasks_status CHECK ({CK_TASK_STATUS})
)""",
    f"""CREATE TABLE IF NOT EXISTS equipment_import_batches (
    id SERIAL PRIMARY KEY,
    file_name VARCHAR(255) NOT NULL,
    file_sha256 VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'nowa',
    summary JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    applied_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    applied_at TIMESTAMPTZ NULL,
    CONSTRAINT ck_equipment_import_batches_status CHECK ({CK_IMPORT_BATCH_STATUS})
)""",
    f"""CREATE TABLE IF NOT EXISTS equipment_import_rows (
    id SERIAL PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES equipment_import_batches(id) ON DELETE CASCADE,
    sheet VARCHAR(120) NOT NULL,
    row_number INTEGER NOT NULL,
    data JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    decision VARCHAR(16) NOT NULL,
    reason TEXT NULL,
    holder_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    holder_contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE SET NULL,
    item_id INTEGER NULL REFERENCES equipment_items(id) ON DELETE SET NULL,
    applied_at TIMESTAMPTZ NULL,
    CONSTRAINT uq_equipment_import_rows_position UNIQUE (batch_id, sheet, row_number),
    CONSTRAINT ck_equipment_import_rows_decision CHECK ({CK_IMPORT_DECISION})
)""",
    f"""CREATE TABLE IF NOT EXISTS equipment_protocol_templates (
    id SERIAL PRIMARY KEY,
    kind VARCHAR(16) NOT NULL,
    name VARCHAR(120) NOT NULL,
    description VARCHAR(300) NULL,
    file_name VARCHAR(255) NOT NULL,
    content BYTEA NOT NULL,
    file_sha256 VARCHAR(64) NOT NULL,
    file_size INTEGER NOT NULL,
    fields JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_equipment_protocol_templates_kind CHECK ({CK_TEMPLATE_KIND}),
    CONSTRAINT ck_equipment_protocol_templates_name CHECK ({CK_TEMPLATE_NAME}),
    CONSTRAINT ck_equipment_protocol_templates_size CHECK ({CK_TEMPLATE_SIZE})
)""",
    f"""CREATE TABLE IF NOT EXISTS client_onboarding_packs (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    issue_template_id INTEGER NULL
        REFERENCES equipment_protocol_templates(id) ON DELETE SET NULL,
    return_template_id INTEGER NULL
        REFERENCES equipment_protocol_templates(id) ON DELETE SET NULL,
    first_day_contact_id INTEGER NULL REFERENCES contacts(id) ON DELETE SET NULL,
    first_day_place VARCHAR(300) NULL,
    first_day_time VARCHAR(5) NULL,
    first_day_bring VARCHAR(500) NULL,
    version INTEGER NOT NULL DEFAULT 1,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_client_onboarding_packs_client UNIQUE (client_id),
    CONSTRAINT ck_client_onboarding_packs_time CHECK ({CK_PACK_TIME}),
    CONSTRAINT ck_client_onboarding_packs_version CHECK ({CK_PACK_VERSION})
)""",
    f"""CREATE TABLE IF NOT EXISTS client_onboarding_pack_items (
    id SERIAL PRIMARY KEY,
    pack_id INTEGER NOT NULL REFERENCES client_onboarding_packs(id) ON DELETE CASCADE,
    section VARCHAR(16) NOT NULL,
    position SMALLINT NOT NULL,
    name VARCHAR(200) NOT NULL,
    note VARCHAR(300) NULL,
    assignee VARCHAR(24) NULL,
    offset_days SMALLINT NULL,
    required BOOLEAN NOT NULL DEFAULT TRUE,
    requires_file BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT uq_client_onboarding_pack_items_position
        UNIQUE (pack_id, section, position),
    CONSTRAINT ck_client_onboarding_pack_items_section CHECK ({CK_PACK_ITEM_SECTION}),
    CONSTRAINT ck_client_onboarding_pack_items_name CHECK ({CK_PACK_ITEM_NAME}),
    CONSTRAINT ck_client_onboarding_pack_items_assignee
        CHECK ({CK_PACK_ITEM_ASSIGNEE}),
    CONSTRAINT ck_client_onboarding_pack_items_offset CHECK ({CK_PACK_ITEM_OFFSET})
)""",
    f"""CREATE TABLE IF NOT EXISTS consultant_welcome_mails (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    recipient_email VARCHAR(255) NOT NULL,
    subject VARCHAR(200) NOT NULL,
    body TEXT NOT NULL,
    delivery VARCHAR(16) NOT NULL DEFAULT 'sent',
    sent_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_consultant_welcome_mails_body CHECK ({CK_WELCOME_BODY}),
    CONSTRAINT ck_consultant_welcome_mails_delivery CHECK ({CK_WELCOME_DELIVERY})
)""",
)

COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE contract_equipment ADD COLUMN IF NOT EXISTS item_id INTEGER NULL "
    "REFERENCES equipment_items(id) ON DELETE SET NULL",
    "ALTER TABLE contract_equipment ADD COLUMN IF NOT EXISTS assignment_id INTEGER NULL "
    "REFERENCES equipment_assignments(id) ON DELETE SET NULL",
    "ALTER TABLE clients ADD COLUMN IF NOT EXISTS equipment_provider VARCHAR(16) "
    "NOT NULL DEFAULT 'nieznany'",
    # Etap 3: wgrany wzór, z którego powstał protokół (NULL = standard). Wzoru
    # użytego w protokole nie da się skasować — recepcja go tylko wycofuje.
    "ALTER TABLE equipment_protocols ADD COLUMN IF NOT EXISTS template_id INTEGER NULL "
    "REFERENCES equipment_protocol_templates(id) ON DELETE RESTRICT",
)

INDEX_DDL: tuple[str, ...] = (
    *(
        f"CREATE UNIQUE INDEX IF NOT EXISTS ux_equipment_items_{column} "
        f"ON equipment_items ({column}) WHERE {column} IS NOT NULL"
        for column in ITEM_UNIQUE_COLUMNS
    ),
    "CREATE INDEX IF NOT EXISTS ix_equipment_items_model ON equipment_items (model_id)",
    "CREATE INDEX IF NOT EXISTS ix_equipment_items_status ON equipment_items (status)",
    # Jeden aktywny posiadacz na egzemplarz — baza pilnuje także wyścigu dwóch wydań.
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_equipment_assignments_active "
    "ON equipment_assignments (item_id) WHERE returned_at IS NULL",
    "CREATE INDEX IF NOT EXISTS ix_equipment_assignments_user "
    "ON equipment_assignments (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_equipment_assignments_contract "
    "ON equipment_assignments (contract_id)",
    "CREATE INDEX IF NOT EXISTS ix_equipment_assignments_external "
    "ON equipment_assignments (external_person_id)",
    "CREATE INDEX IF NOT EXISTS ix_equipment_protocols_status "
    "ON equipment_protocols (status)",
    "CREATE INDEX IF NOT EXISTS ix_equipment_protocols_contract "
    "ON equipment_protocols (contract_id)",
    "CREATE INDEX IF NOT EXISTS ix_equipment_protocols_user "
    "ON equipment_protocols (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_equipment_protocol_links_protocol "
    "ON equipment_protocol_links (protocol_id)",
    "CREATE INDEX IF NOT EXISTS ix_equipment_tasks_status_due "
    "ON equipment_tasks (status, due_on)",
    "CREATE INDEX IF NOT EXISTS ix_equipment_import_rows_batch "
    "ON equipment_import_rows (batch_id, decision)",
    "CREATE INDEX IF NOT EXISTS ix_contract_equipment_item_id "
    "ON contract_equipment (item_id)",
    "CREATE INDEX IF NOT EXISTS ix_contract_equipment_assignment_id "
    "ON contract_equipment (assignment_id)",
    "CREATE INDEX IF NOT EXISTS ix_equipment_protocols_template "
    "ON equipment_protocols (template_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_equipment_protocol_templates_active_name "
    f"ON equipment_protocol_templates (kind, name) WHERE {TEMPLATE_ACTIVE_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_consultant_welcome_mails_contract "
    "ON consultant_welcome_mails (contract_id)",
    "CREATE INDEX IF NOT EXISTS ix_client_onboarding_packs_issue_template "
    "ON client_onboarding_packs (issue_template_id)",
    "CREATE INDEX IF NOT EXISTS ix_client_onboarding_packs_return_template "
    "ON client_onboarding_packs (return_template_id)",
)

CONSTRAINT_DDL: tuple[str, ...] = (
    f"""DO $$ BEGIN
        ALTER TABLE clients ADD CONSTRAINT ck_clients_equipment_provider
            CHECK ({CK_CLIENT_PROVIDER});
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
)

#: Pozycja zakładki „Sprzęt” kontraktu dostaje egzemplarz tylko przy JEDNOZNACZNYM
#: dopasowaniu numeru (S/N albo IMEI, bez wielkości liter); niejednoznaczne
#: zostają puste. Biegnie przy każdym starcie i po zatwierdzeniu importu
#: (``services/equipment/registry.link_contract_equipment``).
LINK_CONTRACT_EQUIPMENT_SQL = """UPDATE contract_equipment AS ce
SET item_id = matched.item_id
FROM (
    SELECT ce2.id AS row_id, min(i.id) AS item_id
    FROM contract_equipment AS ce2
    JOIN equipment_items AS i
      ON upper(btrim(ce2.serial_number)) IN (
          upper(btrim(i.serial_number)), upper(btrim(i.imei))
      )
    WHERE ce2.item_id IS NULL
      AND ce2.serial_number IS NOT NULL
      AND btrim(ce2.serial_number) <> ''
    GROUP BY ce2.id
    HAVING count(DISTINCT i.id) = 1
) AS matched
WHERE ce.id = matched.row_id"""

#: Pozycja w toku dostaje aktywne wydanie egzemplarza, gdy to wydanie należy do
#: TEGO kontraktu (inaczej rejestr i zakładka mówiłyby o dwóch różnych osobach).
LINK_CONTRACT_ASSIGNMENTS_SQL = """UPDATE contract_equipment AS ce
SET assignment_id = a.id
FROM equipment_assignments AS a
WHERE ce.assignment_id IS NULL
  AND ce.item_id = a.item_id
  AND a.returned_at IS NULL
  AND a.contract_id = ce.contract_id
  AND ce.return_status = 'pending'"""

#: Twarde skasowanie kontraktu kasuje kaskadą jego wydania (``contract_lifecycle``
#: traktuje pod-zasoby kontraktu jako dane pomyłki). Egzemplarz wraca wtedy na
#: stan — inaczej wisiałby „wydany” bez posiadacza.
RELEASE_FUNCTION_SQL = """CREATE OR REPLACE FUNCTION equipment_release_deleted_assignment()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
    IF OLD.returned_at IS NULL THEN
        UPDATE equipment_items SET status = 'na_stanie', updated_at = now()
        WHERE id = OLD.item_id AND status = 'wydany';
    END IF;
    RETURN OLD;
END $$"""

DATA_DDL: tuple[str, ...] = (
    RELEASE_FUNCTION_SQL,
    "DROP TRIGGER IF EXISTS trg_equipment_release_deleted_assignment "
    "ON equipment_assignments",
    "CREATE TRIGGER trg_equipment_release_deleted_assignment "
    "AFTER DELETE ON equipment_assignments FOR EACH ROW "
    "EXECUTE FUNCTION equipment_release_deleted_assignment()",
    LINK_CONTRACT_EQUIPMENT_SQL,
    LINK_CONTRACT_ASSIGNMENTS_SQL,
)

TABLES: tuple[str, ...] = (
    "equipment_models",
    "equipment_items",
    "equipment_external_people",
    "equipment_protocols",
    "equipment_assignments",
    "equipment_protocol_lines",
    "equipment_protocol_links",
    "equipment_tasks",
    "equipment_import_batches",
    "equipment_import_rows",
    "equipment_protocol_templates",
    "client_onboarding_packs",
    "client_onboarding_pack_items",
    "consultant_welcome_mails",
)

DOWNGRADE_DDL: tuple[str, ...] = (
    "ALTER TABLE equipment_protocols DROP COLUMN IF EXISTS template_id",
    "ALTER TABLE contract_equipment DROP COLUMN IF EXISTS assignment_id",
    "ALTER TABLE contract_equipment DROP COLUMN IF EXISTS item_id",
    "ALTER TABLE clients DROP CONSTRAINT IF EXISTS ck_clients_equipment_provider",
    "ALTER TABLE clients DROP COLUMN IF EXISTS equipment_provider",
    "DROP FUNCTION IF EXISTS equipment_release_deleted_assignment()",
)

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
