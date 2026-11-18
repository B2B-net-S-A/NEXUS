"""Bot Cpro (decyzje Artura 17.11.2026): SQL migracji ``0732_cpro_bot_runs``
i lustra entrypointu.

Jedno źródło instrukcji dla ``alembic/versions/0732_cpro_bot_runs.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``).

``cpro_bot_runs`` — jeden bieg rutyny „NEXUS Cpro” w Grok Bocie: SHA-256
jednorazowego tokenu (2 godziny, raz), lista kart (``stage_ids``), zlecenie
wysłane botowi (``request``: dane osób do formularza Cpro — świadomy wyjątek
od reguły „bez osób do bota”, decyzja Artura 17.11.2026) i wynik każdej karty
z raportu (``report``). Stan pozycji w kolejce Cpro liczy się z tych wierszy,
bez osobnej tabeli pozycji.
"""

from __future__ import annotations

from app.services.consultant_portal_schema import quoted

RUN_STATUSES: tuple[str, ...] = ("started", "received", "failed", "expired")
#: Wynik jednej karty w raporcie bota.
ITEM_OUTCOMES: tuple[str, ...] = ("submitted", "draft", "failed", "skipped")

CK_RUN_STATUS = f"status IN ({quoted(RUN_STATUSES)})"
CK_STAGE_IDS = "jsonb_typeof(stage_ids) = 'array'"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS cpro_bot_runs (
    id SERIAL PRIMARY KEY,
    status VARCHAR(10) NOT NULL DEFAULT 'started',
    submit BOOLEAN NOT NULL DEFAULT TRUE,
    token_hash VARCHAR(64) NULL,
    token_expires_at TIMESTAMPTZ NULL,
    stage_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    request JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    report JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    error VARCHAR(255) NULL,
    requested_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    received_at TIMESTAMPTZ NULL,
    CONSTRAINT ck_cpro_bot_runs_status CHECK ({CK_RUN_STATUS}),
    CONSTRAINT ck_cpro_bot_runs_stage_ids CHECK ({CK_STAGE_IDS})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_cpro_bot_runs_started ON cpro_bot_runs (started_at)",
)

CONSTRAINT_DDL: tuple[str, ...] = ()

DATA_DDL: tuple[str, ...] = ()

TABLES: tuple[str, ...] = ("cpro_bot_runs",)

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
