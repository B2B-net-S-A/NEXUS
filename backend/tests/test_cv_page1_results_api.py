"""Trasa „najmocniejszy wynik” strony 1 i wyzwalacz po przełączeniu układu (22.11.2026).

- POST …/cv/page1/results liczy wyniki z bieżącego szkicu i zapisuje je
  w `page1_extras` obok innych kluczy; awaria modelu = 503, dodatki bez zmian,
- przełączenie na „Nowe CV” zleca bieg w tle po commicie,
- bieg w tle pomija CV z aktualnym `results_source_sha`.

Model zawsze podmieniony (`_call_model`, zdania 1–3 `_call_why_model`) — dane
fikcyjne. Trasa liczy też zdania 1–3 (`cv_page1_why`).
"""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate_stage_cv import CandidateStageCV
from app.services import cv_page1_results as service
from app.services.cv_generator_b2b.html_export import render_interactive_html
from app.services.cv_page1_result_checks import source_sha
from tests.test_candidate_stage_cv_branded import _seed_draft, _seed_full_stage

QUOTE = "ograniczyły liczbę defektów produkcyjnych o około 30% w systemie płatności"
RESULT = {
    "text": "Ograniczenie defektów produkcyjnych o **około 30%** w Acme Bank",
    "quote": QUOTE,
    "company": "Acme Bank",
}
HTML = render_interactive_html(
    {
        "candidate_name": "Jan Przykładowy",
        "position": "Tester oprogramowania",
        "language": "pl",
        "blind": False,
        "highlight_keywords": [],
        "why_points": [
            "Ponad 8 lat doświadczenia jako Tester oprogramowania",
            "Praktyczne doświadczenie z Postmanem i Jirą w testach płatności",
            "Doświadczenie w testach API w Acme Bank",
        ],
        "education": [],
        "skills": [],
        "certifications": [],
        "languages": [],
        "experience": [
            {
                "position": "Starszy tester",
                "dates": "01.2021 - obecnie",
                "company": "Acme Bank",
                "technologies": ["Postman"],
                "responsibilities": [
                    "Zaprojektowanie testów regresyjnych, które " + QUOTE + "."
                ],
            }
        ],
    },
    None,
    document_only=True,
)


WHY_ANSWER = {
    "experience": {"text": "{LATA_IT} w IT", "it_roles": [0], "role_roles": []},
    "requirements": {"text": "", "evidence": []},
    "key_task": {"text": "", "quote": "", "source": "cv", "company": ""},
}


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr(settings, "CV_NEW_LAYOUT_ENABLED", True)
    monkeypatch.setattr(service, "api_key_configured", lambda model: True)


@pytest.fixture
def model(monkeypatch):
    calls: list[str] = []

    def fake(system, content, request_id):
        calls.append(content)
        return json.dumps({"results": [RESULT]}, ensure_ascii=False)

    def fake_why(system, content, request_id):
        why_calls.append(content)
        return json.dumps(WHY_ANSWER, ensure_ascii=False)

    why_calls: list[str] = []
    monkeypatch.setattr(service, "_call_model", fake)
    monkeypatch.setattr(service, "_call_why_model", fake_why)
    return calls


async def _csv(sid: int) -> CandidateStageCV:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == sid)
        )


async def _set_extras(sid: int, extras: dict) -> None:
    async with AsyncSessionLocal() as db:
        csv = await db.scalar(
            select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == sid)
        )
        csv.page1_extras = extras
        await db.commit()


@pytest.mark.asyncio
async def test_flag_off_refuses(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, model
):
    monkeypatch.setattr(settings, "CV_NEW_LAYOUT_ENABLED", False)
    sid, _, _ = await _seed_full_stage()
    await _seed_draft(sid, HTML)
    res = await app_client.post(
        f"/api/candidates/stages/{sid}/cv/page1/results", headers=app_auth_headers
    )
    assert res.status_code == 409
    assert model == []


