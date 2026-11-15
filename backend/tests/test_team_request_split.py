"""Odczyt maila na stanowiska zespołu (Z4): parser odpowiedzi modelu i trasa.

Model nigdy nie jest wołany: trasa dostaje atrapę odczytu. Dane fikcyjne.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.api import job_request_intake as api
from app.models.ai_feature import AIFeatureKey
from app.models.user import UserRole
from app.services import ai_models
from app.services import champion_draft_service
from app.services import team_request_split as split
from app.services.llm_prompts import ALL_TEMPLATES, TEAM_REQUEST_SPLIT
from tests._jarvis_helpers import make_user

URL = "/api/job-intake/team-positions"

MAIL = (
    "Dzień dobry, szukamy do nowego projektu: 2 programistów Android "
    "(Kotlin, Jetpack Compose), jednego testera automatyzującego (Selenium) "
    "oraz seniora backendu w Pythonie z doświadczeniem w Django."
)


# ── Parser odpowiedzi modelu ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [None, "nie JSON", [], {"positions": "Android"}, {"stanowiska": []}],
)
def test_wrong_shape_gives_an_empty_list(raw) -> None:
    assert split.normalize_positions(raw, MAIL) == []


def test_positions_are_grounded_in_the_mail() -> None:
    raw = {
        "positions": [
            {
                "title": "  Programista   Android ",
                "headcount": 2,
                "headcount_quote": "2 programistów Android",
                "seniority": "Regular",
                "words": ["Kotlin", "kotlin", "Jetpack Compose", "Flutter", 7],
            },
            {
                "title": "Tester automatyzujący",
                "headcount": 1,
                "headcount_quote": "jednego testera automatyzującego",
                "seniority": "mid",
                "words": ["Selenium"],
            },
            {"title": "", "headcount": 3, "words": ["Python"]},
            "nie słownik",
        ]
    }

    assert split.normalize_positions(raw, MAIL) == [
        {
            "title": "Programista Android",
            "headcount": 2,
            "seniority": "regular",
            # „Flutter” nie stoi w mailu, duplikat i liczba wypadają.
            "words": ["Kotlin", "Jetpack Compose"],
        },
        {
            "title": "Tester automatyzujący",
            "headcount": 1,
            "seniority": None,
            "words": ["Selenium"],
        },
    ]


@pytest.mark.parametrize(
    "headcount, quote",
    [
        (0, "2 programistów Android"),
        (51, "2 programistów Android"),
        (True, "2 programistów Android"),
        ("dwóch", "2 programistów Android"),
        # Liczba bez cytatu, cytat spoza maila albo cytat bez tej liczby.
        (4, None),
        (4, "4 programistów Android"),
        (3, "2 programistów Android"),
    ],
)
def test_headcount_without_backing_in_the_mail_is_one(headcount, quote) -> None:
    raw = {
        "positions": [
            {
                "title": "Programista Android",
                "headcount": headcount,
                "headcount_quote": quote,
            }
        ]
    }
    (position,) = split.normalize_positions(raw, MAIL)
    assert position["headcount"] == 1
    assert position["words"] == []


def test_words_and_positions_are_capped() -> None:
    text = "Szukamy osób: " + ", ".join(f"Narzędzie{n}" for n in range(12))
    raw = {
        "positions": [
            {"title": f"Rola {n}", "words": [f"Narzędzie{i}" for i in range(12)]}
            for n in range(40)
        ]
    }
    positions = split.normalize_positions(raw, text)
    assert len(positions) == split.MAX_POSITIONS
    assert len(positions[0]["words"]) == split.MAX_WORDS


def test_prompt_and_model_are_registered() -> None:
    assert ALL_TEMPLATES["team_request_split"] is TEAM_REQUEST_SPLIT
    assert "{request_text}" in TEAM_REQUEST_SPLIT.template
    # Ten sam model co odczyt requestu na /jobs/new.
    assert split.FEATURE is AIFeatureKey.champion_draft
    assert split.model_name() == ai_models.model_for(AIFeatureKey.champion_draft)


# ── Trasa ────────────────────────────────────────────────────────────────────


async def test_route_returns_grounded_positions_and_the_model(
    app_client: AsyncClient, monkeypatch
) -> None:
    seen: dict = {}

    async def fake_model(*, prompt, system_prompt, model, max_tokens):
        seen["prompt"] = prompt
        seen["model"] = model
        return {
            "positions": [
                {
                    "title": "Programista Android",
                    "headcount": 2,
                    "headcount_quote": "2 programistów Android",
                    "seniority": None,
                    "words": ["Kotlin", "Swift"],
                }
            ]
        }

    monkeypatch.setattr(champion_draft_service, "_call_claude_json", fake_model)
    _, headers = await make_user(UserRole.delivery_lead)

    response = await app_client.post(URL, json={"text": MAIL}, headers=headers)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "positions": [
            {
                "title": "Programista Android",
                "headcount": 2,
                "seniority": None,
                "words": ["Kotlin"],
            }
        ],
        "model": split.model_name(),
    }
    assert "2 programistów Android" in seen["prompt"]
    assert seen["model"] == split.model_name()


@pytest.mark.parametrize("error", [ValueError("Invalid JSON"), RuntimeError("klucz")])
async def test_model_failure_is_an_empty_list_not_an_error(
    app_client: AsyncClient, monkeypatch, caplog, error
) -> None:
    async def broken(**kwargs):
        raise error

    monkeypatch.setattr(champion_draft_service, "_call_claude_json", broken)
    _, headers = await make_user(UserRole.delivery_lead)

    with caplog.at_level("WARNING", logger=api.logger.name):
        response = await app_client.post(URL, json={"text": MAIL}, headers=headers)

    assert response.status_code == 200, response.text
    assert response.json() == {"positions": [], "model": split.model_name()}
    assert any("team_request_split" in record.message for record in caplog.records)
    # Log bez treści maila.
    assert all("Kotlin" not in record.message for record in caplog.records)


async def test_route_is_gated_and_validated(
    app_client: AsyncClient, monkeypatch
) -> None:
    async def forbidden(**kwargs):
        raise AssertionError("odmowa przed modelem")

    monkeypatch.setattr(champion_draft_service, "_call_claude_json", forbidden)
    assert (await app_client.post(URL, json={"text": MAIL})).status_code == 401
    _, recruiter = await make_user(UserRole.recruiter)
    response = await app_client.post(URL, json={"text": MAIL}, headers=recruiter)
    assert response.status_code == 403, response.text
    _, lead = await make_user(UserRole.delivery_lead)
    for text in ("za krótko", "x" * (split.MAX_TEXT_CHARS + 1)):
        response = await app_client.post(URL, json={"text": text}, headers=lead)
        assert response.status_code == 422, response.text
