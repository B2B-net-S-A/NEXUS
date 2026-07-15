"""Single-leader worker loop for the bidirectional Traffit integration.

The module is intentionally not registered in ``main.py`` here. Wiring is a
separate deployment step after migrations, sandbox verification and explicit
kill-switch activation.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.traffit_integration import TraffitSyncRun
from app.services.traffit.client import (
    TraffitClient,
    TraffitConfig,
    integration_scopes_from_env,
)
from app.services.traffit.control import effective_control, integration_master_enabled
from app.services.traffit.field_contracts import refresh_contracts_if_due
from app.services.traffit.inbound import (
    run_inbox_batch,
    run_poll_reconcile,
    scrub_completed_webhook_payloads,
)
from app.services.traffit.lease import acquire_lease, heartbeat_lease, release_lease
from app.services.traffit.outbound import run_outbound_batch

logger = logging.getLogger(__name__)

LEASE_NAME = "traffit-integration-worker"
LEASE_TTL = timedelta(seconds=90)


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


async def _lease_heartbeat_loop(
    worker_id: str,
    generation: int,
    stop: asyncio.Event,
    lost: asyncio.Event,
) -> None:
    try:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=30.0)
                return
            except asyncio.TimeoutError:
                pass
            async with AsyncSessionLocal() as heartbeat_db:
                alive = await heartbeat_lease(
                    heartbeat_db,
                    name=LEASE_NAME,
                    holder_id=worker_id,
                    generation=generation,
                    ttl=LEASE_TTL,
                )
                if not alive:
                    lost.set()
                    return
                await heartbeat_db.commit()
    except Exception:
        lost.set()
        raise


async def traffit_integration_worker_loop() -> None:
    """Run inbox/outbox every few seconds and polling at five-minute cadence."""
    if not integration_master_enabled():
        logger.info("Traffit integration worker disabled by master kill-switch")
        return
    worker_id = _worker_id()
    poll_elapsed = 300.0
    interval = max(
        1.0,
        min(float(os.environ.get("TRAFFIT_INTEGRATION_WORKER_INTERVAL_SECONDS", "5")), 30.0),
    )
    poll_interval = max(
        300.0,
        float(os.environ.get("TRAFFIT_INTEGRATION_POLL_INTERVAL_SECONDS", "300")),
    )

    generation = None
    try:
        while integration_master_enabled():
            generation = None
            heartbeat_task = None
            heartbeat_stop = asyncio.Event()
            lease_lost = asyncio.Event()
            try:
                async with AsyncSessionLocal() as db:
                    lease = await acquire_lease(
                        db,
                        name=LEASE_NAME,
                        holder_id=worker_id,
                        ttl=LEASE_TTL,
                        metadata={"component": "traffit_integration"},
                    )
                    await db.commit()
                    if not lease.acquired:
                        await asyncio.sleep(interval)
                        continue
                    generation = lease.generation
                    assert generation is not None
                    heartbeat_task = asyncio.create_task(
                        _lease_heartbeat_loop(
                            worker_id, generation, heartbeat_stop, lease_lost
                        )
                    )
                    control = await effective_control(db)

                    # Credentials are opened only by the elected leader.
                    async with TraffitClient(
                        TraffitConfig.from_env(),
                        scope=integration_scopes_from_env(),
                    ) as client:
                        await refresh_contracts_if_due(
                            db,
                            client,
                            interval=timedelta(
                                seconds=max(
                                    300,
                                    int(
                                        os.environ.get(
                                            "TRAFFIT_INTEGRATION_SCHEMA_REFRESH_INTERVAL_SECONDS",
                                            "86400",
                                        )
                                    ),
                                )
                            ),
                        )
                        await db.commit()
                        # Receiver acceptance and durable queue processing are
                        # separate gates: pausing new webhooks must not strand
                        # already accepted inbox rows.
                        await run_inbox_batch(
                            db,
                            client,
                            worker_id=worker_id,
                            apply_changes=(
                                control.inbound_apply_enabled and not control.dry_run
                            ),
                        )
                        if lease_lost.is_set():
                            raise RuntimeError("Traffit integration lease lost")
                        if control.outbound_enabled or control.dry_run:
                            await run_outbound_batch(
                                db,
                                client,
                                worker_id=worker_id,
                                dry_run=control.dry_run,
                            )
                        queued_run = await db.scalar(
                            select(TraffitSyncRun)
                            .where(TraffitSyncRun.status == "queued")
                            .order_by(TraffitSyncRun.created_at.asc())
                            .with_for_update(skip_locked=True)
                            .limit(1)
                        )
                        ran_queued = False
                        if control.poll_enabled and queued_run is not None:
                            queued_run.status = "running"
                            await db.commit()
                            await run_poll_reconcile(
                                db,
                                client,
                                mode=queued_run.mode,
                                trigger=queued_run.trigger,
                                dry_run=(
                                    control.dry_run
                                    or not control.inbound_apply_enabled
                                ),
                                leader_id=worker_id,
                                existing_run=queued_run,
                                lease_lost=lease_lost,
                            )
                            await db.commit()
                            ran_queued = True
                            poll_elapsed = 0.0
                        poll_elapsed += interval
                        if (
                            control.poll_enabled
                            and not ran_queued
                            and poll_elapsed >= poll_interval
                        ):
                            await scrub_completed_webhook_payloads(
                                db,
                                retention=timedelta(
                                    seconds=max(
                                        86400,
                                        int(
                                            os.environ.get(
                                                "TRAFFIT_INTEGRATION_WEBHOOK_PAYLOAD_RETENTION_SECONDS",
                                                "604800",
                                            )
                                        ),
                                    )
                                ),
                            )
                            reconcile_dry_run = (
                                control.dry_run
                                or not control.inbound_apply_enabled
                            )
                            last_full = await db.scalar(
                                select(TraffitSyncRun)
                                .where(
                                    TraffitSyncRun.mode == "full",
                                    TraffitSyncRun.dry_run == reconcile_dry_run,
                                )
                                .order_by(TraffitSyncRun.created_at.desc())
                                .limit(1)
                            )
                            scheduled_mode = "delta"
                            if last_full is None:
                                scheduled_mode = "full"
                            else:
                                reference = (
                                    last_full.finished_at
                                    or last_full.started_at
                                    or last_full.created_at
                                )
                                interval_seconds = max(
                                    86400,
                                    int(
                                        os.environ.get(
                                            "TRAFFIT_INTEGRATION_FULL_RECONCILE_INTERVAL_SECONDS",
                                            "604800",
                                        )
                                    ),
                                )
                                if last_full.status not in {"succeeded", "partial"}:
                                    interval_seconds = max(
                                        900,
                                        int(
                                            os.environ.get(
                                                "TRAFFIT_INTEGRATION_FULL_RETRY_INTERVAL_SECONDS",
                                                "3600",
                                            )
                                        ),
                                    )
                                if reference <= datetime.now(timezone.utc) - timedelta(
                                    seconds=interval_seconds
                                ):
                                    scheduled_mode = "full"
                            await run_poll_reconcile(
                                db,
                                client,
                                mode=scheduled_mode,
                                trigger="scheduler",
                                dry_run=reconcile_dry_run,
                                leader_id=worker_id,
                                lease_lost=lease_lost,
                            )
                            await db.commit()
                            poll_elapsed = 0.0
                    if lease_lost.is_set():
                        logger.error("Traffit worker lost its database lease")
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - loop must survive transient outages
                logger.exception("Traffit integration worker iteration failed")
            finally:
                heartbeat_stop.set()
                if heartbeat_task is not None:
                    try:
                        await heartbeat_task
                    except Exception:  # noqa: BLE001
                        logger.exception("Traffit lease heartbeat failed")
            await asyncio.sleep(interval)
    finally:
        try:
            async with AsyncSessionLocal() as db:
                # A stale generation cannot release a successor's lease.
                if generation is not None:
                    await release_lease(
                        db,
                        name=LEASE_NAME,
                        holder_id=worker_id,
                        generation=generation,
                    )
                    await db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("Failed to release Traffit integration lease")
