"""Porównanie ORM z żywą bazą przez alembicowe ``compare_metadata``.

Etap 1 pozycji B3 z audytu 07.11.2026: lustro DDL w ``entrypoint.sh`` można zamrozić
dopiero, gdy wiadomo, czym schemat produkcji różni się od modeli. Wynik jest
informacją w ``/api/health/deep`` i nie zmienia jej statusu.

Pełne odbicie schematu trwa kilkanaście sekund, a sonda jest bez logowania, więc:
osobny wątek i własne połączenie (pętla zdarzeń obsługuje w tym czasie żądania),
najwyżej jeden bieg naraz, wynik trzymany ``_TTL_SECONDS``. Pierwsze pytanie po
starcie dostaje ``pending``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from typing import Any

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.database import Base
from app.core.tasks import spawn

logger = logging.getLogger(__name__)

_TTL_SECONDS = 3600
_FAILED_TTL_SECONDS = 300
_SAMPLE_LIMIT = 50
# Tabele spoza modeli z założenia: bookmark alembica.
_IGNORED_TABLES = frozenset({"alembic_version"})
# Brak po stronie bazy psuje zapytania ORM; reszta to dług do przeglądu.
BREAKING_KINDS = frozenset({"add_table", "add_column"})

_result: dict[str, Any] | None = None
_expires_at = 0.0
_running: asyncio.Task[None] | None = None


def _include_object(_obj: Any, name: str | None, type_: str, *_rest: Any) -> bool:
    return not (type_ == "table" and name in _IGNORED_TABLES)


def _describe(diff: Any) -> dict[str, str]:
    """Jeden wiersz raportu: same identyfikatory schematu, bez danych."""
    if isinstance(diff, list):  # modify_* przychodzi jako lista krotek
        diff = diff[0]
    kind = str(diff[0])
    if kind in {"add_table", "remove_table"}:
        return {"kind": kind, "object": diff[1].name}
    if kind in {"add_column", "remove_column"}:
        return {"kind": kind, "object": f"{diff[2]}.{diff[3].name}"}
    if kind.startswith("modify_"):
        return {"kind": kind, "object": f"{diff[2]}.{diff[3]}"}
    if kind in {"add_index", "remove_index"}:
        return {"kind": kind, "object": f"{diff[1].table.name}.{diff[1].name}"}
    if kind in {"add_constraint", "remove_constraint", "add_fk", "remove_fk"}:
        constraint = diff[1]
        # Klucz obcy i unikat z modelu bywają bez nazwy: wtedy po kolumnach.
        name = constraint.name or ",".join(c.name for c in constraint.columns)
        return {"kind": kind, "object": f"{constraint.table.name}.{name}"}
    return {"kind": kind, "object": ""}


def summarize(diffs: list[Any]) -> dict[str, Any]:
    rows = sorted(
        (_describe(diff) for diff in diffs), key=lambda r: (r["kind"], r["object"])
    )
    counts = Counter(row["kind"] for row in rows)
    breaking = [row for row in rows if row["kind"] in BREAKING_KINDS]
    return {
        "status": "breaking" if breaking else ("drift" if rows else "clean"),
        "total": len(rows),
        "counts": dict(sorted(counts.items())),
        # Najpierw to, co psuje zapytania: lista bywa dłuższa niż próbka.
        "sample": (breaking + [r for r in rows if r not in breaking])[:_SAMPLE_LIMIT],
    }


def _compare_sync() -> dict[str, Any]:
    started = time.monotonic()
    url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(
                conn,
                opts={
                    "compare_type": True,
                    "include_object": _include_object,
                },
            )
            report = summarize(compare_metadata(context, Base.metadata))
    finally:
        engine.dispose()
    report["seconds"] = round(time.monotonic() - started, 1)
    return report


async def _refresh() -> None:
    global _result, _expires_at
    try:
        _result = await asyncio.to_thread(_compare_sync)
        _expires_at = time.monotonic() + _TTL_SECONDS
    except Exception as exc:  # noqa: BLE001 — sonda nie może wywrócić health/deep
        logger.warning("schema_compare: %r", exc)
        _result = {"status": "unavailable", "error": type(exc).__name__}
        _expires_at = time.monotonic() + _FAILED_TTL_SECONDS


def schema_compare_report() -> dict[str, Any]:
    """Ostatni wynik; przeterminowany odświeża się w tle, ``pending`` przed pierwszym."""
    global _running
    if time.monotonic() >= _expires_at and (_running is None or _running.done()):
        _running = spawn(_refresh(), "schema_compare")
    return _result if _result is not None else {"status": "pending"}
