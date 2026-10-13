"""Jednorazowa naprawa dat dodania kandydatów z Traffita (13.10.2026) — z panelu admina.

„W bazie od” (prośba rekrutera, decyzja Artura 13.10.2026): import z Traffita
stemplował ``candidates.created_at = NOW()``, więc 65 tys. osób miało w bazie
dzień importu (16.04 i 04.05.2026). Prawdziwą datę dodania niesie lista
``/employees/`` (``created_at``, czas Europe/Warsaw bez strefy). Import od 0436
zapisuje ją sam w ``candidates.source_created_at``; ta naprawa domyka historię.

Zasady:
* przegląd listy ``/employees/`` stronami po 100 (sort ``id ASC`` — prefiks
  stron jest stały, więc kursor = numer ostatniej zapisanej strony), ok. 650
  zapytań zamiast 65 tys. zapytań o osobę;
* zmienia WYŁĄCZNIE ``source_created_at`` wierszy ``external_source='traffit'``
  o ``external_id`` = id osoby w Traffit (surowy SQL, bez ``updated_at``);
  ``created_at`` zostaje czasem wstawienia do NEXUSA;
* zapis warunkowy ``source_created_at IS NOT DISTINCT FROM <stara>`` —
  równoległa zmiana wygrywa; ponowny bieg nic nie zmienia;
* przebieg próbny niczego nie zapisuje w kandydatach i nie przesuwa kursora —
  raport (liczby, zakres dat, do 20 przykładów: id kandydata, data przed i po)
  w ``app_settings``; zapis wymaga próby nie starszej niż 7 dni;
* każda strona we własnej transakcji z blokadą doradczą, cały bieg pod blokadą
  syncu Traffita; padnięta strona (albo błąd Traffita) zatrzymuje bieg
  z kursorem PRZED nią;
* raport = liczby i ID; daty sprzed zmiany pod ``repair_details_…`` (żaden
  klucz nie pasuje do publicznego wzorca paragonów ``^\\d{4}_``).
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.traffit.importer import safe_db_error
from app.services.traffit.mappers import _parse_traffit_datetime

logger = logging.getLogger(__name__)

STATE_KEY = "traffit_added_dates_repair_2026_10"
DRY_RUN_KEY = "traffit_added_dates_repair_2026_10_dry_run"
DETAILS_KEY = "repair_details_traffit_added_dates_2026_10"
LOCK_KEY = "traffit_added_dates_repair_2026_10"
PAGE_SIZE = 100
SAMPLE_SIZE = 20
DRY_RUN_MAX_AGE = timedelta(days=7)
# Data z Traffita późniejsza niż wstawienie do NEXUSA o więcej niż tyle — do
# kontroli sensu (zdarza się tylko przy adopcji wiersza założonego w NEXUSIE).
LATER_THAN_CREATED_SLACK = timedelta(days=1)

COUNT_KEYS = (
    "employees",
    "no_date",
    "not_in_nexus",
    "unchanged",
    "set",
    "changed",
    "later_than_created",
)

_ROWS_SQL = """
SELECT id, external_id, created_at, source_created_at
FROM candidates
WHERE external_source = 'traffit'
  AND external_id = ANY(CAST(:ids AS text[]))
"""

_UPDATE_SQL = """
UPDATE candidates
SET source_created_at = :new
WHERE id = :id
  AND external_source = 'traffit'
  AND source_created_at IS NOT DISTINCT FROM :old
"""

_TRAFFIT_ROWS_SQL = """
SELECT count(*) AS total,
       count(*) FILTER (WHERE source_created_at IS NULL) AS without_date
