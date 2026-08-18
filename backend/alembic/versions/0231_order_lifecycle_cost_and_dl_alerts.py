"""Cykl życia zamówienia, zamówienia kosztowe i powiadomienia Delivery Leada.

Revision ID: 0231_order_lifecycle_cost_and_dl_alerts
Revises: 0230_notes_extraction_ai_feature
Create Date: 2026-08-18

Trzy tickety, jedna rewizja. Rozbicie na trzy dałoby wyłącznie trzy okazje do
rozjazdu głów alembica, a wszystkie trzy obszary i tak spotykają się na jednym
wierszu ``client_order_groups``.

**1. Cykl życia (`status` + `closure_*` + `predecessor_group_id`).**
Grupa nie miała dotąd żadnego stanu — „zakończone" dało się wyrazić tylko
datą, a data nie odróżnia zamówienia domkniętego świadomie od takiego, któremu
minął termin. Bez tego rozróżnienia nie da się ani przenieść zamówienia do
zakładki „Zakończeni", ani go stamtąd przywrócić, ani odmówić dodania
konsultanta do wyczerpanego budżetu.

**2. Zamówienie kosztowe (`is_cost_based` + `budget_*`).**
U Polkomtela obok zamówień MD funkcjonują zamówienia z ustaloną z góry kwotą,
z której schodzi się fakturami. Kwota mieszka na GRUPIE, nie na linii, bo to
jedna pula dzielona przez kilku konsultantów — trzymanie jej per linia
wymagałoby dzielenia budżetu z góry, czego nikt nie robi, i uniemożliwiłoby
odpowiedź na jedyne pytanie, które ma tu znaczenie: ile jeszcze zostało.
``budget_manual_adjustment`` jest OSOBNĄ kolumną z tego samego powodu co
``client_orders.md_manual_adjustment``: korekta nadpisująca ``budget_remaining``
wprost przeżyłaby dokładnie do najbliższego importu, który przelicza resztę od
``budget_amount`` i skasowałby ją po cichu.

**3. Rozliczenie fakturami (`client_order_invoice_consumptions`).**
Lustro ``client_order_md_consumptions`` z tym samym UNIQUE ``(order_id,
period_month)`` — i to ten indeks, a nie ostrożność w kodzie, czyni ponowny
import miesiąca idempotentnym. ``settled_amount``/``unsettled_amount`` są
zapisane, a nie wyliczane w locie, bo „której osobie zabrakło budżetu" zależy
od KOLEJNOŚCI rozliczania; bez utrwalenia wyniku ta sama baza dawałaby różne
odpowiedzi przy różnym sortowaniu odczytu.

**4. `dl_alerts` — osobno od `notifications`.**
Tamta tabela zna wyłącznie ``is_read``: nie ma kto/kiedy obsłużył, więc nie ma
czasu reakcji, czyli nie ma czego wyeksportować do raportu. Ma też unikalny
indeks dobowy, który tłumiłby powtórki, i fail-closed filtr widoczności, przez
który rola Finanse nie zobaczyłaby tych wpisów niezależnie od uprawnień.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0231_order_lifecycle_cost_and_dl_alerts"
down_revision = "0230_notes_extraction_ai_feature"
branch_labels = None
depends_on = None


# 'YYYY-MM' — ten sam kształt co przy MD, bo miesiąc jest częścią klucza
# idempotencji: '2026-7' i '2026-07' to dwa wiersze na ten sam miesiąc.
_PERIOD_MONTH_RE = r"^[0-9]{4}-(0[1-9]|1[0-2])$"

# Zamówienie kosztowe jest albo kompletne, albo go nie ma. Kwota bez reszty
# (albo odwrotnie) wysadza odejmowanie w środku transakcji importu, a kwota
# <= 0 nie jest budżetem.
_COST_COHERENCE = """(
    (
        is_cost_based = FALSE
        AND budget_amount IS NULL
        AND budget_remaining IS NULL
    )
    OR (
        is_cost_based = TRUE
        AND budget_amount IS NOT NULL
        AND budget_amount > 0
        AND budget_remaining IS NOT NULL
    )
)"""

# Zakończenie bez daty jest nieodróżnialne od pomyłki w statusie — a data jest
# jedyną rzeczą, o którą ticket każe zapytać przy zamykaniu.
_CLOSURE_COHERENCE = "(status <> 'completed' OR closure_date IS NOT NULL)"

_GROUP_STATUSES = "('active', 'completed', 'exhausted')"

# Domena poszerzona o pięć zdarzeń cyklu życia. DROP + ADD, nie
# `EXCEPTION WHEN duplicate_object` — tamten wzorzec po pierwszym wykonaniu
# nigdy więcej nie zadziała, więc poszerzenie domeny przeszłoby na prodzie
# bez śladu i bez skutku (lekcja z 0226).
_EVENT_TYPES = (
    "('utworzenie', 'dodanie_konsultanta', 'import_md', 'zamiana_kontraktora', "
    "'edycja_reczna', 'zakonczenie', 'przywrocenie', 'wyczerpanie', "
    "'przedluzenie', 'import_faktur')"
)

# Linia zamówienia KOSZTOWEGO ma obie stawki, ale nie ma budżetu MD — pula
# jest wspólna i mieszka na zamówieniu. Dotychczasowy CHECK z 0227 zabraniał
# `md_rate_revenue` bez budżetu, więc taka linia nie dałaby się zapisać.
#
# Gwarancja, o którą naprawdę chodziło, zostaje w mocy i jest tu wypowiedziana
# wprost: BUDŻET wymaga dodatniej stawki przychodowej (jest dzielnikiem przy
# przeliczaniu kwoty na MD i przy zamianie kontraktora). Odwrotnie już nie —
# stawka bez budżetu nikogo nie dzieli. Drugi człon pilnuje, żeby zero nie
# weszło tylnymi drzwiami przez linię kosztową, która kiedyś dostanie budżet.
_MD_COHERENCE = """(
    (
        (
        md_total IS NULL
        AND md_remaining IS NULL
        AND md_input_mode IS NULL
        AND md_input_value IS NULL
    )
    OR (
        md_total IS NOT NULL
        AND md_remaining IS NOT NULL
        AND md_input_mode IN ('md', 'amount')
        AND md_input_value IS NOT NULL
        AND md_rate_revenue IS NOT NULL
        AND md_rate_revenue > 0
    )
)
    AND (md_rate_revenue IS NULL OR md_rate_revenue > 0)
)"""

_ALERT_TYPES = (
    "('cost_order_exhausted', 'draft_consultant_unassigned', "
    "'md_budget_low', 'missing_revenue_rate')"
)


def upgrade() -> None:
    # ── 1. Cykl życia + zamówienie kosztowe na grupie ───────────────────────
    op.add_column(
        "client_order_groups",
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column(
        "client_order_groups", sa.Column("closure_date", sa.Date(), nullable=True)
    )
    op.add_column(
        "client_order_groups", sa.Column("closure_reason", sa.Text(), nullable=True)
    )
    op.add_column(
        "client_order_groups",
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "client_order_groups",
        sa.Column(
            "closed_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "client_order_groups",
        sa.Column(
            "is_cost_based",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "client_order_groups",
        sa.Column("budget_amount", sa.Numeric(16, 2), nullable=True),
    )
    op.add_column(
        "client_order_groups",
        sa.Column("budget_remaining", sa.Numeric(16, 2), nullable=True),
    )
    op.add_column(
        "client_order_groups",
        sa.Column(
            "budget_manual_adjustment",
            sa.Numeric(16, 2),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "client_order_groups",
        sa.Column(
            "predecessor_group_id",
            sa.Integer(),
            sa.ForeignKey("client_order_groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # NOT VALID: dodanie CHECK-a bez skanu całej tabeli pod ACCESS EXCLUSIVE.
    # Istniejące wiersze spełniają go z definicji (same defaulty).
    op.execute(
        "ALTER TABLE client_order_groups ADD CONSTRAINT "
        "ck_client_order_groups_status "
        f"CHECK (status IN {_GROUP_STATUSES}) NOT VALID"
    )
    op.execute(
        "ALTER TABLE client_order_groups ADD CONSTRAINT "
        f"ck_client_order_groups_cost_coherence CHECK {_COST_COHERENCE} NOT VALID"
    )
    op.execute(
        "ALTER TABLE client_order_groups ADD CONSTRAINT "
        f"ck_client_order_groups_closure CHECK {_CLOSURE_COHERENCE} NOT VALID"
    )
    op.create_index(
        "ix_client_order_groups_status",
        "client_order_groups",
        ["client_id", "status"],
    )

    # ── 1b. Rozluźnienie spójności MD pod linie kosztowe ────────────────────
    op.execute(
        "ALTER TABLE client_orders "
        "DROP CONSTRAINT IF EXISTS ck_client_orders_md_coherence"
    )
    op.execute(
        "ALTER TABLE client_orders ADD CONSTRAINT ck_client_orders_md_coherence "
        f"CHECK {_MD_COHERENCE} NOT VALID"
    )

    # ── 2. Poszerzenie domeny zdarzeń ───────────────────────────────────────
    op.execute(
        "ALTER TABLE client_order_group_events "
        "DROP CONSTRAINT IF EXISTS ck_client_order_group_events_type"
    )
    op.execute(
        "ALTER TABLE client_order_group_events ADD CONSTRAINT "
        f"ck_client_order_group_events_type CHECK (event_type IN {_EVENT_TYPES})"
    )

    # ── 3. Konsumpcja fakturowa ─────────────────────────────────────────────
    op.create_table(
        "client_order_invoice_consumptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "order_id",
            sa.Integer(),
            sa.ForeignKey("client_orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_month", sa.String(length=7), nullable=False),
        sa.Column("invoice_amount", sa.Numeric(16, 2), nullable=False),
        sa.Column(
            "settled_amount", sa.Numeric(16, 2), nullable=False, server_default="0"
        ),
        sa.Column(
            "unsettled_amount", sa.Numeric(16, 2), nullable=False, server_default="0"
        ),
        # SET NULL, nie CASCADE — skasowanie partii importu nie może cofać już
        # zastosowanego rozliczenia. Wpis jest faktem, partia tylko jego
        # pochodzeniem (ta sama reguła co przy MD).
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
            name="ck_invoice_consumptions_source",
        ),
        sa.CheckConstraint(
            f"period_month ~ '{_PERIOD_MONTH_RE}'",
            name="ck_invoice_consumptions_period",
        ),
    )
    op.create_index(
        "ux_invoice_consumptions_order_month",
        "client_order_invoice_consumptions",
        ["order_id", "period_month"],
        unique=True,
    )

    # ── 4. Wiersz importu: „Uwagi" + „Faktura" + wynik dopasowania kosztowego
    op.add_column(
        "md_consumption_import_rows", sa.Column("notes_raw", sa.Text(), nullable=True)
    )
    op.add_column(
        "md_consumption_import_rows",
        sa.Column("order_number_hint", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "md_consumption_import_rows",
        sa.Column("invoice_amount", sa.Numeric(16, 2), nullable=True),
    )
    op.add_column(
        "md_consumption_import_rows",
        sa.Column(
            "matched_group_id",
            sa.Integer(),
            sa.ForeignKey("client_order_groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # OSOBNA kolumna, nie poszerzenie `status`: jeden wiersz bywa jednocześnie
    # MD-dopasowany po nazwisku i kosztowo-niedopasowany po numerze. Wciśnięcie
    # obu prawd w jedno pole zgubiłoby jedną z nich.
    op.add_column(
        "md_consumption_import_rows",
        sa.Column("cost_status", sa.String(length=24), nullable=True),
    )
    op.execute(
        "ALTER TABLE md_consumption_import_rows ADD CONSTRAINT "
        "ck_md_import_rows_cost_status CHECK (cost_status IS NULL OR cost_status IN "
        "('applied', 'unmatched_number', 'unmatched_consultant')) NOT VALID"
    )

    op.add_column(
        "md_consumption_imports",
        sa.Column(
            "rows_cost_applied", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "md_consumption_imports",
        sa.Column(
            "rows_cost_unmatched", sa.Integer(), nullable=False, server_default="0"
        ),
    )

    # ── 5. Powiadomienia Delivery Leada ─────────────────────────────────────
    op.create_table(
        "dl_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("alert_type", sa.String(length=48), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "order_group_id",
            sa.Integer(),
            sa.ForeignKey("client_order_groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "order_id",
            sa.Integer(),
            sa.ForeignKey("client_orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("link", sa.String(length=1000), nullable=True),
        sa.Column("payload", JSONB(), nullable=True),
        # Klucz claimu. Powtórka co 7 dni jest NOWYM wierszem, więc numer
        # tygodnia jest częścią klucza — bez tego `ON CONFLICT DO NOTHING`
        # zdusiłby każdą powtórkę i alert pojawiłby się raz w życiu.
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="new"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "handled_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"alert_type IN {_ALERT_TYPES}", name="ck_dl_alerts_type"),
        sa.CheckConstraint("status IN ('new', 'handled')", name="ck_dl_alerts_status"),
        sa.CheckConstraint(
            "status <> 'handled' OR handled_at IS NOT NULL",
            name="ck_dl_alerts_handled_coherence",
        ),
        sa.UniqueConstraint("dedupe_key", name="uq_dl_alerts_dedupe_key"),
    )
    op.create_index(
        "ix_dl_alerts_open",
        "dl_alerts",
        ["user_id", "created_at"],
        postgresql_where=sa.text("status = 'new'"),
    )
    # Skaner pyta „czy ta para była już kiedykolwiek obsłużona / kiedy padł
    # pierwszy alert" przy KAŻDYM przebiegu — bez tego indeksu to sekwencyjny
    # skan rosnącego logu.
    op.create_index(
        "ix_dl_alerts_rule_scope",
        "dl_alerts",
        ["alert_type", "user_id", "client_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_dl_alerts_rule_scope", table_name="dl_alerts")
    op.drop_index("ix_dl_alerts_open", table_name="dl_alerts")
    op.drop_table("dl_alerts")

    op.drop_column("md_consumption_imports", "rows_cost_unmatched")
    op.drop_column("md_consumption_imports", "rows_cost_applied")

    op.execute(
        "ALTER TABLE md_consumption_import_rows "
        "DROP CONSTRAINT IF EXISTS ck_md_import_rows_cost_status"
    )
    op.drop_column("md_consumption_import_rows", "cost_status")
    op.drop_column("md_consumption_import_rows", "matched_group_id")
    op.drop_column("md_consumption_import_rows", "invoice_amount")
    op.drop_column("md_consumption_import_rows", "order_number_hint")
    op.drop_column("md_consumption_import_rows", "notes_raw")

    op.drop_index(
        "ux_invoice_consumptions_order_month",
        table_name="client_order_invoice_consumptions",
    )
    op.drop_table("client_order_invoice_consumptions")

    op.execute(
        "ALTER TABLE client_order_group_events "
        "DROP CONSTRAINT IF EXISTS ck_client_order_group_events_type"
    )
    op.execute(
        "ALTER TABLE client_order_group_events ADD CONSTRAINT "
        "ck_client_order_group_events_type CHECK (event_type IN "
        "('utworzenie', 'dodanie_konsultanta', 'import_md', "
        "'zamiana_kontraktora', 'edycja_reczna'))"
    )

    # Przywrócenie węższego CHECK-a z 0227. Zadziała tylko wtedy, gdy nie ma
    # już linii kosztowych — i to jest poprawne: one same są tym, co ten
    # constraint zabrania.
    op.execute(
        "ALTER TABLE client_orders "
        "DROP CONSTRAINT IF EXISTS ck_client_orders_md_coherence"
    )
    op.execute(
        "ALTER TABLE client_orders ADD CONSTRAINT ck_client_orders_md_coherence "
        "CHECK ("
        "(md_total IS NULL AND md_remaining IS NULL AND md_input_mode IS NULL "
        "AND md_input_value IS NULL AND md_rate_revenue IS NULL) OR ("
        "md_total IS NOT NULL AND md_remaining IS NOT NULL "
        "AND md_input_mode IN ('md', 'amount') AND md_input_value IS NOT NULL "
        "AND md_rate_revenue IS NOT NULL AND md_rate_revenue > 0)"
        ") NOT VALID"
    )

    op.drop_index("ix_client_order_groups_status", table_name="client_order_groups")
    for name in (
        "ck_client_order_groups_closure",
        "ck_client_order_groups_cost_coherence",
        "ck_client_order_groups_status",
    ):
        op.execute(f"ALTER TABLE client_order_groups DROP CONSTRAINT IF EXISTS {name}")
    for col in (
        "predecessor_group_id",
        "budget_manual_adjustment",
        "budget_remaining",
        "budget_amount",
        "is_cost_based",
        "closed_by_user_id",
        "closed_at",
        "closure_reason",
        "closure_date",
        "status",
    ):
        op.drop_column("client_order_groups", col)
