"""Martwa pętla w tle musi być POLICZALNA, nie ukryta w nierównym ułamku.

`_background_tasks_status` raportowało tylko `running` i `expected`. Ten ułamek
jest z założenia nierówny: większość zarejestrowanych pętli kończy się CELOWO
przed swoim `while True`, bo sprawdza własny kill-switch (`AUTENTI_ENABLED`,
`AI_INDEX_WORKER_ENABLED`, `CLOUDTALK_ENABLED`, …). Więc `running: 22,
expected: 34` to zdrowy odczyt, a `running: 21` — jedna pętla PADŁA — jest od
niego nieodróżnialny. Nic w kodzie nie odtwarza zakończonego taska, więc taka
pętla jest martwa do najbliższego deployu (alerty z zapisanych wyszukiwań albo
przypomnienia o rozmowach po prostu przestają przychodzić).

`crashed` przy zdrowej instalacji wynosi ZERO — i dopiero taka liczba nadaje
się na alert.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api.admin_snapshot import _background_tasks_status

BACKEND = Path(__file__).resolve().parents[1]


def _request_with(tasks: dict) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(background_tasks=tasks)))


@pytest.mark.asyncio
async def test_crashed_is_separated_from_a_clean_kill_switch_exit() -> None:
    async def _alive() -> None:
        await asyncio.sleep(3600)

    async def _exits_on_kill_switch() -> None:
        return

    async def _crashes() -> None:
        raise RuntimeError("boom")

    alive = asyncio.create_task(_alive())
    quiet = asyncio.create_task(_exits_on_kill_switch())
    dead = asyncio.create_task(_crashes())
    await asyncio.sleep(0)
    await asyncio.gather(quiet, dead, return_exceptions=True)

    status = _background_tasks_status(
        _request_with({"alive": alive, "quiet": quiet, "dead": dead})
    )

    alive.cancel()
    await asyncio.gather(alive, return_exceptions=True)

    assert status["running"] == 1
    assert status["expected"] == 3
    assert status["exited_cleanly"] == ["quiet"], (
        "powrót z kill-switcha to stan ZDROWY — wliczenie go do awarii "
        "sprawiłoby, że alarm dzwoni zawsze i przestaje cokolwiek znaczyć"
    )
    assert status["crashed"] == 1
    assert "dead" in status["crashed_tasks"]
    assert "RuntimeError" in status["crashed_tasks"]["dead"], (
        "repr wyjątku musi wyjść na zewnątrz — inaczej operator wie tylko, "
        "że COŚ padło"
    )


@pytest.mark.asyncio
async def test_healthy_install_reports_zero_crashed() -> None:
    async def _exits() -> None:
        return

    quiet = asyncio.create_task(_exits())
    await asyncio.gather(quiet, return_exceptions=True)
    status = _background_tasks_status(_request_with({"quiet": quiet}))
    assert status["crashed"] == 0


def test_missing_registry_does_not_explode() -> None:
    status = _background_tasks_status(_request_with(None))
    assert status["crashed"] == 0
    assert status["expected"] == 0


def test_lifespan_logs_task_death_at_error_level() -> None:
    """Silna referencja w rejestrze tłumi wbudowany log asyncio „Task exception
    was never retrieved", więc bez własnego callbacku wyjątek nie pojawiłby się
    NIGDZIE. `logger.error` jest progiem, od którego Sentry robi zdarzenie."""
    src = (BACKEND / "app/main.py").read_text(encoding="utf-8")
    assert "add_done_callback" in src
    assert "background task %r died" in src


def test_shutdown_waits_for_every_task_even_after_one_died() -> None:
    """`await t` na tasku, który padł na PRAWDZIWYM wyjątku, podnosił go
    ponownie i przerywał pętlę zamykania — reszta tasków nie była doczekana,
    a `engine.dispose()` nie leciało wcale."""
    src = (BACKEND / "app/main.py").read_text(encoding="utf-8")
    at = src.index("    # Shutdown")
    window = src[at : at + 1200]
    assert "asyncio.gather(*tasks, return_exceptions=True)" in window
    assert "engine.dispose()" in window


def test_health_exposes_crashed_loops() -> None:
    """`/api/admin/snapshot` stoi za autoryzacją admina i nikt go nie odpytuje;
    `/api/health` to jedyne miejsce, w którym automatyczny czytelnik to zobaczy."""
    src = (BACKEND / "app/main.py").read_text(encoding="utf-8")
    assert 'checks["background_tasks"]' in src
