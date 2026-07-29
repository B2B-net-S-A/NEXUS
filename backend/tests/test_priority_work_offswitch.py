"""Priority Work przy RECRUITMENT_PRIORITY_MODE=off ma być BEZCZYNNY.

Dwie regresje w jednym miejscu:

1. `priority_work_loop` nie miał kill-switcha — mimo domyślnego mode=off wchodził
   w `while True` i co 300 s robił pełny przemiał (SELECT ... FOR UPDATE na
   singletonie + cztery `count()` po `recruitment_processes`), bo bramka trybu
   siedzi dopiero w środku sweepa. Reszta pętli w tym repo (np. `cloudtalk_sync`)
   sprawdza flagę RAZ, przed pętlą. Health raportował przy tym „disabled", więc
   operator nie miał żadnego sygnału, że sweep jednak chodzi.

2. Przy mode=off `alert_specs` jest z definicji puste, więc auto-resolve zamykał
   KAŻDY otwarty alert. Rollback shadow → off (albo ostatni tick starego workera
   w czasie rolling restartu) po cichu czyścił listę alertów zebranych w shadow.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest


async def test_loop_exits_before_touching_db_at_mode_off(monkeypatch) -> None:
    """Pętla ma wyjść PRZED otwarciem sesji, a nie budzić się co interwał."""
    from app.core.config import settings
    from app.tasks import priority_work

    monkeypatch.setattr(settings, "RECRUITMENT_PRIORITY_MODE", "off")

    def _explode(*args, **kwargs):  # pragma: no cover - ma się nie wykonać
        raise AssertionError(
            "priority_work_loop otworzył sesję DB mimo RECRUITMENT_PRIORITY_MODE=off"
        )

    monkeypatch.setattr(priority_work, "AsyncSessionLocal", _explode)

    # wait_for pilnuje, że to return, a nie uśpiona pętla.
    await asyncio.wait_for(priority_work.priority_work_loop(), timeout=5)


async def test_loop_starts_when_mode_enabled(monkeypatch) -> None:
    """Kontrola negatywna — kill-switch nie może wyłączyć trybu shadow."""
    from app.core.config import settings
    from app.tasks import priority_work

    monkeypatch.setattr(settings, "RECRUITMENT_PRIORITY_MODE", "shadow")

    swept = asyncio.Event()

    async def _fake_sweep(db):
        swept.set()
        return {}

    monkeypatch.setattr(priority_work, "run_priority_work_sweep", _fake_sweep)

    task = asyncio.create_task(priority_work.priority_work_loop())
    try:
        await asyncio.wait_for(swept.wait(), timeout=5)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def _seed_open_alert() -> str:
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_priority import (
        PriorityAlertSeverity,
        RecruitmentPriorityAlert,
    )

    dedupe_key = f"test-orphan-{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        db.add(
            RecruitmentPriorityAlert(
                dedupe_key=dedupe_key,
                kind="test_orphan",
                severity=PriorityAlertSeverity.warning,
                payload={},
                first_seen_at=now - timedelta(minutes=5),
                last_seen_at=now,
            )
        )
        await db.commit()
    return dedupe_key


async def _resolved_at(dedupe_key: str):
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_priority import RecruitmentPriorityAlert
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(RecruitmentPriorityAlert.resolved_at).where(
                RecruitmentPriorityAlert.dedupe_key == dedupe_key
            )
        )


async def test_sweep_at_mode_off_does_not_wipe_open_alerts(monkeypatch) -> None:
    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.tasks.priority_work import run_priority_work_sweep

    monkeypatch.setattr(settings, "RECRUITMENT_PRIORITY_MODE", "off")
    dedupe_key = await _seed_open_alert()

    async with AsyncSessionLocal() as db:
        await run_priority_work_sweep(db)
        await db.commit()

    assert await _resolved_at(dedupe_key) is None, (
        "sweep przy mode=off zamknął alert — rollback shadow → off czyści "
        "listę otwartych alertów"
    )


async def test_sweep_still_resolves_stale_alerts_when_enabled(monkeypatch) -> None:
    """Kontrola negatywna — auto-resolve ma nadal działać w trybie aktywnym."""
    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.tasks.priority_work import run_priority_work_sweep

    monkeypatch.setattr(settings, "RECRUITMENT_PRIORITY_MODE", "shadow")
    dedupe_key = await _seed_open_alert()

    async with AsyncSessionLocal() as db:
        await run_priority_work_sweep(db)
        await db.commit()

    assert await _resolved_at(dedupe_key) is not None
