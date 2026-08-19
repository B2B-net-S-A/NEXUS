"""ProposalSnapshot.hidden — liczniki dealbreakerów w snapshotcie rankingu.

Revision ID: 0237_proposal_snapshot_hidden
Revises: 0236_champion_parse_ai_feature

Decyzja produktowa 19.08: znany budżet oferty działa Z AUTOMATU jako twardy
sufit (bez marginesu) — także w snapshotcie propozycji (fast-path Fazy 13),
żeby domyślny widok nie pokazywał ludzi powyżej stawki. Ukrywanie nigdy nie
jest ciche (reguła „awaria ≠ pustka"), więc snapshot musi nieść liczniki
ukrytych per powód — stąd ta kolumna: ``{"over_budget": N, "remote_only": M}``.
NULL = snapshot sprzed tej zmiany (nieprzefiltrowany, bez chipa).

Zdublowane w safety-net ``entrypoint.sh`` (prod alembic bywa orphaned).
"""

from alembic import op

revision = "0237_proposal_snapshot_hidden"
down_revision = "0236_champion_parse_ai_feature"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE proposal_snapshots ADD COLUMN IF NOT EXISTS hidden JSONB NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE proposal_snapshots DROP COLUMN IF EXISTS hidden")
