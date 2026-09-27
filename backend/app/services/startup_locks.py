"""Bounded lock waits for the schema safety nets that run before uvicorn.

`entrypoint.sh` runs under ``set -e`` and re-applies idempotent DDL on every
start. ``ADD COLUMN IF NOT EXISTS`` and friends request ACCESS EXCLUSIVE even
when there is nothing to add, so without a limit the start waits for as long
as anybody holds a conflicting lock — the nightly ``pg_dump`` holds ACCESS
SHARE on every table for the whole dump. And the waiting request is not
harmless: it sits in the lock queue in front of every later reader of that
table, so the container that is still serving traffic stalls with it.
"""

from __future__ import annotations

import os
import re

BOOT_LOCK_TIMEOUT = "10s"
# Runda 10 (R10-N12-2): sufit pojedynczej instrukcji ``alembic upgrade`` przy
# starcie. Hojny, bo migracje danych bywają długie (0143 liczyła się minutami);
# chroni przed wiszeniem, nie przed pracą. ``ALEMBIC_STATEMENT_TIMEOUT`` /
# ``ALEMBIC_LOCK_TIMEOUT`` w env podnoszą go dla migracji, która naprawdę
# potrzebuje więcej.
ALEMBIC_STATEMENT_TIMEOUT = "20min"
_LOCK_NOT_AVAILABLE = "55P03"
_PG_DURATION = re.compile(r"^\d{1,7}\s*(ms|s|min|h|d)?$")


def _duration(env_name: str, default: str) -> str:
    value = (os.environ.get(env_name) or "").strip()
    return value if _PG_DURATION.match(value) else default


def apply_migration_session_limits(connection) -> dict[str, str]:
    """Ustaw ``lock_timeout`` i ``statement_timeout`` na sesji alembica.

    Runda 10 (R10-N12-2): ``alembic upgrade heads`` przy starcie nie miał
    żadnego limitu. Migracja z DDL wdrożona w trakcie nocnego ``pg_dump``
    czekała na ACCESS EXCLUSIVE do końca zrzutu, a stary kontener był już
    zatrzymany — API leżało przez cały zrzut. Z limitem pada szybko (55P03)
    i idzie istniejącą ścieżką „degraded + siatka + ponowienie przy
    następnym starcie”.

    Ustawienia są SESYJNE (``set_config(..., false)``), więc obejmują też
    bloki ``autocommit_block()`` z ``CREATE INDEX CONCURRENTLY``. Transakcję
    otwartą przez ``SELECT`` zatwierdzamy od razu: gdyby została otwarta,
    ``context.begin_transaction()`` alembica uznałby ją za cudzą i nie
    zatwierdziłby migracji.
    """
    from sqlalchemy import text

    limits = {
        "lock_timeout": _duration("ALEMBIC_LOCK_TIMEOUT", BOOT_LOCK_TIMEOUT),
        "statement_timeout": _duration(
            "ALEMBIC_STATEMENT_TIMEOUT", ALEMBIC_STATEMENT_TIMEOUT
        ),
    }
    for name, value in limits.items():
        connection.execute(
            text("SELECT set_config(:name, :value, false)"),
            {"name": name, "value": value},
        )
    connection.commit()
    return limits


def is_lock_timeout(exc: BaseException) -> bool:
    """True for PostgreSQL ``lock_not_available`` (lock_timeout, NOWAIT).

    SQLAlchemy wraps the driver error in ``DBAPIError.orig``; asyncpg's adapter
    exposes ``sqlstate`` there, psycopg ``pgcode``. The chain is walked too, so
    a wrapper that re-raises keeps being recognised.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        for candidate in (current, getattr(current, "orig", None)):
            code = getattr(candidate, "sqlstate", None) or getattr(
                candidate, "pgcode", None
            )
            if code == _LOCK_NOT_AVAILABLE:
                return True
        current = current.__cause__ or current.__context__
    return False
