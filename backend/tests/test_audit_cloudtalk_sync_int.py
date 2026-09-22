"""INT-01/02/03 (audyt 22.09.2026): backfill CloudTalk jak webhook."""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from app.core.database import AsyncSessionLocal
from app.models.call import Call, CallDirection, CallStatus
from app.models.candidate import Candidate
from app.tasks import cloudtalk_sync as sync
from tests.test_cloudtalk_sync_loop import _candidate_with_phone, _drop


async def _two_candidates_same_last9() -> tuple[list[int], str]:
    for _ in range(5):
        nine = "6" + "".join(random.choice("0123456789") for _ in range(8))
        async with AsyncSessionLocal() as db:
            clash = await db.scalar(
                select(func.count(Candidate.id)).where(
                    func.right(
                        func.regexp_replace(Candidate.phone, r"[^\d]", "", "g"), 9
                    )
                    == nine
                )
            )
            if clash:
                continue
            a = Candidate(name="Amb", lastname=f"A-{uuid.uuid4().hex[:6]}", phone=nine)
            b = Candidate(
                name="Amb", lastname=f"B-{uuid.uuid4().hex[:6]}", phone=f"+48 {nine}"
            )
            db.add_all([a, b])
            await db.commit()
            return [a.id, b.id], f"0048{nine}"
    raise RuntimeError("no free phone")


async def test_ambiguous_phone_is_stored_unassigned_not_guessed():
    ids, phone = await _two_candidates_same_last9()
    ct_id = f"ct-amb-{uuid.uuid4().hex}"
    try:
        async with AsyncSessionLocal() as db:
            assert await sync._upsert_call(db, {"id": ct_id, "phone": phone}) == 1
            await db.commit()
        async with AsyncSessionLocal() as db:
            row = await db.scalar(select(Call).where(Call.cloudtalk_call_id == ct_id))
        assert row is not None
        assert row.candidate_id is None, "2+ matches → NULL, never LIMIT 1"
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Call).where(Call.cloudtalk_call_id == ct_id))
            await db.execute(delete(Candidate).where(Candidate.id.in_(ids)))
            await db.commit()


async def test_initiated_stub_moves_to_final_status_but_final_stays():
    cand_id, phone = await _candidate_with_phone()
    ct_id = f"ct-init-{uuid.uuid4().hex}"
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                Call(
                    candidate_id=cand_id,
                    direction=CallDirection.outbound,
                    status=CallStatus.initiated,
                    cloudtalk_call_id=ct_id,
                )
            )
            await db.commit()
        async with AsyncSessionLocal() as db:
            touched = await sync._upsert_call(
                db, {"id": ct_id, "phone": phone, "status": "missed"}
            )
            await db.commit()
        assert touched == 1
        async with AsyncSessionLocal() as db:
            await sync._upsert_call(
                db, {"id": ct_id, "phone": phone, "status": "answered"}
            )
            await db.commit()
        async with AsyncSessionLocal() as db:
            row = await db.scalar(select(Call).where(Call.cloudtalk_call_id == ct_id))
        assert row.status == CallStatus.missed, "initiated → final, then monotonic"
    finally:
        await _drop(cand_id)


async def test_existing_webhook_row_is_backfilled_even_without_phone_match():
    ct_id = f"ct-orphan-{uuid.uuid4().hex}"
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                Call(
                    candidate_id=None,
                    direction=CallDirection.inbound,
                    status=CallStatus.completed,
                    cloudtalk_call_id=ct_id,
                )
            )
            await db.commit()
        ghost = "5" + str(uuid.uuid4().int)[:8]
        async with AsyncSessionLocal() as db:
            touched = await sync._upsert_call(
                db, {"id": ct_id, "phone": ghost, "transcript": "Rozmowa"}
            )
            await db.commit()
        assert touched == 1
        async with AsyncSessionLocal() as db:
            row = await db.scalar(select(Call).where(Call.cloudtalk_call_id == ct_id))
        assert row.transcript == "Rozmowa"
        assert row.candidate_id is None
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Call).where(Call.cloudtalk_call_id == ct_id))
            await db.commit()


async def test_window_is_always_the_full_backfill_window(monkeypatch):
    """A fresh call must NOT shrink the window to max(started_at)."""
    cand_id, _phone = await _candidate_with_phone()
    seen: dict = {}

    class _Client:
        def __init__(self, _cfg):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def list_calls(self, **kw):
            seen.update(kw)
            return []

    monkeypatch.setattr(sync.settings, "CLOUDTALK_HISTORICAL_BACKFILL_DAYS", 30)
    monkeypatch.setattr(
        sync.CloudTalkConfig, "from_settings", staticmethod(lambda: object())
    )
    monkeypatch.setattr(sync, "CloudTalkClient", _Client)
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                Call(
                    candidate_id=cand_id,
                    direction=CallDirection.inbound,
                    status=CallStatus.completed,
                    cloudtalk_call_id=f"ct-new-{uuid.uuid4().hex}",
                    started_at=datetime.now(timezone.utc) - timedelta(minutes=5),
                )
            )
            await db.commit()
        await sync._run_sync_window()
        since = datetime.strptime(seen["date_from"], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
        age = datetime.now(timezone.utc) - since
        assert timedelta(days=29, hours=23) < age < timedelta(days=30, minutes=5)
    finally:
        await _drop(cand_id)
