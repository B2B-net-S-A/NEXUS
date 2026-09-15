"""`cloudtalk_sync` — kill-switch, payload parsing and idempotent upsert.

CloudTalk is switched off in production (decision 28.07), but the module stays
as the anchor for the next telephony provider. These tests keep it honest: the
disabled loop must not even start, the parsers must be defensive, and the
backfill upsert keyed on ``cloudtalk_call_id`` must never duplicate a call.
"""

from __future__ import annotations

import asyncio
import random
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import delete, func, select

from app.core.database import AsyncSessionLocal
from app.models.call import Call, CallDirection, CallStatus
from app.models.candidate import Candidate
from app.tasks import cloudtalk_sync as sync


# ── kill-switch ──────────────────────────────────────────────────────────────


async def test_disabled_integration_returns_before_the_loop(monkeypatch):
    monkeypatch.setattr(sync.settings, "CLOUDTALK_ENABLED", False)
    sleep = AsyncMock()
    run = AsyncMock()
    monkeypatch.setattr(sync.asyncio, "sleep", sleep)
    monkeypatch.setattr(sync, "_run_sync_window", run)

    assert await sync.cloudtalk_sync_loop() is None

    sleep.assert_not_awaited()
    run.assert_not_awaited()


async def test_enabled_loop_survives_a_crash_and_exits_on_cancel(monkeypatch):
    monkeypatch.setattr(sync.settings, "CLOUDTALK_ENABLED", True)
    monkeypatch.setattr(sync.settings, "CLOUDTALK_SYNC_INTERVAL_SECONDS", 10)
    run = AsyncMock(side_effect=[RuntimeError("api down"), {"skipped": True}])
    sleep = AsyncMock(side_effect=[None, asyncio.CancelledError])
    monkeypatch.setattr(sync, "_run_sync_window", run)
    monkeypatch.setattr(sync.asyncio, "sleep", sleep)

    assert await sync.cloudtalk_sync_loop() is None  # cancellation → clean return

    assert run.await_count == 2
    assert [c.args for c in sleep.await_args_list] == [(300,), (300,)]


# ── pure parsers ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (5, 300),
        (300, 300),
        (301, 301),
        ("7200", 7200),
    ],
)
def test_interval_is_clamped_to_five_minutes(monkeypatch, raw, expected):
    monkeypatch.setattr(sync.settings, "CLOUDTALK_SYNC_INTERVAL_SECONDS", raw)
    assert sync._interval_seconds() == expected


def test_parse_dt_accepts_z_suffix_and_naive_values():
    assert sync._parse_dt("2026-03-01T10:15:00Z") == datetime(
        2026, 3, 1, 10, 15, tzinfo=timezone.utc
    )
    naive = sync._parse_dt("2026-03-01 10:15:00")
    assert naive.tzinfo == timezone.utc
    offset = sync._parse_dt("2026-03-01T12:15:00+02:00")
    assert offset == datetime(2026, 3, 1, 10, 15, tzinfo=timezone.utc)


@pytest.mark.parametrize("value", [None, "", "not a date", 0, "2026-13-45"])
def test_parse_dt_returns_none_for_garbage(value):
    assert sync._parse_dt(value) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("incoming", CallDirection.inbound),
        (" Inbound ", CallDirection.inbound),
        ("in", CallDirection.inbound),
        ("outgoing", CallDirection.outbound),
        (None, CallDirection.outbound),
        ("weird", CallDirection.outbound),
    ],
)
def test_parse_direction(value, expected):
    assert sync._parse_direction(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("missed", CallStatus.missed),
        ("NO-ANSWER", CallStatus.missed),
        ("no_answer", CallStatus.missed),
        ("voicemail", CallStatus.voicemail),
        ("vm", CallStatus.voicemail),
        ("busy", CallStatus.failed),
        ("rejected", CallStatus.failed),
        ("error", CallStatus.failed),
        ("answered", CallStatus.completed),
        (None, CallStatus.completed),
    ],
)
def test_parse_status(value, expected):
    assert sync._parse_status(value) == expected


# ── _upsert_call (real DB) ───────────────────────────────────────────────────


def _unique_phone() -> tuple[str, str]:
    """Return (stored phone, differently formatted same number)."""
    digits = "".join(random.choice("0123456789") for _ in range(8))
    nine = "7" + digits  # a leading 7 keeps it a plausible PL mobile
    stored = f"+48 {nine[:3]} {nine[3:6]} {nine[6:]}"
    return stored, f"0048-{nine}"


