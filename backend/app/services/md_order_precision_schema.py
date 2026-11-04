"""Stawki linii MD z trzema miejscami i podział zejść wspólnej puli — SQL
migracji 0419 i lustra w ``entrypoint.sh`` (alembic na prodzie bywa
osierocony, więc entrypoint importuje ten moduł).

Dwa tickety z 10.2026:

* ``client_orders.md_rate_cost`` / ``md_rate_revenue`` NUMERIC(12,2) →
  NUMERIC(12,3). Stawki z zamówień klientów bywają trzymiejscowe (Alior
  164.375 PLN/h, 36.375 PLN/h po przeliczeniu z MD), a druga kolumna tej samej
  linii (``rate_client``) od 0149 ma trzy miejsca — linia gubiła trzecie
  miejsce dopiero przy zapisie stawki MD.
* ``client_order_group_md_consumptions.breakdown`` JSONB — podział miesięcznego
  zejścia wspólnej puli na konsultantów (``[{"order_id": 1, "md": "4.5"}]``).
  ``md_reported`` dalej jest sumą i to ona liczy pulę; ``NULL`` = zapis bez
  podziału (import albo stara ręczna suma).

Oba bloki są warunkowe: ALTER tylko przy różnicy typu, więc kolejne starty nie
biorą zamka tabeli, a świeża baza (tabele jeszcze nie istnieją) nic nie robi.
"""

from __future__ import annotations

MD_RATE_SCALE_DDL = """DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT c.column_name
        FROM information_schema.columns c
        WHERE c.table_schema = current_schema()
          AND c.table_name = 'client_orders'
          AND c.column_name IN ('md_rate_cost', 'md_rate_revenue')
          AND (c.data_type <> 'numeric'
               OR c.numeric_precision IS DISTINCT FROM 12
               OR c.numeric_scale IS DISTINCT FROM 3)
    LOOP
        EXECUTE format(
            'ALTER TABLE client_orders ALTER COLUMN %I TYPE NUMERIC(12, 3) USING %I::numeric(12, 3)',
            r.column_name, r.column_name
        );
    END LOOP;
END $$"""

CONSUMPTION_BREAKDOWN_DDL = """DO $$
BEGIN
    IF to_regclass('client_order_group_md_consumptions') IS NOT NULL THEN
        ALTER TABLE client_order_group_md_consumptions
            ADD COLUMN IF NOT EXISTS breakdown JSONB NULL;
    END IF;
END $$"""

ALL_DDL = (MD_RATE_SCALE_DDL, CONSUMPTION_BREAKDOWN_DDL)
