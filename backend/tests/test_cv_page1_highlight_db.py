"""Wyróżnik strony 1 z propozycji AI — trasy w Postgresie (Artur 26.11.2026).

- POST …/cv/page1/highlight szuka propozycji w bieżącym szkicu i zapisuje je
  w `page1_extras.highlight_proposals` obok innych kluczy; wybór wyróżnika
  zostaje; awaria modelu = 503, dodatki bez zmian;
- PATCH …/cv/page1 z `highlight.mode = "ai"` przyjmuje sprawdzoną propozycję
  (Historia zdarzeń bez treści), propozycji spoza listy albo z cytatem, którego
  nie ma już w szkicu, nie przyjmuje (422); `highlight_reject` ją odrzuca;
- przełączenie na „Nowe CV” zleca też bieg propozycji w tle.

Model zawsze podmieniony (`cv_page1_highlight._call_model`) — dane fikcyjne.
Logika bez bazy: `test_cv_page1_highlight.py`.
"""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate_stage_cv import CandidateStageCV
from app.services import cv_page1_highlight as service
from app.services import cv_page1_results as results_service
from app.services.cv_generator_b2b.html_export import render_interactive_html
from tests.test_candidate_stage_cv_branded import _seed_draft, _seed_full_stage

AWARD_LINE = (
    "Wyróżnienie Best Project Manager 2021 za program KYC w klastrze bałtyckim."
)
HTML = render_interactive_html(
    {
        "candidate_name": "Jan Przykładowy",
        "position": "Kierownik projektu",
        "language": "pl",
        "blind": False,
        "highlight_keywords": [],
        "why_points": ["Ponad 8 lat doświadczenia jako Kierownik projektu"],
        "education": [],
        "skills": [],
        "certifications": [],
        "languages": [],
        "experience": [
            {
                "position": "Kierownik projektu",
                "dates": "01.2019 - obecnie",
                "company": "Example Bank",
                "technologies": ["Jira"],
                "responsibilities": [AWARD_LINE],
            }
        ],
    },
    None,
    document_only=True,
)
AWARD = {
    "kind": "award",
    "label": "Wyróżnienie Best Project Manager",
    "token": "2021",
    "text": "**Best Project Manager 2021** za program KYC w Example Bank.",
    "quote": "Wyróżnienie Best Project Manager 2021 za program KYC",
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
        return json.dumps({"proposals": [AWARD]}, ensure_ascii=False)

    monkeypatch.setattr(service, "_call_model", fake)
    return calls


async def _csv(sid: int) -> CandidateStageCV:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == sid)
        )


async def _set(sid: int, **fields) -> None:
    async with AsyncSessionLocal() as db:
        csv = await db.scalar(
            select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == sid)
        )
        for key, value in fields.items():
            setattr(csv, key, value)
        await db.commit()


async def _draft(extras: dict | None = None, html: str = HTML) -> int:
    sid, _, _ = await _seed_full_stage()
    await _seed_draft(sid, html)
    await _set(sid, cv_layout="new", page1_extras=extras)
    return sid


def _post(sid: int) -> str:
    return f"/api/candidates/stages/{sid}/cv/page1/highlight"


def _patch(sid: int) -> str:
    return f"/api/candidates/stages/{sid}/cv/page1"


