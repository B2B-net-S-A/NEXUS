"""Stawki kontraktów z 6 miejscami po przecinku (ticket: stawki w Kontraktach w zł/h).

Stawki w module Kontrakty są godzinowe: stawka dzienna (MD) wchodzi do
kontraktu jako MD ÷ 8. Taki wynik ma do 5 miejsc po przecinku
(1001,55 zł/MD = 125,19375 zł/h), a dotychczasowe NUMERIC(12,3) i NUMERIC(12,2)
przycinałyby kwotę — po powrocie do MD (koszt przekazywany do zamówienia)
wyszłaby inna liczba niż ta, którą podpisano.

Poszerzenie do NUMERIC(16,6) — tej samej precyzji co budżety MD zamówień.
Tylko zwiększa zakres i skalę, więc żadna istniejąca wartość się nie zmienia.
Przeliczenie DANYCH (kontrakty w MD → zł/h) robi jednorazowa korekta
w ``entrypoint.sh`` (``app/services/contract_hourly_rate_repair.py``), bo
potrzebuje logiki ORM i paragonu; ta migracja jest wyłącznie schematem.
Lustro DDL: ``entrypoint.sh`` (prod alembic bywa osierocony).
"""

from alembic import op

revision = "0309_contract_hourly_rates"
down_revision = "0307_client_deletion_event_history"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("contracts", "rate_candidate", "NUMERIC(12, 3)"),
    ("contracts", "rate_client", "NUMERIC(12, 3)"),
    ("contracts", "margin", "NUMERIC(12, 3)"),
    ("contracts", "framework_rate", "NUMERIC(12, 2)"),
    ("contracts", "target_rate_min", "NUMERIC(12, 2)"),
    ("contracts", "target_rate_max", "NUMERIC(12, 2)"),
    ("contract_candidate_rates", "rate", "NUMERIC(12, 3)"),
    ("contract_client_rates", "rate", "NUMERIC(12, 3)"),
    ("contract_framework_rates", "rate", "NUMERIC(12, 2)"),
)


# ``margin`` jest w ``UPDATE OF`` triggera walut (0248): Postgres odmawia zmiany
# typu kolumny, od której zależy trigger. Zdejmujemy go i zakładamy ponownie
# w tej samej transakcji migracji.
_DROP_TRIGGER_SQL = (
    "DROP TRIGGER IF EXISTS trg_contract_rate_currencies_legacy_sync ON contracts"
)
_CREATE_TRIGGER_SQL = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_proc WHERE proname = 'sync_contract_rate_currencies_from_legacy'
    ) AND NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_contract_rate_currencies_legacy_sync'
          AND tgrelid = 'contracts'::regclass
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER trg_contract_rate_currencies_legacy_sync
        BEFORE INSERT OR UPDATE OF
            margin, currency, rate_client_currency, rate_candidate_currency
        ON contracts
        FOR EACH ROW
        EXECUTE FUNCTION sync_contract_rate_currencies_from_legacy();
    END IF;
END
$$
"""


def _retype(target: str, using: str) -> None:
    op.execute(_DROP_TRIGGER_SQL)
    for table, column, previous in _COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE "
            f"{target or previous} USING {using.format(column=column, previous=previous)}"
        )
    op.execute(_CREATE_TRIGGER_SQL)


def upgrade():
    _retype("NUMERIC(16, 6)", "{column}::numeric(16, 6)")


def downgrade():
    # Stratne: wartości z więcej niż 3 (2) miejscami po przecinku są zaokrąglane.
    _retype("", "{column}::{previous}")
