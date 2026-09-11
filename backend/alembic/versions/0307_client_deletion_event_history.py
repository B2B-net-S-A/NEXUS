"""Ręczne usuwanie klienta z profilu + ogólnosystemowa „Historia zdarzeń".

Cztery zmiany, każda z własnego powodu:

* ``users.can_delete_clients`` — uprawnienie IMIENNE, nie rolowe. Ticket
  wskazuje cztery konkretne osoby, a macierz akcji RBAC daje administratorowi
  każdą akcję automatycznie — więc nie da się nią wyrazić „tylko te osoby".
  Flaga domyślnie ``false`` dla wszystkich; nadaje ją administrator w edycji
  użytkownika, a każda zmiana trafia do Historii zdarzeń.
* ``clients.deleted_at`` / ``deleted_by`` — klient Z HISTORIĄ (zakończone
  zamówienia, umowy, archiwum konsultantów) jest usuwany z list, ale jego
  wiersz zostaje: kontrakty, zamówienia i umowy nadal na niego wskazują, a
  usunięcie fizyczne skasowałoby je kaskadą albo osierociło. ``deleted_at``
  odróżnia takie usunięcie od archiwizacji duplikatu po scaleniu.
* ``purged_clients.run_id`` bez NOT NULL — klient PUSTY jest usuwany trwale
  z tym samym nagrobkiem co w jednorazowym czyszczeniu (0303); bez nagrobka
  nocny sync Traffita odtworzyłby go następnej nocy. Ręczne usunięcie nie
  należy do żadnego przebiegu czyszczenia.
* ``critical_events`` — dziennik krytycznych operacji (wykonanych i
  zablokowanych). Bez kluczy obcych: wpis ma przeżyć usunięcie obiektu, którego
  dotyczy, i konta osoby, która go wykonała, więc niesie zdenormalizowane
  nazwy. Brak FK oznacza też, że zapis zablokowanej próby z osobnej sesji nigdy
  nie czeka na blokady trzymane przez żądanie, które właśnie odmawia.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0307_client_deletion_event_history"
down_revision = "0306_pfron_renewal_split_repair"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column(
            "can_delete_clients",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "clients",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "clients",
        sa.Column(
            "deleted_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.alter_column("purged_clients", "run_id", nullable=True)
    op.create_table(
        "critical_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("entity_label", sa.String(500), nullable=True),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_name", sa.String(255), nullable=True),
        sa.Column("actor_email", sa.String(255), nullable=True),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("client_name", sa.String(255), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            "outcome IN ('executed', 'blocked')",
            name="ck_critical_events_outcome",
        ),
    )
    op.create_index(
        "ix_critical_events_occurred_at", "critical_events", ["occurred_at"]
    )
    op.create_index(
        "ix_critical_events_entity",
        "critical_events",
        ["entity_type", "entity_id"],
    )
    op.create_index("ix_critical_events_client_id", "critical_events", ["client_id"])


def downgrade():
    op.drop_index("ix_critical_events_client_id", table_name="critical_events")
    op.drop_index("ix_critical_events_entity", table_name="critical_events")
    op.drop_index("ix_critical_events_occurred_at", table_name="critical_events")
    op.drop_table("critical_events")
    op.execute("DELETE FROM purged_clients WHERE run_id IS NULL")
    op.alter_column("purged_clients", "run_id", nullable=False)
    op.drop_column("clients", "deleted_by")
    op.drop_column("clients", "deleted_at")
    op.drop_column("users", "can_delete_clients")
