"""Zadania asystenta prawnego — stan „załatwione / odrzucone” (0790, część F).

Jedno źródło instrukcji dla ``alembic/versions/0790_legal_assistant_tasks.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Każda
instrukcja idempotentna.

* ``legal_assistant_tasks`` — tylko zadania, które ktoś zamknął. Same zadania
  liczą dostawcy z danych NEXUSA (``services/legal/tasks.py``) przy każdym
  odczycie; wiersz z tym samym ``task_key`` chowa zadanie z paska.
  ``done`` = pismo zatwierdzone („Zatwierdzam”), ``dismissed`` = „Pomiń”.
  Klucz niesie datę zdarzenia (np. wypowiedzenia), więc nowe wypowiedzenie
  na tym samym kontrakcie to nowe zadanie.
"""

from __future__ import annotations

STATUS_DONE = "done"
STATUS_DISMISSED = "dismissed"
STATUSES: tuple[str, ...] = (STATUS_DONE, STATUS_DISMISSED)

TABLE_DDL: tuple[str, ...] = (
    "CREATE TABLE IF NOT EXISTS legal_assistant_tasks ("
    "id SERIAL PRIMARY KEY, "
    "task_key VARCHAR(160) NOT NULL, "
    "kind VARCHAR(32) NOT NULL, "
    "status VARCHAR(16) NOT NULL, "
    "contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE CASCADE, "
    "client_id INTEGER NULL REFERENCES clients(id) ON DELETE CASCADE, "
    "letter_kind VARCHAR(32) NULL, "
    "resolved_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "resolved_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "CONSTRAINT uq_legal_assistant_tasks_key UNIQUE (task_key), "
    "CONSTRAINT ck_legal_assistant_tasks_status "
    "CHECK (status IN ('done', 'dismissed')))",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_legal_assistant_tasks_contract "
    "ON legal_assistant_tasks (contract_id)",
)

CONSTRAINT_DDL: tuple[str, ...] = ()
DATA_DDL: tuple[str, ...] = ()

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)

DOWNGRADE_DDL: tuple[str, ...] = ("DROP TABLE IF EXISTS legal_assistant_tasks",)
