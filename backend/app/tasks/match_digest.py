"""Cotygodniowy digest top dopasowań — push do rekruterów (punkt 6).

Adopcja rekomendacji w NEXUS-ie to ułamek procenta ruchów pipeline'u:
najlepszy ranking nic nie daje, jeśli nikt nie wchodzi w zakładkę. Digest
odwraca kierunek — raz w tygodniu (poniedziałek 06:00 UTC) każdy rekruter
i TAC opublikowanej rekrutacji dostaje in-app notyfikację z top ŚWIEŻYCH
dopasowań (kandydaci spoza pipeline'u tej rekrutacji, score >= progu).

Świadome wybory:
- **Świeżość = spoza pipeline'u**: kandydat z jakimkolwiek CandidateStage tej
  rekrutacji odpada — digest powtarzający znanych ludzi uczy ignorowania.
- **Próg score** (`MATCH_DIGEST_MIN_SCORE`, default 55): digest 20-punktowych
  trafień to spam, który zabija zaufanie do funkcji szybciej niż jej brak.
- **Zero nazwisk w treści notyfikacji**: liczba + link do zakładki dopasowań.
  Notyfikacje wiszą w dzwonku długo i bywają widoczne przez ramię; profil
  jest o klik dalej, za pełnym RBAC.
- Ranking tą samą ścieżką co /recommendations (`retrieve_candidate_pool` +
  `rank_candidates_for_job` + aktywny profil wag) — digest pokazujący inne
  wyniki niż zakładka byłby samopodważający.
- `emit()` ma dzienny dedup (user+typ+encja), więc restart pętli w dniu
  wysyłki nie dubluje powiadomień.

Wzorce operacyjne jak notes_insights_sync/weekly_eval: kill-switch przed
while, watermark `match_digest` w traffit_sync_state, wspólny lock.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.job import Job, JobStatus
from app.models.notification import NotificationType
from app.models.recruitment_pipeline import CandidateStage

logger = logging.getLogger(__name__)

STATE_PHASE = "match_digest"
_run_lock = asyncio.Lock()


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


async def _save_state(stats: dict[str, Any]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                """
                INSERT INTO traffit_sync_state
                    (phase, last_synced_at, last_run_started_at,
                     last_run_finished_at, last_status, stats,
                     created_at, updated_at)
                VALUES (:p, now(), now(), now(), :status,
                        CAST(:stats AS jsonb), now(), now())
                ON CONFLICT (phase) DO UPDATE SET
                    last_synced_at = now(),
                    last_run_started_at = now(),
                    last_run_finished_at = now(),
                    last_status = EXCLUDED.last_status,
                    stats = EXCLUDED.stats,
                    updated_at = now()
                """
            ),
            {
                "p": STATE_PHASE,
                "status": stats.get("status", "ok"),
                "stats": json.dumps(stats, ensure_ascii=False),
            },
        )
        await db.commit()


def _is_due(last_synced_at: Optional[datetime], now: datetime) -> bool:
    """Raz w tygodniu w `MATCH_DIGEST_WEEKDAY` po `MATCH_DIGEST_HOUR_UTC`.

    Pierwszy bieg po włączeniu — od razu. Okno >=6 dni jak w weekly_eval
    (bieg o 06:10 nie może przesuwać okna w nieskończoność).
    """
    if last_synced_at is None:
        return True
    last = last_synced_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if (now - last).days < 6:
        return False
    if now.weekday() != int(settings.MATCH_DIGEST_WEEKDAY):
        return False
    return now.hour >= int(settings.MATCH_DIGEST_HOUR_UTC)


async def _fresh_top_matches(db, job: Job) -> list[tuple[int, float]]:
    """Top świeżych dopasowań (spoza pipeline'u) dla jednej rekrutacji."""
    from app.services.embedding_service import _build_job_text
    from app.services.match_score_cache import bulk_get_or_compute
    from app.services.retrieval_pool import retrieve_candidate_pool
    from app.services.scoring_service import resolve_active_profile

    try:
        hits = await retrieve_candidate_pool(
            db, _build_job_text(job), top_k=int(settings.MATCH_DIGEST_TOP_N) * 40
        )
    except Exception as exc:  # noqa: BLE001 — awaria retrievalu = pusta lista
        logger.warning("match-digest: retrieval padł dla job=%s: %s", job.id, exc)
        return []
    similarity_map = {h["candidate_id"]: h["score"] for h in hits}
    if not similarity_map:
        return []

    staged = set(
        (
            await db.execute(
                select(CandidateStage.candidate_id).where(
                    CandidateStage.job_id == job.id
                )
            )
        )
        .scalars()
        .all()
    )
    fresh_ids = [cid for cid in similarity_map if cid not in staged]
    if not fresh_ids:
        return []

    candidates = (
        (await db.execute(select(Candidate).where(Candidate.id.in_(fresh_ids))))
        .scalars()
        .all()
    )
    profile = await resolve_active_profile(db)
    breakdowns = await bulk_get_or_compute(
        job, candidates, db, similarity_map=similarity_map, profile=profile
    )
    floor = float(settings.MATCH_DIGEST_MIN_SCORE)
    ranked = sorted(
        ((b.candidate_id, b.total) for b in breakdowns if b.total >= floor),
        key=lambda item: -item[1],
    )
    return ranked[: int(settings.MATCH_DIGEST_TOP_N)]


async def run_match_digest() -> dict[str, Any]:
    """Jeden bieg: opublikowane rekrutacje → top świeżych → notyfikacje."""
    from app.services.notification_triggers import emit

    stats: dict[str, Any] = {
        "status": "ok",
        "jobs_scanned": 0,
        "jobs_with_matches": 0,
        "notifications_sent": 0,
        "dedup_skipped": 0,
        "errors": 0,
    }
    async with AsyncSessionLocal() as db:
        jobs = (
            (
                await db.execute(
                    select(Job).where(
                        Job.status == JobStatus.published,
                        (Job.recruiter_id.isnot(None)) | (Job.tac_id.isnot(None)),
                    )
                )
            )
            .scalars()
            .all()
        )

    for job in jobs:
        stats["jobs_scanned"] += 1
        try:
            async with AsyncSessionLocal() as db:
                job_row = (
                    await db.execute(select(Job).where(Job.id == job.id))
                ).scalar_one_or_none()
                if job_row is None:
                    continue
                top = await _fresh_top_matches(db, job_row)
                if not top:
                    continue
                stats["jobs_with_matches"] += 1
                best = top[0][1]
                recipients = {
                    uid
                    for uid in (job_row.recruiter_id, job_row.tac_id)
                    if uid is not None
                }
                for uid in recipients:
                    notif = await emit(
                        db,
                        user_id=uid,
                        title=f"Top dopasowania tygodnia: {job_row.title}",
                        message=(
                            f"{len(top)} świeżych kandydatów spoza pipeline'u "
                            f"(najlepszy {best:.0f} pkt). Zobacz zakładkę "
                            "dopasowań rekrutacji."
                        ),
                        ntype=NotificationType.match_digest,
                        related_entity_type="job",
                        related_entity_id=job_row.id,
                        link=f"/jobs/{job_row.id}",
                    )
                    if notif is None:
                        stats["dedup_skipped"] += 1
                    else:
                        stats["notifications_sent"] += 1
                await db.commit()
        except Exception:  # noqa: BLE001 — jedna rekrutacja nie zabija biegu
            logger.exception("match-digest: bieg padł dla job=%s", job.id)
            stats["errors"] += 1

    if stats["errors"] and stats["status"] == "ok":
        stats["status"] = "partial"
    return stats


async def run_and_persist() -> dict[str, Any]:
    async with _run_lock:
        stats = await run_match_digest()
        await _save_state(stats)
        return stats


async def match_digest_loop() -> None:
    """Pętla tła — rejestrowana w lifespanie main.py."""
    if not settings.MATCH_DIGEST_ENABLED:
        logger.info("match-digest wyłączony (MATCH_DIGEST_ENABLED=false)")
        return
    interval = max(600, int(settings.MATCH_DIGEST_CHECK_INTERVAL_SECONDS))
    logger.info("match-digest aktywny (interwał kontroli %ss)", interval)
    while True:
        try:
            state = await _load_state()
            last = state["last_synced_at"] if state else None
            if _is_due(last, datetime.now(timezone.utc)) and not _run_lock.locked():
                stats = await run_and_persist()
                logger.info("match-digest: %s", stats)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("match-digest: bieg padł, ponowię po interwale")
        await asyncio.sleep(interval)
