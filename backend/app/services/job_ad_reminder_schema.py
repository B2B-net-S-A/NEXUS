"""Przypomnienia o brakujących ogłoszeniach — SQL migracji 0525 i lustra.

JEDNO źródło instrukcji dla ``alembic/versions/0525_job_ad_reminders.py``
i ``entrypoint.sh`` (alembic na prodzie bywa osierocony); test
``test_job_ad_reminders_migration_mirror.py`` sprawdza, że każda stoi
w entrypoincie dosłownie.

``job_ad_channel_skips`` = „Nie publikujemy tej rekrutacji na …”: jeden
wiersz na rekrutację i kanał (``kariera``, ``pracuj``, ``jjit``), z powodem
i autorem. Kanał z wierszem nie jest brakiem — przypomnienie o nim nie
przychodzi. Cofnięcie usuwa wiersz; ślad zostaje w Historii zdarzeń.
"""

from __future__ import annotations

CHANNEL_CAREER = "kariera"
CHANNEL_PRACUJ = "pracuj"
CHANNEL_JJIT = "jjit"
CHANNELS = (CHANNEL_CAREER, CHANNEL_PRACUJ, CHANNEL_JJIT)

REASON_MAX = 300

TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS job_ad_channel_skips ("
    "job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE, "
    "channel VARCHAR(16) NOT NULL, "
    "reason VARCHAR(300) NOT NULL, "
    "created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "CONSTRAINT pk_job_ad_channel_skips PRIMARY KEY (job_id, channel), "
    "CONSTRAINT ck_job_ad_channel_skips_channel "
    "CHECK (channel IN ('kariera', 'pracuj', 'jjit')))"
)

# Typy dzwonka: przypomnienie o rekrutacji, zbiorczy o zaległych, prośba DL-a.
NOTIFICATION_TYPES = ("job_ad_missing", "job_ad_backlog", "job_ad_nudge")
ENUM_DDL = tuple(
    f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'"
    for value in NOTIFICATION_TYPES
)

ALL_DDL = (TABLE_DDL,)

DOWNGRADE_DDL = ("DROP TABLE IF EXISTS job_ad_channel_skips",)