@pytest.mark.asyncio
async def test_endpoint_stores_results_next_to_other_extras(
    app_client: AsyncClient, app_auth_headers: dict, flag_on, model
):
    sid, _, _ = await _seed_full_stage()
    await _seed_draft(sid, HTML)
    await _set_extras(sid, {"why": ["a", "b", "c"], "result_index": 2})
    res = await app_client.post(
        f"/api/candidates/stages/{sid}/cv/page1/results", headers=app_auth_headers
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["why"] == ["a", "b", "c"]
    assert body["result_index"] == 0
    assert body["results"][0]["verified"] is True
    assert body["results"][0]["company"] == "Acme Bank"
    stored = (await _csv(sid)).page1_extras
    assert stored == body
    assert stored["results_source_sha"] == source_sha(HTML)
    assert "Jan Przykładowy" not in model[0]


@pytest.mark.asyncio
async def test_model_failure_is_503_and_leaves_extras(
    app_client: AsyncClient, app_auth_headers: dict, flag_on, monkeypatch
):
    def broken(system, content, request_id):
        raise TimeoutError("brak odpowiedzi")

    monkeypatch.setattr(service, "_call_model", broken)
    monkeypatch.setattr(service, "_call_why_model", broken)
    sid, _, _ = await _seed_full_stage()
    await _seed_draft(sid, HTML)
    await _set_extras(sid, {"why": ["a"]})
    res = await app_client.post(
        f"/api/candidates/stages/{sid}/cv/page1/results", headers=app_auth_headers
    )
    assert res.status_code == 503
    assert "trzeci punkt" in res.json()["detail"]
    assert (await _csv(sid)).page1_extras == {"why": ["a"]}


@pytest.mark.asyncio
async def test_stage_without_cv_is_refused(
    app_client: AsyncClient, app_auth_headers: dict, flag_on, model
):
    sid, _, _ = await _seed_full_stage()
    await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )
    res = await app_client.post(
        f"/api/candidates/stages/{sid}/cv/page1/results", headers=app_auth_headers
    )
    assert res.status_code in (404, 409)
    assert model == []


@pytest.mark.asyncio
async def test_switch_to_new_layout_queues_background_run(
    app_client: AsyncClient, app_auth_headers: dict, flag_on, monkeypatch
):
    spawned: list[int] = []
    monkeypatch.setattr(service, "_spawn", spawned.append)
    sid, _, _ = await _seed_full_stage()
    await _seed_draft(sid, HTML)
    res = await app_client.patch(
        f"/api/candidates/stages/{sid}/cv/layout",
        json={"cv_layout": "new"},
        headers=app_auth_headers,
    )
    assert res.status_code == 200, res.text
    assert spawned == [(await _csv(sid)).id]
    back = await app_client.patch(
        f"/api/candidates/stages/{sid}/cv/layout",
        json={"cv_layout": "classic"},
        headers=app_auth_headers,
    )
    assert back.status_code == 200
    assert len(spawned) == 1


@pytest.mark.asyncio
async def test_background_run_computes_once_per_html(flag_on, model):
    sid, _, _ = await _seed_full_stage()
    await _seed_draft(sid, HTML)
    async with AsyncSessionLocal() as db:
        csv = await db.scalar(
            select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == sid)
        )
        csv.cv_layout = "new"
        await db.commit()
        csv_id = csv.id
    await service.refresh_in_background(csv_id)
    first = (await _csv(sid)).page1_extras
    assert first["results_source_sha"] == source_sha(HTML)
    assert len(model) == 1
    await service.refresh_in_background(csv_id)
    assert len(model) == 1
    assert (await _csv(sid)).page1_extras == first


@pytest.mark.asyncio
async def test_generated_cv_in_new_layout_queues_background_run(
    app_client: AsyncClient, app_auth_headers: dict, flag_on, monkeypatch
):
    from app.models.cv_generated_document import CvGeneratedDocument

    spawned: list[int] = []
    monkeypatch.setattr(service, "_spawn", spawned.append)
    sid, cid, jid = await _seed_full_stage()
    base = f"/api/candidates/stages/{sid}/cv/branded"
    initial = (await app_client.get(base, headers=app_auth_headers)).json()
    async with AsyncSessionLocal() as db:
        source = CvGeneratedDocument(
            candidate_id=cid,
            job_id=jid,
            candidate_name="Synthetic",
            filename="selected.docx",
            status="ready",
            cv_layout="new",
            render_payload={"name": "Synthetic", "why_points": ["Python w Acme"]},
        )
        db.add(source)
        await db.commit()
        generated_id = source.id
    choice = await app_client.post(
        base + "/select-generated",
        headers=app_auth_headers,
        json={
            "expected_revision": initial["edit_revision"],
            "generated_document_id": generated_id,
        },
    )
    assert choice.status_code == 200, choice.text
    csv = await _csv(sid)
    assert csv.cv_layout == "new"
    assert spawned == [csv.id]
