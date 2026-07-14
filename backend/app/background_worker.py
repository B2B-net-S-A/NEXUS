"""Singleton owner for every NEXUS periodic background loop.

FastAPI used to create all 23 loops in every web replica. This process owns the
complete registry instead. Only the PostgreSQL session advisory-lock holder
starts tasks. Each leadership term also receives a monotonic fencing token;
heartbeat writes require the current instance/token pair, so a stale leader
cannot overwrite a newer leader's operational state.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# Standalone workers do not import routers. Load the ORM registry explicitly
# before any task can trigger global mapper configuration.
import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.core.logging_config import configure_json_logging

logger = logging.getLogger(__name__)

WORKER_NAME = "scheduler"
_ADVISORY_LOCK_NAMESPACE = 0x4E455855  # signed-int32 "NEXU"
_ADVISORY_LOCK_ID = 1

ALL_LOOP_NAMES = frozenset(
    {
        "calendar_reminder",
        "match_history_ttl",
        "slack_sla_alerts",
        "contract_alerts",
        "fx_refresh",
        "competition_autofreeze",
        "cc_centroid_sync",
        "kpi_coach_nudger",
        "notification_triggers",
        "rejection_email",
        "linkedin_sync",
        "microsoft365_sync",
        "m365_rematch",
        "m365_webhook_renewal",
        "m365_recording_discovery",
        "marketplace_sweeper",
        "saved_search_alerts",
        "chat_email_fallback",
        "autenti_sweeper",
        "signing_sweeper",
        "dl_portal_expiry",
        "cloudtalk_sync",
        "traffit_sync",
    }
)


class LeadershipFenced(RuntimeError):
    """The database rejected a stale worker's heartbeat."""


@dataclass(frozen=True)
class LoopSpec:
    name: str
    factory: Callable[[], Awaitable[None]]
    enabled: Callable[[], bool] = lambda: True


@dataclass(frozen=True)
class WorkerHealth:
    status: str
    reason: str
    heartbeat_at: datetime | None = None
    expected_tasks: int = 0
    running_tasks: int = 0
    task_names: tuple[str, ...] = ()
    fencing_token: int | None = None
    version: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason": self.reason,
            "heartbeat_at": self.heartbeat_at.isoformat()
            if self.heartbeat_at
            else None,
            "expected_tasks": self.expected_tasks,
            "running_tasks": self.running_tasks,
            "task_names": list(self.task_names),
            "fencing_token": self.fencing_token,
            "version": self.version,
        }


