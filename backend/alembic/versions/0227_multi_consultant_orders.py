"""Zamówienia wielo-konsultantowe: grupa nad zamówieniami + budżet i zużycie MD.

Klienci rozliczani w T&M na MD (BIK, Polkomtel, BNP) dostają JEDNO zamówienie
obejmujące kilku konsultantów naraz. Każdy z nich ma własną stawkę kosztową,
przychodową i własny budżet MD, który topnieje wraz z miesięcznymi raportami.

**Dlaczego GRUPA nad ``client_orders``, a nie „wiele konsultantów w jednym
wierszu ``client_orders``".** Naturalny odruch to zdjąć ``NOT NULL`` z
``client_orders.contract_id`` i przenieść konsultanta do tabeli linii. To by
zepsuło siedemnaście istniejących ścieżek, bo CAŁY system czyta zamówienie
przez jego kontrakt: skaner wygasania (``dl_portal_expiry_scanner`` robi INNER
JOIN po ``contract_id`` — zamówienie bez kontraktu przestałoby ostrzegać na
30/14/7 dni, a i tak zostałoby przestemplowane na ``completed``), sync
terminacji (``contracts.py`` domyka zamówienia po ``contract_id`` — osierocone
biegłyby w nieskończoność po zakończeniu współpracy), zgrupowana lista
zamówień (iteruje po ``Contract.client_orders``, więc osierocone zamówienie
ZNIKA z widoku), rejestr kontraktów, inwentarz zaangażowania i kaskada
usunięcia. Do tego ``ClientOrderRead.contract_id`` jest typu ``int``, więc
pierwszy odczyt takiego wiersza kończy się błędem walidacji, nie pustką.

Odwrócenie problemu kosztuje jedną tabelę i zero ryzyka: „Zamówienie nr 445"
od klienta to GRUPA, a każdy konsultant pod nią to zwykłe ``ClientOrder`` ze
swoim kontraktem. Wszystkie powyższe ścieżki działają dalej bez zmian, bo
każde zamówienie nadal ma kontrakt. Zamówienia dotychczasowych klientów mają
``order_group_id IS NULL`` i nie zmienia się dla nich dosłownie nic.

Precyzja MD
-----------
``md_total = kwota / stawka_przychodowa`` bywa ułamkiem nieskończonym, więc
``NUMERIC(16, 6)`` jest nośnikiem „pełnej precyzji": cztery miejsca zapasu
ponad prezentację (2 miejsca), żeby kolejne importy i zamiany kontraktora nie
kumulowały błędu widocznego dla użytkownika.

``md_remaining`` jest WYLICZANE (``md_total - Σ konsumpcji + korekta ręczna``)
i przechowywane. Wyliczanie od zera przy każdym zapisie jest tym, co czyni
import idempotentnym: powtórka tego samego miesiąca nadpisuje wiersz
konsumpcji (UNIQUE na ``(order_id, period_month)``) i przelicza pozostałość
od nowa, zamiast odjąć MD drugi raz.

Revision ID: 0227_multi_consultant_orders
Revises: 0226_b2b_generated_contract_suspended
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0227_multi_consultant_orders"
down_revision = "0226_b2b_generated_contract_suspended"
branch_labels = None
depends_on = None


# Linia MD jest albo kompletna, albo jej nie ma. Częściowo wypełniona linia
# (budżet bez stawki przychodowej) wysadziłaby dzielenie przy zamianie
# kontraktora w środku transakcji, a stawka <= 0 jest dzielnikiem, więc baza
# odrzuca ją niezależnie od tego, co przepuści API.
_MD_COHERENCE = """CHECK (
            (
                md_total IS NULL
                AND md_remaining IS NULL
                AND md_input_mode IS NULL
                AND md_input_value IS NULL
                AND md_rate_revenue IS NULL
            )
            OR (
                md_total IS NOT NULL
                AND md_remaining IS NOT NULL
                AND md_input_mode IN ('md', 'amount')
                AND md_input_value IS NOT NULL
                AND md_rate_revenue IS NOT NULL
                AND md_rate_revenue > 0
            )
        )"""

# 'YYYY-MM'. Miesiąc jest częścią klucza idempotencji, więc jego kształt musi
# być wymuszony w bazie — '2026-7' i '2026-07' to dwa różne stringi, czyli dwa
# wiersze na ten sam miesiąc i podwójnie odjęte MD.
_PERIOD_MONTH_RE = r"^[0-9]{4}-(0[1-9]|1[0-2])$"


def upgrade() -> None:
    # ── 1. Grupa = „Zamówienie nr 445" od klienta ───────────────────────────
    op.create_table(
        "client_order_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("order_number", sa.String(length=64), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        # NULL = bezterminowo (jak w `client_orders.end_date`).
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
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
        sa.CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_client_order_groups_dates",
        ),
    )
    op.create_index(
        "ix_client_order_groups_client",
        "client_order_groups",
        ["client_id"],
    )

    # ── 2. Kolumny linii MD na istniejących zamówieniach ────────────────────
    # Wszystkie nullable → wiersze dotychczasowych klientów zostają nietknięte
    # i nie muszą niczego wypełniać.
    op.add_column(
        "client_orders",
        sa.Column(
            "order_group_id",
            sa.Integer(),
            sa.ForeignKey("client_order_groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_client_orders_order_group",
        "client_orders",
        ["order_group_id"],
    )
    op.add_column(
        "client_orders",
        sa.Column("md_rate_cost", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "client_orders",
        sa.Column("md_rate_revenue", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "client_orders",
        sa.Column("md_input_mode", sa.String(length=8), nullable=True),
    )
    op.add_column(
        "client_orders",
        sa.Column("md_input_value", sa.Numeric(16, 6), nullable=True),
    )
    op.add_column(
        "client_orders", sa.Column("md_total", sa.Numeric(16, 6), nullable=True)
    )
    op.add_column(
        "client_orders", sa.Column("md_remaining", sa.Numeric(16, 6), nullable=True)
    )
    # Korekta ręczna trzymana OSOBNO od konsumpcji, żeby `md_remaining` dało
    # się przeliczyć od zera bez gubienia poprawki operatora. Gdyby korekta
    # nadpisywała `md_remaining` wprost, najbliższy import miesiąca skasowałby
    # ją po cichu.
    op.add_column(
        "client_orders",
        sa.Column(
            "md_manual_adjustment",
            sa.Numeric(16, 6),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "client_orders",
        sa.Column(
            "predecessor_order_id",
            sa.Integer(),
            sa.ForeignKey("client_orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # NOT VALID — spójnie z lustrem w entrypoint.sh. Bez tego Postgres skanuje
    # całą tabelę pod ACCESS EXCLUSIVE, żeby zweryfikować wiersze, które
    # z definicji spełniają pierwszą gałąź (wszystkie kolumny MD są świeże,
    # więc NULL). Skan niczego by nie wykrył, a zablokowałby zamówienia
    # na czas migracji.
    op.execute(
        "ALTER TABLE client_orders ADD CONSTRAINT "
        f"ck_client_orders_md_coherence {_MD_COHERENCE} NOT VALID"
    )

    # ── 3. Partia importu z Finansów ────────────────────────────────────────
    op.create_table(
        "md_consumption_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("period_month", sa.String(length=7), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column(
            "rows_total", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "rows_applied", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "rows_ambiguous", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "rows_unmatched", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "uploaded_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"period_month ~ '{_PERIOD_MONTH_RE}'",
            name="ck_md_consumption_imports_period",
        ),
    )

    # Wiersz importu ŻYJE DALEJ po imporcie — to on niesie „Wymaga przypisania"
    # do czasu ręcznego rozstrzygnięcia. Bez trwałego wiersza niejednoznaczne
    # dopasowanie przepadałoby razem z odpowiedzią HTTP, a MD nigdy by nie
    # trafiły na żadną linię.
    op.create_table(
        "md_consumption_import_rows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "import_id",
            sa.Integer(),
            sa.ForeignKey("md_consumption_imports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("consultant_name", sa.String(length=255), nullable=False),
        sa.Column("md_reported", sa.Numeric(16, 6), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "matched_order_id",
            sa.Integer(),
            sa.ForeignKey("client_orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Kandydaci do przypisania, gdy dopasowań jest więcej niż jedno.
        sa.Column("candidate_order_ids", JSONB(), nullable=True),
        sa.Column(
            "resolved_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('applied', 'needs_assignment', 'unmatched')",
            name="ck_md_import_rows_status",
        ),
    )
    op.create_index(
        "ix_md_import_rows_import",
        "md_consumption_import_rows",
        ["import_id"],
    )
    op.create_index(
        "ix_md_import_rows_status",
        "md_consumption_import_rows",
        ["status"],
    )

    # ── 4. Miesięczna konsumpcja MD ─────────────────────────────────────────
    op.create_table(
        "client_order_md_consumptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "order_id",
            sa.Integer(),
            sa.ForeignKey("client_orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_month", sa.String(length=7), nullable=False),
        sa.Column("md_reported", sa.Numeric(16, 6), nullable=False),
        sa.Column(
            "import_id",
            sa.Integer(),
            sa.ForeignKey("md_consumption_imports.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
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
        sa.CheckConstraint(
            "source IN ('import', 'manual')",
            name="ck_md_consumptions_source",
        ),
        sa.CheckConstraint(
            f"period_month ~ '{_PERIOD_MONTH_RE}'",
            name="ck_md_consumptions_period",
        ),
    )
    # Klucz idempotencji importu — jeden wiersz na (linia, miesiąc).
    op.create_index(
        "ux_md_consumptions_order_month",
        "client_order_md_consumptions",
        ["order_id", "period_month"],
        unique=True,
    )

    # ── 5. Historia zamówienia ──────────────────────────────────────────────
    # Powrót linii do stanu sprzed zamiany jest niemożliwy do odtworzenia z
    # samych kolumn (nowa linia zna tylko swoje MD), więc obie stawki, obie
    # liczby MD i data zamiany muszą wylądować w dzienniku — to z niego
    # rozliczy się fakturę za miesiąc zamiany.
    op.create_table(
        "client_order_group_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "group_id",
            sa.Integer(),
            sa.ForeignKey("client_order_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            sa.Integer(),
            sa.ForeignKey("client_orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('utworzenie', 'dodanie_konsultanta', 'import_md', "
            "'zamiana_kontraktora', 'edycja_reczna')",
            name="ck_client_order_group_events_type",
        ),
    )
    op.create_index(
        "ix_client_order_group_events_group",
        "client_order_group_events",
        ["group_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_client_order_group_events_group", table_name="client_order_group_events"
    )
    op.drop_table("client_order_group_events")

    op.drop_index(
        "ux_md_consumptions_order_month", table_name="client_order_md_consumptions"
    )
    op.drop_table("client_order_md_consumptions")

    op.drop_index("ix_md_import_rows_status", table_name="md_consumption_import_rows")
    op.drop_index("ix_md_import_rows_import", table_name="md_consumption_import_rows")
    op.drop_table("md_consumption_import_rows")
    op.drop_table("md_consumption_imports")

    op.execute(
        "ALTER TABLE client_orders DROP CONSTRAINT IF EXISTS "
        "ck_client_orders_md_coherence"
    )
    op.drop_column("client_orders", "predecessor_order_id")
    op.drop_column("client_orders", "md_manual_adjustment")
    op.drop_column("client_orders", "md_remaining")
    op.drop_column("client_orders", "md_total")
    op.drop_column("client_orders", "md_input_value")
    op.drop_column("client_orders", "md_input_mode")
    op.drop_column("client_orders", "md_rate_revenue")
    op.drop_column("client_orders", "md_rate_cost")
    op.drop_index("ix_client_orders_order_group", table_name="client_orders")
    op.drop_column("client_orders", "order_group_id")

    op.drop_index("ix_client_order_groups_client", table_name="client_order_groups")
    op.drop_table("client_order_groups")
