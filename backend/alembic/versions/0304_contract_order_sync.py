"""Synchronizacja kontrakt ↔ zamówienia (09.2026).

Dwie kolumny, każda z własnego powodu:

* ``contracts.client_order_start_date`` — okres zamówienia jest OSOBNYM polem
  kontraktu, obok okresu umowy (``start_date``/``end_date``). Koniec zamówienia
  (``client_order_end_date``) istniał od dawna; brakowało początku, więc
  kontrakt nie umiał pokazać „okres zamówienia 15.09 → 31.12" bez nadpisywania
  okresu umowy.
* ``contract_client_rates.source_order_id`` — krok stawki przychodowej
  wyprowadzony z zamówienia. Bez tego wskazania synchronizacja nie odróżni
  kroku z zamówienia od kroku z aneksu ``rate_change``, więc przy kolejnym
  zapisie albo kasowałaby aneksy, albo dokładała duplikaty. CASCADE: skasowany
  szkic zamówienia nie może zostawić po sobie stawki, której nikt nie ustalił.

Jednorazowa korekta istniejących szkiców i migawka raportu zgodności idą
przez ``entrypoint.sh`` (``app/services/contract_order_sync_repair.py``) —
wykonuje je ta sama logika ORM co bieżąca synchronizacja, a migracje alembic
są tu synchroniczne.
"""

from alembic import op
import sqlalchemy as sa

revision = "0304_contract_order_sync"
down_revision = "0303_inactive_client_cleanup"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "contracts",
        sa.Column("client_order_start_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "contract_client_rates",
        sa.Column(
            "source_order_id",
            sa.Integer(),
            sa.ForeignKey("client_orders.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_contract_client_rates_source_order_id",
        "contract_client_rates",
        ["source_order_id"],
    )


def downgrade():
    op.drop_index(
        "ix_contract_client_rates_source_order_id",
        table_name="contract_client_rates",
    )
    op.drop_column("contract_client_rates", "source_order_id")
    op.drop_column("contracts", "client_order_start_date")
