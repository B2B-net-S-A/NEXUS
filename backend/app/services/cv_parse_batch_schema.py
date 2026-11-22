"""Kolejka odczytów CV przez Message Batches API (22.11.2026): SQL migracji
``0750_cv_parse_batch_items`` i lustra entrypointu.

Decyzja Artura z 22.11.2026: CV wgrane przez integrację (scrapery pracuj.pl
i JJIT) do istniejącego profilu czytamy wsadem (−50% ceny), a nie na żywo.
Jeden wiersz = jedno główne CV czekające na odczyt. Tekst pliku leży w wierszu
tylko do zebrania wyniku (``raw_text``), potem jest czyszczony.

Statusy:

* ``queued`` — czeka na wysłanie w paczce,
* ``submitted`` — w paczce ``batch_id``,
* ``fallback`` — czeka na odczyt na żywo (błąd paczki, brak wyniku, limit
  czasu); powód w ``error``,
* ``done`` — wynik paczki zapisany ścieżką wgrania CV,
* ``live`` — odczyt na żywo zrobiony zamiast wyniku paczki,
* ``superseded`` — nowsze CV albo odczyt na żywo zrobiony przez człowieka.
"""

from __future__ import annotations

from app.services.consultant_portal_schema import quoted

STATUSES: tuple[str, ...] = (
    "queued",
    "submitted",
    "fallback",
    "done",
    "live",
    "superseded",
)
OPEN_STATUSES: tuple[str, ...] = ("queued", "submitted", "fallback")

CK_STATUS = f"status IN ({quoted(STATUSES)})"
OPEN_WHERE = f"status IN ({quoted(OPEN_STATUSES)})"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS cv_parse_batch_items (
    id SERIAL PRIMARY KEY,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    document_id INTEGER NOT NULL REFERENCES candidate_documents(id) ON DELETE CASCADE,
    content_sha256 VARCHAR(64) NULL,
    trigger VARCHAR(40) NOT NULL DEFAULT 'cv_upload',
    actor_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    replaced_primary JSONB NULL,
    raw_text TEXT NULL,
    status VARCHAR(12) NOT NULL DEFAULT 'queued',
    batch_id VARCHAR(80) NULL,
    model VARCHAR(80) NULL,
    error VARCHAR(255) NULL,
    live_attempts SMALLINT NOT NULL DEFAULT 0,
    queued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    submitted_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    CONSTRAINT ck_cv_parse_batch_items_status CHECK ({CK_STATUS})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_cv_parse_batch_items_open "
    f"ON cv_parse_batch_items (status, queued_at) WHERE {OPEN_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_cv_parse_batch_items_candidate "
    "ON cv_parse_batch_items (candidate_id)",
)

CONSTRAINT_DDL: tuple[str, ...] = ()

DATA_DDL: tuple[str, ...] = ()

TABLES: tuple[str, ...] = ("cv_parse_batch_items",)

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)

DOWNGRADE_DDL: tuple[str, ...] = ("DROP TABLE IF EXISTS cv_parse_batch_items",)
