"""0410: siatka dla dziewięciu uprawnień przy osieroconym bookmarku Alembica.

Sprawdza, że oba CHECK-i akcji znają nowe uprawnienia i że każda rola ma
komplet wierszy; gdy czegoś brakuje, wykonuje te same instrukcje co migracja
(``permission_schema.apply_statements``). Zwykły restart niczego nie zmienia —
zasiew ma ``ON CONFLICT DO NOTHING``, a rewizja polityki rośnie tylko przy
faktycznej naprawie.

MIĘKKI wyłącznie przy timeoucie zamka (jak ``signature_policy_bootstrap``):
bez naprawy aplikacja działa, bo resolver liczy rolę bez wierszy funkcją
zasiewu (``action_permissions.base_action_policy_from_rows``), a następny
start ponawia. Każdy inny błąd zatrzymuje start.
"""

import asyncio

from sqlalchemy import text

from app.services.permission_schema import READY_SQL, apply_statements
from app.services.signature_policy_bootstrap import POLICY_LOCK
from app.services.startup_locks import BOOT_LOCK_TIMEOUT, is_lock_timeout


async def ensure_named_permissions(connection) -> None:
    for statement in apply_statements():
        await connection.execute(text(statement))


async def main(engine=None) -> None:
    """Verify (and if needed repair) the schema and seed; soft on a lock timeout."""
    owns_engine = engine is None
    if engine is None:
        from app.core.database import engine as app_engine

        engine = app_engine
    try:
        try:
            async with engine.begin() as connection:
                # Before the advisory lock: the wait for it is bounded too.
                await connection.execute(
                    text(f"SET LOCAL lock_timeout = '{BOOT_LOCK_TIMEOUT}'")
                )
                # Ten sam zamek co polityka podpisu: obie naprawy zmieniają
                # CHECK tych samych tabel i nie mogą iść równolegle.
                await connection.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"), {"key": POLICY_LOCK}
                )
                await connection.execute(
                    text("SELECT id FROM rbac_policy_state WHERE id = 1 FOR UPDATE")
                )
                ready = await connection.scalar(text(READY_SQL))
                if not ready:
                    await ensure_named_permissions(connection)
        except Exception as exc:
            if not is_lock_timeout(exc):
                raise
            print(
                "Named permissions skipped after a lock timeout "
                f"(the next start retries): {type(exc).__name__}"
            )
            return
        print("Named permissions verified")
    finally:
        if owns_engine:
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