FROM candidates
WHERE external_source = 'traffit'
"""


@dataclass(frozen=True)
class CandidateRow:
    candidate_id: int
    external_id: str
    created_at: Optional[datetime]
    source_created_at: Optional[datetime]


@dataclass(frozen=True)
class DateChange:
    candidate_id: int
    old: Optional[datetime]
    new: datetime


def employee_dates(items: list[dict[str, Any]]) -> dict[str, Optional[datetime]]:
    """``{id osoby: data dodania}`` ze strony listy ``/employees/``."""
    dates: dict[str, Optional[datetime]] = {}
    for item in items:
        if not isinstance(item, dict) or item.get("id") is None:
            continue
        dates[str(item["id"])] = _parse_traffit_datetime(item.get("created_at"))
    return dates


def plan_page(
    dates: dict[str, Optional[datetime]], rows: list[CandidateRow]
) -> tuple[list[DateChange], dict[str, int]]:
    """Zmiany dat dla jednej strony + liczniki (czysta funkcja)."""
    counts: dict[str, int] = dict.fromkeys(COUNT_KEYS, 0)
    by_external = {row.external_id: row for row in rows}
    changes: list[DateChange] = []
    for emp, when in dates.items():
        counts["employees"] += 1
        if when is None:
            counts["no_date"] += 1
            continue
        row = by_external.get(emp)
        if row is None:
            counts["not_in_nexus"] += 1
            continue
        if (
            row.created_at is not None
            and when > row.created_at + LATER_THAN_CREATED_SLACK
        ):
            counts["later_than_created"] += 1
        if row.source_created_at == when:
            counts["unchanged"] += 1
            continue
        counts["set" if row.source_created_at is None else "changed"] += 1
        changes.append(DateChange(row.candidate_id, row.source_created_at, when))
    return changes, counts


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _sample(change: DateChange) -> dict[str, Any]:
    return {
        "candidate_id": change.candidate_id,
        "before": _iso(change.old),
        "after": _iso(change.new),
    }


async def _read_setting(db: AsyncSession, key: str) -> Optional[dict[str, Any]]:
    row = await db.execute(
        text("SELECT value FROM app_settings WHERE key = :k"), {"k": key}
    )
    value = row.scalar_one_or_none()
    return value if isinstance(value, dict) else None


async def _write_setting(db: AsyncSession, key: str, value: dict[str, Any]) -> None:
    await db.execute(
        text(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (:k, CAST(:v AS jsonb), now())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
            """
        ),
        {"k": key, "v": json.dumps(value, default=str)},
    )


