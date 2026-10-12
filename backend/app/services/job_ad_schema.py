"""Ogłoszenie rekrutacji do wklejenia na portale — SQL migracji 0430 i lustra.

JEDNO źródło instrukcji dla ``alembic/versions/0430_job_ads.py``
i ``entrypoint.sh`` (alembic na prodzie bywa osierocony); test
``test_job_ads_migration_mirror.py`` sprawdza, że każda stoi w entrypoincie
dosłownie.

Jedna treść na rekrutację (``job_id`` jest kluczem): rekruter generuje ją
z Profilu Championa, poprawia ręcznie i kopiuje do Pracuj.pl oraz
JustJoin.IT. ``content`` to pola ogłoszenia, ``tech`` — technologie
z poziomem, ``material_hash`` — odcisk danych rekrutacji z chwili
generowania (zmiana = „rekrutacja zmieniła się od przygotowania”).
"""

from __future__ import annotations

LANG_PL = "pl"
LANG_EN = "en"
LANGS = (LANG_PL, LANG_EN)

SOURCE_AI = "ai"
SOURCE_TEMPLATE = "template"
SOURCES = (SOURCE_AI, SOURCE_TEMPLATE)

TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS job_ads ("
    "job_id INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE, "
    "lang VARCHAR(2) NOT NULL DEFAULT 'pl', "
    "content JSONB NOT NULL, "
    "tech JSONB NOT NULL, "
    "source VARCHAR(16) NOT NULL DEFAULT 'ai', "
    "material_hash VARCHAR(64) NULL, "
    "generated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "generated_at TIMESTAMPTZ NULL, "
    "updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "CONSTRAINT ck_job_ads_lang CHECK (lang IN ('pl', 'en')), "
    "CONSTRAINT ck_job_ads_source CHECK (source IN ('ai', 'template')))"
)

ALL_DDL = (TABLE_DDL,)

DOWNGRADE_DDL = ("DROP TABLE IF EXISTS job_ads",)
