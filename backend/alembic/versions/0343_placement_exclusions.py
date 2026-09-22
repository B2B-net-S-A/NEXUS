"""Wykluczone placementy: tabela, zasianie reguły i widok bez nich (0343).

Revision ID: 0343_placement_exclusions
Revises: 0342_email_send_state

24–25.09.2025 jedno konto ustawiło 45 parom „Zatrudniony" w dwa dni (wiersze
z importu Traffita; 35 z nich nigdy nie miało „CV wysłane"). Dawało to
fałszywy szczyt placementów we wrześniu 2025 w każdej statystyce.

Migracja:

1. zakłada ``placement_exclusions`` (UNIQUE po parze kandydat × rekrutacja);
2. zasiewa CAŁĄ historyczną serię (decyzja A) i regułę na całej historii
   (decyzja B: seria ≥ 10 par jednego konta w dniu warszawskim, pary bez
   „CV wysłane") — SQL z ``app/services/placement_exclusions.py``, bez ani
   jednego ID w kodzie;
3. odtwarza widok ``analytics_first_milestones`` tak, że pomija ``hired``
   wykluczonych par (lista kolumn bez zmian).

Paragon (liczby + ID wierszy etapów) w ``app_settings['0343_placement_exclusions']``.
``candidate_stages`` zostaje nietknięte. Lustro w ``entrypoint.sh`` (prod
alembic bywa osierocony): DDL + widok w ``_COLUMN_STATEMENTS``, zasianie
w fazie ``seed-placement-exclusions``.
"""

import json

import sqlalchemy as sa
from alembic import op

from app.services.placement_exclusions import (
    HISTORICAL_SERIES_SQL,
    PREVIOUS_VIEW_SQL,
    RECEIPT_SQL,
    RULE_SQL,
    SEED_MARKER,
    TABLE_DDL,
    VIEW_SQL,
    historical_params,
    receipt,
    rule_params,
)

revision = "0343_placement_exclusions"
down_revision = "0342_email_send_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in TABLE_DDL:
        op.execute(stmt)
    bind = op.get_bind()
    done = bind.execute(
        sa.text("SELECT 1 FROM app_settings WHERE key = :key"), {"key": SEED_MARKER}
    ).scalar()
    if not done:
        historical = [
            row[0]
            for row in bind.execute(sa.text(HISTORICAL_SERIES_SQL), historical_params())
        ]
        rule = [row[0] for row in bind.execute(sa.text(RULE_SQL), rule_params())]
        bind.execute(
            sa.text(RECEIPT_SQL),
            {"key": SEED_MARKER, "value": json.dumps(receipt(historical, rule))},
        )
    op.execute(VIEW_SQL)


def downgrade() -> None:
    # Najpierw widok (zależy od tabeli), potem tabela. Paragon zostaje —
    # opisuje, co było wykluczone.
    op.execute(PREVIOUS_VIEW_SQL)
    op.execute("DROP TABLE IF EXISTS placement_exclusions")
