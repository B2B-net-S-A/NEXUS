"""DDL raportów kompetencji (0785) — JEDNO źródło dla migracji i siatki
w ``entrypoint.sh`` (produkcyjny alembic bywa osierocony).

``competence_reports``: jeden wiersz na zgłoszenie ze strony z ``report=1``
(decyzje Artura 25.11.2026). Raport czeka na odczyt CV (``waiting_cv``),
potem pętla składa snapshot (``ready``) i wysyła go najpóźniej o
``send_due_at`` (zgłoszenie + 23 h). „Wstrzymaj” rekrutera to ``held_at``,
nie osobny stan. Baza trzyma tylko skrót tokenu strony raportu.

``competence_report_owners``: lista rekruterów ustawiana przez admina;
opiekun raportu idzie po kolei (najdawniej przypisany, remis po ``position``).
Kształt ``conditions`` i ``snapshot``: ``services/competence_report_schema.py``.
"""

from __future__ import annotations

STATUSES: tuple[str, ...] = (
    "waiting_cv",
    "ready",
    "sent",
    "skipped",
    "opted_out",
    "failed",
)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


TABLE_DDL: list[str] = [
    f"""CREATE TABLE IF NOT EXISTS competence_reports (
           id SERIAL PRIMARY KEY,
           candidate_id INTEGER NOT NULL REFERENCES candidates (id) ON DELETE CASCADE,
           submission_id INTEGER NULL REFERENCES application_submissions (id) ON DELETE SET NULL,
           email VARCHAR(254) NOT NULL,
           status VARCHAR(16) NOT NULL DEFAULT 'waiting_cv'
               CONSTRAINT ck_competence_reports_status CHECK (status IN ({_in(STATUSES)})),
           conditions JSONB NOT NULL,
           snapshot JSONB NULL,
           owner_user_id INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           ready_at TIMESTAMPTZ NULL,
           send_due_at TIMESTAMPTZ NOT NULL,
           sent_at TIMESTAMPTZ NULL,
           sent_by_user_id INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           held_at TIMESTAMPTZ NULL,
           held_by_user_id INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           token_hash VARCHAR(64) NULL,
           token_expires_at TIMESTAMPTZ NULL,
           opted_out_at TIMESTAMPTZ NULL,
           attempts INTEGER NOT NULL DEFAULT 0,
           last_error TEXT NULL
       )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_competence_reports_token
           ON competence_reports (token_hash) WHERE token_hash IS NOT NULL""",
    """CREATE INDEX IF NOT EXISTS ix_competence_reports_queue
           ON competence_reports (status, send_due_at)""",
    """CREATE INDEX IF NOT EXISTS ix_competence_reports_candidate
           ON competence_reports (candidate_id)""",
    """CREATE TABLE IF NOT EXISTS competence_report_owners (
           user_id INTEGER PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
           active BOOLEAN NOT NULL DEFAULT true,
           position INTEGER NOT NULL DEFAULT 0,
           last_assigned_at TIMESTAMPTZ NULL
       )""",
]

DOWNGRADE_DDL: list[str] = [
    "DROP TABLE IF EXISTS competence_report_owners",
    "DROP TABLE IF EXISTS competence_reports",
]
