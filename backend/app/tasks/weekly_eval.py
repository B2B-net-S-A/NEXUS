"""Cotygodniowy strażnik jakości matchingu — pomiar na zamrożonym zbiorze.

Po 17.08.2026 na prodzie żyje pięć zmierzonych flipów scoringu (sygnały v1,
kara seniority, rozszerzone aliasy, wagi 45/25/10/8/2, pula 1000) i ZERO
mechanizmu, który za miesiąc powie, czy nadal działają. Cichy regres po
cudzej zmianie (nowy import, edycja promptu, dryf danych) byłby niewidzialny
do następnego ręcznego pomiaru. Ten strażnik odpala harness ewaluacyjny raz
w tygodniu na zamrożonych 50 ofertach i porównuje z poprzednim tygodniem.

Mechanika:
- Harness biegnie jako SUBPROCES (`python -m scripts.eval_matching`) —
  osobny proces nie konkuruje z pętlą zdarzeń serwującego backendu; okno
  niedziela 05:00 UTC (po nocnych syncach) minimalizuje wpływ na ruch.
- Wynik (P@5, R@20n, MRR, nDCG) ląduje w `traffit_sync_state` (wiersz
  `weekly_eval`) — widoczny w `GET /api/admin/traffit/sync/status` bez
  nowych powierzchni; poprzedni tydzień siedzi w tym samym wierszu.
- **Alert regresu**: spadek P@5 albo R@20n o >15% względem poprzedniego
  pomiaru → `logger.error` (LoggingIntegration niesie go do Sentry)
  + `last_status='regression'`. Próg 15% > szum harnessu (~1-2%), więc
  alarm oznacza realne zdarzenie, nie fluktuację.

Wzorce operacyjne jak w notes_insights_sync: kill-switch kończy pętlę PRZED
while, watermark w bazie (restart-safe przy redeployach Coolify), wspólny
lock jednego biegu.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

STATE_PHASE = "weekly_eval"
_run_lock = asyncio.Lock()

# Względny spadek, od którego mówimy o regresie (nie szumie).
_REGRESSION_DROP = 0.15


def sync_is_running() -> bool:
    return _run_lock.locked()


async def _load_state() -> Optional[dict]:
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                text(
                    "SELECT last_synced_at, stats FROM traffit_sync_state "
                    "WHERE phase = :p"
                ),
                {"p": STATE_PHASE},
            )
        ).first()
    if row is None:
        return None
    return {"last_synced_at": row[0], "stats": row[1]}


# Statusy, które PRZESUWAJĄ watermark. Awaria (timeout/harness_failed/
# parse_failed) go nie przesuwa — inaczej przejściowy czkawka w niedzielę
# 05:00 wyciszałaby strażnika na cały tydzień. Ponowienia są naturalnie
# ograniczone oknem: _is_due wymaga właściwego dnia tygodnia, więc nieudane
# próby powtarzają się co interwał TYLKO do końca niedzieli.
_ADVANCING_STATUSES = frozenset({"ok", "regression"})


async def _save_state(stats: dict[str, Any]) -> None:
    advance = stats.get("status") in _ADVANCING_STATUSES
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                """
                INSERT INTO traffit_sync_state
                    (phase, last_synced_at, last_run_started_at,
                     last_run_finished_at, last_status, stats,
                     created_at, updated_at)
                VALUES (:p,
                        CASE WHEN :advance THEN now() ELSE NULL END,
                        now(), now(), :status,
                        CAST(:stats AS jsonb), now(), now())
                ON CONFLICT (phase) DO UPDATE SET
                    last_synced_at = CASE
                        WHEN :advance THEN now()
                        ELSE traffit_sync_state.last_synced_at
                    END,
                    last_run_started_at = now(),
                    last_run_finished_at = now(),
                    last_status = EXCLUDED.last_status,
                    stats = EXCLUDED.stats,
                    updated_at = now()
                """
            ),
            {
                "p": STATE_PHASE,
                "advance": advance,
                "status": stats.get("status", "ok"),
                "stats": json.dumps(stats, ensure_ascii=False),
            },
        )
        await db.commit()


def _is_due(last_synced_at: Optional[datetime], now: datetime) -> bool:
    """Raz w tygodniu, w dzień `WEEKLY_EVAL_WEEKDAY` po `WEEKLY_EVAL_HOUR_UTC`.

    Pierwszy bieg po włączeniu — od razu (weryfikacja instalacji bez czekania
    tygodnia). Potem: należny, gdy od ostatniego minęło >=6 dni i jest właściwy
    dzień po właściwej godzinie (>=6, nie 7 — bieg o 05:10 nie może przesuwać
    okna w nieskończoność o te 10 minut co tydzień).
    """
    if last_synced_at is None:
        return True
    last = last_synced_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if (now - last).days < 6:
        return False
    if now.weekday() != int(settings.WEEKLY_EVAL_WEEKDAY):
        return False
    return now.hour >= int(settings.WEEKLY_EVAL_HOUR_UTC)


def _extract_metrics(payload: dict) -> dict[str, Any]:
    profiles = payload.get("profiles") or []
    if not profiles:
        raise ValueError(
            "harness zwrócił 0 ofert — zamrożony zbiór nie spełnia --min-gt? "
            "Sprawdź /tmp/weekly-eval.md w kontenerze."
        )
    prof = profiles[0]
    return {
        "p5": round(float(prof["mean_precision_at_5"]), 4),
        "r20n": round(float(prof["mean_recall_at_20_normalized"]), 4),
        "mrr": round(float(prof["mean_mrr"]), 4),
        "ndcg10": round(float(prof["mean_ndcg_at_10"]), 4),
        "jobs": len(prof.get("per_job") or []),
    }


def detect_regression(
    current: dict[str, Any], previous: Optional[dict[str, Any]]
) -> list[str]:
    """Nazwy metryk z regresem >15% względem poprzedniego pomiaru."""
    if not isinstance(previous, dict):
        return []
    regressed: list[str] = []
    for key in ("p5", "r20n"):
        prev_val = previous.get(key)
        cur_val = current.get(key)
        if (
            isinstance(prev_val, (int, float))
            and isinstance(cur_val, (int, float))
            and prev_val > 0
            and cur_val < prev_val * (1.0 - _REGRESSION_DROP)
        ):
            regressed.append(key)
    return regressed


async def run_weekly_eval() -> dict[str, Any]:
    """Jeden pomiar: subproces harnessu → metryki → porównanie → zapis."""
    from scripts.eval_frozen_set import frozen_ids_csv

    started = datetime.now(timezone.utc)
    cmd = [
        sys.executable,
        "-m",
        "scripts.eval_matching",
        "--job-ids",
        frozen_ids_csv(),
        "--jobs",
        "50",
        "--min-gt",
        "3",
        "--pool",
        "1000",
        "--json",
        "--output",
        "/tmp/weekly-eval.md",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=settings.WEEKLY_EVAL_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()  # reap — bez tego zombie + ResourceWarning
        return {"status": "timeout", "measured_at": started.isoformat()}
    if proc.returncode != 0:
        tail = (stderr or b"")[-500:].decode("utf-8", "replace")
        logger.error("weekly-eval: harness padł (rc=%s): %s", proc.returncode, tail)
        return {
            "status": "harness_failed",
            "rc": proc.returncode,
            "measured_at": started.isoformat(),
        }

    out_json = "/tmp/weekly-eval.json"
    try:
        with open(out_json, encoding="utf-8") as fh:
            metrics = _extract_metrics(json.load(fh))
    except Exception as exc:  # noqa: BLE001
        logger.error("weekly-eval: nieczytelny wynik: %s", exc)
        return {"status": "parse_failed", "measured_at": started.isoformat()}

    prev_state = await _load_state()
    previous = None
    if prev_state and isinstance(prev_state.get("stats"), dict):
        previous = prev_state["stats"].get("metrics")

    regressed = detect_regression(metrics, previous)
    status = "regression" if regressed else "ok"
    if regressed:
        logger.error(
            "weekly-eval: REGRES jakości matchingu na zamrożonym zbiorze — "
            "%s spadło >15%% tydzień do tygodnia (teraz %s, poprzednio %s). "
            "Sprawdź ostatnie zmiany scoringu/importów.",
            ", ".join(regressed),
            metrics,
            previous,
        )
    else:
        logger.info("weekly-eval: %s (poprzednio %s)", metrics, previous)

    return {
        "status": status,
        "metrics": metrics,
        "previous": previous,
        "regressed": regressed,
        "measured_at": started.isoformat(),
        "duration_s": int((datetime.now(timezone.utc) - started).total_seconds()),
    }


async def run_and_persist() -> dict[str, Any]:
    async with _run_lock:
        stats = await run_weekly_eval()
        await _save_state(stats)
        return stats


async def weekly_eval_loop() -> None:
    """Pętla tła — rejestrowana w lifespanie main.py."""
    if not settings.WEEKLY_EVAL_ENABLED:
        logger.info("weekly-eval wyłączony (WEEKLY_EVAL_ENABLED=false)")
        return
    interval = max(600, int(settings.WEEKLY_EVAL_CHECK_INTERVAL_SECONDS))
    logger.info("weekly-eval aktywny (interwał kontroli %ss)", interval)
    while True:
        try:
            state = await _load_state()
            last = state["last_synced_at"] if state else None
            if _is_due(last, datetime.now(timezone.utc)) and not _run_lock.locked():
                stats = await run_and_persist()
                logger.info("weekly-eval: bieg zakończony: %s", stats.get("status"))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("weekly-eval: bieg padł, ponowię po interwale")
        await asyncio.sleep(interval)
