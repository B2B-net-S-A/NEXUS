"""„Ludzie w NEXUSIE” — dokumenty osoby (e-teczka, etap 5, E4): SQL migracji ``0469_hr_documents`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0469_hr_documents.py`` i ``entrypoint.sh``
(przez ``app/services/hr_schema_bundle.py``). Kontrakt modułu jak w pozostałych
``*_schema.py``; każda instrukcja idempotentna (entrypoint wykonuje je przy
każdym starcie).

Tabela ``hr_documents`` — dokument przy osobie (kartoteka), jeden wiersz na plik:

* **rodzaj** (``kind``) ze słownika: umowa, aneks, oświadczenie, zaświadczenie,
  protokół, potwierdzenie nieobecności, inne (etykiety —
  ``services/hr/documents_rules.KIND_LABELS``); potwierdzenie nieobecności
  bywa załącznikiem wniosku urlopowego (``leave_request_id``, 0473 —
  ``hr_leave_proofs_schema``);
  ``purpose = 'student_status'`` oznacza oświadczenie o statusie ucznia lub
  studenta — jego „ważny do” zasila datę końca zwolnienia ze składek
  w kartotece, a z niej przypomnienie dla Płac 30 dni wcześniej
  (``student_reminders``; drugiego przypomnienia nie ma),
* **plik** w magazynie uploadów aplikacji (``storage_service.STORAGE_ROOT``,
  podkatalog ``hr_documents/<osoba>/``): ścieżka względna, nazwa pliku od
  człowieka, typ (tylko PDF, DOCX, JPG, PNG), rozmiar i SHA-256 treści,
* **źródło**: ``upload`` — wgrany przez Kadry, ``agreement`` — z generatora
  umów z ludźmi (E5, ``documents.attach_generated``; ``source_ref`` wskazuje
  umowę, a para ``source``+``source_ref`` jest unikalna, więc ponowne wołanie
  po podpisie nie dubluje dokumentu). Protokoły sprzętu NIE są tu kopiowane —
  e-teczka czyta je z ``equipment_protocols`` jako odnośniki,
* **krąg widzących**: Kadry i admin zawsze; osoba, Płace i recepcja
  („Sprzęt”) według znaczników. Przełożony nie widzi dokumentów osoby,
* **retencja po odejściu**: nic nie kasuje się samo. Okres na rodzaj jest
  w ``app_settings['hr_document_retention']``; po terminie dokument trafia na
  listę Kadr „do usunięcia po terminie”, a usuwa go człowiek z potwierdzeniem.
  Usunięcie (po terminie albo pomyłkowo wgranego pliku — z powodem) kasuje
  plik, a wiersz zostaje jako ślad (rodzaj, tytuł, skrót, kto i kiedy).

PESEL i numer dowodu nie są polami tej tabeli — wgrany plik może je mieć
w treści, ale NEXUS ich nie czyta ani nie wyświetla.
"""

from __future__ import annotations

DOCUMENT_KINDS: tuple[str, ...] = (
    "contract",
    "annex",
    "statement",
    "certificate",
    "protocol",
    "absence_proof",
    "other",
)
DOCUMENT_PURPOSES: tuple[str, ...] = ("student_status",)
DOCUMENT_SOURCES: tuple[str, ...] = ("upload", "agreement")
#: Źródła dokumentów z generatora (``attach_generated``) — bez ręcznego wgrania.
GENERATED_SOURCES: tuple[str, ...] = ("agreement",)
DELETION_REASONS: tuple[str, ...] = ("retention", "mistake")
#: Typy, które przyjmujemy (wgranie i generator). HTML, SVG i inne typy
#: renderowane przez przeglądarkę nie wchodzą — plik bywa otwierany w karcie.
DOCUMENT_MIME_TYPES: tuple[str, ...] = (
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/jpeg",
    "image/png",
)

TITLE_MAX_LENGTH = 300
NOTE_MAX_LENGTH = 500
SOURCE_REF_MAX_LENGTH = 128
FILE_NAME_MAX_LENGTH = 255
MAX_FILE_BYTES = 20 * 1024 * 1024

RETENTION_SETTING = "hr_document_retention"


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


