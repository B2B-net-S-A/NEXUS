"""„Ludzie w NEXUSIE” — załącznik do wniosku urlopowego: SQL migracji ``0473_hr_leave_proofs`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0473_hr_leave_proofs.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Kontrakt
modułu jak w pozostałych ``*_schema.py``; każda instrukcja idempotentna.

Compass miał przy wniosku jeden plik (``uploadLeaveProof``: akt ślubu,
urodzenia, zgonu, zaświadczenie o krwiodawstwie). W NEXUSIE załącznik jest
dokumentem e-teczki (``hr_documents``) rodzaju „potwierdzenie nieobecności”
(``absence_proof``) z odnośnikiem do wniosku:

* ``hr_documents.leave_request_id`` — wniosek, do którego osoba dołączyła
  plik (``ON DELETE SET NULL``: wniosków się nie kasuje, ale dokument osoby
  przeżyłby wniosek). Odnośnik ma tylko rodzaj ``absence_proof``,
* rodzaj ``absence_proof`` dochodzi do CHECK-a ``ck_hr_documents_kind``
  (lista rodzajów żyje w ``hr_documents_schema.DOCUMENT_KINDS`` — ta sama
  stała buduje CREATE TABLE z 0469 i poszerzenie tutaj, więc definicja
  więzu jest jedna).

Krąg: osoba i Kadry (admin). Przełożony widzi przy wniosku tylko, że
załącznik jest — treść bywa aktem zgonu albo dokumentem dziecka (D6).
"""

from __future__ import annotations

from app.services.hr_documents_schema import CK_DOCUMENT_KIND

#: Odnośnik do wniosku ma tylko potwierdzenie nieobecności.
CK_DOCUMENT_LEAVE_REQUEST = "leave_request_id IS NULL OR kind = 'absence_proof'"
LEAVE_REQUEST_WHERE = "leave_request_id IS NOT NULL"

TABLE_DDL: tuple[str, ...] = ()

COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE hr_documents ADD COLUMN IF NOT EXISTS "
    "leave_request_id UUID NULL REFERENCES leave_requests(id) ON DELETE SET NULL",
)

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_hr_documents_leave_request "
    f"ON hr_documents (leave_request_id) WHERE {LEAVE_REQUEST_WHERE}",
)

CONSTRAINT_DDL: tuple[str, ...] = (
    f"""DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'ck_hr_documents_kind'
              AND pg_get_constraintdef(oid) LIKE '%absence_proof%'
        ) THEN
            ALTER TABLE hr_documents DROP CONSTRAINT IF EXISTS ck_hr_documents_kind;
            ALTER TABLE hr_documents
                ADD CONSTRAINT ck_hr_documents_kind CHECK ({CK_DOCUMENT_KIND});
        END IF;
    END $$""",
    f"""DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'ck_hr_documents_leave_request'
        ) THEN
            ALTER TABLE hr_documents
                ADD CONSTRAINT ck_hr_documents_leave_request
                CHECK ({CK_DOCUMENT_LEAVE_REQUEST});
        END IF;
    END $$""",
)

DATA_DDL: tuple[str, ...] = ()
TABLES: tuple[str, ...] = ()
DOWNGRADE_DDL: tuple[str, ...] = (
    "ALTER TABLE hr_documents DROP CONSTRAINT IF EXISTS ck_hr_documents_leave_request",
    "DROP INDEX IF EXISTS ix_hr_documents_leave_request",
    "ALTER TABLE hr_documents DROP COLUMN IF EXISTS leave_request_id",
)

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
