"""Atomic dedup ledger for contract expiry alerts (contract_alert_dedup).

``contract_alerts_loop`` deduped notifications with a non-atomic
SELECT-then-INSERT (no unique constraint), so overlapping / concurrent loop
passes (restart, multi-worker) could insert DUPLICATE alert notifications. This
table gives an atomic claim: ``INSERT ... ON CONFLICT (dedup_key) DO NOTHING`` —
only one pass wins the key, the rest skip. Append-only, no FK (``dedup_key`` is
an opaque string keyed per category / threshold / entity).

New empty table — no existing data to dedupe. Mirrored idempotently in
backend/entrypoint.sh (prod alembic is orphaned; every schema change must be
reflected there too).

Revision ID: 0186_contract_alert_dedup
Revises: 0185_widen_scoring_algorithm_version
"""

from alembic import op

revision = "0188_contract_alert_dedup"
down_revision = "0187_notes_fireflies_source_ref_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS contract_alert_dedup (
            id SERIAL PRIMARY KEY,
            dedup_key VARCHAR(128) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_contract_alert_dedup_key UNIQUE (dedup_key)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS contract_alert_dedup")
