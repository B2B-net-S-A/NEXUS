"""Zgodność umów B2B z umową ramową klienta (część G, 0790): SQL migracji i lustra entrypointu.

Jedno źródło instrukcji dla ``alembic/versions/0790_legal_client_fit.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Każda
instrukcja idempotentna.

* ``legal_client_fit_checks`` — jeden wiersz na klienta: stan ostatniego
  sprawdzenia (w kolejce, trwa, gotowe, niedostępne, nieudane, brak umowy),
  odcisk źródeł, z których powstały ustalenia, i model. Ponowne zlecenie
  nadpisuje ten wiersz, nie dokłada nowego.
* ``legal_client_fit_findings`` — ustalenie na temat (``UNIQUE (client_id,
  topic)``): wymóg klienta z cytatem i oznaczeniem fragmentu, nasz zapis
  z cytatem i paragrafem albo brak, stan ``ok`` / ``gap`` / ``decide``.
  Ponowne sprawdzenie nadpisuje ustalenie tego tematu, więc nie dubluje.
  Szkic klauzuli klienta dla programisty to kolumny ``clause_draft_*`` —
  wzoru (``clause_overrides``) nic tu nie zmienia.
"""

from __future__ import annotations

from app.services.consultant_portal_schema import quoted

CHECK_STATUSES: tuple[str, ...] = (
    "queued",
    "running",
    "done",
    "unavailable",
    "failed",
    "no_contract",
)
TRIGGERS: tuple[str, ...] = ("upload", "manual")
STATES: tuple[str, ...] = ("ok", "gap", "decide")
SOURCE_KINDS: tuple[str, ...] = ("framework_contract", "amendment")

TOPIC_MAX = 32
CLIENT_REF_MAX = 300
OUR_REF_MAX = 120
MODEL_MAX = 64
LABEL_MAX = 255

CK_STATUS = f"status IN ({quoted(CHECK_STATUSES)})"
CK_TRIGGER = f"trigger IN ({quoted(TRIGGERS)})"
CK_STATE = f"state IN ({quoted(STATES)})"
CK_SOURCE_KIND = f"client_source_kind IN ({quoted(SOURCE_KINDS)})"
#: Zgodność albo „do decyzji” bez naszego cytatu byłaby twierdzeniem bez
#: pokrycia — tylko luka może mieć „brak” po naszej stronie.
CK_OUR_SIDE = "state = 'gap' OR our_quote IS NOT NULL"
CK_OUR_PAIR = "(our_quote IS NULL) = (our_ref IS NULL)"
CK_LAWYER = "jsonb_typeof(lawyer_review) = 'array'"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS legal_client_fit_checks (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    status VARCHAR(16) NOT NULL,
    status_message TEXT NULL,
    trigger VARCHAR(16) NOT NULL,
    requested_by_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    source_fingerprint VARCHAR(64) NULL,
    template_label VARCHAR({LABEL_MAX}) NULL,
    model VARCHAR({MODEL_MAX}) NULL,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ NULL,
    checked_at TIMESTAMPTZ NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_legal_client_fit_checks_client UNIQUE (client_id),
    CONSTRAINT ck_legal_client_fit_checks_status CHECK ({CK_STATUS}),
    CONSTRAINT ck_legal_client_fit_checks_trigger CHECK ({CK_TRIGGER})
)""",
    f"""CREATE TABLE IF NOT EXISTS legal_client_fit_findings (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    topic VARCHAR({TOPIC_MAX}) NOT NULL,
    state VARCHAR(8) NOT NULL,
    summary TEXT NOT NULL,
    client_quote TEXT NOT NULL,
    client_ref VARCHAR({CLIENT_REF_MAX}) NOT NULL,
    client_source_kind VARCHAR(20) NOT NULL,
    client_source_id INTEGER NOT NULL,
    our_quote TEXT NULL,
    our_ref VARCHAR({OUR_REF_MAX}) NULL,
    next_step TEXT NULL,
    annex_text TEXT NULL,
    lawyer_review JSONB NOT NULL DEFAULT '[]'::jsonb,
    clause_draft_text TEXT NULL,
    clause_draft_requested_at TIMESTAMPTZ NULL,
    clause_draft_requested_by_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_legal_client_fit_findings_topic UNIQUE (client_id, topic),
    CONSTRAINT ck_legal_client_fit_findings_state CHECK ({CK_STATE}),
    CONSTRAINT ck_legal_client_fit_findings_source_kind CHECK ({CK_SOURCE_KIND}),
    CONSTRAINT ck_legal_client_fit_findings_our_side CHECK ({CK_OUR_SIDE}),
    CONSTRAINT ck_legal_client_fit_findings_our_pair CHECK ({CK_OUR_PAIR}),
    CONSTRAINT ck_legal_client_fit_findings_lawyer CHECK ({CK_LAWYER})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_legal_client_fit_findings_state "
    "ON legal_client_fit_findings (state, client_id)",
)

CONSTRAINT_DDL: tuple[str, ...] = ()

DATA_DDL: tuple[str, ...] = ()

#: Kolejność zakładania; ``downgrade`` kasuje odwrotnie.
TABLES: tuple[str, ...] = ("legal_client_fit_checks", "legal_client_fit_findings")

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)

DOWNGRADE_DDL: tuple[str, ...] = tuple(
    f"DROP TABLE IF EXISTS {table}" for table in reversed(TABLES)
)
