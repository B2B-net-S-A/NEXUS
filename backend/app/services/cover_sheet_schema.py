"""Karta przed CV (Credit Agricole, 29.10.2026) — SQL migracji 0626 i lustra w ``entrypoint.sh``.

Wzór karty to plik Word klienta z telefonami opiekunów po stronie dostawcy,
więc nie leży w repo, tylko w bazie: jeden wiersz na klienta, osobna tabela
(``clients`` czyta się wszędzie — kolumna bytea ciągnęłaby plik do każdej
listy). Wiersz istnieje = karta jest włączona dla klienta; usunięcie wzoru
w edytorze reguły CV ją wyłącza.

Poprawki Delivery Leada leżą w ``candidate_client_forms`` z ``kind = 'cover'``
(bez ``job_file_id``) — ta sama unikalność ``(candidate_id, job_id, kind)``
co formularz i tabela punktowa; ``kind`` to VARCHAR(8) bez CHECK.

Test ``test_cover_sheet_migration_mirror.py`` sprawdza, że każda instrukcja
stoi w entrypoincie dosłownie, po tabeli ``candidate_client_forms``.
"""

from __future__ import annotations

KIND_COVER = "cover"

TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS client_cover_sheet_templates ("
    "client_id INTEGER PRIMARY KEY REFERENCES clients(id) ON DELETE CASCADE, "
    "filename VARCHAR(255) NOT NULL, "
    "content BYTEA NOT NULL, "
    "sha256 VARCHAR(64) NOT NULL, "
    "fields JSONB NOT NULL DEFAULT '[]'::jsonb, "
    "uploaded_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now())"
)

ALL_DDL = (TABLE_DDL,)

DOWNGRADE_DDL = (
    "DELETE FROM candidate_client_forms WHERE kind = 'cover'",
    "DROP TABLE IF EXISTS client_cover_sheet_templates",
)