@pytest.mark.asyncio
async def test_search_stores_proposals_and_keeps_the_choice(
    app_client: AsyncClient, app_auth_headers: dict, flag_on, model
):
    sid = await _draft({"highlight": {"mode": "off"}, "why": ["a", "b", "c"]})
    res = await app_client.post(_post(sid), headers=app_auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["highlight"] == {"mode": "off"}
    assert body["why"] == ["a", "b", "c"]
    (proposal,) = body["highlight_proposals"]
    assert proposal["verified"] is True and proposal["source"] == "role"
    assert (await _csv(sid)).page1_extras == body
    assert "Jan Przykładowy" not in model[0]


@pytest.mark.asyncio
async def test_model_failure_is_503_and_leaves_extras(
    app_client: AsyncClient, app_auth_headers: dict, flag_on, monkeypatch
):
    def broken(system, content, request_id):
        raise TimeoutError("brak odpowiedzi")

    monkeypatch.setattr(service, "_call_model", broken)
    sid = await _draft({"why": ["a"]})
    res = await app_client.post(_post(sid), headers=app_auth_headers)
    assert res.status_code == 503
    assert "wyróżnik działa jak dotąd" in res.json()["detail"]
    assert (await _csv(sid)).page1_extras == {"why": ["a"]}


@pytest.mark.asyncio
async def test_flag_off_refuses(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, model
):
    monkeypatch.setattr(settings, "CV_NEW_LAYOUT_ENABLED", False)
    sid = await _draft()
    res = await app_client.post(_post(sid), headers=app_auth_headers)
    assert res.status_code == 409
    assert model == []


@pytest.mark.asyncio
async def test_accept_then_reject_a_proposal(
    app_client: AsyncClient, app_auth_headers: dict, flag_on, model
):
    sid = await _draft()
    found = await app_client.post(_post(sid), headers=app_auth_headers)
    assert found.status_code == 200, found.text

    accepted = await app_client.patch(
        _patch(sid),
        json={"highlight": {"mode": "ai", "proposal": 0}},
        headers=app_auth_headers,
    )
    assert accepted.status_code == 200, accepted.text
    extras = (await _csv(sid)).page1_extras
    assert extras["highlight"]["mode"] == "ai"
    assert extras["highlight"]["quote"] == AWARD["quote"]
    async with AsyncSessionLocal() as db:
        logged = await db.scalar(
            select(Activity)
            .where(
                Activity.entity_type == "candidate_stage_cv",
                Activity.action == "cv_page1_changed",
            )
            .order_by(Activity.id.desc())
        )
    assert logged.details["highlight"] == "ai"
    assert "Best Project Manager" not in str(logged.details)

    rejected = await app_client.patch(
        _patch(sid), json={"highlight_reject": 0}, headers=app_auth_headers
    )
    assert rejected.status_code == 200, rejected.text
    extras = (await _csv(sid)).page1_extras
    assert "highlight" not in extras  # odrzucona przyjęta = automat
    assert extras["highlight_proposals"] == []
    assert len(extras["highlight_rejected"]) == 1
    again = await app_client.post(_post(sid), headers=app_auth_headers)
    assert again.json()["highlight_proposals"] == []


@pytest.mark.asyncio
async def test_bad_or_stale_proposal_is_refused(
    app_client: AsyncClient, app_auth_headers: dict, flag_on, model
):
    sid = await _draft()
    await app_client.post(_post(sid), headers=app_auth_headers)
    missing = await app_client.patch(
        _patch(sid),
        json={"highlight": {"mode": "ai", "proposal": 3}},
        headers=app_auth_headers,
    )
    assert missing.status_code == 422
    # Rekruter usunął nagrodę z CV po wyliczeniu propozycji.
    await _set(
        sid, branded_draft_html=HTML.replace(AWARD_LINE, "Zarządzanie projektem.")
    )
    stale = await app_client.patch(
        _patch(sid),
        json={"highlight": {"mode": "ai", "proposal": 0}},
        headers=app_auth_headers,
    )
    assert stale.status_code == 422
    assert "nie ma już w CV" in stale.json()["detail"]
    assert "highlight" not in (await _csv(sid)).page1_extras


@pytest.mark.asyncio
async def test_switch_to_new_layout_queues_the_proposal_too(
    app_client: AsyncClient, app_auth_headers: dict, flag_on, monkeypatch
):
    spawned: list[int] = []
    monkeypatch.setattr(results_service, "_spawn", lambda csv_id: None)
    monkeypatch.setattr(service, "spawn_background", spawned.append)
    sid, _, _ = await _seed_full_stage()
    await _seed_draft(sid, HTML)
    res = await app_client.patch(
        f"/api/candidates/stages/{sid}/cv/layout",
        json={"cv_layout": "new"},
        headers=app_auth_headers,
    )
    assert res.status_code == 200, res.text
    assert spawned == [(await _csv(sid)).id]
