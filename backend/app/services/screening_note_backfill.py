"""Uzupełnienie historii: odpowiedzi z kart rekomendacji do arkuszy (07.10.2026).

Karty rekomendacji z Traffita niosą odpowiedzi na pytania screeningowe
(``recommendation_cards.note_answers``), a arkuszy w NEXUSIE prawie nie ma.
Od decyzji Artura z 07.10.2026 karta, która się zmienia, przepisuje odpowiedzi
do arkusza sama (``screening_note_sync``); ta naprawa robi to RAZ dla
wszystkich kart z odpowiedziami — także w rekrutacjach archiwalnych.

Reguły zapisu są w ``screening_note_sync`` (jedno miejsce): arkusz ludzki
zostaje, notatka sprzed bieżącej próby procesu nie zasila arkusza, przypięcie
do pytań po treści i — ostrożnie — po numerze.

Zasady jak przy innych naprawach z panelu admina:

* przebieg próbny niczego nie zapisuje poza raportem (akcje, powody,
  dopasowania po treści i po numerze, histogram, ≤ 20 przykładów z samymi ID);
* zapis wymaga próby z ostatnich 7 dni i ``expected`` równego liczbie par do
  zmiany z tej próby (inaczej 409);
* zapis paczkami po 200 par, pod blokadą doradczą, każda para w savepoincie
  i ponownie liczona pod blokadą wierszy etapów; wyniki dopasowania kandydatów
  z paczki oznaczane jako stare hurtem;
* paragon (``screening_note_backfill_2026_10``) = liczby i ID; dane do
  odwrócenia (wiersz etapu i jego poprzednia treść) pod
  ``repair_details_screening_note_backfill_2026_10``;
* ponowny bieg nic nie zmienia (para ma już arkusz automatu o tej samej
  treści).
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import screening_note_sync as sync

logger = logging.getLogger(__name__)

STATE_KEY = "screening_note_backfill_2026_10"
DRY_RUN_KEY = "screening_note_backfill_2026_10_dry_run"
DETAILS_KEY = "repair_details_screening_note_backfill_2026_10"
LOCK_KEY = "screening_note_backfill_2026_10"
CHUNK = 200
SAMPLE_SIZE = 20
FAILED_SAMPLE = 50
DRY_RUN_MAX_AGE = timedelta(days=7)
CHANGING_ACTIONS = (sync.ACTION_CREATE, sync.ACTION_UPDATE, sync.ACTION_CLEAR)

# Karty z co najmniej jedną odpowiedzią z notatki.
_PAIRS_SQL = text(
    "SELECT c.candidate_id, c.job_id FROM recommendation_cards c "
    "WHERE jsonb_typeof(c.note_answers -> 'items') = 'array' "
    "AND jsonb_array_length(c.note_answers -> 'items') > 0 "
    "ORDER BY c.id"
)


async def load_pairs(db: AsyncSession) -> list[tuple[int, int]]:
    rows = (await db.execute(_PAIRS_SQL)).all()
    return [(int(row[0]), int(row[1])) for row in rows]


def _sample(plan: sync.PairPlan) -> dict[str, Any]:
    summary = plan.summary()
    return {
        key: summary[key]
        for key in (
            "candidate_id",
            "job_id",
            "stage_id",
            "note_id",
            "action",
            "question_ids",
            "by_content",
            "by_number",
        )
    }


async def plan(
    db: AsyncSession, *, only_pairs: Optional[set[tuple[int, int]]] = None
) -> dict[str, Any]:
    """Przebieg próbny: liczby, powody i przykłady. Niczego nie zapisuje."""
    pairs = [
        pair
        for pair in await load_pairs(db)
        if only_pairs is None or pair in only_pairs
    ]
    actions: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    skipped_answers: Counter[str] = Counter()
    histogram: Counter[str] = Counter()
    by_content = by_number = 0
    samples: list[dict[str, Any]] = []
    for candidate_id, job_id in pairs:
        result = await sync.plan_pair(
            db, candidate_id=candidate_id, job_id=job_id, lock=False
        )
        actions[result.action] += 1
        if result.reason:
            reasons[result.reason] += 1
        skipped_answers.update(result.skipped)
        if result.action in (sync.ACTION_CREATE, sync.ACTION_UPDATE):
            by_content += result.by_content
            by_number += result.by_number
            histogram[str(len(result.question_ids))] += 1
        if result.action in CHANGING_ACTIONS and len(samples) < SAMPLE_SIZE:
            samples.append(_sample(result))
    await db.rollback()
    return {
        "dry_run": True,
        "pairs": len(pairs),
        "to_change": sum(actions[action] for action in CHANGING_ACTIONS),
        "actions": dict(actions),
        "reasons": dict(reasons),
        "answers": {"by_content": by_content, "by_number": by_number},
        "skipped_answers": dict(skipped_answers),
        "answers_per_sheet": dict(sorted(histogram.items(), key=lambda i: int(i[0]))),
        "samples": samples,
    }


async def _read_setting(db: AsyncSession, key: str) -> Optional[dict[str, Any]]:
    value = (
        await db.execute(
            text("SELECT value FROM app_settings WHERE key = :k"), {"k": key}
        )
    ).scalar_one_or_none()
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


async def _append_details(db: AsyncSession, entries: list[dict[str, Any]]) -> None:
    """Dane do odwrócenia: wiersz etapu i jego treść sprzed zapisu."""
    await db.execute(
        text(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (:key, jsonb_build_object('rows', CAST(:value AS jsonb)), now())
            ON CONFLICT (key) DO UPDATE SET
                value = jsonb_build_object(
                    'rows',
                    COALESCE(app_settings.value -> 'rows', '[]'::jsonb)
                    || CAST(:value AS jsonb)
                ),
                updated_at = now()
            """
        ),
        {"key": DETAILS_KEY, "value": json.dumps(entries, default=str)},
    )


