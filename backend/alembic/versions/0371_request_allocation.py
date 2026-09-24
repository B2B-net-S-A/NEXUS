"""Cztery kategorie kompetencji, stany requestów i przydział ludzi do requestów.

Revision ID: 0371_request_allocation
Revises: 0370_teams_prep_transcripts

Decyzje Artura 24.09.2026:

* kategorie kompetencji zespołu to cztery grupy z InfraReportera
  (``services/competence_category_four.py`` — nazwy, przepięcie ``data_ai``
  na grupę Infra, rekrutacje security z QA do Infra);
* ``users.allocation_excluded`` — konto „Poza przydziałem”;
* ``jobs.work_state`` — stan pracy nad requestem prowadzony w NEXUSIE
  (Traffit go nie nadpisuje);
* ``job_work_assignments`` — kto pracuje nad requestem (automat i ręcznie).

DDL i dane mają jedno źródło w ``app/services`` — to samo czyta blok
w ``entrypoint.sh`` (prod alembic bywa osierocony).
"""

import json

import sqlalchemy as sa
from alembic import op

from app.services.competence_category_four import MARKER as CC_MARKER
from app.services.competence_category_four import sync_statements
from app.services.request_allocation_schema import (
    COLUMN_STATEMENTS,
    ENUM_STATEMENTS,
    INITIAL_STATE_MARKER,
    INITIAL_STATE_STATEMENTS,
)

revision = "0371_request_allocation"
down_revision = "0370_teams_prep_transcripts"
branch_labels = None
depends_on = None


def _marker(bind, key: str) -> bool:
    return (
        bind.execute(
            sa.text("SELECT 1 FROM app_settings WHERE key = :k"), {"k": key}
        ).scalar()
        is not None
    )


def _stamp(bind, key: str, value: dict) -> None:
    bind.execute(
        sa.text(
            "INSERT INTO app_settings (key, value, updated_at) "
            "VALUES (:k, CAST(:v AS jsonb), now()) ON CONFLICT (key) DO NOTHING"
        ),
        {"k": key, "v": json.dumps(value)},
    )


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for statement in ENUM_STATEMENTS:
            op.execute(statement)
    for statement in COLUMN_STATEMENTS:
        op.execute(statement)

    bind = op.get_bind()
    has_categories = bind.execute(
        sa.text("SELECT count(*) FROM competence_categories")
    ).scalar()
    if has_categories and not _marker(bind, CC_MARKER):
        for statement, params in sync_statements():
            bind.execute(sa.text(statement), params)
        _stamp(bind, CC_MARKER, {"source": "migration_0371"})
    if not _marker(bind, INITIAL_STATE_MARKER):
        for statement in INITIAL_STATE_STATEMENTS:
            bind.execute(sa.text(statement))
        _stamp(bind, INITIAL_STATE_MARKER, {})


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS job_work_assignments")
    op.execute("ALTER TABLE jobs DROP CONSTRAINT IF EXISTS ck_jobs_work_state")
    op.execute("DROP INDEX IF EXISTS ix_jobs_work_state")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS work_state_changed_by")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS work_state_changed_at")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS work_state")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS allocation_excluded")
    # Nazwy kategorii i przepięte klucze obce zostają — cofnięcie podziału
    # zespołu to decyzja biznesowa, nie techniczna. Wartości enumów też
    # zostają (Postgres nie ma `ALTER TYPE … DROP VALUE`).
