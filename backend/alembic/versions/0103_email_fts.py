"""Full-text search on emails (tsvector + GIN index).

Revision ID: 0103_email_fts
Revises: 0102_m365_connection_hardening
Create Date: 2026-05-14 12:00:00.000000

Phase 4.4 of the M365 repair plan (.claude/plans/elegant-percolating-thimble.md).

The UI now lists synced emails for a candidate — recruiters scroll through
dozens or hundreds per active mailbox. Searching by sender / subject / body is
the highest-leverage UX upgrade in the Phase 4 set.

Schema additions:

1. ``emails.search_vector`` — generated ``tsvector`` STORED column built from
   ``subject`` (weight A — query terms in the subject rank highest),
   ``from_name`` + ``from_address`` (weight B — "find every mail from Anna" is
   the second most common query shape), and ``body_text`` (weight C — the
   long-tail fallback). ``simple`` postgres config (no stemming): mailboxes
   contain mixed PL / EN / DE which stemming garbles in any single language.

2. ``ix_emails_search_vector`` — GIN index built CONCURRENTLY. Production
   ``emails`` has tens of thousands of rows for active recruiters; a
   blocking CREATE INDEX would freeze m365 sync writes during deploy.

Why generated (not trigger): stays consistent on UPDATE without app
intervention. Trigger would require maintaining the function lifecycle and
makes alembic-time test ordering more fragile.

Idempotent: ``IF NOT EXISTS`` guards on both ALTER and CREATE INDEX so a
half-applied state can be safely re-run.
"""

from alembic import op


revision = "0103_email_fts"
down_revision = "0102_m365_connection_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE emails
        ADD COLUMN IF NOT EXISTS search_vector tsvector
        GENERATED ALWAYS AS (
            setweight(
                to_tsvector('simple', coalesce(subject, '')),
                'A'
            ) ||
            setweight(
                to_tsvector(
                    'simple',
                    coalesce(from_name, '') || ' ' || coalesce(from_address, '')
                ),
                'B'
            ) ||
            setweight(
                to_tsvector('simple', coalesce(body_text, '')),
                'C'
            )
        ) STORED;
        """
    )

    # CONCURRENTLY requires running outside a transaction. Alembic wraps
    # upgrades in a transaction by default; end the implicit transaction
    # before issuing the CONCURRENTLY DDL.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_emails_search_vector ON emails USING GIN(search_vector);"
        )


def downgrade() -> None:
    # Forward-only. The column is a STORED generated column, which is cheap
    # to drop, but keeping the migration directional matches the rest of the
    # M365 series (0101, 0102) and prevents accidental data-shape rollbacks
    # during a hot-fix window.
    raise NotImplementedError(
        "Cannot downgrade 0103_email_fts. If you really need to roll back, "
        "manually run: "
        "DROP INDEX CONCURRENTLY IF EXISTS ix_emails_search_vector; "
        "ALTER TABLE emails DROP COLUMN IF EXISTS search_vector;"
    )
