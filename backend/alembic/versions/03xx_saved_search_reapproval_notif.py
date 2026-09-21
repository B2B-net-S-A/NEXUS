"""notificationtype: ``saved_search_reapproval`` — zapisane wyszukiwanie do akceptacji.

Revision ID: saved_search_reapproval_notif
Revises: 0330_jarvis

Migracja zapisanych wyszukiwań na wspólną semantykę filtrów
(``services/saved_search_migration.py``) wstrzymuje alert, gdy nowa semantyka
zwraca inny zbiór osób, i RAZ powiadamia właściciela. Sama migracja danych nie
wymaga DDL: kolumna ``saved_searches.requires_reapproval`` istnieje od
wycofania stawek miesięcznych, a szczegóły jadą w JSONB ``filters``.
Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony). Postgres nie usuwa
wartości enuma, więc downgrade jest no-opem.
"""

from alembic import op

# Identyfikator BEZ numeru — żeby migrację dało się przenumerować przy merge'u
# bez szukania po repo. Przy zmianie kolejności zmień WYŁĄCZNIE: nazwę tego
# pliku (`03xx_…` → właściwy numer) i `down_revision` poniżej. Nic innego w repo
# nie odwołuje się do tego identyfikatora ani do numeru.
revision = "saved_search_reapproval_notif"
down_revision = "0330_jarvis"
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
