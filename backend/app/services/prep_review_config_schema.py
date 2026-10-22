"""DDL ustawień oceny prepów — JEDNO źródło dla migracji 0505 i siatki
w ``entrypoint.sh`` (produkcyjny alembic bywa osierocony).

``prep_review_configs``: wiersz = jedna opublikowana wersja ustawień
(Ustawienia → Ocena prepów, Head of Recruitment i admin). Obowiązuje wiersz
o najwyższym ``id``; brak wierszy = ustawienia startowe z kodu.
``prep_reviews.config_version`` mówi, według której wersji powstała ocena
(``NULL`` = sprzed 0505 albo ustawienia startowe).
"""

from __future__ import annotations

TABLE_DDL: list[str] = [
    """CREATE TABLE IF NOT EXISTS prep_review_configs (
           id SERIAL PRIMARY KEY,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           created_by INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           config JSONB NOT NULL,
           reason TEXT NULL
       )""",
    """ALTER TABLE prep_reviews
       ADD COLUMN IF NOT EXISTS config_version INTEGER NULL""",
]

DOWNGRADE_DDL: list[str] = [
    "ALTER TABLE prep_reviews DROP COLUMN IF EXISTS config_version",
    "DROP TABLE IF EXISTS prep_review_configs",
]
