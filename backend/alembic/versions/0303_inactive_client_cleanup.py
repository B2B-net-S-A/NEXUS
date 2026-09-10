"""Jednorazowe czyszczenie zakładki „Nieaktywni klienci".

Trzy rzeczy, każda z własnego powodu:

* ``client_cleanup_runs`` — raport wykonanej operacji (lista B: wstrzymani
  z powodem). UNIQUE po ``kind`` jest bezpiecznikiem jednorazowości w bazie;
  serwis sprawdza to samo pod blokadą doradczą, żeby odmówić czytelnym 409.
* ``purged_clients`` — lista A (trwale usunięci) ORAZ nagrobek. Nocny sync
  Traffita robi pełny skan ``/clients/`` i upsertuje po ``external_id``; bez
  nagrobka usunięty klient wracałby do Nexusa następnej nocy. Stąd brak
  kaskady z ``client_cleanup_runs`` — skasowanie raportu nie może po cichu
  zdjąć nagrobków.
* ``client_import_rows.purged_at`` / ``purged_client_id`` — usunięcie klienta
  zeruje (SET NULL) jego powiązanie w audycie manifestu portfela, a inwariant
  ``get_client_portfolio_import_health`` porównuje żywe zakresy z liczbą
  wierszy audytu. Bez znacznika skasowanie klienta z manifestu wyglądałoby
  jak dryf i czerwieniło ``/api/health/deep`` (503).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0303_inactive_client_cleanup"
down_revision = "0302_cv_version_maps"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "client_cleanup_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(48), nullable=False),
        sa.Column(
            "executed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "executed_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("executed_by_name", sa.String(255), nullable=True),
        sa.Column("candidates_count", sa.Integer(), nullable=False),
        sa.Column("kept_count", sa.Integer(), nullable=False),
        sa.Column("deleted_count", sa.Integer(), nullable=False),
        sa.Column("held_count", sa.Integer(), nullable=False),
        sa.Column(
            "held",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "summary",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.UniqueConstraint("kind", name="uq_client_cleanup_runs_kind"),
    )
    op.create_table(
        "purged_clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("client_cleanup_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("legal_name", sa.String(255), nullable=True),
        sa.Column("nip", sa.String(32), nullable=True),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("external_source", sa.String(50), nullable=True),
        sa.Column("external_id", sa.String(100), nullable=True),
        sa.Column("client_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "purged_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("client_id", name="uq_purged_clients_client_id"),
    )
    op.create_index("ix_purged_clients_run_id", "purged_clients", ["run_id"])
    op.create_index(
        "ix_purged_clients_external",
        "purged_clients",
        ["external_source", "external_id"],
    )
    op.add_column(
        "client_import_rows",
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "client_import_rows",
        sa.Column("purged_client_id", sa.Integer(), nullable=True),
    )


def downgrade():
    op.drop_column("client_import_rows", "purged_client_id")
    op.drop_column("client_import_rows", "purged_at")
    op.drop_index("ix_purged_clients_external", table_name="purged_clients")
    op.drop_index("ix_purged_clients_run_id", table_name="purged_clients")
    op.drop_table("purged_clients")
    op.drop_table("client_cleanup_runs")
