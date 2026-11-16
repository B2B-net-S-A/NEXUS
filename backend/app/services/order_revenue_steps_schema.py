"""Kroki stawki przychodowej linii zamówienia: SQL migracji ``0722`` i lustra entrypointu.

Jedno źródło instrukcji dla ``alembic/versions/0722_order_revenue_steps.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Każda
instrukcja jest idempotentna.

* ``client_order_revenue_steps`` — stawka przychodowa zamówienia od dnia
  (aneks stawki klienta w kontrakcie, ticket Finansów 16.11.2026). Stawka
  sprzed pierwszego kroku to kolumny zamówienia (``rate_client``,
  ``md_rate_revenue``), więc zamówienie bez kroków liczy się jak dotąd.
  ``rate_client`` jest w jednostce i walucie zamówienia, ``md_rate_revenue``
  w PLN/MD (tylko gdy zamówienie ma stawkę MD).

``DATA_DDL`` jednorazowo przenosi aneksy dodane przed wdrożeniem (stawka
klienta od 01.11.2026, dodane do 20.11.2026), w tym aneks, od którego zaczął
się ticket. Okno dat jest zamknięte, więc przy kolejnych startach instrukcja
nic nie robi; aneksy po wdrożeniu zapisuje kod
(``services/order_revenue_steps.apply_annex_client_rate``) z tą samą regułą:
kontrakt godzinowy → zamówienie w MD = stawka × 8 zaokrąglona do grosza,
zamówienie godzinowe = ta sama stawka.
"""

from __future__ import annotations

TABLE = "client_order_revenue_steps"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS {TABLE} (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES client_orders(id) ON DELETE CASCADE,
    effective_from DATE NOT NULL,
    rate_client NUMERIC(16,3) NOT NULL,
    md_rate_revenue NUMERIC(16,3) NULL,
    contract_amendment_id INTEGER NULL
        REFERENCES contract_amendments(id) ON DELETE SET NULL,
    note TEXT NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_client_order_revenue_steps_rate CHECK (rate_client > 0),
    CONSTRAINT ck_client_order_revenue_steps_md
        CHECK (md_rate_revenue IS NULL OR md_rate_revenue > 0)
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{TABLE}_order_day "
    f"ON {TABLE} (order_id, effective_from)",
)

CONSTRAINT_DDL: tuple[str, ...] = ()

# Aneksy sprzed wdrożenia (patrz docstring). ``ON CONFLICT DO NOTHING`` —
# krok zapisany już przez kod wygrywa.
_RATE = "(a.new_values->>'rate_client')::numeric"
DATA_DDL: tuple[str, ...] = (
    f"""INSERT INTO {TABLE}
    (order_id, effective_from, rate_client, md_rate_revenue,
     contract_amendment_id, note, created_by)
SELECT o.id, a.effective_date,
       CASE WHEN o.rate_unit = 'daily' THEN round({_RATE} * 8, 2)
            ELSE round({_RATE}, 3) END,
       CASE WHEN o.md_rate_revenue IS NULL THEN NULL
            ELSE round({_RATE} * 8, 2) END,
       a.id, 'Aneks w kontrakcie (przeniesiony przy wdrożeniu)', a.created_by
FROM contract_amendments a
JOIN contracts c ON c.id = a.contract_id
JOIN client_orders o ON o.contract_id = c.id AND o.client_id = c.client_id
WHERE a.amendment_type = 'rate_change'
  AND a.new_values ? 'rate_client'
  AND {_RATE} > 0
  AND a.effective_date >= DATE '2026-11-01'
  AND a.created_at < TIMESTAMPTZ '2026-11-21 00:00:00+01'
  AND c.rate_unit = 'hourly'
  AND o.rate_unit IN ('daily', 'hourly')
  AND upper(coalesce(o.rate_client_currency, o.currency, 'PLN'))
      = upper(coalesce(c.rate_client_currency, c.currency, 'PLN'))
  AND o.status <> 'cancelled'
  AND o.start_date IS NOT NULL AND o.start_date < a.effective_date
  AND (o.end_date IS NULL OR o.end_date >= a.effective_date)
ON CONFLICT (order_id, effective_from) DO NOTHING""",
)

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)

TABLES: tuple[str, ...] = (TABLE,)

DOWNGRADE_DDL: tuple[str, ...] = tuple(
    f"DROP TABLE IF EXISTS {table}" for table in TABLES
)
