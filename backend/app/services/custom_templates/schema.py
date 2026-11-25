"""Wzory własne Generatora Umów B2B (asystent prawny, część B, 25.11.2026):
SQL migracji ``0785_custom_document_templates`` i lustra entrypointu.

Jedno źródło instrukcji dla ``alembic/versions/0785_custom_document_templates.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``).

Tabele:

* ``custom_document_templates`` — wzór: która wersja jest w użyciu
  (``active_version_id``, zatwierdzona) i czy wzór wycofano. Bez klucza obcego
  na wersję: tabele wskazują na siebie nawzajem, a spójność pilnuje serwis.
* ``custom_document_template_versions`` — wersja: DOCX (szablon docxtpl),
  lista pól, opis i ustawienia (nazwa, rodzaj, klienci, podpis), status
  ``draft`` → ``pending`` → ``approved`` (albo z powrotem ``draft`` z uwagą
  zatwierdzającego), ``withdrawn`` po wycofaniu wzoru; kto i kiedy.
  Jedna wersja robocza (szkic albo do zatwierdzenia) na wzór.

Wydany dokument trafia do ``b2b_contract_documents`` jako typ
``custom_template`` z kluczem ``custom_v<id wersji>`` — pobiera się zawsze tą
wersją, którą wydano (jak ``template_revision`` typów z rejestru).
"""

from __future__ import annotations

from app.services.consultant_portal_schema import quoted

VERSION_STATUSES: tuple[str, ...] = ("draft", "pending", "approved", "withdrawn")
#: Rodzaj dokumentu — tylko etykieta i sekcja w „Nowy dokument”; skutków
#: w kontraktach wzór własny nie ma (decyzja Artura, 25.11.2026).
KINDS: tuple[str, ...] = ("contract", "preliminary", "annex", "letter")
CLIENT_SCOPES: tuple[str, ...] = ("all", "selected")
SIGNATORIES: tuple[str, ...] = ("both", "company", "partner_and_company")
#: ``written`` = podpis na papierze albo kwalifikowany (np. przeniesienie
#: autorskich praw majątkowych, art. 53 pr. aut.).
SIGNATURE_FORMS: tuple[str, ...] = ("any", "written")
ORIGINS: tuple[str, ...] = ("base", "upload", "brief")

NAME_MAX = 150
BASE_KEY_MAX = 80

CK_STATUS = f"status IN ({quoted(VERSION_STATUSES)})"
CK_KIND = f"kind IN ({quoted(KINDS)})"
CK_CLIENT_SCOPE = f"client_scope IN ({quoted(CLIENT_SCOPES)})"
CK_SIGNATORIES = f"signatories IN ({quoted(SIGNATORIES)})"
CK_SIGNATURE_FORM = f"signature_form IN ({quoted(SIGNATURE_FORMS)})"
CK_ORIGIN = f"origin IN ({quoted(ORIGINS)})"

TABLES: tuple[str, ...] = (
    "custom_document_templates",
    "custom_document_template_versions",
)

TABLE_DDL: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS custom_document_templates (
    id SERIAL PRIMARY KEY,
    active_version_id INTEGER NULL,
    withdrawn_at TIMESTAMPTZ NULL,
    withdrawn_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    withdrawn_reason TEXT NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
    f"""CREATE TABLE IF NOT EXISTS custom_document_template_versions (
    id SERIAL PRIMARY KEY,
    template_id INTEGER NOT NULL
        REFERENCES custom_document_templates(id) ON DELETE CASCADE,
    version_no INTEGER NOT NULL,
    status VARCHAR(12) NOT NULL DEFAULT 'draft',
    name VARCHAR({NAME_MAX}) NOT NULL,
    kind VARCHAR(16) NOT NULL DEFAULT 'contract',
    description TEXT NOT NULL DEFAULT '',
    client_scope VARCHAR(8) NOT NULL DEFAULT 'all',
    client_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    signatories VARCHAR(24) NOT NULL DEFAULT 'both',
    signature_form VARCHAR(12) NOT NULL DEFAULT 'any',
    origin VARCHAR(12) NOT NULL,
    base_key VARCHAR({BASE_KEY_MAX}) NULL,
    instruction TEXT NULL,
    docx BYTEA NOT NULL,
    docx_sha256 VARCHAR(64) NOT NULL,
    fields JSONB NOT NULL DEFAULT '[]'::jsonb,
    changes JSONB NOT NULL DEFAULT '[]'::jsonb,
    checks JSONB NOT NULL DEFAULT '[]'::jsonb,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    ai_used BOOLEAN NOT NULL DEFAULT FALSE,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    submitted_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    submitted_at TIMESTAMPTZ NULL,
    reviewed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMPTZ NULL,
    review_note TEXT NULL,
    CONSTRAINT uq_custom_template_versions_no UNIQUE (template_id, version_no),
    CONSTRAINT ck_custom_template_versions_status CHECK ({CK_STATUS}),
    CONSTRAINT ck_custom_template_versions_kind CHECK ({CK_KIND}),
    CONSTRAINT ck_custom_template_versions_client_scope CHECK ({CK_CLIENT_SCOPE}),
    CONSTRAINT ck_custom_template_versions_signatories CHECK ({CK_SIGNATORIES}),
    CONSTRAINT ck_custom_template_versions_signature_form
        CHECK ({CK_SIGNATURE_FORM}),
    CONSTRAINT ck_custom_template_versions_origin CHECK ({CK_ORIGIN}),
    CONSTRAINT ck_custom_template_versions_arrays CHECK (
        jsonb_typeof(client_ids) = 'array' AND jsonb_typeof(fields) = 'array'
    )
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_custom_template_versions_template "
    "ON custom_document_template_versions (template_id)",
    "CREATE INDEX IF NOT EXISTS ix_custom_template_versions_status "
    "ON custom_document_template_versions (status)",
    # Jedna wersja robocza na wzór: drugi szkic obok czekającego na
    # zatwierdzenie rozjechałby się z nim bez śladu.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_custom_template_versions_open "
    "ON custom_document_template_versions (template_id) "
    "WHERE status IN ('draft', 'pending')",
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

#: Funkcja AI szkicu wzoru — wartość enuma ``aifeaturekey`` i wiersz
#: ``ai_features`` (migracja i lustro ``entrypoint.sh``).
AI_FEATURE = "legal_template_draft"
AI_ENUM_DDL = f"ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS '{AI_FEATURE}'"
AI_SEED_DDL = (
    "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
    f"SELECT '{AI_FEATURE}', TRUE, 0, now(), now() "
    "WHERE NOT EXISTS "
    f"(SELECT 1 FROM ai_features WHERE feature = '{AI_FEATURE}')"
)