async def apply(
    db: AsyncSession,
    *,
    actor_user_id: Optional[int],
    only_pairs: Optional[set[tuple[int, int]]] = None,
) -> dict[str, Any]:
    """Zapis: para po parze w savepointach, paczki po ``CHUNK`` z commitem.

    ``only_pairs`` zawęża bieg (testy na wspólnej bazie); endpoint go nie
    przekazuje.
    """
    from app.services.match_score_cache import (  # noqa: PLC0415
        mark_stale_for_candidates,
    )

    pairs = [
        pair
        for pair in await load_pairs(db)
        if only_pairs is None or pair in only_pairs
    ]
    await db.rollback()
    counts: Counter[str] = Counter({action: 0 for action in CHANGING_ACTIONS})
    counts.update({"unchanged": 0, "failed": 0})
    samples: list[dict[str, Any]] = []
    failed: list[dict[str, int]] = []
    stopped = False
    for start in range(0, len(pairs), CHUNK):
        chunk = pairs[start : start + CHUNK]
        chunk_counts: Counter[str] = Counter()
        chunk_failed: list[dict[str, int]] = []
        chunk_samples: list[dict[str, Any]] = []
        details: list[dict[str, Any]] = []
        touched: set[int] = set()
        try:
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": LOCK_KEY}
            )
            for candidate_id, job_id in chunk:
                try:
                    async with db.begin_nested():
                        result = await sync.plan_pair(
                            db, candidate_id=candidate_id, job_id=job_id, lock=True
                        )
                        previous = [
                            {
                                "candidate_id": candidate_id,
                                "job_id": job_id,
                                "stage_id": row.id,
                                "previous": before,
                            }
                            for row, before, _ in result.changes
                        ]
                        changed = await sync.apply_plan(
                            db,
                            result,
                            mark_stale=False,
                            actor_user_id=actor_user_id,
                        )
                except Exception as exc:  # noqa: BLE001 — para, nie cały bieg
                    logger.warning(
                        "screening note backfill: pair %s/%s failed: %s",
                        candidate_id,
                        job_id,
                        type(exc).__name__,
                    )
                    chunk_counts["failed"] += 1
                    chunk_failed.append(
                        {"candidate_id": candidate_id, "job_id": job_id}
                    )
                    continue
                if not changed:
                    chunk_counts["unchanged"] += 1
                    continue
                chunk_counts[result.action] += 1
                touched.add(candidate_id)
                details.extend(previous)
                if len(chunk_samples) + len(samples) < SAMPLE_SIZE:
                    chunk_samples.append(_sample(result))
            if touched:
                await mark_stale_for_candidates(db, sorted(touched))
            if details:
                await _append_details(db, details)
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            logger.error(
                "screening note backfill: chunk failed: %s", type(exc).__name__
            )
            stopped = True
            break
        counts.update(chunk_counts)
        samples.extend(chunk_samples)
        failed.extend(chunk_failed[: max(0, FAILED_SAMPLE - len(failed))])
    return {
        "dry_run": False,
        "pairs": len(pairs),
        "stopped_on_error": stopped,
        "counts": dict(counts),
        "failed_pairs": failed,
        "samples": samples,
    }


async def finish_run(
    db: AsyncSession, report: dict[str, Any], *, started: datetime
) -> None:
    """Próba → ``DRY_RUN_KEY``; zapis → paragon z sumami (liczby i ID)."""
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
    for key, value in report["counts"].items():
        totals[key] = int(totals.get(key) or 0) + int(value)
    await _write_setting(
        db,
        STATE_KEY,
        {
            "runs": int(state.get("runs") or 0) + 1,
            "totals": totals,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "last_run": report,
        },
    )
    await db.commit()


async def fresh_dry_run(db: AsyncSession) -> Optional[dict[str, Any]]:
    """Raport próby z ostatnich 7 dni albo ``None``."""
    report = await _read_setting(db, DRY_RUN_KEY)
    if not report or not report.get("finished_at"):
        return None
    try:
        finished = datetime.fromisoformat(str(report["finished_at"]))
    except ValueError:
        return None
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - finished > DRY_RUN_MAX_AGE:
        return None
    return report


# ── Przebieg w tle ───────────────────────────────────────────────────────────

_running: dict[str, bool] = {"apply": False}


def is_running() -> bool:
    return _running["apply"]


def reserve() -> bool:
    """Zajmij bieg synchronicznie w handlerze (dwa szybkie POST-y = jeden bieg)."""
    if _running["apply"]:
        return False
    _running["apply"] = True
    return True


def release() -> None:
    _running["apply"] = False


async def run_apply(*, actor_user_id: int) -> None:
    """Zapis w tle (spawn z endpointu). Bieg musi być zajęty przez ``reserve``."""
    from app.core.database import AsyncSessionLocal  # noqa: PLC0415

    started = datetime.now(timezone.utc)
    try:
        async with AsyncSessionLocal() as db:
            report = await apply(db, actor_user_id=actor_user_id)
            await finish_run(db, report, started=started)
            logger.info(
                "screening note backfill done: %s", json.dumps(report["counts"])
            )
    finally:
        _running["apply"] = False


async def read_status(db: AsyncSession) -> dict[str, Any]:
    return {
        "running": is_running(),
        "dry_run": await _read_setting(db, DRY_RUN_KEY),
        "state": await _read_setting(db, STATE_KEY),
    }


__all__ = [
    "DETAILS_KEY",
    "DRY_RUN_KEY",
    "STATE_KEY",
    "apply",
    "finish_run",
    "fresh_dry_run",
    "load_pairs",
    "plan",
    "read_status",
    "release",
    "reserve",
    "run_apply",
]
