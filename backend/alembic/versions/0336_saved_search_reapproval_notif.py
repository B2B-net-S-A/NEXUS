"""notificationtype: ``saved_search_reapproval`` — zapisane wyszukiwanie do akceptacji.

Revision ID: 0336_saved_search_reapproval_notif
Revises: 0335_recruitment_automations

Migracja zapisanych wyszukiwań na wspólną semantykę filtrów
(``services/saved_search_migration.py``) wstrzymuje alert, gdy nowa semantyka
zwraca inny zbiór osób, i RAZ powiadamia właściciela. Sama migracja danych nie
wymaga DDL: kolumna ``saved_searches.requires_reapproval`` istnieje od
wycofania stawek miesięcznych, a szczegóły jadą w JSONB ``filters``.
Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony). Postgres nie usuwa
wartości enuma, więc downgrade jest no-opem.
"""

from alembic import op

revision = "0336_saved_search_reapproval_notif"
down_revision = "0335_recruitment_automations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS "
            "'saved_search_reapproval'"
        )


def downgrade() -> None:
    pass