def all_loop_specs() -> tuple[LoopSpec, ...]:
    """Return the complete web-era registry with explicit feature gates."""
    from app.api.calendar import calendar_reminder_loop
    from app.services.fx_service import fx_refresh_loop
    from app.tasks.autenti_expiry_sweeper import autenti_sweeper_loop
    from app.tasks.cc_centroid_sync import cc_centroid_sync_loop
    from app.tasks.chat_email_fallback import chat_email_fallback_loop
    from app.tasks.cloudtalk_sync import cloudtalk_sync_loop
    from app.tasks.competition_autofreeze import competition_autofreeze_loop
    from app.tasks.contract_alerts import contract_alerts_loop
    from app.tasks.dl_portal_expiry_scanner import dl_portal_expiry_loop
    from app.tasks.kpi_coach_nudger import kpi_coach_nudger_loop
    from app.tasks.linkedin_sync import linkedin_sync_loop
    from app.tasks.marketplace_sweeper import marketplace_sweeper_loop
    from app.tasks.match_history_ttl import match_history_ttl_loop
    from app.tasks.microsoft365_sync import (
        graph_subscription_renewal_loop,
        meeting_recording_discovery_loop,
        microsoft365_sync_loop,
        rematch_unlinked_emails_loop,
    )
    from app.tasks.rejection_email_loop import rejection_email_loop
    from app.tasks.saved_search_alerts import saved_search_alerts_loop
    from app.tasks.signing_sweeper import signing_sweeper_loop
    from app.tasks.slack_sla_alerts import slack_sla_alerts_loop
    from app.tasks.traffit_sync import traffit_daily_sync_loop
    from app.tasks.triggers_loop import notification_triggers_loop

    return (
        LoopSpec("calendar_reminder", calendar_reminder_loop),
        LoopSpec("match_history_ttl", match_history_ttl_loop),
        LoopSpec(
            "slack_sla_alerts",
            slack_sla_alerts_loop,
            lambda: bool(os.environ.get("SLACK_WEBHOOK_URL", "").strip()),
        ),
        LoopSpec("contract_alerts", contract_alerts_loop),
        LoopSpec("fx_refresh", fx_refresh_loop),
        LoopSpec("competition_autofreeze", competition_autofreeze_loop),
        LoopSpec("cc_centroid_sync", cc_centroid_sync_loop),
        LoopSpec("kpi_coach_nudger", kpi_coach_nudger_loop),
        LoopSpec("notification_triggers", notification_triggers_loop),
        LoopSpec("rejection_email", rejection_email_loop),
        LoopSpec(
            "linkedin_sync",
            linkedin_sync_loop,
            lambda: settings.PROXYCURL_ENABLED and bool(settings.PROXYCURL_API_KEY),
        ),
        LoopSpec(
            "microsoft365_sync",
            microsoft365_sync_loop,
            lambda: (
                settings.M365_INTEGRATION_ENABLED and settings.M365_SYNC_LOOP_ENABLED
            ),
        ),
        LoopSpec(
            "m365_rematch",
            rematch_unlinked_emails_loop,
            lambda: settings.M365_INTEGRATION_ENABLED and settings.M365_REMATCH_ENABLED,
        ),
        LoopSpec(
            "m365_webhook_renewal",
            graph_subscription_renewal_loop,
            lambda: (
                settings.M365_INTEGRATION_ENABLED and settings.M365_WEBHOOKS_ENABLED
            ),
        ),
        LoopSpec(
            "m365_recording_discovery",
            meeting_recording_discovery_loop,
            lambda: (
                settings.M365_INTEGRATION_ENABLED
                and settings.M365_RECORDING_DISCOVERY_ENABLED
            ),
        ),
        LoopSpec(
            "marketplace_sweeper",
            marketplace_sweeper_loop,
            lambda: settings.MARKETPLACE_ENABLED,
        ),
        LoopSpec("saved_search_alerts", saved_search_alerts_loop),
        LoopSpec("chat_email_fallback", chat_email_fallback_loop),
        LoopSpec(
            "autenti_sweeper",
            autenti_sweeper_loop,
            lambda: settings.AUTENTI_ENABLED,
        ),
        LoopSpec(
            "signing_sweeper",
            signing_sweeper_loop,
            lambda: settings.SIGNING_ENABLED,
        ),
        LoopSpec("dl_portal_expiry", dl_portal_expiry_loop),
        LoopSpec("cloudtalk_sync", cloudtalk_sync_loop),
        LoopSpec(
            "traffit_sync",
            traffit_daily_sync_loop,
            lambda: settings.TRAFFIT_SYNC_ENABLED,
        ),
    )


def active_loop_specs() -> tuple[LoopSpec, ...]:
    specs = all_loop_specs()
    names = {spec.name for spec in specs}
    if names != ALL_LOOP_NAMES or len(specs) != len(ALL_LOOP_NAMES):
        raise RuntimeError("background worker registry is incomplete or duplicated")
    return tuple(spec for spec in specs if spec.enabled())


def classify_worker_heartbeat(
    row: Mapping[str, object] | None,
    *,
    expected_task_names: frozenset[str],
    expected_version: str | None = None,
    now: datetime | None = None,
    stale_after_seconds: int | None = None,
) -> WorkerHealth:
    if row is None:
        return WorkerHealth(status="unhealthy", reason="missing")

    heartbeat_at = row.get("heartbeat_at")
    raw_names = row.get("task_names")
    expected = int(row.get("expected_tasks") or 0)
    running = int(row.get("running_tasks") or 0)
    token = int(row.get("fencing_token") or 0)
    version = str(row.get("version") or "unknown")
    if not isinstance(heartbeat_at, datetime) or not isinstance(raw_names, list):
        return WorkerHealth(status="unhealthy", reason="invalid_heartbeat")

    task_names = tuple(sorted(str(name) for name in raw_names))
    health_fields = {
        "heartbeat_at": heartbeat_at,
        "expected_tasks": expected,
        "running_tasks": running,
        "task_names": task_names,
        "fencing_token": token or None,
        "version": version,
    }
    if heartbeat_at.tzinfo is None:
        heartbeat_at = heartbeat_at.replace(tzinfo=timezone.utc)
        health_fields["heartbeat_at"] = heartbeat_at
    current = now or datetime.now(timezone.utc)
    max_age = max(
        1,
        stale_after_seconds
        if stale_after_seconds is not None
        else settings.BACKGROUND_WORKER_STALE_AFTER_SECONDS,
    )
    if (current - heartbeat_at).total_seconds() > max_age:
        return WorkerHealth(status="unhealthy", reason="stale", **health_fields)
    if token < 1:
        return WorkerHealth(
            status="unhealthy", reason="invalid_fencing_token", **health_fields
        )
    if str(row.get("status") or "unhealthy") != "healthy":
        return WorkerHealth(
            status="unhealthy", reason="worker_reported_unhealthy", **health_fields
        )
    if expected != running or expected != len(expected_task_names):
        return WorkerHealth(
            status="unhealthy", reason="task_count_mismatch", **health_fields
        )
    if frozenset(task_names) != expected_task_names:
        return WorkerHealth(
            status="unhealthy", reason="task_registry_mismatch", **health_fields
        )
    if (
        expected_version
        and expected_version != "unknown"
        and version != expected_version
    ):
        return WorkerHealth(
            status="unhealthy", reason="version_mismatch", **health_fields
        )
    return WorkerHealth(status="healthy", reason="ok", **health_fields)