async def _candidate_with_phone() -> tuple[int, str]:
    for _ in range(5):
        stored, alt = _unique_phone()
        async with AsyncSessionLocal() as db:
            last9 = alt[-9:]
            clash = await db.scalar(
                select(func.count(Candidate.id)).where(
                    func.right(
                        func.regexp_replace(Candidate.phone, r"[^\d]", "", "g"), 9
                    )
                    == last9
                )
            )
            if clash:
                continue
            cand = Candidate(
                name="Call", lastname=f"Sync-{uuid.uuid4().hex[:8]}", phone=stored
            )
            db.add(cand)
            await db.commit()
            return cand.id, alt
    raise RuntimeError("could not find a free phone number")


async def _drop(candidate_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Call).where(Call.candidate_id == candidate_id))
        await db.execute(delete(Candidate).where(Candidate.id == candidate_id))
        await db.commit()


async def test_upsert_inserts_once_and_is_idempotent_on_call_id():
    cand_id, phone = await _candidate_with_phone()
    ct_id = f"ct-{uuid.uuid4().hex}"
    started = datetime.now(timezone.utc) - timedelta(hours=1)
    payload = {
        "id": ct_id,
        "phone": phone,
        "type": "incoming",
        "status": "missed",
        "duration": "42",
        "started_at": started.isoformat(),
    }
    try:
        async with AsyncSessionLocal() as db:
            assert await sync._upsert_call(db, payload) == 1
            await db.commit()
        async with AsyncSessionLocal() as db:
            assert await sync._upsert_call(db, payload) == 0, "nothing new to backfill"
            await db.commit()
        async with AsyncSessionLocal() as db:
            rows = (
                (await db.execute(select(Call).where(Call.cloudtalk_call_id == ct_id)))
                .scalars()
                .all()
            )
        assert len(rows) == 1
        call = rows[0]
        assert call.candidate_id == cand_id
        assert call.direction == CallDirection.inbound
        assert call.status == CallStatus.missed
        assert call.duration_seconds == 42
        assert call.transcript is None
    finally:
        await _drop(cand_id)


async def test_upsert_backfills_missing_fields_but_keeps_first_status():
    cand_id, phone = await _candidate_with_phone()
    ct_id = f"ct-{uuid.uuid4().hex}"
    try:
        async with AsyncSessionLocal() as db:
            await sync._upsert_call(
                db, {"id": ct_id, "phone": phone, "status": "missed"}
            )
            await db.commit()
        async with AsyncSessionLocal() as db:
            touched = await sync._upsert_call(
                db,
                {
                    "call_id": ct_id,
                    "phone": phone,
                    "status": "answered",
                    "type": "incoming",
                    "transcript": "Rozmowa o projekcie",
                    "summary": "Kandydat zainteresowany",
                    "recording_url": "https://rec.example.com/1.mp3",
                },
            )
            await db.commit()
        assert touched == 1
        async with AsyncSessionLocal() as db:
            call = await db.scalar(select(Call).where(Call.cloudtalk_call_id == ct_id))
        assert call.transcript == "Rozmowa o projekcie"
        assert call.summary == "Kandydat zainteresowany"
        assert call.recording_url == "https://rec.example.com/1.mp3"
        assert call.status == CallStatus.missed, "first event wins for status"
        assert call.direction == CallDirection.outbound, (
            "first event wins for direction"
        )
    finally:
        await _drop(cand_id)


async def test_upsert_skips_payloads_without_id_or_matching_candidate():
    async with AsyncSessionLocal() as db:
        assert await sync._upsert_call(db, {"phone": "+48 700 000 000"}) == 0
        assert (
            await sync._upsert_call(db, {"id": f"ct-{uuid.uuid4().hex}", "phone": ""})
            == 0
        )
        # a number nobody has: a 9-digit suffix built from a fresh uuid
        ghost = "9" + str(uuid.uuid4().int)[:8]
        clash = await db.scalar(
            select(func.count(Candidate.id)).where(
                func.right(func.regexp_replace(Candidate.phone, r"[^\d]", "", "g"), 9)
                == ghost
            )
        )
        if not clash:
            assert (
                await sync._upsert_call(
                    db, {"id": f"ct-{uuid.uuid4().hex}", "phone": ghost}
                )
                == 0
            )
        await db.rollback()


# ── _run_sync_window ─────────────────────────────────────────────────────────


async def test_missing_credentials_skip_the_window(monkeypatch):
    def _raise():
        raise RuntimeError(
            "CLOUDTALK_API_KEY_ID and CLOUDTALK_API_KEY_SECRET must be set"
        )

    monkeypatch.setattr(sync.CloudTalkConfig, "from_settings", staticmethod(_raise))
    client = MagicMock(side_effect=AssertionError("no client without credentials"))
    monkeypatch.setattr(sync, "CloudTalkClient", client)

    assert await sync._run_sync_window() == {"skipped": True}
    client.assert_not_called()
