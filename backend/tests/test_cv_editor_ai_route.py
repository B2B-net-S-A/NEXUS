"""Trasa `POST /api/pipeline/stages/{id}/cv-ai/selection` (Edytor CV 2, PR 3).

Granice żądania sprawdza schemat (bez bazy). Pełny przebieg — dostęp, brak
zapisu w szkicu CV, ślad użycia bez treści — wymaga bazy i biegnie w CI.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import delete, select

from app.api.cv_editor_ai import SelectionRequest, propose_for_selection
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.user import UserRole
from app.services import cv_selection_ai as ai
from tests.test_board_tasks import _cleanup, _login, _seed_user, _seed_world
from tests.test_cv_qc import _cleanup_qc, api_client  # noqa: F401 — fixture
from tests.test_dz_review import _seed_review

BASE = {
    "action": "shorten",
    "fragment": "Rozwój usług w **Java 17**",
    "block_text": "Rozwój usług w **Java 17** i Spring Boot.",
}


def test_request_accepts_the_shape_the_editor_sends() -> None:
    body = SelectionRequest(
        **BASE,
        block_kind="li",
        section="experience",
        role={
            "title": "Senior Developer 2021 – 2024",
            "employer": "Acme Bank",
            "points": ["Przeglądy kodu."],
        },
        instruction="krócej",
        previous=["Usługi w **Java 17**"],
    )
    dumped = body.model_dump(exclude_none=True)
    assert dumped["role"]["points"] == ["Przeglądy kodu."]
    assert dumped["previous"] == ["Usługi w **Java 17**"]


@pytest.mark.parametrize(
    "change",
    [
        {"action": "summarize"},
        {"fragment": "ab"},
        {
            "fragment": "x" * (ai.FRAGMENT_MAX + 1),
            "block_text": "x" * (ai.FRAGMENT_MAX + 1),
        },
        {"block_text": "y" * (ai.BLOCK_MAX + 1)},
        # Fragment musi stać w podanym akapicie — inaczej kontekst jest zmyślony.
        {"fragment": "Zupełnie inny tekst"},
        {"instruction": "z" * (ai.INSTRUCTION_MAX + 1)},
        {"previous": ["a", "b", "c", "d"]},
        {"previous": ["p" * (ai.PROPOSED_MAX + 1)]},
        {"role": {"points": ["punkt"] * 13}},
        {"role": {"title": "t" * 201}},
        {"block_kind": "h2"},
        {"section": "rodo"},
    ],
)
def test_request_bounds(change: dict) -> None:
    with pytest.raises(ValidationError):
        SelectionRequest(**{**BASE, **change})


def test_previous_proposal_may_be_as_long_as_a_proposal() -> None:
    """„Jeszcze raz” odsyła pokazaną propozycję — rozwinięcie bywa dłuższe niż
    zaznaczony fragment, więc limit fragmentu dawał 422 przy każdej próbie."""
    body = SelectionRequest(**BASE, previous=["p" * ai.PROPOSED_MAX])
    assert len(body.previous[0]) == ai.PROPOSED_MAX


def test_fragment_may_differ_from_the_block_in_spacing_and_bold_only() -> None:
    SelectionRequest(
        action="rephrase",
        fragment="Rozwój  usług w Java 17",
        block_text="Rozwój usług w **Java 17** i Spring Boot.",
    )


@pytest.mark.asyncio
async def test_integration_token_cannot_order_a_paid_proposal() -> None:
    """Token klienta OAuth działa jako konto z rolą operacyjną; propozycję AI
    do CV zamawia osoba (jak decyzje QC „mimo uwag”)."""
    from fastapi import HTTPException

    request = SimpleNamespace(state=SimpleNamespace(oauth_client_id="scrapers"))
    with pytest.raises(HTTPException) as refused:
        await propose_for_selection.__wrapped__(  # type: ignore[attr-defined]
            request=request,
            stage_id=1,
            payload=SelectionRequest(**BASE),
            current_user=SimpleNamespace(id=1),
            db=None,
        )
    assert refused.value.status_code == 403


@pytest.mark.asyncio
async def test_proposal_is_returned_and_the_draft_is_left_alone(
    api_client: AsyncClient,  # noqa: F811 — fixture z test_cv_qc
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = await _seed_world()
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    hor = await _login(api_client, hor_creds)
    stage_id = await _seed_review(world, hor, api_client)
    url = f"/api/pipeline/stages/{stage_id}/cv-ai/selection"
    calls: list[str] = []

    def fake_model(system: str, prompt: str, chain: tuple[str, ...]) -> str:
        calls.append(prompt)
        return json.dumps({"text": "Usługi w **Java 17**", "quotes": []})

    monkeypatch.setattr(ai, "_call_model", fake_model)
    monkeypatch.setattr(ai, "api_key_configured", lambda _model: True)
    try:
        async with AsyncSessionLocal() as db:
            csv = await db.scalar(
                select(CandidateStageCV).where(
                    CandidateStageCV.candidate_stage_id == stage_id
                )
            )
            csv_id = csv.id
            before = (csv.branded_draft_html, csv.edit_revision, csv.branded_status)

        ok = await api_client.post(url, headers=hor, json=BASE)
        assert ok.status_code == 200, ok.text
        body = ok.json()
        assert body["status"] == "ok" and body["action"] == "shorten"
        assert body["proposed_text"] == "Usługi w **Java 17**"
        assert body["verified"] is False and len(calls) == 1

        calls.clear()
        monkeypatch.setattr(
            ai, "_call_model", lambda *_a: json.dumps({"text": "Usługi w **Java 21**"})
        )
        rejected = (await api_client.post(url, headers=hor, json=BASE)).json()
        assert (rejected["status"], rejected["reason"], rejected["problem"]) == (
            "rejected",
            "new_fact",
            "21",
        )
        assert rejected["proposed_text"] is None

        def broken(*_a):
            raise RuntimeError("model padł")

        monkeypatch.setattr(ai, "_call_model", broken)
        down = await api_client.post(url, headers=hor, json=BASE)
        assert down.status_code == 200 and down.json()["status"] == "unavailable"

        async with AsyncSessionLocal() as db:
            csv = await db.get(CandidateStageCV, csv_id)
            assert (
                csv.branded_draft_html,
                csv.edit_revision,
                csv.branded_status,
            ) == before
            logged = (
                await db.scalars(
                    select(Activity)
                    .where(
                        Activity.action == "cv_selection_ai",
                        Activity.entity_type == "candidate_stage_cv",
                        Activity.entity_id == csv_id,
                    )
                    .order_by(Activity.id)
                )
            ).all()
            # Dwa wpisy: propozycja i odmowa. Awaria modelu nie zostawia wpisu.
            assert [row.details["status"] for row in logged] == ["ok", "rejected"]
            assert logged[1].details["reason"] == "new_fact"
            # W śladzie nie ma treści CV ani propozycji.
            assert "Java" not in json.dumps([row.details for row in logged])
            await db.execute(
                delete(Activity).where(
                    Activity.entity_type == "candidate_stage_cv",
                    Activity.entity_id == csv_id,
                )
            )
            await db.commit()

        too_long = await api_client.post(
            url, headers=hor, json={**BASE, "instruction": "x" * 400}
        )
        assert too_long.status_code == 422
        missing = await api_client.post(
            "/api/pipeline/stages/999999999/cv-ai/selection", headers=hor, json=BASE
        )
        assert missing.status_code == 404
    finally:
        await _cleanup_qc(world, stage_id)
        await _cleanup(world, [hor_id])
