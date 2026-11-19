"""Koszt zamówienia od dnia zmiany stawki Partnera: SQL migracji ``0741`` i lustra entrypointu.

Jedno źródło instrukcji dla ``alembic/versions/0741_order_cost_steps.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Każda
instrukcja jest idempotentna.

* ``client_order_cost_steps`` — części kosztu zamówienia, gdy stawka Partnera
  zmienia się w trakcie jego okresu (zgłoszenie Artura 18.11.2026: zamówienie
  Nordei 01.07–15.12 z jedną stawką 140 zł/h, a aneks podniósł ją ze 120 na 130
  od 01.09 i na 140 od 01.11). Wiersze są tylko przy co najmniej dwóch różnych
  stawkach w okresie; pierwsza część zaczyna się w dniu startu zamówienia.
  Zamówienie bez wierszy liczy się kolumną ``rate_candidate`` jak dotąd.
  ``source`` = ``contract`` (synchronizacja żywego zamówienia z harmonogramem
  kontraktu) albo ``finance`` (korekta zakończonego zamówienia z listy
  „Do korekty po zmianie stawki”).
* ``client_order_cost_reviews`` — „Zostaw” na tej liście: decyzja Finansów
  dla zakończonego zamówienia przy danym harmonogramie (``signature``). Nowa
  zmiana stawki w tym okresie zmienia podpis i zamówienie wraca na listę.
"""

from __future__ import annotations

STEPS_TABLE = "client_order_cost_steps"
REVIEWS_TABLE = "client_order_cost_reviews"
SOURCES: tuple[str, ...] = ("contract", "finance")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS {STEPS_TABLE} (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES client_orders(id) ON DELETE CASCADE,
    effective_from DATE NOT NULL,
    rate_candidate NUMERIC(16,3) NOT NULL,
    source VARCHAR(16) NOT NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_client_order_cost_steps_rate CHECK (rate_candidate > 0),
    CONSTRAINT ck_client_order_cost_steps_source CHECK (source IN ({_quoted(SOURCES)}))
)""",
    f"""CREATE TABLE IF NOT EXISTS {REVIEWS_TABLE} (
    order_id INTEGER PRIMARY KEY REFERENCES client_orders(id) ON DELETE CASCADE,
    signature VARCHAR(64) NOT NULL,
    decided_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    decided_at TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{STEPS_TABLE}_order_day "
    f"ON {STEPS_TABLE} (order_id, effective_from)",
)

CONSTRAINT_DDL: tuple[str, ...] = ()
DATA_DDL: tuple[str, ...] = ()

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)

TABLES: tuple[str, ...] = (STEPS_TABLE, REVIEWS_TABLE)

DOWNGRADE_DDL: tuple[str, ...] = tuple(
    f"DROP TABLE IF EXISTS {table}" for table in reversed(TABLES)
)
