"""Kontrakt: stawka z umowy ramowej + line manager.

Revision ID: 0142_contracts_framework_rate_line_manager
Revises: 0141_candidate_delete_cascade
Create Date: 2026-06-23

Dodaje do tabeli ``contracts`` dwie kolumny widoczne w formularzu "Nowy
kontrakt":

  * ``framework_rate`` (INTEGER) — "Stawka z umowy ramowej". Referencyjna
    stawka uzgodniona w umowie ramowej (MSA) z klientem. Trzymana jako
    INTEGER (jak ``rate_candidate`` / ``rate_client``) w walucie kontraktu;
    nie wchodzi do liczenia marży — to wartość odniesienia.
  * ``line_manager`` (VARCHAR 255) — osoba (line manager) po stronie klienta,
    pod którą raportuje kontraktor. Analogiczne do ``client_pm_name``, ale
    osobna rola.

Idempotent: ``ADD COLUMN IF NOT EXISTS`` — współgra z entrypoint safety-net
oraz z DEBUG ``Base.metadata.create_all``.
"""

from alembic import op

revision = "0142_contracts_framework_rate_line_manager"
down_revision = "0141_candidate_delete_cascade"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column_sql in (
        "ADD COLUMN IF NOT EXISTS framework_rate INTEGER",
        "ADD COLUMN IF NOT EXISTS line_manager VARCHAR(255)",
    ):
        op.execute(f"ALTER TABLE contracts {column_sql}")


def downgrade() -> None:
    for column in ("line_manager", "framework_rate"):
        op.execute(f"ALTER TABLE contracts DROP COLUMN IF EXISTS {column}")
