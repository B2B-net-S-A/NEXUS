"""Merge two parallel head chains (Traffit-features tip + DL Client Portal).

Revision ID: 0098_merge_heads
Revises: 0091_merge_traffit_features, 0097_jobs_contracts_contact_fk
Create Date: 2026-05-13 12:30:00.000000

Two chains accumulated since 0090 without ever being merged:

- ``0091_merge_traffit_features`` (Traffit-features tip) — already a
  merge node itself, but never got a follow-up. Stayed at 0091.
- ``0091_extend_document_signature_msa → 0092..0097`` — DL Client
  Portal chain (PR #133 + follow-ups #150/#151/#152/#153): MSA
  signature extension → notification types → orders restructure →
  contracts wipe → add_order_rate_client → contacts key relationship
  → jobs_contracts_contact_fk.

Effect on prod NEXUS: ``alembic_version`` has 2 rows
(both heads), every ``alembic upgrade head`` (singular) fails and
defensive ALTERs baked into later migrations never execute. Concrete
symptom: ``fx_rates.updated_at`` missing — see PR #154 safety-net.

This revision is empty — its sole purpose is to declare both ancestors
so ``alembic upgrade heads`` (plural) collapses back to a single tip
on a fresh DB. Existing prod instances need a one-time manual
``alembic stamp 0098_merge_heads`` from Coolify Terminal to collapse
the two ``alembic_version`` rows into one. See memory
``project_alembic_drift.md`` for the playbook.
"""

# Empty merge node — no schema change.

revision = "0098_merge_heads"
down_revision = (
    "0091_merge_traffit_features",
    "0097_jobs_contracts_contact_fk",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
