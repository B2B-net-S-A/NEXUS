"""Idempotent technical schema, shared by Alembic and production safety net.

Audyt 22.09 r2 (DATA-02): `entrypoint.sh` uruchamia ten moduł przy KAŻDYM
starcie pod `set -e`. `ALTER TABLE notifications ADD COLUMN IF NOT EXISTS`
żąda ACCESS EXCLUSIVE nawet wtedy, gdy nie ma czego dodać, a połączenie
z `mail_circuit._engine()` ma `lock_timeout = 1s` — deploy w trakcie nocnego
`pg_dump` (ACCESS SHARE na każdej tabeli) kończył się błędem i pętlą
restartów (odtworzone). Teraz: kompletny schemat = ZERO DDL (same odczyty
katalogu); niekompletny = DDL z `BOOT_LOCK_TIMEOUT`, a timeout zamka jest
fatalny wyłącznie wtedy, gdy schemat nadal jest niekompletny.

Krotka `DDL` zostaje bez zmian — importuje ją migracja 0332.
"""

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.services.startup_locks import BOOT_LOCK_TIMEOUT, is_lock_timeout

DDL = (
    "CREATE TABLE IF NOT EXISTS mail_delivery_state (scope VARCHAR(64) PRIMARY KEY, state JSONB NOT NULL DEFAULT '{}'::jsonb)",
    "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS email_next_attempt_at TIMESTAMPTZ",
    "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS email_delivery_uncertain BOOLEAN NOT NULL DEFAULT false",
    "CREATE INDEX IF NOT EXISTS ix_notifications_mail_retry ON notifications (created_at) WHERE email_sent_at IS NULL AND (email_delivery_uncertain OR email_next_attempt_at IS NOT NULL)",
)

# Lustro `DDL` — same odczyty katalogu, żaden nie czeka za zamkiem tabeli.
READY_SQL = """
SELECT
    (
        SELECT count(*)
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'notifications'
          AND column_name IN ('email_next_attempt_at', 'email_delivery_uncertain')
    ) = 2
    AND to_regclass('mail_delivery_state') IS NOT NULL
    AND to_regclass('ix_notifications_mail_retry') IS NOT NULL
"""


def main(engine=None) -> str:
    """Zwraca `"complete"` | `"repaired"` | `"skipped_lock_timeout"`."""
    owns_engine = engine is None
    if engine is None:
        from app.services.m365.mail_circuit import _engine

        engine = _engine()
    try:
        with engine.connect() as connection:
            if connection.execute(text(READY_SQL)).scalar():
                print("Mail delivery schema already complete; no DDL")
                return "complete"
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(f"SET LOCAL lock_timeout = '{BOOT_LOCK_TIMEOUT}'")
                )
                # `_engine()` ma statement_timeout 2 s — DDL czekający na
                # zamek do BOOT_LOCK_TIMEOUT nie może paść wcześniej na nim.
                connection.execute(text("SET LOCAL statement_timeout = '60s'"))
                for statement in DDL:
                    connection.execute(text(statement))
        except DBAPIError as exc:
            if not is_lock_timeout(exc):
                raise
            with engine.connect() as connection:
                ready = connection.execute(text(READY_SQL)).scalar()
            if not ready:
                raise
            print(
                "Mail delivery schema already complete; repair skipped after a "
                "lock timeout (the next start retries)"
            )
            return "skipped_lock_timeout"
        print("Mail delivery schema repaired")
        return "repaired"
    finally:
        if owns_engine:
            engine.dispose()


if __name__ == "__main__":
    main()
