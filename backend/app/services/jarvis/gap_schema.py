"""„Czego Jarvis nie umie” — SQL migracji 0527 i lustra w entrypoincie.

JEDNO źródło instrukcji dla ``alembic/versions/0527_jarvis_gaps.py``
i ``entrypoint.sh`` (alembic na prodzie bywa osierocony); test
``test_jarvis_gaps_migration_mirror.py`` sprawdza, że każda stoi
w entrypoincie dosłownie.

Wiersz zapisuje serwer, gdy Jarvis pokazuje kartę braku (narzędzie
``report_gap``); kliknięcie „Zgłoś, że tego potrzebuję” ustawia
``reported_at``. Wiersz żyje tyle, co rozmowa (kaskada po
``conversation_id``), więc retencja 30 dni i usunięcie kandydata (RODO)
zabierają go razem z rozmową.
"""

from __future__ import annotations

# Lustro `GapKind` w `frontend/src/lib/jarvis/types.ts`.
GAP_KINDS = ("no_access", "not_supported", "no_data")
NEED_MAX = 160
WHY_MAX = 240

TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS jarvis_gaps ("
    "id UUID PRIMARY KEY, "
    "conversation_id UUID NOT NULL REFERENCES jarvis_conversations(id) ON DELETE CASCADE, "
    "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
    "tool_use_id VARCHAR(100) NOT NULL, "
    "kind VARCHAR(20) NOT NULL, "
    "need VARCHAR(160) NOT NULL, "
    "why VARCHAR(240) NOT NULL, "
    "workaround VARCHAR(240) NOT NULL DEFAULT '', "
    "reported_at TIMESTAMPTZ NULL, "
    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "CONSTRAINT ck_jarvis_gaps_kind "
    "CHECK (kind IN ('no_access', 'not_supported', 'no_data')))"
)
INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS ix_jarvis_gaps_created_at ON jarvis_gaps (created_at)"
)

ALL_DDL = (TABLE_DDL, INDEX_DDL)

DOWNGRADE_DDL = ("DROP TABLE IF EXISTS jarvis_gaps",)
