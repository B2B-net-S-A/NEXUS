"""AI w edytorze CV pod kontraktem zakresu rekrutacji (audyt 13.10.2026).

`cv-ai/selection` i `cv-ai/command` czytają CV jednej pary i wołają płatny
model, a moduł `app.api.cv_editor_ai` nie był w `_SCOPED_MODULES`
kontraktu (`tests/test_job_scope_contract.py`). Dziś obie trasy wołają
`ensure_job_membership`, ale nowa trasa w tym module bez tej bramki
przeszłaby zielono. Odmowa bramki (403) pada, zanim cokolwiek trafi do modelu.

Kogo bramka odrzuca, mówi reguła z 23.09.2026 („Rekrutacje i kandydatów
widzą wszyscy”): role operacyjne — także rekruter spoza zespołu — przechodzą
z samym sprawdzeniem, że rekrutacja istnieje. 403 dostaje dawny podgląd
(`user`). Test HTTP przypina oba przypadki.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select

from app.api import cv_editor_ai as route
from app.api.cv_editor_ai import CommandRequest, SelectionRequest
from app.models.user import UserRole
from tests.test_cv_qc import api_client  # noqa: F401 — fixture
from tests.test_job_scope_contract import _SCOPED_MODULES, _scoped_routes

SELECTION = {
    "action": "shorten",
    "fragment": "Rozwój usług w **Java 17**",
    "block_text": "Rozwój usług w **Java 17** i Spring Boot.",
}
COMMAND = {
    "preset": "shorten",
    "lines": [{"id": 0, "kind": "bullet", "text": "Rozwój usług w Java 17."}],
}


def test_cv_editor_ai_routes_are_under_the_scope_contract() -> None:
    assert "app.api.cv_editor_ai" in _SCOPED_MODULES
    routes = {(method, path): ok for method, path, ok in _scoped_routes()}
    for path in (
        "/api/pipeline/stages/{stage_id}/cv-ai/selection",
        "/api/pipeline/stages/{stage_id}/cv-ai/command",
        # Edytor CV 3, PR 4: „Tak, dopisz” zapisuje notatkę pary.
        "/api/pipeline/stages/{stage_id}/cv-ai/confirm-fact",
    ):
        assert routes.get(("POST", path)) is True, path


class _Db:
    def __init__(self) -> None:
        self.committed = False

    async def get(self, _model, _id):
        return SimpleNamespace(id=5, job_id=9)

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
async def test_outsider_is_refused_before_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = AsyncMock(side_effect=HTTPException(403, "Brak dostępu."))
    selection = AsyncMock()
    plan = AsyncMock()
    confirm = AsyncMock()
    monkeypatch.setattr(route, "ensure_job_membership", guard)
    monkeypatch.setattr(route.cv_selection_ai, "propose", selection)
    monkeypatch.setattr(route.cv_command_ai, "propose_plan", plan)
    monkeypatch.setattr(route.cv_command_ai, "confirm_fact", confirm)
    request = SimpleNamespace(state=SimpleNamespace())
    user = SimpleNamespace(id=1)

    for handler, payload in (
        (route.propose_for_selection, SelectionRequest(**SELECTION)),
        (route.propose_plan_for_command, CommandRequest(**COMMAND)),
        (
            route.confirm_fact_from_conversation,
            route.ConfirmFactRequest(term="Terraform"),
        ),
    ):
        db = _Db()
        with pytest.raises(HTTPException) as refused:
            await handler.__wrapped__(  # type: ignore[attr-defined]
                request=request,
                stage_id=5,
                payload=payload,
                current_user=user,
                db=db,
            )
        assert refused.value.status_code == 403
        assert db.committed is False

    assert [call.args[2] for call in guard.await_args_list] == [9, 9, 9]
    selection.assert_not_awaited()
    plan.assert_not_awaited()
    confirm.assert_not_awaited()


# ── przez HTTP, na bazie (CI) ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_viewer_is_refused_and_recruiter_outside_the_team_is_not(
    api_client: AsyncClient,  # noqa: F811 — fixture z test_cv_qc
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage
    from app.services import cv_command_ai as command_ai
    from app.services import cv_selection_ai as selection_ai
    from tests.test_board_tasks import (
        _cleanup,
        _login,
        _seed_user,
        _seed_world,
        seed_entry_row,
    )

    calls: list[str] = []

    def selection_model(*_a, **_k) -> str:
        calls.append("selection")
        return json.dumps({"text": "Usługi w **Java 17**", "quotes": []})

    def command_model(*_a, **_k) -> str:
        calls.append("command")
        return json.dumps({"operations": []})

    monkeypatch.setattr(selection_ai, "_call_model", selection_model)
    monkeypatch.setattr(selection_ai, "api_key_configured", lambda _model: True)
    monkeypatch.setattr(command_ai, "_call_model", command_model)
    monkeypatch.setattr(command_ai, "api_key_configured", lambda _model: True)
    world = await _seed_world()
    viewer_id, viewer_creds = await _seed_user(UserRole.user)
    outsider_id, outsider_creds = await _seed_user(UserRole.recruiter)
    try:
        await seed_entry_row(world["candidate_id"], world["job_id"])
        async with AsyncSessionLocal() as db:
            stage_id = await db.scalar(
                select(CandidateStage.id).where(
                    CandidateStage.candidate_id == world["candidate_id"],
                    CandidateStage.job_id == world["job_id"],
                )
            )
        base = f"/api/pipeline/stages/{stage_id}/cv-ai"

        viewer = await _login(api_client, viewer_creds)
        refused = [
            await api_client.post(f"{base}/selection", headers=viewer, json=SELECTION),
            await api_client.post(f"{base}/command", headers=viewer, json=COMMAND),
        ]
        assert [r.status_code for r in refused] == [403, 403], [r.text for r in refused]
        assert calls == []

        # Rekruter spoza zespołu przechodzi (decyzja 23.09.2026) — bez przypisania.
        outsider = await _login(api_client, outsider_creds)
        allowed = [
            await api_client.post(
                f"{base}/selection", headers=outsider, json=SELECTION
            ),
            await api_client.post(f"{base}/command", headers=outsider, json=COMMAND),
        ]
        assert [r.status_code for r in allowed] == [200, 200], [r.text for r in allowed]
        assert calls == ["selection", "command"]
    finally:
        await _cleanup(world, [viewer_id, outsider_id])
