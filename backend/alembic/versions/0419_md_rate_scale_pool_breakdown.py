"""Stawki linii MD z trzema miejscami i podział zejść wspólnej puli MD.

Revision ID: 0419_md_rate_scale_pool_breakdown
Revises: 0418_candidate_rate_changes

``client_orders.md_rate_cost`` / ``md_rate_revenue`` dostają trzy miejsca po
przecinku (ticket „Przypisanie konsultantów do zamówienia MD”, 10.2026),
a miesięczne zejście wspólnej puli MD — opcjonalny podział na konsultantów
(``breakdown``), żeby dało się je edytować per osoba.

SQL ma jedno źródło (``app/services/md_order_precision_schema.py``) — ten sam
moduł importuje ``entrypoint.sh``.
"""

from alembic import op

from app.services import md_order_precision_schema as schema

revision = "0419_md_rate_scale_pool_breakdown"
down_revision = "0418_candidate_rate_changes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    # Zawężenie do dwóch miejsc gubiłoby trzecie miejsce zapisanych stawek,
    # a usunięcie kolumny — podział zejść na osoby. Odmawiamy zamiast kasować.
    bind = op.get_bind()
    rows = bind.exec_driver_sql(
        "SELECT count(*) FROM client_order_group_md_consumptions "
        "WHERE breakdown IS NOT NULL"
    ).scalar()
    precise = bind.exec_driver_sql(
        "SELECT count(*) FROM client_orders "
        "WHERE md_rate_cost <> round(md_rate_cost, 2) "
        "OR md_rate_revenue <> round(md_rate_revenue, 2)"
    ).scalar()
    if rows or precise:
        raise RuntimeError(
            "0419 downgrade: są zejścia z podziałem na osoby albo stawki z trzecim "
            "miejscem po przecinku — downgrade by je skasował"
        )
    op.execute(
        "ALTER TABLE client_order_group_md_consumptions DROP COLUMN IF EXISTS breakdown"
    )
    for column in ("md_rate_cost", "md_rate_revenue"):
        op.execute(
            f"ALTER TABLE client_orders ALTER COLUMN {column} TYPE NUMERIC(12, 2)"
        )
