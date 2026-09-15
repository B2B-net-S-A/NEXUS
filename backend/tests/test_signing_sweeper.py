"""`signing_sweeper` — expiry of overdue in-house signatures.

`_expire_overdue` runs against the real Postgres. The sweep is global (it
flips every overdue row in the table), so the assertions only look at the rows
this file seeds; the notification emitter is replaced so the test controls
whether it succeeds.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.document_signature import DocumentSignature, SignatureStatus
from app.models.notification import NotificationType
from app.models.user import User, UserRole
from app.tasks import signing_sweeper as sweeper


async def _seed(plan: dict[str, tuple[str, SignatureStatus, timedelta | None]]) -> dict:
    """Create one contract and a signature per ``plan`` entry.

    ``plan`` maps a label to (provider, status, expires_at offset from now).
    """
    u = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"sweeper-{u}@example.com",
            password_hash=hash_password("x"),
            name="Sweeper Sender",
            role=UserRole.admin,
            is_active=True,
        )
        client = Client(name=f"Sweeper {u}")
        cand = Candidate(name="Jan", lastname=f"Sweeper-{u}")
        db.add_all([user, client, cand])
        await db.flush()
        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
        )
        db.add(contract)
        await db.flush()
        ids: dict[str, int] = {}
        for label, (provider, status, offset) in plan.items():
            sig = DocumentSignature(
                contract_id=contract.id,
                provider=provider,
                provider_ref=f"{label}-{u}" if provider == "autenti" else None,
                signature_type="QES",
                status=status,
                sender_user_id=user.id,
                signer_email=f"signer-{label}-{u}@example.com",
                signer_first_name="Jan",
                signer_last_name="Kowalski",
                expires_at=(now + offset) if offset is not None else None,
            )
            db.add(sig)
            await db.flush()
            ids[label] = sig.id
        await db.commit()
        return {
            "sig_ids": ids,
            "contract_id": contract.id,
            "user_id": user.id,
            "client_id": client.id,
            "candidate_id": cand.id,
        }


async def _statuses(seed: dict) -> dict[str, SignatureStatus]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(DocumentSignature.id, DocumentSignature.status).where(
                    DocumentSignature.id.in_(list(seed["sig_ids"].values()))
                )
            )
        ).all()
    by_id = dict(rows)
    return {label: by_id[sid] for label, sid in seed["sig_ids"].items()}


async def _expired_activities(seed: dict) -> int:
    async with AsyncSessionLocal() as db:
        return len(
            (
                await db.execute(
                    select(Activity.id).where(
                        Activity.entity_type == "contract",
                        Activity.entity_id == seed["contract_id"],
                        Activity.action == "signature_expired",
                    )
                )
            ).all()
        )


async def _cleanup(seed: dict) -> None:
    from app.models.notification import Notification

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(Activity).where(
                Activity.entity_type == "contract",
                Activity.entity_id == seed["contract_id"],
            )
        )
        await db.execute(
            delete(Notification).where(Notification.user_id == seed["user_id"])
        )
        await db.execute(
            delete(DocumentSignature).where(
                DocumentSignature.contract_id == seed["contract_id"]
            )
        )
        await db.execute(delete(Contract).where(Contract.id == seed["contract_id"]))
        await db.execute(delete(Candidate).where(Candidate.id == seed["candidate_id"]))
        await db.execute(delete(Client).where(Client.id == seed["client_id"]))
        await db.execute(delete(User).where(User.id == seed["user_id"]))
        await db.commit()


_PLAN = {
    "overdue_sent": ("upload_validate", SignatureStatus.sent, timedelta(hours=-1)),
    "overdue_progress": (
        "upload_validate",
        SignatureStatus.in_progress,
        timedelta(days=-3),
    ),
    "future_sent": ("upload_validate", SignatureStatus.sent, timedelta(hours=2)),
    "no_deadline": ("upload_validate", SignatureStatus.sent, None),
    "overdue_completed": (
        "upload_validate",
        SignatureStatus.completed,
        timedelta(hours=-1),
    ),
    "overdue_autenti": ("autenti", SignatureStatus.sent, timedelta(hours=-1)),
}


async def test_overdue_in_house_signatures_expire_with_activity_and_notice(monkeypatch):
    seed = await _seed(_PLAN)
    emitted: list[dict] = []

    async def _emit(db, **kwargs):
        emitted.append(kwargs)

    monkeypatch.setattr(sweeper, "emit_notification", _emit)
    try:
        touched = await sweeper._expire_overdue()
        statuses = await _statuses(seed)
        activities = await _expired_activities(seed)
    finally:
        await _cleanup(seed)

    assert touched >= 2
    assert statuses["overdue_sent"] == SignatureStatus.expired
    assert statuses["overdue_progress"] == SignatureStatus.expired
    assert statuses["future_sent"] == SignatureStatus.sent
    assert statuses["no_deadline"] == SignatureStatus.sent
    assert statuses["overdue_completed"] == SignatureStatus.completed
    assert statuses["overdue_autenti"] == SignatureStatus.sent, (
        "Autenti has its own sweeper"
    )
    assert activities == 2

    mine = [e for e in emitted if e["user_id"] == seed["user_id"]]
    assert {e["related_entity_id"] for e in mine} == {
        seed["sig_ids"]["overdue_sent"],
        seed["sig_ids"]["overdue_progress"],
    }
    assert all(e["ntype"] == NotificationType.signature_failed for e in mine)
    assert all(e["related_entity_type"] == "document_signature" for e in mine)


async def test_notification_failure_does_not_roll_back_the_expiry(monkeypatch):
    seed = await _seed(
        {"overdue": ("upload_validate", SignatureStatus.sent, timedelta(minutes=-5))}
    )
    monkeypatch.setattr(
        sweeper, "emit_notification", AsyncMock(side_effect=RuntimeError("smtp down"))
    )
    try:
        await sweeper._expire_overdue()
        statuses = await _statuses(seed)
        activities = await _expired_activities(seed)
    finally:
        await _cleanup(seed)

    assert statuses["overdue"] == SignatureStatus.expired
    assert activities == 1


async def test_second_sweep_does_not_touch_already_expired_rows(monkeypatch):
    seed = await _seed(
        {"overdue": ("upload_validate", SignatureStatus.sent, timedelta(minutes=-5))}
    )
    emit = AsyncMock()
    monkeypatch.setattr(sweeper, "emit_notification", emit)
    try:
        await sweeper._expire_overdue()
        await sweeper._expire_overdue()
        activities = await _expired_activities(seed)
    finally:
        await _cleanup(seed)

    assert activities == 1
    assert (
        sum(1 for c in emit.await_args_list if c.kwargs["user_id"] == seed["user_id"])
        == 1
    )


async def test_disabled_signing_exits_before_the_loop(monkeypatch):
    monkeypatch.setattr(sweeper.settings, "SIGNING_ENABLED", False)

    async def _forbidden(*_a, **_kw):
        raise AssertionError("a disabled sweeper must not wait or sweep")

    monkeypatch.setattr(sweeper.asyncio, "sleep", _forbidden)
    monkeypatch.setattr(sweeper, "_expire_overdue", _forbidden)

    assert await sweeper.signing_sweeper_loop() is None


async def test_loop_survives_a_failing_tick_and_clamps_interval(monkeypatch):
    monkeypatch.setattr(sweeper.settings, "SIGNING_ENABLED", True)
    monkeypatch.setattr(sweeper.settings, "SIGNING_SWEEPER_INTERVAL_SECONDS", 10)
    tick = AsyncMock(side_effect=[RuntimeError("db down"), 3])
    sleep = AsyncMock(side_effect=[None, asyncio.CancelledError])
    monkeypatch.setattr(sweeper, "_expire_overdue", tick)
    monkeypatch.setattr(sweeper.asyncio, "sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        await sweeper.signing_sweeper_loop()

    assert tick.await_count == 2
    assert [c.args for c in sleep.await_args_list] == [(300,), (300,)]
