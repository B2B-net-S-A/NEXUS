"""Make explicit MD orders use per-consultant budgets.

Revision ID: 0251_explicit_md_per_consultant
Revises: 0250_live_order_contract_repair

Revision 0246 accidentally encoded every ``order_type='md'`` as a shared group
budget.  Generic MD budgets belong to each consultant line; only the deliberate
Cyfrowy Polsat/Lotte variants keep one MD pool on the group. Cost orders keep
their one monetary pool unchanged.

This migration changes only the write constraint.  It deliberately performs
no UPDATE. Shared explicit-MD rows remain legal only for the two established
client-specific variants (Lotte Wedel 155 and Cyfrowy Polsat 38339); every
other explicit MD group is per consultant. The upgraded constraint starts as
``NOT VALID`` so an unexpected historical row cannot block deployment, while
PostgreSQL still enforces it for every new INSERT/UPDATE.
"""

from alembic import op


revision = "0251_explicit_md_per_consultant"
down_revision = "0250_live_order_contract_repair"
branch_labels = None
depends_on = None


_CLIENT_SCOPED_CHECK = (
    "order_type IS NULL OR "
    "(order_type = 'cost' AND is_cost_based = TRUE "
    "AND is_md_budget_based = FALSE) OR "
    "(order_type = 'md' AND is_cost_based = FALSE "
    "AND ((client_id IN (155, 38339) AND is_md_budget_based = TRUE) "
    "OR (client_id NOT IN (155, 38339) AND is_md_budget_based = FALSE)))"
)

_ROLLBACK_CHECK = (
    "order_type IS NULL OR "
    "(order_type = 'cost' AND is_cost_based = TRUE "
    "AND is_md_budget_based = FALSE) OR "
    "(order_type = 'md' AND is_cost_based = FALSE)"
)


def upgrade() -> None:
    op.drop_constraint(
        "ck_client_order_groups_explicit_type_coherence",
        "client_order_groups",
        type_="check",
    )
    op.create_check_constraint(
        "ck_client_order_groups_explicit_type_coherence",
        "client_order_groups",
        _CLIENT_SCOPED_CHECK,
        postgresql_not_valid=True,
    )


def downgrade() -> None:
    # A data-safe rollback cannot restore the old shared-pool-only predicate:
    # explicit per-line MD groups may already have been created under 0251.
    # ``NOT VALID`` would not help because PostgreSQL still checks every later
    # UPDATE of those rows.  Keep a rollback-compatible constraint admitting
    # both the old shared shape and the new per-line shape; the rolled-back
    # application continues to write its old shared shape normally.
    op.drop_constraint(
        "ck_client_order_groups_explicit_type_coherence",
        "client_order_groups",
        type_="check",
    )
    op.create_check_constraint(
        "ck_client_order_groups_explicit_type_coherence",
        "client_order_groups",
        _ROLLBACK_CHECK,
        postgresql_not_valid=True,
    )
