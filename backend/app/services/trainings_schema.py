"""Szkolenia i trenerzy (decyzja Artura 13.11.2026): SQL migracji ``0694_trainings`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0694_trainings.py`` i ``entrypoint.sh``
(przez ``app/services/hr_schema_bundle.py``).

Szkolenie prowadzi konsultant z umową szkoleniową B2B albo pracownik. Umowa szkoleniowa
(wzór „Umowa B2B - Szkolenia”) wymaga Załącznika nr 1: dane szkolenia, agenda, pliki do
przekazania, prawa autorskie i wynagrodzenie w pozycjach A–E. Dlatego zamówienie
i wycena to pola ``trainings``, a nie wolny tekst w sprawie.

Tabele:

* ``trainings`` — jedno szkolenie: zamówienie TCM, wycena trenera, umowa i jej podpisy,
  faktura, zapłata i publikacja w bibliotece. Kwoty (``fee_*``) widzą tylko TCM, Finanse,
  admin i sam trener.
* ``training_files`` — pliki szkolenia: przekazane przez trenera pozycje Zał. 1 (z przyjęciem
  albo zwrotem do poprawy), nagranie, faktura, pliki wewnętrzne. Plik leży w SharePoincie
  albo na dysku (``storage``); ``for_participants`` = widoczny w bibliotece.
* ``training_registrations`` — zapisy na szkolenie na żywo (pracownik albo konsultant).
* ``training_attendance`` — obecność z raportu Teams (CSV), dopasowana do osób, gdy się da.

Do ``cp_trainer_applications`` dochodzą pola zgłoszenia zgodnego z umową: propozycja
szkolenia, liczba godzin, odbiorcy i próbka materiałów. Kolumny ``form`` i ``day_rate``
zostają (bez DROP-a), ale panel ich już nie zbiera: szkolenie jest wyłącznie zdalne (§ 3),
a cena to wycena konkretnego zamówienia (§ 7, Zał. 1 pkt 6).
"""

from __future__ import annotations

from app.services.consultant_panel_schema import MATERIAL_URL_MAX, TRAINER_SHORT_MAX
from app.services.consultant_portal_schema import quoted

#: draft → ordered (u trenera) → quoted (wycena u TCM) ⇄ returned → accepted (umowa do
#: podpisu trenera) → trainer_signed → signed. Szkolenie pracownika startuje od ``signed``,
#: bo umowy B2B nie ma. ``cancelled`` z każdego stanu przed ``signed``.
STATUSES: tuple[str, ...] = (
    "draft",
    "ordered",
    "quoted",
    "returned",
    "accepted",
    "trainer_signed",
    "signed",
    "cancelled",
)
TRAINER_KINDS: tuple[str, ...] = ("consultant", "employee")
FILE_KINDS: tuple[str, ...] = (
    "deliverable",
    "recording",
    "invoice",
    "internal",
)
FILE_STATUSES: tuple[str, ...] = ("submitted", "accepted", "returned", "replaced")
#: Zał. 1 pkt 4: materiały dla uczestników, prezentacja, pliki audio, inne.
DELIVERABLE_KEYS: tuple[str, ...] = ("materials", "presentation", "audio", "other")
STORAGES: tuple[str, ...] = ("local", "sharepoint")

TITLE_MAX = 200
TEXT_MAX = 3_000
DESCRIPTION_MAX = 5_000
NOTE_MAX = 2_000
FILE_NAME_MAX = 255
PATH_MAX = 1_000
AGENDA_MAX = 12

