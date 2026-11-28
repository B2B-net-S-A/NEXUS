"""DDL zużytych wyzwań ALTCHA (0805) — JEDNO źródło dla migracji i siatki
w ``entrypoint.sh`` (produkcyjny alembic bywa osierocony).

``altcha_spent_challenges``: wyzwanie przyjęte przy zgłoszeniu (skrót SHA-256
z soli i liczby, nie dane osoby) do końca jego ważności. Kilka procesów web
nie dzieli pamięci, więc powtórka tego samego rozwiązania jest blokowana
w bazie: ``INSERT … ON CONFLICT DO NOTHING`` bez wiersza = już użyte.
Wygasłe wiersze kasuje każde kolejne przyjęcie (``services/altcha.py``).
"""

from __future__ import annotations

from sqlalchemy import DateTime, String, column, table

TABLE_NAME = "altcha_spent_challenges"

# Lekkie `table()` dla sondy `/api/health/deep` i zapytań serwisu.
ALTCHA_SPENT_CHALLENGES = table(
    TABLE_NAME,
    column("challenge", String),
    column("expires_at", DateTime(timezone=True)),
)

TABLE_DDL: list[str] = [
    f"""CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
           challenge VARCHAR(64) PRIMARY KEY,
           expires_at TIMESTAMPTZ NOT NULL,
           spent_at TIMESTAMPTZ NOT NULL DEFAULT now()
       )""",
    f"""CREATE INDEX IF NOT EXISTS ix_{TABLE_NAME}_expires_at
           ON {TABLE_NAME} (expires_at)""",
]

DOWNGRADE_DDL: list[str] = [f"DROP TABLE IF EXISTS {TABLE_NAME}"]