async def get_background_worker_health() -> WorkerHealth:
    if not settings.BACKGROUND_WORKER_ENABLED:
        return WorkerHealth(status="disabled", reason="rollout_kill_switch")

    expected_names = frozenset(spec.name for spec in active_loop_specs())
    try:
        async with AsyncSessionLocal() as session:
            result = await asyncio.wait_for(
                session.execute(
                    text(
                        "SELECT status, heartbeat_at, expected_tasks, running_tasks, "
                        "task_names, fencing_token, version "
                        "FROM background_worker_heartbeats "
                        "WHERE worker_name = :worker_name"
                    ),
                    {"worker_name": WORKER_NAME},
                ),
                timeout=2.0,
            )
            row = result.mappings().one_or_none()
    except Exception:
        logger.warning("background worker heartbeat query failed", exc_info=True)
        return WorkerHealth(status="unhealthy", reason="query_failed")

    return classify_worker_heartbeat(
        row,
        expected_task_names=expected_names,
        expected_version=os.environ.get("GIT_SHA", "unknown"),
    )


async def _schema_ready(connection: AsyncConnection) -> bool:
    ready = await connection.scalar(
        text("SELECT to_regclass('public.background_worker_heartbeats') IS NOT NULL")
    )
    await connection.commit()
    return bool(ready)


async def _try_advisory_lock(connection: AsyncConnection) -> bool:
    acquired = await connection.scalar(
        text("SELECT pg_try_advisory_lock(:namespace, :lock_id)"),
        {"namespace": _ADVISORY_LOCK_NAMESPACE, "lock_id": _ADVISORY_LOCK_ID},
    )
    await connection.commit()
    return bool(acquired)


async def _release_advisory_lock(connection: AsyncConnection) -> None:
    try:
        await connection.execute(
            text("SELECT pg_advisory_unlock(:namespace, :lock_id)"),
            {"namespace": _ADVISORY_LOCK_NAMESPACE, "lock_id": _ADVISORY_LOCK_ID},
        )
        await connection.commit()
    except Exception:
        # A broken PostgreSQL session already released its lock.
        logger.warning("background worker advisory unlock failed", exc_info=True)


async def _claim_fencing_token(
    connection: AsyncConnection,
    *,
    instance_id: str,
    started_at: datetime,
    task_names: tuple[str, ...],
) -> int:
    token = await connection.scalar(
        text(
            """
            INSERT INTO background_worker_heartbeats (
                worker_name, instance_id, fencing_token, status, started_at,
                heartbeat_at, expected_tasks, running_tasks, task_names,
                version, last_error
            ) VALUES (
                :worker_name, :instance_id, 1, 'starting', :started_at, now(),
                :expected_tasks, 0, CAST(:task_names AS jsonb), :version, NULL
            )
            ON CONFLICT (worker_name) DO UPDATE SET
                instance_id = EXCLUDED.instance_id,
                fencing_token = background_worker_heartbeats.fencing_token + 1,
                status = EXCLUDED.status,
                started_at = EXCLUDED.started_at,
                heartbeat_at = EXCLUDED.heartbeat_at,
                expected_tasks = EXCLUDED.expected_tasks,
                running_tasks = EXCLUDED.running_tasks,
                task_names = EXCLUDED.task_names,
                version = EXCLUDED.version,
                last_error = NULL
            RETURNING fencing_token
            """
        ),
        {
            "worker_name": WORKER_NAME,
            "instance_id": instance_id,
            "started_at": started_at,
            "expected_tasks": len(task_names),
            "task_names": json.dumps(task_names),
            "version": os.environ.get("GIT_SHA", "unknown"),
        },
    )
    await connection.commit()
    if token is None:
        raise RuntimeError("database did not issue a fencing token")
    return int(token)


