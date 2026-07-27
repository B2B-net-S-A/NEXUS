"""
Phase 7c — Slack alerts for SLA violations.

Polls pipeline overview-sla logic every N minutes, finds new breaches since
the last check, and posts them to SLACK_WEBHOOK_URL (if configured).

Dedup: DURABLE + ATOMIC (audyt P1 restart-safety). Each alerted CandidateStage
row is stamped with `sla_alerted_at`. A CandidateStage row is a single
stage-entry (a stage move creates a new row), so one durable stamp = exactly one
alert, ever. This replaces the old in-process set that reset on every restart
(Coolify rebuilds on each push) and diverged per uvicorn worker → re-alerting
every breach on restart / duplicate alerts across workers.

Kolejność (F-11, 2026-07-27): stempel jest **commitowany PRZED** POST-em na
webhook, nie po nim. Wcześniej POST szedł wewnątrz otwartej transakcji, a
`sla_alerted_at` lądowało dopiero po nim — twardy crash w tym oknie (prod
restartuje się przy każdym deployu, rolling overlap) cofał transakcję, więc nic
nie odnotowywało, że alert już wyszedł, i kolejny przebieg wysyłał go DRUGI RAZ.

Wybór strony okna jest świadomy. POST na Slacka nie jest ani idempotentny, ani
transakcyjny, więc „dokładnie raz" jest nieosiągalne — można tylko wybrać, po
której stronie leży ryzyko. Tu wybieramy **at-most-once** (najwyżej raz):
zgubiony push zamiast zdublowanego. Jest to możliwe do zaakceptowania tylko
dlatego, że breach SLA **nie jest informacją, którą tracimy** —
`api/phase3.py::sla_alerts` liczy breache na żywo z `candidate_stages` i w ogóle
nie czyta `sla_alerted_at`, więc przypadek zostaje na stałe widoczny w przeglądzie
pipeline'u. Zgubiony push = pominięte szturchnięcie dla sprawy, która i tak jest
na ekranie; zdublowany push = szum, który podkopuje zaufanie do kanału alertów.
Ten sam porządek ma już `tasks/contract_alerts.py`: najpierw commit trwałego
stanu, potem Slack jako best-effort fan-out.

Świadomie NIE stosujemy tu wzorca rezerwacji z `tasks/chat_email_fallback.py`
(`email_send_started_at` → efekt → `email_sent_at`, z odzyskiwaniem wiszącej
rezerwacji). Tamten wzorzec istnieje po to, by pracy NIGDY nie zgubić kosztem
ewentualnego duplikatu — czyli daje dokładnie ten tryb awarii, od którego tu
uciekamy. Ponowienie niepotwierdzonej próby z definicji odtwarza okno duplikatu.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

import httpx
from sqlalchemy import func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage

logger = logging.getLogger(__name__)


_DEFAULT_INTERVAL_MINUTES = 30


async def _compute_breaches(db: AsyncSession) -> list[dict]:
    """Re-implement the overview-sla logic for task use (no HTTP self-call).

    Optymalizacja 2026-07-27: ta funkcja była trzecią kopią pełnego skanu
    `candidate_stages` (~158k obiektów ORM z JSONB/Text) — kopiowaną, jak
    przyznawał docstring, ze stanu SPRZED optymalizacji `api/phase3.py`.
    Teraz ten sam wzorzec co `phase3.py::sla_alerts`:

    1. Najpierw `PipelineStageDef` z `sla_max_days IS NOT NULL` i nie-terminalne
       (kilkanaście wpisów) — tylko one MOGĄ w ogóle wygenerować breach.
    2. `candidate_stages` filtrowane po tej puli `stage_def_id`.
    3. `DISTINCT ON (candidate_id, job_id)` w Postgresie zamiast dedupe w Pythonie.
    4. Kontrola, czy najnowszy stage pary NAPRAWDĘ należy do puli SLA — para może
       mieć nowszy wpis w etapie terminalnym/bez SLA (np. `hired`).
    """
    sla_defs = (
        (
            await db.execute(
                select(PipelineStageDef).where(
                    PipelineStageDef.sla_max_days.isnot(None),
                    PipelineStageDef.is_terminal.is_(False),
                )
            )
        )
        .scalars()
        .all()
    )
    if not sla_defs:
        return []
    stage_defs: dict[int, PipelineStageDef] = {sd.id: sd for sd in sla_defs}

    candidate_rows = (
        (
            await db.execute(
                select(CandidateStage)
                .where(CandidateStage.stage_def_id.in_(list(stage_defs.keys())))
                .distinct(CandidateStage.candidate_id, CandidateStage.job_id)
                .order_by(
                    CandidateStage.candidate_id,
                    CandidateStage.job_id,
                    CandidateStage.moved_at.desc(),
                    CandidateStage.id.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    if not candidate_rows:
        return []

    truly_latest = (
        (
            await db.execute(
                select(CandidateStage)
                .where(
                    # Filtr PO PARACH, nie dwa osobne `IN` — te dawałyby iloczyn
                    # kartezjański (para (A,X) + (B,Y) wciągałaby też (A,Y) i (B,X)),
                    # czyli skanowałyby wiersze, których cała optymalizacja miała
                    # nie dotykać.
                    tuple_(CandidateStage.candidate_id, CandidateStage.job_id).in_(
                        [(s.candidate_id, s.job_id) for s in candidate_rows]
                    )
                )
                .distinct(CandidateStage.candidate_id, CandidateStage.job_id)
                .order_by(
                    CandidateStage.candidate_id,
                    CandidateStage.job_id,
                    CandidateStage.moved_at.desc(),
                    CandidateStage.id.desc(),
                )
            )
        )
        .scalars()
        .all()
    )

    now = datetime.now(timezone.utc)
    breaches: list[dict] = []
    for s in truly_latest:
        sd = stage_defs.get(s.stage_def_id or 0)
        if not sd or not sd.sla_max_days or sd.is_terminal:
            continue
        moved = s.moved_at
        if moved.tzinfo is None:
            moved = moved.replace(tzinfo=timezone.utc)
        days = (now - moved).days
        if days > sd.sla_max_days:
            breaches.append(
                {
                    "candidate_stage_id": s.id,
                    "candidate_id": s.candidate_id,
                    "job_id": s.job_id,
                    "stage_name": sd.name,
                    "days_in_stage": days,
                    "sla_max_days": sd.sla_max_days,
                    "overdue_by_days": days - sd.sla_max_days,
                    # Durable dedup marker — None means "never alerted".
                    "sla_alerted_at": s.sla_alerted_at,
                }
            )
    return breaches


async def _claim_breach(db: AsyncSession, candidate_stage_id: int) -> bool:
    """Atomically stamp ``sla_alerted_at`` — and commit it BEFORE any POST.

    A single ``UPDATE ... WHERE sla_alerted_at IS NULL ... RETURNING id`` guarded
    by the row lock Postgres takes for the write. Returns True only for the
    caller that flipped the row from NULL. A concurrent/overlapping pass
    (multi-worker or a rolling-deploy restart overlap) blocks on the lock, then
    re-evaluates the WHERE against the committed stamp, matches zero rows and
    returns False — so the alert is posted at most once.

    This replaces a ``SELECT ... FOR UPDATE SKIP LOCKED`` whose transaction — and
    row lock — stayed open across the whole Slack call (up to the 10s timeout).
    The claim now commits immediately: no idle-in-transaction connection held
    hostage by a remote HTTP round trip, and the record of the alert survives a
    crash during that round trip.
    """
    result = await db.execute(
        update(CandidateStage)
        .where(
            CandidateStage.id == candidate_stage_id,
            CandidateStage.sla_alerted_at.is_(None),
        )
        .values(sla_alerted_at=func.now())
        .returning(CandidateStage.id)
    )
    claimed = result.scalar_one_or_none() is not None
    await db.commit()
    return claimed


async def _release_claim(db: AsyncSession, candidate_stage_id: int) -> None:
    """Hand a claimed breach back so the next tick retries it.

    Only ever called when the POST failed *cleanly* — a non-2xx response or a
    transport error, both of which ``_post_to_slack`` turns into False. That is
    the case where we know for certain Slack did not accept the message, so
    re-alerting is not a duplicate.

    Deliberately NOT reached via ``try/finally``: a hard crash (the container
    being killed mid-POST) runs no cleanup, which is the whole point — the stamp
    stands and the alert is never sent twice.
    """
    await db.execute(
        update(CandidateStage)
        .where(CandidateStage.id == candidate_stage_id)
        .values(sla_alerted_at=None)
    )
    await db.commit()


async def _dispatch_alert(webhook: str, breach: dict) -> bool:
    """Claim one breach row, then post it to Slack.

    Order is load-bearing (see module docstring): the claim is committed first,
    so a crash between the claim and Slack accepting the message can only ever
    drop the alert — never send it twice. Returns True only when an alert was
    actually accepted by Slack.
    """
    async with AsyncSessionLocal() as db:
        if not await _claim_breach(db, breach["candidate_stage_id"]):
            # Already alerted, claimed by another worker, or the row is gone.
            return False
        if not await _post_to_slack(webhook, breach):
            # Slack explicitly refused it — give the breach back for a retry.
            await _release_claim(db, breach["candidate_stage_id"])
            return False
        return True


async def _post_to_slack(webhook: str, breach: dict) -> bool:
    """Post one breach to Slack. Returns True only on a 2xx response.

    httpx does not raise on 4xx/5xx by default, so we must inspect the status
    code explicitly. On an HTTP error status or a transport error we log a
    warning and return False; the caller then leaves the breach un-alerted so
    the next poll retries it (idempotent — it re-sends only because it was
    never marked as sent).
    """
    text = (
        f":warning: SLA breach — kandydat #{breach['candidate_id']} "
        f"utknął w etapie *{breach['stage_name']}* od {breach['days_in_stage']} dni "
        f"(SLA = {breach['sla_max_days']}d, overdue +{breach['overdue_by_days']}d). "
        f"Oferta: #{breach['job_id']}"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook, json={"text": text})
    except Exception as e:  # noqa: BLE001
        logger.warning("slack_sla_alerts: post failed %s", e)
        return False
    if resp.status_code >= 400:
        logger.warning(
            "slack_sla_alerts: Slack returned HTTP %d — alert not marked sent",
            resp.status_code,
        )
        return False
    return True


async def slack_sla_alerts_loop(
    interval_minutes: float = _DEFAULT_INTERVAL_MINUTES,
) -> None:
    """Long-running task: poll for SLA breaches and alert on Slack."""
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook:
        logger.info("slack_sla_alerts: SLACK_WEBHOOK_URL not set — task disabled")
        return

    logger.info("slack_sla_alerts: started interval=%.1f min", interval_minutes)
    # Initial delay so app startup isn't slowed
    await asyncio.sleep(90)
    while True:
        try:
            async with AsyncSessionLocal() as db:
                breaches = await _compute_breaches(db)
            # Durable dedup: skip anything already stamped as alerted. The
            # per-row FOR UPDATE claim in _dispatch_alert is the atomic guard.
            new_breaches = [b for b in breaches if b["sla_alerted_at"] is None]
            sent = 0
            for b in new_breaches:
                try:
                    if await _dispatch_alert(webhook, b):
                        sent += 1
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "slack_sla_alerts: dispatch failed for stage %s: %s",
                        b["candidate_stage_id"],
                        e,
                    )
            if sent:
                logger.info("slack_sla_alerts: posted %d new breach alerts", sent)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("slack_sla_alerts: cycle error %s", e)
        await asyncio.sleep(interval_minutes * 60)
