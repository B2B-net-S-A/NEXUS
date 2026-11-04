"""DDL decyzji „Wymagania do poprawy” — JEDNO źródło dla migracji 0438
i ``entrypoint.sh`` (produkcyjny alembic bywa osierocony).

Propozycji nie zapisujemy — liczy je na żywo ``requirement_cleanup.build_proposal``.
Tabela trzyma tylko ostatnią decyzję Delivery Leada dla rekrutacji i odcisk
profilu, którego dotyczyła: odrzucona propozycja nie wraca, dopóki profil się
nie zmieni.
"""

from __future__ import annotations

TABLE_DDL: list[str] = [
    """CREATE TABLE IF NOT EXISTS requirement_cleanup_decisions (
           job_id INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
           profile_hash VARCHAR(64) NOT NULL,
           status VARCHAR(12) NOT NULL,
           decided_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
           decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           CONSTRAINT ck_requirement_cleanup_decisions_status
               CHECK (status IN ('applied','dismissed'))
       )""",
]
