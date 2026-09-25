"""Lista kandydatów jest lekka i idzie skompresowana (25.09.2026).

Pomiar na produkcji: jedno wyszukiwanie na liście (50 osób) ściągało
0,4–1,05 MB nieskompresowanego JSON-a, z czego ~⅔ to `cv_extracted_data`
(cały odczyt CV), którego tabela nie wyświetla — czyta go wyłącznie profil.
Nic po drodze nie kompresowało odpowiedzi (API nie stoi za Cloudflare).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _seed(tag: str) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Lekki",
            lastname=f"{tag}-lista",
            cv_extracted_data={"career_summary": "x" * 5000, "_source": "claude"},
        )
        db.add(cand)
        await db.commit()
        return cand.id


@pytest.mark.asyncio
async def test_list_omits_cv_extracted_data_but_profile_keeps_it(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    tag = f"Payload{uuid.uuid4().hex[:8]}"
    candidate_id = await _seed(tag)

    listed = await app_client.get(
        "/api/candidates",
        params={"q": tag, "page_size": 50},
        headers=app_auth_headers,
    )
    assert listed.status_code == 200, listed.text
    row = next(i for i in listed.json()["items"] if i["id"] == candidate_id)
    assert row["cv_extracted_data"] is None

    profile = await app_client.get(
        f"/api/candidates/{candidate_id}", headers=app_auth_headers
    )
    assert profile.status_code == 200, profile.text
    assert profile.json()["cv_extracted_data"]["_source"] == "claude"


@pytest.mark.asyncio
async def test_api_responses_are_gzipped_when_the_browser_accepts_it(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    tag = f"Gzip{uuid.uuid4().hex[:8]}"
    await _seed(tag)
    params = {"page_size": 50}

    compressed = await app_client.get(
        "/api/candidates",
        params=params,
        headers={**app_auth_headers, "Accept-Encoding": "gzip"},
    )
    assert compressed.status_code == 200, compressed.text
    assert compressed.headers.get("content-encoding") == "gzip"
    assert compressed.json()["items"]

    plain = await app_client.get(
        "/api/candidates",
        params=params,
        headers={**app_auth_headers, "Accept-Encoding": "identity"},
    )
    assert plain.status_code == 200
    assert "content-encoding" not in plain.headers


def test_gzip_wraps_the_whole_stack_and_skips_streams_and_binary_files() -> None:
    from fastapi.middleware.cors import CORSMiddleware
    from starlette.middleware.gzip import GZipMiddleware

    from app.main import app

    order = [middleware.cls for middleware in app.user_middleware]  # outermost first
    # Tuż pod CORS: każda odpowiedź trasy (także 500 z `UnhandledErrorMiddleware`)
    # przechodzi przez kompresję.
    assert order[:2] == [CORSMiddleware, GZipMiddleware]
    kwargs = app.user_middleware[1].kwargs
    excluded = set(kwargs["exclude_content_types"])
    # SSE Jarvisa: kompresja buforowałaby strumień i zdarzenia nie dochodziłyby na żywo.
    assert "text/event-stream" in excluded
    assert "application/pdf" in excluded
    assert (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        in excluded
    )
