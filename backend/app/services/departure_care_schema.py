"""DDL opieki po odejściu — JEDNO źródło dla migracji 0620 i siatki
w ``entrypoint.sh`` (produkcyjny alembic bywa osierocony).

``pair_departure_care``: para (kandydat, rekrutacja), którą prowadziła osoba
z wyłączonym kontem, i Delivery Lead, który ją domyka (decyzje Artura
28.10.2026, ``services/departure_care.py``). Wiersz nie wygasa sam: opieka
jest otwarta, dopóki para żyje, rekrutacja jest otwarta, konto dalej jest
wyłączone, a „Prowadzi” wskazuje osobę, która odeszła.

Kolumny ``created_at`` / ``updated_at`` są dla scalania kandydatów:
konflikt klucza rozstrzyga nowszy wiersz (``candidate_merge``).
"""

from __future__ import annotations

NOTIFICATION_TYPE = "departed_pairs_care"

TABLE_DDL: list[str] = [
    """CREATE TABLE IF NOT EXISTS pair_departure_care (
           candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
           job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
           departed_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
           caretaker_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
           via TEXT NOT NULL,
           reminded_at TIMESTAMPTZ NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           PRIMARY KEY (candidate_id, job_id)
       )""",
    """CREATE INDEX IF NOT EXISTS ix_pair_departure_care_caretaker
           ON pair_departure_care (caretaker_user_id)""",
    """CREATE INDEX IF NOT EXISTS ix_pair_departure_care_departed
           ON pair_departure_care (departed_user_id)""",
    """CREATE INDEX IF NOT EXISTS ix_pair_departure_care_job
           ON pair_departure_care (job_id)""",
]

ENUM_DDL = "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'departed_pairs_care'"

DOWNGRADE_DDL: list[str] = [
    "DROP TABLE IF EXISTS pair_departure_care",
]
