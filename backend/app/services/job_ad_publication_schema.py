"""Gdzie wisi ogłoszenie rekrutacji — SQL migracji 0432 i lustra.

JEDNO źródło instrukcji dla ``alembic/versions/0432_job_ad_publications.py``
i ``entrypoint.sh`` (alembic na prodzie bywa osierocony); test
``test_job_ad_publications_migration_mirror.py`` sprawdza, że każda stoi
w entrypoincie dosłownie.

Rekruter wkleja ogłoszenie na portalu RĘCZNIE i oznacza to w NEXUSIE: jeden
wiersz na rekrutację i portal. ``content_hash`` to odcisk zapisanej treści
z chwili oznaczenia — inny niż bieżący znaczy „ogłoszenie do aktualizacji”.
``removed_at`` = zdjęte z portalu (wiersz zostaje jako ślad).

To NIE jest ``job_postings``: tamta tabela to kolejka workera publikacji
przez API, więc ręczny wiersz dostałby zlecenie wysyłki, a przy Pracuj.pl
trwale blokował usunięcie rekrutacji.
"""

from __future__ import annotations

PORTAL_PRACUJ = "pracuj"
PORTAL_JJIT = "jjit"
PORTALS = (PORTAL_PRACUJ, PORTAL_JJIT)

URL_MAX = 500

TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS job_ad_publications ("
    "job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE, "
    "portal VARCHAR(16) NOT NULL, "
    "url VARCHAR(500) NULL, "
    "content_hash VARCHAR(64) NOT NULL, "
    "published_at TIMESTAMPTZ NOT NULL, "
    "published_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "removed_at TIMESTAMPTZ NULL, "
    "removed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "CONSTRAINT pk_job_ad_publications PRIMARY KEY (job_id, portal), "
    "CONSTRAINT ck_job_ad_publications_portal CHECK (portal IN ('pracuj', 'jjit')))"
)

ALL_DDL = (TABLE_DDL,)

DOWNGRADE_DDL = ("DROP TABLE IF EXISTS job_ad_publications",)
