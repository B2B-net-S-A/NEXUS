"""Durable, sender-scoped retry gate. No recipient, content or credentials stored.

Transactions only protect state transitions; HTTP never holds a DB lock.
Healthy calls may run concurrently. After failure exactly one recovery attempt
gets a lease. A late success from before an outage cannot close that outage.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from typing import Callable
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import settings


def circuit_key() -> str:
    scope = "|".join(
        (
            settings.M365_MAIL_TENANT_ID or settings.M365_TENANT_ID,
            settings.M365_CLIENT_ID,
            settings.M365_MAIL_SENDER_UPN.lower(),
        )
    )
    return hashlib.sha256(scope.encode()).hexdigest()


@lru_cache(maxsize=1)
def _engine():
    return create_engine(
        make_url(settings.DATABASE_URL).set(drivername="postgresql+psycopg2"),
        pool_size=2,
        max_overflow=0,
        pool_timeout=2,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 2,
            "options": "-c statement_timeout=2000 -c lock_timeout=1000",
        },
    )


def transition(fn: Callable):
    with _engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO mail_delivery_state (scope, state) VALUES (:scope, '{}'::jsonb) ON CONFLICT DO NOTHING"
            ),
            {"scope": circuit_key()},
        )
        row = conn.execute(
            text(
                "SELECT state, extract(epoch FROM clock_timestamp()) AS now FROM mail_delivery_state WHERE scope=:scope FOR UPDATE"
            ),
            {"scope": circuit_key()},
        ).one()
        state = dict(row.state)
        result = fn(state, float(row.now))
        conn.execute(
            text(
                "UPDATE mail_delivery_state SET state=CAST(:state AS jsonb) WHERE scope=:scope"
            ),
            {"scope": circuit_key(), "state": json.dumps(state)},
        )
        return result


def snapshot() -> dict:
    with _engine().connect() as conn:
        value = conn.execute(
            text("SELECT state FROM mail_delivery_state WHERE scope=:scope"),
            {"scope": circuit_key()},
        ).scalar_one_or_none()
        return dict(value or {})


def acquire() -> int | None:
    def apply(s, now):
        if s.get("next_attempt_at", 0) > now or s.get("lease_until", 0) > now:
            return None
        generation = s.get("generation", 0)
        if s.get("consecutive_failures", 0):
            # Lease outlives both the initial POST and one token-refresh POST.
            s["lease_until"] = now + 90
            s["generation"] = generation = generation + 1
        return generation

    return transition(apply)


def finish(ticket: int, *, code: str | None, retry_after: float = 0) -> bool:
    """Record every attempted result; return True only on incident/recovery transition."""

    def apply(s, now):
        s["attempts"] = s.get("attempts", 0) + 1
        if code is None:
            s["last_success_at"] = now
            if ticket != s.get("generation", 0):
                return False
            changed = bool(s.get("consecutive_failures", 0))
            s.update(consecutive_failures=0, next_attempt_at=0, lease_until=0)
            return changed
        s["failures"] = s.get("failures", 0) + 1
        # Stale results count but cannot overwrite a newer probe's decision.
        if ticket != s.get("generation", 0):
            return False
        changed = (
            not s.get("consecutive_failures", 0) or s.get("last_failure_code") != code
        )
        if changed:
            s["incident_id"] = str(uuid4())
        failures = s.get("consecutive_failures", 0) + 1
        delay = (
            900
            if code in {"http_403", "http_401", "token"}
            else min(900, 60 * 2 ** min(failures - 1, 4))
        )
        s.update(
            consecutive_failures=failures,
            last_failure_code=code,
            last_failure_at=now,
            next_attempt_at=now + max(delay, retry_after),
            lease_until=0,
            generation=ticket + 1,
        )
        return changed

    return transition(apply)