CK_STATUS = f"status IN ({quoted(STATUSES)})"
CK_TRAINER_KIND = f"trainer_kind IN ({quoted(TRAINER_KINDS)})"
CK_TRAINER = (
    "(trainer_kind = 'consultant' AND trainer_user_id IS NULL) "
    "OR (trainer_kind = 'employee' AND trainer_contract_id IS NULL)"
)
CK_JSON_ARRAYS = (
    "jsonb_typeof(deliverables) = 'array' AND jsonb_typeof(agenda) = 'array'"
)
CK_PARTNER = "jsonb_typeof(partner) = 'object'"
CK_FEES = (
    "coalesce(fee_prep, 0) >= 0 AND coalesce(fee_delivery, 0) >= 0 "
    "AND coalesce(fee_presentation, 0) >= 0 AND coalesce(fee_audio, 0) >= 0 "
    "AND coalesce(fee_rights, 0) >= 0"
)
CK_FILE_KIND = f"kind IN ({quoted(FILE_KINDS)})"
CK_FILE_STATUS = f"status IN ({quoted(FILE_STATUSES)})"
CK_FILE_KEY = (
    f"(kind = 'deliverable' AND deliverable_key IN ({quoted(DELIVERABLE_KEYS)})) "
    "OR (kind <> 'deliverable' AND deliverable_key IS NULL)"
)
CK_FILE_STORAGE = f"storage IN ({quoted(STORAGES)})"
CK_REGISTRATION_WHO = "(user_id IS NULL) <> (contract_id IS NULL)"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS trainings (
    id SERIAL PRIMARY KEY,
    title VARCHAR({TITLE_MAX}) NOT NULL,
    topic VARCHAR({TITLE_MAX}) NOT NULL DEFAULT '',
    description VARCHAR({DESCRIPTION_MAX}) NOT NULL DEFAULT '',
    trainer_kind VARCHAR(20) NOT NULL DEFAULT 'consultant',
    trainer_contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE SET NULL,
    trainer_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    application_id INTEGER NULL REFERENCES cp_trainer_applications(id) ON DELETE SET NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    session_date DATE NULL,
    time_from VARCHAR(5) NOT NULL DEFAULT '',
    time_to VARCHAR(5) NOT NULL DEFAULT '',
    duration_minutes INTEGER NULL,
    platform VARCHAR({TITLE_MAX}) NOT NULL DEFAULT 'Microsoft Teams',
    join_url VARCHAR({PATH_MAX}) NOT NULL DEFAULT '',
    expected_participants INTEGER NULL,
    quote_due_on DATE NULL,
    participant_materials VARCHAR({TEXT_MAX}) NOT NULL DEFAULT '',
    deliverables JSONB NOT NULL DEFAULT '[]'::jsonb,
    agenda JSONB NOT NULL DEFAULT '[]'::jsonb,
    own_materials VARCHAR({TEXT_MAX}) NOT NULL DEFAULT '',
    third_party_materials VARCHAR({TEXT_MAX}) NOT NULL DEFAULT '',
    extra_terms VARCHAR({TEXT_MAX}) NOT NULL DEFAULT '',
    knowledge_test BOOLEAN NOT NULL DEFAULT false,
    fee_prep NUMERIC(12, 2) NULL,
    fee_delivery NUMERIC(12, 2) NULL,
    fee_presentation NUMERIC(12, 2) NULL,
    fee_audio NUMERIC(12, 2) NULL,
    fee_rights NUMERIC(12, 2) NULL,
    quote_note VARCHAR({TEXT_MAX}) NOT NULL DEFAULT '',
    return_note VARCHAR({TEXT_MAX}) NOT NULL DEFAULT '',
    ordered_at TIMESTAMPTZ NULL,
    quoted_at TIMESTAMPTZ NULL,
    accepted_at TIMESTAMPTZ NULL,
    accepted_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    agreement_number VARCHAR(50) NOT NULL DEFAULT '',
    partner JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    agreement_pdf_path VARCHAR({PATH_MAX}) NULL,
    agreement_pdf_sha256 VARCHAR(64) NULL,
    agreement_generated_at TIMESTAMPTZ NULL,
    trainer_signed_pdf_path VARCHAR({PATH_MAX}) NULL,
    trainer_signed_at TIMESTAMPTZ NULL,
    company_signed_pdf_path VARCHAR({PATH_MAX}) NULL,
    company_signed_at TIMESTAMPTZ NULL,
    company_signed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    invoice_ready_at TIMESTAMPTZ NULL,
    paid_at TIMESTAMPTZ NULL,
    paid_marked_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    published_at TIMESTAMPTZ NULL,
    published_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    case_id INTEGER NULL REFERENCES admin_cases(id) ON DELETE SET NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    cancelled_at TIMESTAMPTZ NULL,
    cancel_reason VARCHAR({NOTE_MAX}) NOT NULL DEFAULT '',
    CONSTRAINT ck_trainings_status CHECK ({CK_STATUS}),
    CONSTRAINT ck_trainings_trainer_kind CHECK ({CK_TRAINER_KIND}),
    CONSTRAINT ck_trainings_trainer CHECK ({CK_TRAINER}),
    CONSTRAINT ck_trainings_json CHECK ({CK_JSON_ARRAYS}),
    CONSTRAINT ck_trainings_partner CHECK ({CK_PARTNER}),
    CONSTRAINT ck_trainings_fees CHECK ({CK_FEES})
)""",
    f"""CREATE TABLE IF NOT EXISTS training_files (
    id SERIAL PRIMARY KEY,
    training_id INTEGER NOT NULL REFERENCES trainings(id) ON DELETE CASCADE,
    kind VARCHAR(20) NOT NULL,
    deliverable_key VARCHAR(20) NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'submitted',
    file_name VARCHAR({FILE_NAME_MAX}) NOT NULL,
    content_type VARCHAR(120) NOT NULL DEFAULT 'application/octet-stream',
    size_bytes BIGINT NOT NULL DEFAULT 0,
    sha256 VARCHAR(64) NOT NULL DEFAULT '',
    storage VARCHAR(20) NOT NULL DEFAULT 'local',
    storage_key VARCHAR({PATH_MAX}) NOT NULL,
    sp_drive_id VARCHAR(200) NULL,
    uploaded_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    uploaded_by_contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE SET NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    review_note VARCHAR({NOTE_MAX}) NOT NULL DEFAULT '',
    reviewed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMPTZ NULL,
    fix_due_on DATE NULL,
    for_participants BOOLEAN NOT NULL DEFAULT false,
    CONSTRAINT ck_training_files_kind CHECK ({CK_FILE_KIND}),
    CONSTRAINT ck_training_files_status CHECK ({CK_FILE_STATUS}),
    CONSTRAINT ck_training_files_key CHECK ({CK_FILE_KEY}),
    CONSTRAINT ck_training_files_storage CHECK ({CK_FILE_STORAGE})
)""",
    """CREATE TABLE IF NOT EXISTS training_registrations (
    id SERIAL PRIMARY KEY,
    training_id INTEGER NOT NULL REFERENCES trainings(id) ON DELETE CASCADE,
    user_id INTEGER NULL REFERENCES users(id) ON DELETE CASCADE,
    contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_training_registrations_who CHECK ((user_id IS NULL) <> (contract_id IS NULL))
)""",
    f"""CREATE TABLE IF NOT EXISTS training_attendance (
    id SERIAL PRIMARY KEY,
    training_id INTEGER NOT NULL REFERENCES trainings(id) ON DELETE CASCADE,
    display_name VARCHAR({FILE_NAME_MAX}) NOT NULL DEFAULT '',
    email VARCHAR(255) NOT NULL DEFAULT '',
    minutes INTEGER NULL,
    user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE SET NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
)

COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE cp_trainer_applications ADD COLUMN IF NOT EXISTS "
    f"proposal_title VARCHAR({TITLE_MAX}) NOT NULL DEFAULT ''",
    "ALTER TABLE cp_trainer_applications ADD COLUMN IF NOT EXISTS "
    f"proposal_hours VARCHAR({TRAINER_SHORT_MAX}) NOT NULL DEFAULT ''",
    "ALTER TABLE cp_trainer_applications ADD COLUMN IF NOT EXISTS "
    f"audience VARCHAR({TRAINER_SHORT_MAX}) NOT NULL DEFAULT ''",
    "ALTER TABLE cp_trainer_applications ADD COLUMN IF NOT EXISTS "
    f"sample_path VARCHAR({MATERIAL_URL_MAX}) NULL",
    "ALTER TABLE cp_trainer_applications ADD COLUMN IF NOT EXISTS "
    f"sample_name VARCHAR({FILE_NAME_MAX}) NULL",
    "ALTER TABLE cp_trainer_applications ADD COLUMN IF NOT EXISTS "
    "sample_size INTEGER NULL",
)

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_trainings_trainer_contract "
    "ON trainings (trainer_contract_id) WHERE trainer_contract_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_trainings_status ON trainings (status)",
    "CREATE INDEX IF NOT EXISTS ix_trainings_published "
    "ON trainings (published_at) WHERE published_at IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_training_files_training "
    "ON training_files (training_id, kind)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_training_registrations_user "
    "ON training_registrations (training_id, user_id) WHERE user_id IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_training_registrations_contract "
    "ON training_registrations (training_id, contract_id) WHERE contract_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_training_attendance_training "
    "ON training_attendance (training_id)",
)

CONSTRAINT_DDL: tuple[str, ...] = ()
DATA_DDL: tuple[str, ...] = ()

TABLES: tuple[str, ...] = (
    "trainings",
    "training_files",
    "training_registrations",
    "training_attendance",
)

#: Kolumny dokładane do ``cp_trainer_applications`` (downgrade je zdejmuje).
APPLICATION_COLUMNS: tuple[str, ...] = (
    "proposal_title",
    "proposal_hours",
    "audience",
    "sample_path",
    "sample_name",
    "sample_size",
)

ALL_DDL: tuple[str, ...] = (*TABLE_DDL, *COLUMN_DDL, *INDEX_DDL)
