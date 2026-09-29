"""Jednorazowa naprawa dat wgrania plików z Traffita (29.09.2026) — z panelu admina.

Dokumenty z Traffita pokazywały „dodano 05.05.2026” — dzień importu: lista
``/employees/{id}/files`` nie niesie daty wgrania, więc
``candidate_documents.uploaded_at`` zostawał pusty i UI brało ``created_at``.
Prawdziwą datę ma detal osoby: ``/employees/{id}`` → ``files: [{filename,
file_uploaded}]`` (bez id pliku — dopasowanie po nazwie, jak w imporcie).
Czas bez strefy = Europe/Warsaw (``_parse_traffit_datetime``).

Decyzja właściciela (29.09.2026): ``uploaded_at`` = data z Traffita, także dla
dokumentów już zaimportowanych. Import od teraz robi to sam
(``TraffitImporter._employee_file_upload_dates``), a ta naprawa domyka
historię.

Zasady:
* bierze wyłącznie dokumenty ``external_source='traffit'`` z ``external_id``
  w formacie importu ``<osoba>-<plik>``, bez daty albo z datą nie starszą niż
  dzień przed zapisem wiersza (czyli dniem importu); osobę z Traffita wyznacza
  prefiks ``external_id`` — dokument scalonego kandydata też trafia do swojej
  osoby w Traffit;
* zmienia WYŁĄCZNIE ``uploaded_at`` (surowy SQL, bez ``updated_at``) — nie
  dotyka pliku, nie usuwa niczego (CV nie kasujemy nigdy);
* zapis warunkowy ``uploaded_at IS NOT DISTINCT FROM <stara>`` — równoległa
  zmiana wygrywa; ponowny bieg nic nie zmienia (porównanie z wartością
  docelową);
* nazwa bez jednej daty w Traffit (brak, dwie różne daty dla tej samej nazwy)
  i plik, którego Traffit nie zna po nazwie, zostają nietknięte — liczniki
  ``no_date``/``no_match``;
* przebieg próbny niczego nie zapisuje w dokumentach i nie przesuwa kursora —
  raport (liczby + do 20 przykładów: id dokumentu, data przed i po) w
  ``app_settings``;
* zapis budżetowany (``limit`` osób Traffita na bieg) i wznawialny kursorem
  ``after_emp`` w stanie, paczki po 50 osób, każda we własnej transakcji
  z blokadą doradczą, a cały bieg pod blokadą syncu Traffita (jak naprawa
  notatek); padnięta paczka zatrzymuje bieg z kursorem PRZED nią;
* paragon = liczby i ID; daty sprzed zmiany pod ``repair_details_…`` (żaden
  klucz nie pasuje do publicznego wzorca ``^\\d{4}_``).
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
from app.services.traffit.mappers import (
    employee_files_from_detail,
    traffit_file_upload_dates,
    traffit_file_upload_lookup,
)

logger = logging.getLogger(__name__)

STATE_KEY = "traffit_file_dates_repair_2026_09"
DRY_RUN_KEY = "traffit_file_dates_repair_2026_09_dry_run"
DETAILS_KEY = "repair_details_traffit_file_dates_2026_09"
LOCK_KEY = "traffit_file_dates_repair_2026_09"
CHUNK = 50
SAMPLE_SIZE = 20
FAILED_SAMPLE = 50
DRY_RUN_MAX_AGE = timedelta(days=7)

COUNT_KEYS = ("changed", "unchanged", "no_date", "no_match")
PERSON_KEYS = ("people", "gone_upstream", "failed")

_GONE = (404, 410)

# Dokumenty z Traffita do sprawdzenia: bez daty albo z datą z okolic importu.
_DOC_FILTER = """
    d.external_source = 'traffit'
    AND d.external_id ~ '^[0-9]{1,18}-[0-9]+$'
    AND (d.uploaded_at IS NULL OR d.uploaded_at >= d.created_at - interval '1 day')
"""

_TARGETS_SQL = f"""
SELECT emp FROM (
    SELECT DISTINCT split_part(d.external_id, '-', 1)::bigint AS emp
    FROM candidate_documents d
    WHERE {_DOC_FILTER}
) t
WHERE emp > :after
ORDER BY emp
LIMIT :limit
"""

_DOCS_SQL = f"""
SELECT d.id, d.filename, d.uploaded_at, split_part(d.external_id, '-', 1) AS emp
FROM candidate_documents d
WHERE {_DOC_FILTER}
  AND split_part(d.external_id, '-', 1) = ANY(CAST(:emps AS text[]))
ORDER BY d.id
"""

_UPDATE_SQL = """
UPDATE candidate_documents
SET uploaded_at = :new
WHERE id = :id
  AND external_source = 'traffit'
  AND uploaded_at IS NOT DISTINCT FROM :old
