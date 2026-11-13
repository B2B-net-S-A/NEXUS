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

import json
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
# Kroki startu poddające się przy żywym ruchu: czekanie na zamek, limit czasu
# instrukcji i zakleszczenie z transakcją obsługującą żądanie.
_SKIP_SQLSTATES = frozenset({_LOCK_NOT_AVAILABLE, "57014", "40P01"})
SKIPPED_DDL_FILE_ENV = "STARTUP_DDL_SKIPS_FILE"
DEFAULT_SKIPPED_DDL_FILE = "/tmp/nexus-startup-ddl-skips.jsonl"
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


def _sqlstate(exc: BaseException) -> str | None:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        for candidate in (current, getattr(current, "orig", None)):
            code = getattr(candidate, "sqlstate", None) or getattr(
                candidate, "pgcode", None
            )
            if code:
                return str(code)
        current = current.__cause__ or current.__context__
    return None


def _skipped_ddl_path() -> str:
    return os.environ.get(SKIPPED_DDL_FILE_ENV) or DEFAULT_SKIPPED_DDL_FILE


def record_skipped_ddl(step: str, exc: BaseException) -> None:
    """Zapisz krok DDL pominięty przy starcie przez limit zamka albo czasu.

    Przy rolling update (etap B2) ``entrypoint.sh`` biegnie, gdy stary kontener
    obsługuje ruch, więc ``lock_timeout`` realnie odpuszcza instrukcje. Pominięty
    krok trafia do pliku, z którego ``checks.migrations`` w ``/api/health`` robi
    ``degraded``, a start aplikacji ``logger.error`` (→ Sentry). Inne błędy nie
    są tu liczone: to idempotentna siatka, „już istnieje” jest normalne.
    Do pliku idzie etykieta kroku z kodu i SQLSTATE, nigdy treść błędu.
    Nie rzuca: zapis diagnostyki nie może zatrzymać startu.
    """
    code = _sqlstate(exc)
    if code not in _SKIP_SQLSTATES:
        return
    line = json.dumps({"step": " ".join(step.split())[:200], "sqlstate": code})
    try:
        with open(_skipped_ddl_path(), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError as error:
        print(f"startup ddl skips: zapis nieudany -> {type(error).__name__}")


def read_skipped_ddl() -> list[dict[str, str]]:
    """Kroki pominięte przy ostatnim starcie; brak pliku = żadnych."""
    try:
        with open(_skipped_ddl_path(), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("step"):
            rows.append(
                {"step": str(row["step"]), "sqlstate": str(row.get("sqlstate"))}
            )
    return rows


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
