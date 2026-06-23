"""Candidate hard-delete: ON DELETE rules for FKs that referenced candidates.id.

Revision ID: 0141_candidate_delete_cascade
Revises: 0138_candidate_expected_hourly_rate, 0138_contracts_per_client_register
Create Date: 2026-06-22

NOTE on down_revision: the committed history forks into two unmerged 0138 heads
(``0138_candidate_expected_hourly_rate`` + ``0138_contracts_per_client_register``,
both off 0137). This migration merges them, so after it the chain has a single
head again. (``alembic upgrade heads`` already tolerated the fork.)

Hard-deleting a candidate (``DELETE /api/candidates/{id}``) failed with a
foreign-key violation whenever the candidate had rows in tables that referenced
``candidates.id`` WITHOUT an ``ON DELETE`` rule and WITHOUT an ORM
``cascade="all, delete-orphan"`` relationship on the ``Candidate`` model. Those
five tables were the only gaps — every other candidate FK already had
``ON DELETE CASCADE``/``SET NULL`` at the DB level or an ORM cascade.

This migration backfills the missing ``ON DELETE`` behaviour so a candidate can
be removed atomically:

  * ``contracts``                 → CASCADE   (contract belongs to the candidate)
  * ``screening_notes``           → CASCADE
  * ``talent_pool_memberships``   → CASCADE   (pool membership)
  * ``match_history``             → CASCADE   (cached match rows)
  * ``calendar_events``           → SET NULL  (event survives, just unlinked;
                                               column is nullable)

The existing constraint name is discovered by reflection (it is the Postgres
auto-generated ``{table}_{column}_fkey`` for most, but a couple were recreated
under different names by later migrations), so we never hard-code names.

Online migration only — relies on DB reflection (CI + Coolify both run against a
real Postgres; the project does not use offline ``--sql`` mode).
"""

import sqlalchemy as sa
from alembic import op

revision = "0141_candidate_delete_cascade"
# Merge the two committed 0138 heads (the 0139/0140 files present in some local
# worktrees are uncommitted WIP — do NOT depend on them).
down_revision = (
    "0138_candidate_expected_hourly_rate",
    "0138_contracts_per_client_register",
)
branch_labels = None
depends_on = None

# (table, column, ondelete-on-upgrade)
_TARGETS = (
    ("contracts", "candidate_id", "CASCADE"),
    ("screening_notes", "candidate_id", "CASCADE"),
    ("talent_pool_memberships", "candidate_id", "CASCADE"),
    ("match_history", "candidate_id", "CASCADE"),
    ("calendar_events", "candidate_id", "SET NULL"),
)


def _candidate_fk_names(insp, table: str, column: str) -> list[str]:
    """Names of FK constraints on ``table.column`` that reference ``candidates``."""
    names: list[str] = []
    for fk in insp.get_foreign_keys(table):
        referred = fk.get("referred_table")
        cols = fk.get("constrained_columns") or []
        if referred == "candidates" and column in cols and fk.get("name"):
            names.append(fk["name"])
    return names


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table, column, ondelete in _TARGETS:
        if not insp.has_table(table):
            continue
        for name in _candidate_fk_names(insp, table, column):
            op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(
            f"{table}_{column}_candidates_fkey",
            table,
            "candidates",
            [column],
            ["id"],
            ondelete=ondelete,
        )


def downgrade() -> None:
    # Restore plain FKs without any ON DELETE rule (original schema).
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table, column, _ in _TARGETS:
        if not insp.has_table(table):
            continue
        for name in _candidate_fk_names(insp, table, column):
            op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(
            f"{table}_{column}_fkey",
            table,
            "candidates",
            [column],
            ["id"],
        )
