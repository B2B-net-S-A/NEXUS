"""Cortex — skill-fact store + unmatched terms (PR1 modułu Cortex).

Revision ID: 0158_cortex_skill_facts
Revises: 0157_framework_target_rates_numeric
Create Date: 2026-07-12

Fundament warstwy „central intelligence" (docs/cortex/00-discovery.md):

``cortex_skill_facts`` — fakty kompetencyjne per (kandydat, skill kanoniczny,
źródło) z confidence/evidence/observed_at. UNIQUE(candidate_id, skill_id,
source) = cel upsertów; re-run backfillu jest idempotentny.

``cortex_unmatched_terms`` — tokeny spoza taksonomii ``skills``/``skill_aliases``
(pętla kuracji słownika).

Idempotent: CREATE TABLE/INDEX z IF NOT EXISTS — współgra z entrypoint
``alembic upgrade heads`` oraz safety-netem ``Base.metadata.create_all``
(nowe TABELE powstają na prodzie nawet przy multi-head; patrz main.py).
"""

from alembic import op

revision = "0158_cortex_skill_facts"
down_revision = "0157_framework_target_rates_numeric"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cortex_skill_facts (
            id            BIGSERIAL PRIMARY KEY,
            candidate_id  INTEGER NOT NULL
                              REFERENCES candidates(id) ON DELETE CASCADE,
            skill_id      INTEGER NOT NULL
                              REFERENCES skills(id) ON DELETE CASCADE,
            source        VARCHAR(20) NOT NULL,
            level         VARCHAR(20) NULL,
            years         INTEGER NULL,
            confidence    DOUBLE PRECISION NOT NULL DEFAULT 0.8,
            evidence      TEXT NULL,
            observed_at   TIMESTAMPTZ NULL,
            extracted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_cortex_fact_cand_skill_source
                UNIQUE (candidate_id, skill_id, source)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cortex_skill_facts_candidate_id "
        "ON cortex_skill_facts (candidate_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cortex_skill_facts_skill_id "
        "ON cortex_skill_facts (skill_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cortex_facts_skill_source "
        "ON cortex_skill_facts (skill_id, source)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cortex_unmatched_terms (
            id            SERIAL PRIMARY KEY,
            term          TEXT NOT NULL,
            occurrences   INTEGER NOT NULL DEFAULT 1,
            last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            status        VARCHAR(12) NOT NULL DEFAULT 'new',
            CONSTRAINT uq_cortex_unmatched_term UNIQUE (term)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cortex_skill_facts")
    op.execute("DROP TABLE IF EXISTS cortex_unmatched_terms")