CK_DOCUMENT_KIND = f"kind IN ({quoted(DOCUMENT_KINDS)})"
#: Oświadczenie studenta ma datę „ważny do” — bez niej nie zasili przypomnienia.
CK_DOCUMENT_PURPOSE = (
    "purpose IS NULL OR (purpose IN ("
    f"{quoted(DOCUMENT_PURPOSES)}) AND kind = 'statement' AND valid_until IS NOT NULL)"
)
CK_DOCUMENT_SOURCE = f"source IN ({quoted(DOCUMENT_SOURCES)})"
#: Wgrany dokument nie ma odnośnika; dokument z generatora ma go zawsze.
CK_DOCUMENT_SOURCE_REF = (
    "(source = 'upload') = (source_ref IS NULL) AND (source_ref IS NULL "
    f"OR char_length(source_ref) BETWEEN 1 AND {SOURCE_REF_MAX_LENGTH})"
)
CK_DOCUMENT_TITLE = f"char_length(btrim(title)) BETWEEN 1 AND {TITLE_MAX_LENGTH}"
CK_DOCUMENT_MIME = f"mime IN ({quoted(DOCUMENT_MIME_TYPES)})"
CK_DOCUMENT_SIZE = f"size_bytes > 0 AND size_bytes <= {MAX_FILE_BYTES}"
CK_DOCUMENT_SHA = "sha256 ~ '^[0-9a-f]{64}$'"
#: Plik jest, dopóki dokument nie został usunięty; usunięcie kasuje plik.
CK_DOCUMENT_FILE = "(deleted_at IS NULL) = (file_path IS NOT NULL)"
CK_DOCUMENT_DELETED = (
    "(deleted_at IS NULL) = (deletion_reason IS NULL) AND (deletion_reason IS NULL "
    f"OR deletion_reason IN ({quoted(DELETION_REASONS)}))"
)
#: Usunięcie pomyłki wymaga powodu (po terminie wystarczy termin).
CK_DOCUMENT_DELETION_NOTE = (
    "deletion_reason IS DISTINCT FROM 'mistake' OR "
    f"char_length(btrim(deletion_note)) BETWEEN 1 AND {NOTE_MAX_LENGTH}"
)
SOURCE_REF_WHERE = "source_ref IS NOT NULL"
LIVE_UPLOAD_WHERE = "source = 'upload' AND deleted_at IS NULL"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS hr_documents (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    kind VARCHAR(16) NOT NULL,
    purpose VARCHAR(32) NULL,
    title VARCHAR({TITLE_MAX_LENGTH}) NOT NULL,
    source VARCHAR(16) NOT NULL DEFAULT 'upload',
    source_ref VARCHAR({SOURCE_REF_MAX_LENGTH}) NULL,
    file_path TEXT NULL,
    file_name VARCHAR({FILE_NAME_MAX_LENGTH}) NULL,
    mime VARCHAR(100) NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    valid_until DATE NULL,
    visible_to_person BOOLEAN NOT NULL DEFAULT true,
    visible_to_payroll BOOLEAN NOT NULL DEFAULT false,
    visible_to_equipment BOOLEAN NOT NULL DEFAULT false,
    added_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    deleted_at TIMESTAMPTZ NULL,
    deleted_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    deletion_reason VARCHAR(16) NULL,
    deletion_note VARCHAR({NOTE_MAX_LENGTH}) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_hr_documents_kind CHECK ({CK_DOCUMENT_KIND}),
    CONSTRAINT ck_hr_documents_purpose CHECK ({CK_DOCUMENT_PURPOSE}),
    CONSTRAINT ck_hr_documents_source CHECK ({CK_DOCUMENT_SOURCE}),
    CONSTRAINT ck_hr_documents_source_ref CHECK ({CK_DOCUMENT_SOURCE_REF}),
    CONSTRAINT ck_hr_documents_title CHECK ({CK_DOCUMENT_TITLE}),
    CONSTRAINT ck_hr_documents_mime CHECK ({CK_DOCUMENT_MIME}),
    CONSTRAINT ck_hr_documents_size CHECK ({CK_DOCUMENT_SIZE}),
    CONSTRAINT ck_hr_documents_sha CHECK ({CK_DOCUMENT_SHA}),
    CONSTRAINT ck_hr_documents_file CHECK ({CK_DOCUMENT_FILE}),
    CONSTRAINT ck_hr_documents_deleted CHECK ({CK_DOCUMENT_DELETED}),
    CONSTRAINT ck_hr_documents_deletion_note CHECK ({CK_DOCUMENT_DELETION_NOTE})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_hr_documents_user ON hr_documents (user_id)",
    # Ponowne wołanie generatora po podpisie (retry, webhook) nie dubluje dokumentu.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_hr_documents_source_ref "
    f"ON hr_documents (source, source_ref) WHERE {SOURCE_REF_WHERE}",
    # Ten sam plik wgrany drugi raz tej samej osobie = 409, także w wyścigu.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_hr_documents_live_upload "
    f"ON hr_documents (user_id, sha256) WHERE {LIVE_UPLOAD_WHERE}",
)

CONSTRAINT_DDL: tuple[str, ...] = ()
DATA_DDL: tuple[str, ...] = ()
TABLES: tuple[str, ...] = ("hr_documents",)
DOWNGRADE_DDL: tuple[str, ...] = ()

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
