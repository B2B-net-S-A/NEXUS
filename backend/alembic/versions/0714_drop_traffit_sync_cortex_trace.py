"""Usunięcie 9 nieużywanych tabel: synchronizacja dwukierunkowa Traffita i ślad Cortexa.

Revision ID: 0714_drop_traffit_sync_cortex_trace
Revises: 0713_job_team_variants

Decyzja Artura z 15.11.2026: usuwamy wszystkie 9, a tabele Cortexa najpierw idą do zaszyfrowanego zrzutu na 30 dni. Siedem tabel synchronizacji
dwukierunkowej z Traffitem (0173, #767) nie dostało na produkcji ani jednego
wiersza; przebiegi i obserwacje Cortexa (0167) zostały po zdjęciu modułu
w #1751 (23.09.2026). Modele, sondy `/api/health/deep` i DDL siatki zdjął
#3463. Klucze obce łączą tylko tabele z listy albo wychodzą z nich na
zewnątrz, więc każda grupa idzie jedną instrukcją bez CASCADE: nieznana
zależność przerwie migrację głośno. Lustro jest w `entrypoint.sh`; pilnuje go
`tests/test_drop_traffit_sync_cortex_tables_mirror.py`.
"""

from alembic import op

revision = "0714_drop_traffit_sync_cortex_trace"
down_revision = "0713_job_team_variants"
branch_labels = None
depends_on = None

_TRAFFIT_SYNC = (
    "traffit_field_contracts",
    "traffit_outbox_events",
    "traffit_sync_conflicts",
    "traffit_sync_runs",
    "traffit_sync_run_phases",
    "integration_leases",
    "traffit_integration_control",
)
_CORTEX_TRACE = ("cortex_extraction_runs", "cortex_unmatched_observations")
TABLE_GROUPS = (_TRAFFIT_SYNC, _CORTEX_TRACE)


def drop_statements() -> list[str]:
    return [f"DROP TABLE IF EXISTS {', '.join(group)}" for group in TABLE_GROUPS]


def upgrade() -> None:
    # zgodne-wstecz: tabel nie czyta kod od #3463 (wdrożone 15.11.2026)
    for statement in drop_statements():
        op.execute(statement)


def downgrade() -> None:
    """Bez cofania schematem: treść tabel Cortexa przywraca się z zaszyfrowanego zrzutu, tabele Traffita były puste."""
