"""Strażnik zastoju pętli (24.11.2026): stos wątku pętli w logu, gdy pętla stoi."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from app.tasks import loop_stall_guard as guard


def _blocks_the_loop_on_purpose(seconds: float) -> None:
    # Celowo synchronicznie: tak wygląda kod, który trzyma pętlę zdarzeń.
    time.sleep(seconds)


@pytest.mark.asyncio
async def test_stall_logs_stack_of_the_loop_thread(tmp_path, caplog) -> None:
    stall_guard = guard.LoopStallGuard(0.3, path=tmp_path / "stall.txt")
    task = asyncio.create_task(stall_guard.run())
    await asyncio.sleep(0.05)
    with caplog.at_level("WARNING", logger=guard.logger.name):
        _blocks_the_loop_on_purpose(0.8)
        await asyncio.sleep(stall_guard.rearm_seconds + 0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    stalls = [r for r in caplog.records if r.getMessage() == "loop_stall"]
    assert len(stalls) == 1
    record = stalls[0]
    assert record.event_kind == "loop_stall"
    assert record.threads >= 1
    assert any("_blocks_the_loop_on_purpose" in frame for frame in record.frames)
    assert any(
        "time.sleep" not in f and "test_loop_stall_guard.py:" in f
        for f in record.frames
    )
    # Plik wyczyszczony — kolejny obrót nie loguje tego samego zastoju drugi raz.
    assert (tmp_path / "stall.txt").read_text() == ""


@pytest.mark.asyncio
async def test_no_log_without_stall(tmp_path, caplog) -> None:
    stall_guard = guard.LoopStallGuard(0.5, path=tmp_path / "stall.txt")
    task = asyncio.create_task(stall_guard.run())
    with caplog.at_level("WARNING", logger=guard.logger.name):
        await asyncio.sleep(1.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not [r for r in caplog.records if r.getMessage() == "loop_stall"]


@pytest.mark.asyncio
async def test_zero_threshold_disables_guard(monkeypatch) -> None:
    called = False

    def fake_arm(*_args, **_kwargs) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(guard.faulthandler, "dump_traceback_later", fake_arm)
    await asyncio.wait_for(guard.loop_stall_guard(0), timeout=1)
    assert called is False


@pytest.mark.asyncio
async def test_guard_failure_does_not_raise(monkeypatch, caplog) -> None:
    def broken_init(self, *_args, **_kwargs) -> None:
        raise OSError("read-only fs")

    monkeypatch.setattr(guard.LoopStallGuard, "__init__", broken_init)
    with caplog.at_level("WARNING", logger=guard.logger.name):
        await asyncio.wait_for(guard.loop_stall_guard(5), timeout=1)
    assert [r for r in caplog.records if r.getMessage() == "loop_stall guard failed"]


def test_parse_dump_keeps_only_loop_thread_frames() -> None:
    loop_id = threading.get_ident()
    dump = (
        "Timeout (0:00:05)!\n"
        "Thread 0x00000000000000ab (most recent call first):\n"
        '  File "/usr/lib/python3.13/threading.py", line 359 in wait\n'
        "\n"
        f"Thread {loop_id:#018x} (most recent call first):\n"
        '  File "/app/app/api/pipeline.py", line 3801 in build_kanban_views\n'
        '  File "/usr/local/lib/python3.13/site-packages/starlette/routing.py", line 74 in app\n'
    )
    frames, threads = guard.parse_dump(dump, loop_id)
    assert threads == 2
    assert frames == [
        "app/api/pipeline.py:3801 build_kanban_views",
        "starlette/routing.py:74 app",
    ]