async def _append_details(db: AsyncSession, entries: list[list[Any]]) -> None:
    """Dopisz ``[id kandydata, data sprzed zmiany]`` do klucza szczegółów."""
    await db.execute(
        text(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (:key, jsonb_build_object('before', CAST(:value AS jsonb)), now())
            ON CONFLICT (key) DO UPDATE SET
                value = jsonb_build_object(
                    'before',
                    COALESCE(app_settings.value -> 'before', '[]'::jsonb)
                    || CAST(:value AS jsonb)
                ),
                updated_at = now()
            """
        ),
        {"key": DETAILS_KEY, "value": json.dumps(entries)},
    )


async def _traffit_rows(db: AsyncSession) -> dict[str, int]:
    row = (await db.execute(text(_TRAFFIT_ROWS_SQL))).one()
    return {"total": int(row.total), "without_date": int(row.without_date)}


def _widen(bounds: dict[str, Optional[datetime]], when: datetime) -> None:
    if bounds["min"] is None or when < bounds["min"]:
        bounds["min"] = when
    if bounds["max"] is None or when > bounds["max"]:
        bounds["max"] = when


async def process(
    db: AsyncSession,
    traffit: Any,
    *,
    dry_run: bool,
    pages: int,
) -> dict[str, Any]:
    """Jeden bieg: najwyżej ``pages`` stron od kursora. Zwraca raport."""
    pages = max(1, int(pages))
    state = await _read_setting(db, STATE_KEY) or {}
    after_page = int(state.get("after_page") or 0)
    await db.rollback()

    counts: Counter[str] = Counter(dict.fromkeys(COUNT_KEYS, 0))
    bounds: dict[str, Optional[datetime]] = {"min": None, "max": None}
    samples: list[dict[str, Any]] = []
    skipped_concurrent = 0
    pages_done = 0
    last_page = after_page
    stopped = False
    budget_hit = False
    error: Optional[str] = None

    try:
        async for page, items in traffit.get_pages(
            "/employees/", page_size=PAGE_SIZE, start_page=after_page + 1
        ):
            if pages_done >= pages:
                budget_hit = True
                break
            dates = employee_dates(items)
            result = await db.execute(text(_ROWS_SQL), {"ids": list(dates)})
            rows = [
                CandidateRow(
                    int(r.id), str(r.external_id), r.created_at, r.source_created_at
                )
                for r in result.all()
            ]
            # Połączenie wraca do puli na czas zapytania o następną stronę.
            await db.rollback()

            changes, page_counts = plan_page(dates, rows)
            written: list[DateChange] = changes
            if not dry_run:
                try:
                    await db.execute(
                        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
                        {"k": LOCK_KEY},
                    )
                    written = []
                    for change in changes:
                        res = await db.execute(
                            text(_UPDATE_SQL),
                            {
                                "id": change.candidate_id,
                                "old": change.old,
                                "new": change.new,
                            },
                        )
                        if res.rowcount:
                            written.append(change)
                    if written:
                        await _append_details(
                            db, [[c.candidate_id, _iso(c.old)] for c in written]
                        )
                    await _write_setting(
                        db,
                        STATE_KEY,
                        {
                            **state,
                            "after_page": page,
                            "finished": False,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    await db.commit()
                except Exception as exc:  # noqa: BLE001
                    await db.rollback()
                    error = safe_db_error(exc)
                    logger.error(
                        "Traffit added dates repair: page %s failed: %s", page, error
                    )
                    stopped = True
                    break
                lost = len(changes) - len(written)
                skipped_concurrent += lost
                if lost:
                    # „set”/„changed” w zapisie = faktycznie zapisane.
                    for change in changes:
                        if change not in written:
                            page_counts["set" if change.old is None else "changed"] -= 1

            counts.update(page_counts)
            for change in written:
                _widen(bounds, change.new)
                if len(samples) < SAMPLE_SIZE:
                    samples.append(_sample(change))
            pages_done += 1
            last_page = page
    except Exception as exc:  # noqa: BLE001
        # Błąd Traffita (5xx po ponowieniach, zła odpowiedź) — kursor zostaje
        # za ostatnią zapisaną stroną, ponowny bieg zacznie od następnej.
        await db.rollback()
        error = type(exc).__name__
        logger.error("Traffit added dates repair: Traffit list failed: %s", error)
        stopped = True

    pass_complete = not stopped and not budget_hit
    traffit_rows = await _traffit_rows(db) if pass_complete else None
    await db.rollback()
    return {
        "dry_run": dry_run,
        "pages_budget": pages,
        "after_page_start": after_page,
        "after_page_end": last_page,
        "pages": pages_done,
        "pass_complete": pass_complete,
        "stopped_on_error": stopped,
        "error": error,
        "counts": {k: int(counts[k]) for k in COUNT_KEYS},
        "skipped_concurrent": skipped_concurrent,
        "dates": {"min": _iso(bounds["min"]), "max": _iso(bounds["max"])},
        # Po pełnym przebiegu: ile naszych kartotek z Traffita nadal nie ma daty
        # (w próbie — przed zapisem, czyli wszystkie bez daty).
        "traffit_rows": traffit_rows,
        "samples": samples,
    }


async def finish_run(
    db: AsyncSession, report: dict[str, Any], *, started: datetime
) -> None:
    """Zapisz raport: próba → ``DRY_RUN_KEY``, zapis → stan z sumami i kursorem."""
    report = {
        **report,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    if report["dry_run"]:
        await _write_setting(db, DRY_RUN_KEY, report)
        await db.commit()
        return
    state = await _read_setting(db, STATE_KEY) or {}
    totals = dict(state.get("totals") or {})
    for k, v in report["counts"].items():
        totals[k] = int(totals.get(k) or 0) + int(v)
    passes = int(state.get("passes_completed") or 0)
    if report["pass_complete"]:
        # Koniec przejścia: kursor od zera — kolejny bieg obejrzy całość, ale
        # zapis warunkowy i porównanie z celem nic już nie zmienią.
        after_page, passes = 0, passes + 1
    else:
        after_page = int(report["after_page_end"])
    new_state = {
        "after_page": after_page,
        "finished": bool(report["pass_complete"]),
        "passes_completed": passes,
        "totals": totals,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "last_run": report,
    }
    await _write_setting(db, STATE_KEY, new_state)
    await db.commit()


# ── Przebieg w tle ───────────────────────────────────────────────────────────

_running: dict[str, bool] = {"added_dates": False}


def is_running() -> bool:
    return _running["added_dates"]


async def fresh_dry_run_exists(db: AsyncSession) -> bool:
    report = await _read_setting(db, DRY_RUN_KEY)
    if not report or not report.get("finished_at"):
        return False
    try:
        finished = datetime.fromisoformat(str(report["finished_at"]))
    except ValueError:
        return False
    return datetime.now(timezone.utc) - finished <= DRY_RUN_MAX_AGE


async def run_added_dates_repair(*, dry_run_mode: bool, pages: int) -> None:
    """Bieg w tle (spawn z endpointu) pod blokadą syncu Traffita."""
    from app.core.database import AsyncSessionLocal
    from app.services.traffit.client import TraffitClient, TraffitConfig
    from app.tasks.traffit_sync import traffit_exclusive_lock

    if _running["added_dates"]:
        return
    _running["added_dates"] = True
    started = datetime.now(timezone.utc)
    try:
        lock = traffit_exclusive_lock()
        if lock.locked():
            logger.warning("Traffit added dates repair skipped: sync running")
            return
        async with lock:
            config = TraffitConfig.from_env()
            async with TraffitClient(config) as traffit:
                async with AsyncSessionLocal() as db:
                    report = await process(
                        db, traffit, dry_run=dry_run_mode, pages=pages
                    )
                    await finish_run(db, report, started=started)
                    logger.info(
                        "Traffit added dates repair done (dry_run=%s, pages=%s): %s",
                        dry_run_mode,
                        report["pages"],
                        json.dumps(report["counts"]),
                    )
    finally:
        _running["added_dates"] = False


async def read_status(db: AsyncSession) -> dict[str, Any]:
    return {
        "running": is_running(),
        "dry_run": await _read_setting(db, DRY_RUN_KEY),
        "state": await _read_setting(db, STATE_KEY),
    }


def spawn_running_guard() -> Optional[str]:
    """Powód odmowy startu (409) albo ``None``."""
    from app.services import (
        traffit_file_dates_repair,
        traffit_notes_repair,
        traffit_transfer,
    )
    from app.tasks.traffit_sync import sync_is_running

    if sync_is_running():
        return "Trwa synchronizacja z Traffitem — spróbuj po jej zakończeniu."
    if traffit_notes_repair.is_running() or traffit_file_dates_repair.is_running():
        return "Trwa naprawa danych z Traffita — spróbuj po jej zakończeniu."
    if traffit_transfer.is_running():
        return "Trwa przeniesienie rekrutacji z Traffita — spróbuj po jego zakończeniu."
    if is_running():
        return "Naprawa dat dodania z Traffita już trwa."
    return None


__all__ = [
    "DETAILS_KEY",
    "DRY_RUN_KEY",
    "STATE_KEY",
    "CandidateRow",
    "DateChange",
    "employee_dates",
    "finish_run",
    "fresh_dry_run_exists",
    "plan_page",
    "process",
    "read_status",
    "run_added_dates_repair",
    "spawn_running_guard",
]
