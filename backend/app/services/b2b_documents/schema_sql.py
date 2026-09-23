"""DDL dokumentów pochodnych — JEDNO źródło dla migracji 0358 i ``entrypoint.sh``.

Produkcyjny alembic bywa osierocony, więc siatka bezpieczeństwa w
``entrypoint.sh`` jest wdrożeniem równorzędnym z migracją. Dwie ręczne kopie
tego samego ``CREATE TABLE`` rozjeżdżają się przy pierwszej poprawce — dlatego
obie strony importują listy stąd.
"""

from __future__ import annotations

from app.services.b2b_documents.constants import (
    B2B_DOCUMENT_STATUSES,
    B2B_DOCUMENT_TYPES,
)


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


#: Nowe typy aneksu w ``contractamendmenttype``. ``ADD VALUE`` nie może biec
#: w transakcji — migracja używa ``autocommit_block``, entrypoint listy enumów.
AMENDMENT_ENUM_VALUES: tuple[str, ...] = (
    "start_date_change",
    "party_data_change",
    "subcontractor_consent",
    "mandate_change",
)

ENUM_DDL: list[str] = [
    f"ALTER TYPE contractamendmenttype ADD VALUE IF NOT EXISTS '{value}'"
    for value in AMENDMENT_ENUM_VALUES
]

TABLE_DDL: list[str] = [
    f"""CREATE TABLE IF NOT EXISTS b2b_contract_documents (
           id SERIAL PRIMARY KEY,
           document_type VARCHAR(40) NOT NULL,
           language VARCHAR(2) NOT NULL DEFAULT 'pl',
           parent_generated_contract_id INTEGER NULL
               REFERENCES b2b_generated_contracts (id) ON DELETE CASCADE,
           contract_id INTEGER NULL REFERENCES contracts (id) ON DELETE SET NULL,
           candidate_id INTEGER NULL REFERENCES candidates (id) ON DELETE SET NULL,
           job_id INTEGER NULL REFERENCES jobs (id) ON DELETE SET NULL,
           client_id INTEGER NULL REFERENCES clients (id) ON DELETE SET NULL,
           document_date DATE NOT NULL,
           render_payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
           template_key VARCHAR(80) NOT NULL,
           status VARCHAR(16) NOT NULL DEFAULT 'issued',
           signature_status VARCHAR(16) NOT NULL DEFAULT 'unsigned',
           signed_at TIMESTAMPTZ NULL,
           signed_by_user_id INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           effect_applied_at TIMESTAMPTZ NULL,
           effect_summary JSONB NULL,
           cancelled_reason TEXT NULL,
           created_by INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           CONSTRAINT ck_b2b_contract_documents_type
               CHECK (document_type IN ({_in_list(B2B_DOCUMENT_TYPES)})),
           CONSTRAINT ck_b2b_contract_documents_status
               CHECK (status IN ({_in_list(B2B_DOCUMENT_STATUSES)})),
           CONSTRAINT ck_b2b_contract_documents_language
               CHECK (language IN ('pl', 'en')),
           CONSTRAINT ck_b2b_contract_documents_signature_status
               CHECK (signature_status IN ('unsigned', 'signed_both'))
       )""",
    """CREATE INDEX IF NOT EXISTS ix_b2b_contract_documents_id
       ON b2b_contract_documents (id)""",
    """CREATE INDEX IF NOT EXISTS ix_b2b_contract_documents_document_type
       ON b2b_contract_documents (document_type)""",
    """CREATE INDEX IF NOT EXISTS ix_b2b_contract_documents_parent_generated_contract_id
       ON b2b_contract_documents (parent_generated_contract_id)""",
    """CREATE INDEX IF NOT EXISTS ix_b2b_contract_documents_contract_id
       ON b2b_contract_documents (contract_id)""",
    """CREATE INDEX IF NOT EXISTS ix_b2b_contract_documents_candidate_id
       ON b2b_contract_documents (candidate_id)""",
    """CREATE INDEX IF NOT EXISTS ix_b2b_contract_documents_client_id
       ON b2b_contract_documents (client_id)""",
    # Wersja wzoru umowy bazowej — od niej zależą paragrafy w aneksach.
    """ALTER TABLE b2b_generated_contracts
       ADD COLUMN IF NOT EXISTS template_version VARCHAR(16) NULL""",
]

#: Każda umowa wydana dotąd przez generator poszła ze wzoru 2026 (szablony
#: zbudowano z draftu prawnika z 2026 r.). Samoograniczające: dotyka tylko
#: wierszy z payloadem i bez wersji.
BACKFILL_DDL: list[str] = [
    """UPDATE b2b_generated_contracts
       SET template_version = '2026'
       WHERE template_version IS NULL AND render_payload IS NOT NULL""",
]
