"""Historia stawek z faktur KSeF (0781): SQL migracji i lustra entrypointu.

Jedno źródło instrukcji dla ``alembic/versions/0781_contract_rate_history_ksef.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Każda
instrukcja idempotentna.

``contract_rate_history_findings`` — jeden wiersz na kontrakt: kroki stawki
klienta i kosztowej wyprowadzone z faktur KSeF (``infer``), których nie ma
w harmonogramie (``steps``), ``signature`` = te same kroki w kolejnym przebiegu,
``status`` = co z nimi zrobiono. Stawkę zmienia wyłącznie zapis kroku
w ``contract_client_rates`` / ``contract_candidate_rates`` (człowiek albo wpis
automatyczny), nigdy ten wiersz.
"""

from __future__ import annotations

STATUSES: tuple[str, ...] = (
    "open",
    "auto_applied",
    "applied",
    "dismissed",
    "undone",
    "resolved",
)


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS contract_rate_history_findings (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    category VARCHAR(24) NOT NULL,
    automatic BOOLEAN NOT NULL DEFAULT FALSE,
    steps JSONB NOT NULL DEFAULT '[]'::jsonb,
    signature VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'open',
    created_steps JSONB NULL,
    decided_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    decided_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_contract_rate_history_findings_status CHECK (status IN ({_quoted(STATUSES)})),
    CONSTRAINT ck_contract_rate_history_findings_steps CHECK (jsonb_typeof(steps) = 'array'),
    CONSTRAINT uq_contract_rate_history_findings_contract UNIQUE (contract_id)
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_contract_rate_history_findings_open "
    "ON contract_rate_history_findings (contract_id) WHERE status IN ('open', 'undone')",
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

DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP TABLE IF EXISTS contract_rate_history_findings",
)
