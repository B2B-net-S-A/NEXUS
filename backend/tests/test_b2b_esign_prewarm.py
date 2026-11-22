"""Lista zaufanych UE wczytana z wyprzedzeniem także w procesie web (22.11.2026).

Podpisany PDF waliduje trasa w web (``api/b2b_esign.py``), a lista to pamięć
procesu (``qualified._registry``). Do 22.11 wczytywała ją tylko pętla
``b2b_esign_sweeper``, czyli worker, więc pierwsze wgranie po każdym
wdrożeniu pobierało całą listę w żądaniu HTTP. Bez bazy i bez sieci.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.process_role import keep_tasks_for_role
from app.services import background_task_health as health
from app.services.b2b_esign import qualified
from app.tasks.b2b_esign_sweeper import prewarm_trusted_list

MAIN = Path(__file__).resolve().parents[1] / "app" / "main.py"


def test_lifespan_registers_the_prewarm_as_its_own_task() -> None:
    source = MAIN.read_text(encoding="utf-8")
    assert re.search(
        r'^ +"trusted_list_prewarm": asyncio\.create_task\(prewarm_trusted_list\(\)\)',
        source,
        re.M,
    )


@pytest.mark.parametrize(
    ("role", "starts"), [("web", True), ("all", True), ("worker", False)]
)
async def test_prewarm_starts_in_web_without_holding_startup(
    monkeypatch: pytest.MonkeyPatch, role: str, starts: bool
) -> None:
    monkeypatch.setattr(settings, "B2B_ESIGN_VALIDATOR", "pyhanko")
    calls: list[str] = []
    release = asyncio.Event()

    async def _slow_registry() -> object:
        calls.append("fetch")
        await release.wait()  # pobranie listy trwa ok. 20 s
        return object()

    async def _sweeper() -> None:
        await asyncio.sleep(3600)

    monkeypatch.setattr(qualified, "trusted_registry", _slow_registry)
    tasks = keep_tasks_for_role(
        {
            "trusted_list_prewarm": asyncio.create_task(prewarm_trusted_list()),
            "b2b_esign_sweeper": asyncio.create_task(_sweeper()),
        },
        role,
    )
    await asyncio.sleep(0)

    assert ("trusted_list_prewarm" in tasks) is starts
    assert calls == (["fetch"] if starts else [])
    if starts:
        # Start idzie dalej, choć lista jeszcze się pobiera.
        assert not tasks["trusted_list_prewarm"].done()
        release.set()
        await tasks["trusted_list_prewarm"]
    for task in tasks.values():
        task.cancel()
    await asyncio.gather(*tasks.values(), return_exceptions=True)


async def test_failed_prewarm_is_a_warning_not_a_crashed_task(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(settings, "B2B_ESIGN_VALIDATOR", "pyhanko")

    async def _down() -> object:
        raise OSError("ec.europa.eu nie odpowiada")

    monkeypatch.setattr(qualified, "trusted_registry", _down)
    caplog.set_level(logging.WARNING, logger="app.tasks.b2b_esign_sweeper")
    task = asyncio.create_task(prewarm_trusted_list())
    await asyncio.gather(task, return_exceptions=True)

    status = health.classify_background_tasks({"trusted_list_prewarm": task})
    assert status["crashed"] == 0
    assert status["exited_cleanly"] == ["trusted_list_prewarm"]
    assert "wstępne pobranie listy UE nie wyszło" in caplog.text


async def test_dss_validator_skips_the_eu_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "B2B_ESIGN_VALIDATOR", "dss")
    calls: list[str] = []

    async def _registry() -> object:
        calls.append("fetch")
        return object()

    monkeypatch.setattr(qualified, "trusted_registry", _registry)
    await prewarm_trusted_list()
    assert calls == []


async def test_successful_fetch_logs_a_line(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Linia, po której w logu web widać, że lista jest w pamięci procesu."""

    async def _ok() -> object:
        return object()

    monkeypatch.setattr(qualified, "_registry", None)
    monkeypatch.setattr(qualified, "_loaded_at", 0.0)
    monkeypatch.setattr(qualified, "_fetch_registry", _ok)
    caplog.set_level(logging.INFO, logger="app.services.b2b_esign.qualified")
    assert await qualified.trusted_registry(now=1000.0) is not None
    assert "lista zaufanych UE pobrana w" in caplog.text
