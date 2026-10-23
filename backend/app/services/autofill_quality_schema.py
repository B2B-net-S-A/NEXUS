"""DDL raportów „Jakość podpowiedzi systemu” — JEDNO źródło dla migracji 0517
i siatki w ``entrypoint.sh`` (produkcyjny alembic bywa osierocony).

``autofill_quality_reports``: jeden raport na tydzień (``week_start`` =
poniedziałek tygodnia, którego dotyczy). ``summary`` = liczby policzone przez
kod, ``proposals`` = 3–5 propozycji poprawek (z modelu albo z reguł, gdy model
milczał) z decyzją „Robimy / Nie” (``decision``, ``decided_by``).
"""

from __future__ import annotations

TABLE_DDL: list[str] = [
    """CREATE TABLE IF NOT EXISTS autofill_quality_reports (
           id SERIAL PRIMARY KEY,
           week_start DATE NOT NULL,
           summary JSONB NOT NULL,
           proposals JSONB NOT NULL,
           from_model BOOLEAN NOT NULL DEFAULT FALSE,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           CONSTRAINT uq_autofill_quality_reports_week UNIQUE (week_start)
       )""",
]

DOWNGRADE_DDL: list[str] = ["DROP TABLE IF EXISTS autofill_quality_reports"]
