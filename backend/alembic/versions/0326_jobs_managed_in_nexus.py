"""Przełącznik „Rekrutacja prowadzona w NEXUSIE" (per oferta).

Revision ID: 0326_jobs_managed_in_nexus
Revises: 0325_pending_verification_retired

Why: nocny import Traffita pisze `candidate_stages` dla KAŻDEJ rekrutacji z Traffita,
a tablica czyta NAJNOWSZY wiersz per (kandydat, oferta) — ruch zrobiony w NEXUSIE był
nadpisywany nazajutrz (131 z 32 872 ruchów w 90 dniach = 0,4 % w NEXUSIE). Decyzja
Artura 17.09.2026: flaga PER OFERTA; `import_pipelines` pomija jej etapy, `_UPSERT_JOB`
nie nadpisuje `title`/`status`/`closed_at`. `_at`/`_by` = ślad audytowy w nagłówku.
Lustro w `entrypoint.sh` (`_COLUMN_STATEMENTS`) — pilnuje
`tests/test_managed_in_nexus_migration_mirror.py`.
"""

from alembic import op

revision = "0326_jobs_managed_in_nexus"
down_revision = "0325_pending_verification_retired"
branch_labels = None
depends_on = None

ADD_MANAGED_IN_NEXUS = (
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS managed_in_nexus "
    "BOOLEAN NOT NULL DEFAULT false"
)
ADD_MANAGED_IN_NEXUS_AT = (
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS managed_in_nexus_at TIMESTAMPTZ NULL"
)
ADD_MANAGED_IN_NEXUS_BY = (
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS managed_in_nexus_by "
    "INTEGER NULL REFERENCES users(id) ON DELETE SET NULL"
)


def upgrade() -> None:
    op.execute(ADD_MANAGED_IN_NEXUS)
    op.execute(ADD_MANAGED_IN_NEXUS_AT)
    op.execute(ADD_MANAGED_IN_NEXUS_BY)


def downgrade() -> None:
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS managed_in_nexus_by")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS managed_in_nexus_at")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS managed_in_nexus")
