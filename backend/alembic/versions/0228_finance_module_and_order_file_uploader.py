"""Moduł Finanse (import miesięcznych wyników) + atrybucja pliku zamówienia.

Jedna migracja obsługuje dwa niezależne tickety, bo oba jadą w jednym PR-ze,
a rozbicie na dwie rewizje dałoby wyłącznie drugą okazję do rozjazdu głów.

── MODUŁ FINANSE ────────────────────────────────────────────────────────────

DWIE TABELE, NIE JEDNA. `finance_import_runs` opisuje WGRANY PLIK (kto, kiedy,
za jaki miesiąc, gdzie leży oryginał), `finance_monthly_results` — jego treść.
Rozdzielenie jest tym, co czyni „Przywróć jako aktualny" wykonalnym: wiersze
są związane z konkretnym biegiem i nigdy nie są nadpisywane w miejscu, więc
wersja zastąpiona zachowuje własne ręczne poprawki i wraca dokładnie w tym
stanie, w jakim ją porzucono. Gdyby wiersze wisiały na (rok, miesiąc), re-import
musiałby je skasować i przywracanie odtwarzałoby dane z pliku — czyli gubiło
każdą ręczną korektę.

STATUS JAKO VARCHAR + CHECK, NIE NATYWNY ENUM PG. Poszerzenie domeny to wtedy
przepisanie CHECK-a (DROP + ADD), a nie `ALTER TYPE ... ADD VALUE`, które
w lustrze `entrypoint.sh` bywa opakowane w `EXCEPTION WHEN duplicate_object`
i po pierwszym wykonaniu nigdy więcej nie zadziała (lekcja z 0226). Wzorzec
przejęty z `client_import_runs`.

INDEKS CZĘŚCIOWY ZAMIAST UNIQUE NA (rok, miesiąc). Aktualna wersja miesiąca
musi być dokładnie jedna, ale zastąpionych wolno mieć dowolnie wiele — to cała
treść Archiwum. Zwykły UNIQUE zabroniłby drugiego importu tego samego miesiąca,
czyli funkcji, o którą ticket prosi wprost.

`file_sha256` CELOWO BEZ UNIQUE. `client_import_runs` ma taki indeks
(`... WHERE status='applied'`) i dla tamtego przepływu jest poprawny — tam
powtórzony plik to pomyłka. Tutaj najczęstszy scenariusz „Zastąp" to poprawka
w arkuszu i ponowne wgranie; przy części importów bajty bywają identyczne
(operator poprawia dane już w NEXUSIE, a plik wgrywa ponownie „dla porządku").
Unikalność blokowałaby dokładnie tę ścieżkę. Hash zostaje informacyjnie.

SZEŚCIU KOLUMN ARKUSZA SPOZA TABELI WYNIKOWEJ (Uwagi, Projekt, Stawka z VD,
Czy wystawiono fakturę, Data wysłania, Płatny urlop) NIE MA W SCHEMACIE.
Ticket wymaga, żeby nie były widoczne w żadnym widoku; zapisanie ich „na
wszelki wypadek" w JSONB tworzyłoby stałą powierzchnię wycieku — każda przyszła
serializacja wiersza by je wyniosła, a żadna z nich nie byłaby świadoma tego
zakazu. Oryginalny plik i tak leży na dysku i jest pobieralny z Archiwum, więc
kolumny nie znikają — przestają tylko być danymi aplikacji.

── ATRYBUCJA PLIKU ZAMÓWIENIA ───────────────────────────────────────────────

`client_orders` dostaje `file_uploaded_by` / `file_uploaded_at`. Dotąd
`replace_order_po` nie zapisywał NIC o autorze wgrania (kod miał tam wręcz
no-op `_ = user, datetime, timezone` z komentarzem, że atrybucja jest „gdzie
indziej" — nie była). Kolumny są osobne od `created_by_user_id`, bo zamówienie
i jego PDF powstają w różnych momentach i zwykle z ręki różnych osób: drafty
zakłada automat z hooka „hired", plik dokłada człowiek później. Sekcja
„Dokumenty zamówień" w zakładce Dokumenty kontraktu pokazuje tę atrybucję
w kolumnie „Dodał" — tak samo jak `contract_documents.uploaded_by` dla każdego
innego dokumentu kontraktu.

Revision ID: 0228_finance_module_and_order_file_uploader
Revises: 0227_multi_consultant_orders
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0228_finance_module_and_order_file_uploader"
down_revision = "0227_multi_consultant_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "finance_import_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("period_year", sa.Integer(), nullable=False),
        sa.Column("period_month", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="current",
            nullable=False,
        ),
        sa.Column("source_filename", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=512), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("row_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "needs_completion_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("rejected_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "rejected_details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('current', 'superseded')",
            name="ck_finance_import_runs_status",
        ),
        sa.CheckConstraint(
            "period_month BETWEEN 1 AND 12",
            name="ck_finance_import_runs_period_month",
        ),
        sa.CheckConstraint(
            "period_year BETWEEN 2000 AND 2100",
            name="ck_finance_import_runs_period_year",
        ),
    )
    op.create_index(
        op.f("ix_finance_import_runs_id"), "finance_import_runs", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_finance_import_runs_status"),
        "finance_import_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_finance_import_runs_period",
        "finance_import_runs",
        ["period_year", "period_month"],
        unique=False,
    )
    # Dokładnie jedna aktualna wersja miesiąca; zastąpionych dowolnie wiele.
    op.create_index(
        "uq_finance_import_runs_current_period",
        "finance_import_runs",
        ["period_year", "period_month"],
        unique=True,
        postgresql_where=sa.text("status = 'current'"),
    )

    op.create_table(
        "finance_monthly_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("import_run_id", sa.Integer(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("consultant_name", sa.String(length=255), nullable=False),
        sa.Column("client_name", sa.String(length=255), nullable=True),
        sa.Column("cost_rate_md", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("md_count", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("compensation", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("revenue_rate_md", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("invoice_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("margin_pln", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("margin_pct", sa.Numeric(precision=7, scale=2), nullable=True),
        sa.Column(
            "edited_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["import_run_id"], ["finance_import_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "import_run_id", "row_number", name="uq_finance_monthly_results_row"
        ),
        sa.CheckConstraint(
            "row_number >= 1", name="ck_finance_monthly_results_row_number"
        ),
    )
    op.create_index(
        op.f("ix_finance_monthly_results_id"),
        "finance_monthly_results",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_finance_monthly_results_import_run_id",
        "finance_monthly_results",
        ["import_run_id"],
        unique=False,
    )

    op.add_column(
        "client_orders", sa.Column("file_uploaded_by", sa.Integer(), nullable=True)
    )
    op.add_column(
        "client_orders",
        sa.Column("file_uploaded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_client_orders_file_uploaded_by_users",
        "client_orders",
        "users",
        ["file_uploaded_by"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_client_orders_file_uploaded_by_users", "client_orders", type_="foreignkey"
    )
    op.drop_column("client_orders", "file_uploaded_at")
    op.drop_column("client_orders", "file_uploaded_by")

    op.drop_index(
        "ix_finance_monthly_results_import_run_id", table_name="finance_monthly_results"
    )
    op.drop_index(
        op.f("ix_finance_monthly_results_id"), table_name="finance_monthly_results"
    )
    op.drop_table("finance_monthly_results")

    op.drop_index(
        "uq_finance_import_runs_current_period", table_name="finance_import_runs"
    )
    op.drop_index("ix_finance_import_runs_period", table_name="finance_import_runs")
    op.drop_index(
        op.f("ix_finance_import_runs_status"), table_name="finance_import_runs"
    )
    op.drop_index(op.f("ix_finance_import_runs_id"), table_name="finance_import_runs")
    op.drop_table("finance_import_runs")
