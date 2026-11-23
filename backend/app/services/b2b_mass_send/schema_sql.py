"""Masowa wysyłka nowej umowy B2B (E5b, 0757): SQL migracji i lustra entrypointu.

Jedno źródło instrukcji dla ``alembic/versions/0757_b2b_mass_send.py``
i ``entrypoint.sh`` (alembic na produkcji bywa osierocony). Każda instrukcja
idempotentna. Moduł bez importów z aplikacji: siatka DDL czyta go, zanim
ustawi adres bazy.

* ``b2b_mass_send_batches`` — jedna wysyłka: kto ją zaczął, kto podpisuje za
  B2Bnetwork, termin linku w dniach, stan i liczby z chwili planu.
* ``b2b_mass_send_items`` — jedna osoba w wysyłce: kontrakt, kandydat, wiersz
  Generatora, z którego wzięto dane, nowy wiersz Generatora, wniosek o podpis
  i stan pozycji z powodem. Osoba ma najwyżej jedną pozycję w toku albo
  wysłaną (``uq_b2b_mass_send_items_live_person``) — druga wysyłka jej nie
  dubluje.
"""

from __future__ import annotations

BATCH_STATUSES: tuple[str, ...] = ("running", "finished", "cancelled")
ITEM_STATUSES: tuple[str, ...] = (
    "pending",
    "created",
    "sent",
    "failed",
    "needs_review",
    "skipped",
)
#: Stany, w których osoba „jest już w wysyłce”.
LIVE_ITEM_STATUSES: tuple[str, ...] = ("pending", "created", "sent")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS b2b_mass_send_batches (
    id SERIAL PRIMARY KEY,
    status VARCHAR(16) NOT NULL DEFAULT 'running',
    started_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    company_signer_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    link_days SMALLINT NOT NULL,
    skip_ending BOOLEAN NOT NULL DEFAULT TRUE,
    template_label VARCHAR(160) NOT NULL,
    planned JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    finished_at TIMESTAMPTZ NULL,
    cancelled_at TIMESTAMPTZ NULL,
    cancelled_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_b2b_mass_send_batches_status CHECK (status IN ({_quoted(BATCH_STATUSES)})),
    CONSTRAINT ck_b2b_mass_send_batches_days CHECK (link_days BETWEEN 1 AND 30)
)""",
    f"""CREATE TABLE IF NOT EXISTS b2b_mass_send_items (
    id SERIAL PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES b2b_mass_send_batches(id) ON DELETE CASCADE,
    contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE SET NULL,
    candidate_id INTEGER NULL REFERENCES candidates(id) ON DELETE SET NULL,
    client_id INTEGER NULL REFERENCES clients(id) ON DELETE SET NULL,
    source_generated_contract_id INTEGER NULL REFERENCES b2b_generated_contracts(id) ON DELETE SET NULL,
    generated_contract_id INTEGER NULL REFERENCES b2b_generated_contracts(id) ON DELETE SET NULL,
    signing_request_id INTEGER NULL REFERENCES b2b_signing_requests(id) ON DELETE SET NULL,
    status VARCHAR(16) NOT NULL,
    reason VARCHAR(32) NULL,
    missing JSONB NOT NULL DEFAULT '[]'::jsonb,
    error TEXT NULL,
    attempts SMALLINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_b2b_mass_send_items_status CHECK (status IN ({_quoted(ITEM_STATUSES)})),
    CONSTRAINT ck_b2b_mass_send_items_missing CHECK (jsonb_typeof(missing) = 'array')
)""",
)

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_b2b_mass_send_items_batch_status "
    "ON b2b_mass_send_items (batch_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_b2b_mass_send_items_generated "
    "ON b2b_mass_send_items (generated_contract_id) "
    "WHERE generated_contract_id IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_b2b_mass_send_items_live_person "
    "ON b2b_mass_send_items (candidate_id) "
    f"WHERE status IN ({_quoted(LIVE_ITEM_STATUSES)})",
)

ALL_DDL: tuple[str, ...] = (*TABLE_DDL, *INDEX_DDL)

DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP TABLE IF EXISTS b2b_mass_send_items",
    "DROP TABLE IF EXISTS b2b_mass_send_batches",
)
