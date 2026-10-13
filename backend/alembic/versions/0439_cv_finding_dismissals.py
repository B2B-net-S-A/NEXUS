"""Pominięte uwagi QC CV i edytora — „To nieprawda” (13.10.2026, D5).

Revision ID: 0439_cv_finding_dismissals
Revises: 0438_requirement_cleanup_decisions

Zespół nie miał jak powiedzieć „ta uwaga QC jest nieprawdziwa”: ta sama
fałszywa uwaga wracała przy każdym otwarciu okna i blokowała ruch karty.
Pominięcie dotyczy pary (kandydat, rekrutacja) — nowe CV tej samej osoby
w tej rekrutacji nie wskrzesza pominiętej uwagi. Klucz uwagi
(``finding_key``) liczy serwer z pól pozycji, nigdy z indeksu roli.

* ``source``: ``qc`` (okno QC), ``generator`` (uwagi generatora w edytorze),
  ``review`` (kontrola AI w edytorze).
* ``blocking``: pominięcie uwagi blokującej działa jak obejście QC — Delivery
  Lead dostaje dzwonek, zwrot karty przywraca pominięcia osób bez prawa
  wysyłki (``restored_reason = 'card_returned'``).
* Aktywne pominięcie pary i klucza jest jedno (indeks częściowy).

Lustro w ``entrypoint.sh`` — pilnuje ``test_cv_finding_dismissals.py``.
"""

from alembic import op

revision = "0439_cv_finding_dismissals"
down_revision = "0438_requirement_cleanup_decisions"
branch_labels = None
depends_on = None

CREATE_TABLE = """CREATE TABLE IF NOT EXISTS cv_finding_dismissals (
    id BIGSERIAL PRIMARY KEY,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    candidate_stage_id INTEGER NULL
        REFERENCES candidate_stages(id) ON DELETE SET NULL,
    source VARCHAR(16) NOT NULL,
    check_key VARCHAR(40) NOT NULL,
    finding_key VARCHAR(400) NOT NULL,
    label TEXT NOT NULL,
    reason VARCHAR(32) NOT NULL,
    note TEXT NULL,
    evidence_quote TEXT NULL,
    blocking BOOLEAN NOT NULL DEFAULT false,
    dismissed_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    restored_at TIMESTAMPTZ NULL,
    restored_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    restored_reason VARCHAR(16) NULL
)"""
CREATE_ACTIVE_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_cv_finding_dismissals_active "
    "ON cv_finding_dismissals (candidate_id, job_id, source, finding_key) "
    "WHERE restored_at IS NULL"
)
CREATE_CREATED_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_cv_finding_dismissals_created "
    "ON cv_finding_dismissals (created_at)"
)


def upgrade() -> None:
    op.execute(CREATE_TABLE)
    op.execute(CREATE_ACTIVE_INDEX)
    op.execute(CREATE_CREATED_INDEX)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cv_finding_dismissals")