async def _write_heartbeat(
    connection: AsyncConnection,
    *,
    instance_id: str,
    fencing_token: int,
    tasks: Mapping[str, asyncio.Task[None]],
    status: str,
    last_error: str | None = None,
) -> None:
    running = sum(not task.done() for task in tasks.values())
    result = await connection.execute(
        text(
            """
            UPDATE background_worker_heartbeats
            SET status = :status,
                heartbeat_at = now(),
                expected_tasks = :expected_tasks,
                running_tasks = :running_tasks,
                task_names = CAST(:task_names AS jsonb),
                version = :version,
                last_error = :last_error
            WHERE worker_name = :worker_name
              AND instance_id = :instance_id
              AND fencing_token = :fencing_token
            """
        ),
        {
            "worker_name": WORKER_NAME,
            "instance_id": instance_id,
            "fencing_token": fencing_token,
            "status": status,
            "expected_tasks": len(tasks),
            "running_tasks": running,
            "task_names": json.dumps(sorted(tasks)),
            "version": os.environ.get("GIT_SHA", "unknown"),
            "last_error": last_error,
        },
    )
    await connection.commit()
    if result.rowcount != 1:
        raise LeadershipFenced("worker heartbeat rejected by a newer leader")


async def _heartbeat_loop(
    connection: AsyncConnection,
    *,
    instance_id: str,
    fencing_token: int,
    tasks: Mapping[str, asyncio.Task[None]],
) -> None:
    interval = max(1, settings.BACKGROUND_WORKER_HEARTBEAT_SECONDS)
    while True:
        running = sum(not task.done() for task in tasks.values())
        status = "healthy" if running == len(tasks) else "unhealthy"
        await _write_heartbeat(
            connection,
            instance_id=instance_id,
            fencing_token=fencing_token,
            tasks=tasks,
            status=status,
            last_error=None if status == "healthy" else "loop_exited",
        )
        if status != "healthy":
            raise RuntimeError("one or more background loops exited")
        await asyncio.sleep(interval)


async def _run_leader_once() -> bool:
    """Run one leadership term; return false while another replica leads."""
    async with engine.connect() as connection:
        if not await _schema_ready(connection):
            logger.info("background worker waiting for heartbeat migration")
            return False
        if not await _try_advisory_lock(connection):
            logger.info("background worker standby: advisory lock already held")
            return False

        specs = active_loop_specs()
        instance_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc)
        task_names = tuple(sorted(spec.name for spec in specs))
        fencing_token = await _claim_fencing_token(
            connection,
            instance_id=instance_id,
            started_at=started_at,
            task_names=task_names,
        )
        tasks = {
            spec.name: asyncio.create_task(
                spec.factory(), name=f"nexus-worker:{spec.name}"
            )
            for spec in specs
        }
        heartbeat = asyncio.create_task(
            _heartbeat_loop(
                connection,
                instance_id=instance_id,
                fencing_token=fencing_token,
                tasks=tasks,
            ),
            name="nexus-worker:heartbeat",
        )
        logger.info(
            "background worker became leader token=%d loops=%s",
            fencing_token,
            task_names,
        )

        try:
            done, _ = await asyncio.wait(
                [heartbeat, *tasks.values()],
                return_when=asyncio.FIRST_COMPLETED,
            )
            completed = next(iter(done))
            if completed.cancelled():
                raise asyncio.CancelledError
            error = completed.exception()
            if error is not None:
                raise error
            raise RuntimeError(f"background task exited: {completed.get_name()}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            try:
                await _write_heartbeat(
                    connection,
                    instance_id=instance_id,
                    fencing_token=fencing_token,
                    tasks=tasks,
                    status="unhealthy",
                    last_error=type(exc).__name__[:64],
                )
            except Exception:
                logger.warning(
                    "failed to persist unhealthy worker state", exc_info=True
                )
            raise
        finally:
            heartbeat.cancel()
            for task in tasks.values():
                task.cancel()
            await asyncio.gather(heartbeat, *tasks.values(), return_exceptions=True)
            await _release_advisory_lock(connection)


async def run_worker_forever() -> None:
    if not settings.BACKGROUND_WORKER_ENABLED:
        logger.info("BACKGROUND_WORKER_ENABLED=false; scheduler has no side effects")
        await asyncio.Event().wait()
        return

    retry_seconds = max(1, settings.BACKGROUND_WORKER_LOCK_RETRY_SECONDS)
    while True:
        try:
            await _run_leader_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("background worker leadership term failed; retrying")
        await asyncio.sleep(retry_seconds)


async def _health_exit_code() -> int:
    health = await get_background_worker_health()
    print(json.dumps({"status": health.status, "reason": health.reason}))
    return 0 if health.status in {"healthy", "disabled"} else 1


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command == "run":
        configure_json_logging(debug=settings.DEBUG)
        asyncio.run(run_worker_forever())
        return
    if command == "health":
        raise SystemExit(asyncio.run(_health_exit_code()))
    raise SystemExit(f"unknown background worker command: {command}")


if __name__ == "__main__":
    main()