"""


@dataclass(frozen=True)
class DocRow:
    doc_id: int
    filename: Optional[str]
    uploaded_at: Optional[datetime]


@dataclass(frozen=True)
class DocChange:
    doc_id: int
    old: Optional[datetime]
    new: datetime


def plan_documents(
    docs: list[DocRow], dates: dict[str, Optional[datetime]]
) -> tuple[list[DocChange], dict[str, int]]:
    """Zmiany dat dla dokumentów jednej osoby + liczniki (czysta funkcja)."""
    counts: dict[str, int] = dict.fromkeys(COUNT_KEYS, 0)
    changes: list[DocChange] = []
    for doc in docs:
        known, when = traffit_file_upload_lookup(doc.filename, dates)
        if not known:
            counts["no_match"] += 1
        elif when is None:
            counts["no_date"] += 1
        elif doc.uploaded_at == when:
            counts["unchanged"] += 1
        else:
            counts["changed"] += 1
            changes.append(DocChange(doc.doc_id, doc.uploaded_at, when))
    return changes, counts


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _sample(change: DocChange) -> dict[str, Any]:
    return {
        "document_id": change.doc_id,
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
    """Dopisz ``[id dokumentu, data sprzed zmiany]`` do klucza szczegółów."""
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


async def _traffit_dates(traffit: Any, emp: str) -> tuple[str, dict]:
    """``(status, daty)`` — status: ``ok`` | ``gone`` | ``failed``."""
    try:
        resp = await traffit._get_raw(  # noqa: SLF001
            f"/employees/{emp}", page=1, page_size=1
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Traffit file dates: employee %s detail failed: %s",
            emp,
            type(exc).__name__,
        )
        return "failed", {}
    if resp.status_code in _GONE:
        return "gone", {}
    if resp.status_code != 200:
        return "failed", {}
    try:
        return "ok", traffit_file_upload_dates(employee_files_from_detail(resp.json()))
    except Exception:  # noqa: BLE001
        return "failed", {}


async def process(
    db: AsyncSession,
    traffit: Any,
    *,
    dry_run: bool,
    limit: int,
) -> dict[str, Any]:
    """Jeden bieg: ``limit`` osób od kursora. Zwraca raport (bez zapisu raportu)."""
    limit = max(1, int(limit))
    state = await _read_setting(db, STATE_KEY) or {}
    after = int(state.get("after_emp") or 0)
    rows = await db.execute(text(_TARGETS_SQL), {"after": after, "limit": limit})
    targets = [int(r[0]) for r in rows.all()]
    await db.rollback()

    counts: Counter[str] = Counter(dict.fromkeys(COUNT_KEYS + PERSON_KEYS, 0))
    samples: list[dict[str, Any]] = []
    failed_emps: list[int] = []
    skipped_concurrent = 0
    stopped = False
    last_done = after

    for i in range(0, len(targets), CHUNK):
        chunk = targets[i : i + CHUNK]
        doc_rows = await db.execute(text(_DOCS_SQL), {"emps": [str(e) for e in chunk]})
        docs_by_emp: dict[str, list[DocRow]] = {}
        for r in doc_rows.all():
            docs_by_emp.setdefault(str(r.emp), []).append(
                DocRow(int(r.id), r.filename, r.uploaded_at)
            )
        # Połączenie wraca do puli na czas zapytań do Traffita.
        await db.rollback()

        chunk_counts: Counter[str] = Counter()
        chunk_failed: list[int] = []
        chunk_changes: list[DocChange] = []
        for emp in chunk:
            chunk_counts["people"] += 1
            status, dates = await _traffit_dates(traffit, str(emp))
            if status == "gone":
                chunk_counts["gone_upstream"] += 1
                continue
            if status == "failed":
                chunk_counts["failed"] += 1
                chunk_failed.append(emp)
                continue
            changes, per = plan_documents(docs_by_emp.get(str(emp), []), dates)
            chunk_counts.update(per)
            chunk_changes.extend(changes)

        written: list[DocChange] = chunk_changes
        if not dry_run:
            try:
                await db.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
                    {"k": LOCK_KEY},
                )
                written = []
                for change in chunk_changes:
                    result = await db.execute(
                        text(_UPDATE_SQL),
                        {"id": change.doc_id, "old": change.old, "new": change.new},
                    )
                    if result.rowcount:
                        written.append(change)
                if written:
                    await _append_details(
                        db, [[c.doc_id, _iso(c.old)] for c in written]
                    )
                await _write_setting(
                    db,
                    STATE_KEY,
                    {
                        **state,
                        "after_emp": chunk[-1],
                        "finished": False,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                await db.commit()
            except Exception as exc:  # noqa: BLE001
                await db.rollback()
                logger.error(
                    "Traffit file dates repair: chunk failed: %s", safe_db_error(exc)
                )
                # Kursor zostaje przed paczką — ponowny bieg zacznie od niej,
                # a jej liczniki nie wchodzą do raportu.
                stopped = True
                break
            # „changed” w zapisie = faktycznie zapisane.
            skipped_concurrent += len(chunk_changes) - len(written)
            chunk_counts["changed"] -= len(chunk_changes) - len(written)

        counts.update(chunk_counts)
        failed_emps.extend(chunk_failed[: max(0, FAILED_SAMPLE - len(failed_emps))])
        for change in written:
            if len(samples) < SAMPLE_SIZE:
                samples.append(_sample(change))
        last_done = chunk[-1]

    pass_complete = not stopped and len(targets) < limit
    return {
        "dry_run": dry_run,
        "limit": limit,
        "after_emp_start": after,
        "after_emp_end": last_done,
        "targets": len(targets),
        "pass_complete": pass_complete,
        "stopped_on_error": stopped,
        "changes": {k: int(counts[k]) for k in COUNT_KEYS},
        "people": {k: int(counts[k]) for k in PERSON_KEYS},
        "skipped_concurrent": skipped_concurrent,
        "failed_emp_ids": failed_emps,
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
    for k, v in {**report["changes"], **report["people"]}.items():
        totals[k] = int(totals.get(k) or 0) + int(v)
    passes = int(state.get("passes_completed") or 0)
    if report["pass_complete"]:
        # Koniec przejścia: kursor od zera — kolejny bieg obejrzy tylko to,
        # co nadal nie ma daty (filtr dokumentów), bez parkowania na końcu.
        after_emp, passes = 0, passes + 1
    else:
        after_emp = int(report["after_emp_end"])
    new_state = {
        "after_emp": after_emp,
        "finished": bool(report["pass_complete"]),
        "passes_completed": passes,
        "totals": totals,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "last_run": report,
    }
    await _write_setting(db, STATE_KEY, new_state)
    await db.commit()


# ── Przebieg w tle ───────────────────────────────────────────────────────────

_running: dict[str, bool] = {"file_dates": False}


def is_running() -> bool:
    return _running["file_dates"]


async def fresh_dry_run_exists(db: AsyncSession) -> bool:
    report = await _read_setting(db, DRY_RUN_KEY)
    if not report or not report.get("finished_at"):
        return False
    try:
        finished = datetime.fromisoformat(str(report["finished_at"]))
    except ValueError:
        return False
    return datetime.now(timezone.utc) - finished <= DRY_RUN_MAX_AGE


async def run_file_dates_repair(*, dry_run_mode: bool, limit: int) -> None:
    """Bieg w tle (spawn z endpointu) pod blokadą syncu Traffita."""
    from app.core.database import AsyncSessionLocal
    from app.services.traffit.client import TraffitClient, TraffitConfig
    from app.tasks.traffit_sync import traffit_exclusive_lock

    if _running["file_dates"]:
        return
    _running["file_dates"] = True
    started = datetime.now(timezone.utc)
    try:
        lock = traffit_exclusive_lock()
        if lock.locked():
            logger.warning("Traffit file dates repair skipped: sync running")
            return
        async with lock:
            config = TraffitConfig.from_env()
            async with TraffitClient(config) as traffit:
                async with AsyncSessionLocal() as db:
                    report = await process(
                        db, traffit, dry_run=dry_run_mode, limit=limit
                    )
                    await finish_run(db, report, started=started)
                    logger.info(
                        "Traffit file dates repair done (dry_run=%s): %s %s",
                        dry_run_mode,
                        json.dumps(report["changes"]),
                        json.dumps(report["people"]),
                    )
    finally:
        _running["file_dates"] = False


async def read_status(db: AsyncSession) -> dict[str, Any]:
    return {
        "running": is_running(),
        "dry_run": await _read_setting(db, DRY_RUN_KEY),
        "state": await _read_setting(db, STATE_KEY),
    }


def spawn_running_guard() -> Optional[str]:
    """Powód odmowy startu (409) albo ``None``."""
    from app.services import traffit_notes_repair
    from app.tasks.traffit_sync import sync_is_running

    if sync_is_running():
        return "Trwa synchronizacja z Traffitem — spróbuj po jej zakończeniu."
    if traffit_notes_repair.is_running():
        return "Trwa naprawa notatek z Traffita — spróbuj po jej zakończeniu."
    if is_running():
        return "Naprawa dat plików z Traffita już trwa."
    return None


__all__ = [
    "DETAILS_KEY",
    "DRY_RUN_KEY",
    "STATE_KEY",
    "DocChange",
    "DocRow",
    "finish_run",
    "fresh_dry_run_exists",
    "plan_documents",
    "process",
    "read_status",
    "run_file_dates_repair",
    "spawn_running_guard",
]
