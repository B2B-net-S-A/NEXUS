"""DDL powodów odrzucenia osób od systemu — JEDNO źródło dla migracji 0516
i siatki w ``entrypoint.sh`` (produkcyjny alembic bywa osierocony).

``autofill_feedback``: jeden wiersz na odrzucenie osoby dodanej przez silnik
„Nowi na 20” (decyzja Artura 23.10.2026). Powód ze stałej listy, skąd
rekruter to wie, kosz raportu liczony przy zapisie z migawki tego, co system
wiedział, i ta migawka (``snapshot`` = ``entry_meta`` procesu, same nazwy
wymagań i liczby). Z tych wierszy powstaje ekran „Jakość podpowiedzi” i raport
poniedziałkowy. ``whole_client`` (0606): powód dotyczy osoby u całego klienta
— silnik nie podsuwa jej żadnej rekrutacji tego klienta.
"""

from __future__ import annotations

REASONS: tuple[str, ...] = (
    # Nie pasuje do wymagań.
    "missing_skill",
    "too_junior",
    "other_level_or_role",
    "location_mode",
    "language",
    # Pieniądze i dane.
    "too_expensive",
    "outdated_cv",
    "profile_mismatch",
    # Sprawa osoby.
    "not_looking",
    "no_answer",
    "in_other_process",
    # Klient, nie osoba (0606, 27.10.2026): 13 z 20 „Inne” to „pracuje
    # w Nordei przez inną firmę” albo „nie chce do Nordei”.
    "client_employed",
    "client_refused",
    "other",
)
LEARNED_FROM: tuple[str, ...] = ("profile", "call")
BUCKETS: tuple[str, ...] = ("search", "data", "person", "other")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


# 0606 (27.10.2026): powody „klient” i odrzucenie na cały klient. Więz powodów
# ma JEDNĄ definicję — tu; entrypoint wykonuje cały ``TABLE_DDL`` przy każdym
# starcie, więc DROP + ADD zawsze kończy się pełną listą.
WHOLE_CLIENT_DDL: list[str] = [
    "ALTER TABLE autofill_feedback "
    "ADD COLUMN IF NOT EXISTS whole_client BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE autofill_feedback DROP CONSTRAINT IF EXISTS ck_autofill_feedback_reason",
    f"ALTER TABLE autofill_feedback ADD CONSTRAINT ck_autofill_feedback_reason "
    f"CHECK (reason IN ({_in(REASONS)}))",
]

TABLE_DDL: list[str] = [
    f"""CREATE TABLE IF NOT EXISTS autofill_feedback (
           id BIGSERIAL PRIMARY KEY,
           job_id INTEGER NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
           candidate_id INTEGER NOT NULL REFERENCES candidates (id) ON DELETE CASCADE,
           stage_id INTEGER NULL REFERENCES candidate_stages (id) ON DELETE SET NULL,
           reason VARCHAR(32) NOT NULL,
           learned_from VARCHAR(16) NOT NULL,
           bucket VARCHAR(16) NOT NULL,
           rate_hourly NUMERIC(10, 2) NULL,
           note VARCHAR(500) NULL,
           snapshot JSONB NULL,
           created_by INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           CONSTRAINT ck_autofill_feedback_learned_from
               CHECK (learned_from IN ({_in(LEARNED_FROM)})),
           CONSTRAINT ck_autofill_feedback_bucket CHECK (bucket IN ({_in(BUCKETS)}))
       )""",
    "CREATE INDEX IF NOT EXISTS ix_autofill_feedback_created_at "
    "ON autofill_feedback (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_autofill_feedback_job_id "
    "ON autofill_feedback (job_id)",
    "CREATE INDEX IF NOT EXISTS ix_autofill_feedback_candidate_id "
    "ON autofill_feedback (candidate_id)",
    *WHOLE_CLIENT_DDL,
]

DOWNGRADE_DDL: list[str] = ["DROP TABLE IF EXISTS autofill_feedback"]
