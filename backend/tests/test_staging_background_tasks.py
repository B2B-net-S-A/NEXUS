"""Staging (``NEXUS_ENV=staging``): każda pętla w tle ma decyzję „wolno / nie wolno”.

Staging stoi na pełnej kopii produkcji, więc pętla, która ruszy tam bez
decyzji, wyśle prawdziwe maile albo zsynchronizuje prawdziwe konta. Test czyta
rejestr ``app.state.background_tasks`` wprost ze źródła ``app/main.py``, bez
importu aplikacji i bez bazy.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

from app.core.staging import (
    STAGING_ALLOWED_TASKS,
    STAGING_BLOCKED_TASKS,
    stop_blocked_background_tasks,
)

MAIN = Path(__file__).resolve().parents[1] / "app" / "main.py"


def _registry_names() -> list[str]:
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            ast.unparse(t) == "app.state.background_tasks" for t in node.targets
        ):
            assert isinstance(node.value, ast.Dict)
            return [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
    raise AssertionError("nie znaleziono rejestru app.state.background_tasks w main.py")


def test_every_background_task_has_a_staging_decision():
    names = set(_registry_names())
    missing = sorted(names - STAGING_ALLOWED_TASKS - STAGING_BLOCKED_TASKS)
    assert not missing, (
        "Nowa pętla w tle bez decyzji dla stagingu — dopisz ją do "
        f"STAGING_ALLOWED_TASKS albo STAGING_BLOCKED_TASKS w app/core/staging.py: {missing}"
    )


def test_staging_lists_are_disjoint_and_have_no_stale_names():
    names = set(_registry_names())
    assert not STAGING_ALLOWED_TASKS & STAGING_BLOCKED_TASKS
    stale = sorted((STAGING_ALLOWED_TASKS | STAGING_BLOCKED_TASKS) - names)
    assert not stale, f"Nazwy spoza rejestru main.py: {stale}"


def test_mail_and_sync_loops_stay_blocked():
    for name in (
        "notification_email_outbox",
        "daily_digest_email",
        "rejection_email",
        "microsoft365_sync",
        "m365_webhook_renewal",
        "compass_lifecycle_sync",
        "cloudtalk_sync",
        "hr_m365_outbox",
        "integration_webhooks",
        "auto_full_review",
    ):
        assert name in STAGING_BLOCKED_TASKS, name


def test_blocked_task_is_cancelled_before_its_first_line():
    ran: list[str] = []

    async def loop(name: str) -> None:
        ran.append(name)
        await asyncio.sleep(3600)

    async def scenario() -> list[str]:
        tasks = {
            "queue_retention": asyncio.create_task(loop("queue_retention")),
            "daily_digest_email": asyncio.create_task(loop("daily_digest_email")),
            "nowa_petla_bez_decyzji": asyncio.create_task(
                loop("nowa_petla_bez_decyzji")
            ),
        }
        stopped = stop_blocked_background_tasks(tasks)
        await asyncio.sleep(0)
        tasks["queue_retention"].cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        return stopped

    stopped = asyncio.run(scenario())
    assert sorted(stopped) == ["daily_digest_email", "nowa_petla_bez_decyzji"]
    assert ran == ["queue_retention"]
