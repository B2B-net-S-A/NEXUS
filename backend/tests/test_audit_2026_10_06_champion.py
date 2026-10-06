"""Audyt 06.10.2026 — Profil Championa i tworzenie rekrutacji (PR 2, z bazą).

- N2: zapis z nieaktualnym ``expected_profile_hash`` = 409 z aktualnym profilem,
- P6: krytyczne, które przestało być technologią, zostaje „musi mieć” z uwagą,
- P2: zapis z wierszami wyrównuje kolumnę ``must_skills`` z etykietami,
- P7: kolumny must/nice rekrutacji z wierszami idą wyłącznie za Championem,
- P8: szablon od innego klienta przenosi tylko opis wymagań,
- N6: jawne ``headcount: null`` nie jest „1”.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.models.job import Job


async def _client() -> int:
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        client = Client(name=f"Audyt0610-{uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.commit()
        return client.id


@pytest.fixture
def offline_matching(monkeypatch):
    from app.services import canonical_fit, embedding_service

    async def _empty(*_a, **_k):
        return []

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", _empty)
    monkeypatch.setattr(embedding_service, "embed_job", _noop)
    monkeypatch.setattr(canonical_fit, "score_candidates", _empty)


async def _create(app_client, headers, client_id: int, **over) -> dict:
    from tests._job_factory import complete_job_payload

    payload = await complete_job_payload(client_id, **over)
    resp = await app_client.post("/api/jobs", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _url(job_id: int) -> str:
    return f"/api/jobs/{job_id}/champion-profile"


async def test_stale_profile_hash_is_refused_with_the_current_profile(
    app_client: AsyncClient, app_auth_headers: dict, offline_matching
):
    job = await _create(app_client, app_auth_headers, await _client())
    read = await app_client.get(_url(job["id"]), headers=app_auth_headers)
    assert read.status_code == 200, read.text
    loaded_hash = read.json()["profile_hash"]

    first = await app_client.put(
        _url(job["id"]),
        json={
            "project": {"about": "Platforma płatności — nowy moduł rozliczeń."},
            "expected_profile_hash": loaded_hash,
        },
        headers=app_auth_headers,
    )
    assert first.status_code == 200, first.text
    assert first.json()["profile_hash"] != loaded_hash

    # Drugi edytor z tym samym, już nieaktualnym odczytem.
    stale = await app_client.put(
        _url(job["id"]),
        json={
            "project": {"about": "Starsza wersja opisu."},
            "expected_profile_hash": loaded_hash,
        },
        headers=app_auth_headers,
    )
    assert stale.status_code == 409, stale.text
    detail = stale.json()["detail"]
    assert detail["code"] == "champion_profile_conflict"
    assert detail["profile_hash"] == first.json()["profile_hash"]
    assert "nowy moduł rozliczeń" in detail["champion_profile"]["project"]["about"]

    bad = await app_client.put(
        _url(job["id"]),
        json={"project": {"about": "x"}, "expected_profile_hash": 123},
        headers=app_auth_headers,
    )
    assert bad.status_code == 422, bad.text


async def test_critical_that_stops_being_a_technology_stays_must_with_a_notice(
    app_client: AsyncClient, app_auth_headers: dict, offline_matching
):
    from tests.taxonomy_fixture import hydrated_taxonomy

    job = await _create(app_client, app_auth_headers, await _client())
    with hydrated_taxonomy():
        saved = await app_client.put(
            _url(job["id"]),
            json={
                "stack": {
                    "rows": [
                        {"words": ["Python"], "level": "must"},
                        {"words": ["komunikatywność"], "level": "must"},
                    ],
                    "critical": ["Python", "komunikatywność"],
                }
            },
            headers=app_auth_headers,
        )
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["champion_profile"]["stack"].get("critical") == ["Python"], body
        assert any("komunikatywność" in notice for notice in body["notices"])

        only_soft = await app_client.put(
            _url(job["id"]),
            json={
                "stack": {
                    "rows": [{"words": ["komunikatywność"], "level": "must"}],
                    "critical": ["komunikatywność"],
                }
            },
            headers=app_auth_headers,
        )
    assert only_soft.status_code == 200, only_soft.text
    # Bez krytycznych z wyboru DL-a = „nie zdecydowano”.
    assert "critical" not in only_soft.json()["champion_profile"]["stack"]


async def test_saving_rows_realigns_the_must_column(
    app_client: AsyncClient, app_auth_headers: dict, offline_matching
):
    job = await _create(app_client, app_auth_headers, await _client())
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Job).where(Job.id == job["id"]).values(must_skills=["Kafka"])
        )
        await db.commit()
    profile = (await app_client.get(_url(job["id"]), headers=app_auth_headers)).json()
    rows = profile["champion_profile"]["stack"]["rows"]

    saved = await app_client.put(
        _url(job["id"]), json={"stack": {"rows": rows}}, headers=app_auth_headers
    )
    assert saved.status_code == 200, saved.text
    async with AsyncSessionLocal() as db:
        refreshed = await db.get(Job, job["id"])
    from app.services.champion_requirement_rows import skill_column_names

    assert skill_column_names(refreshed.must_skills) == skill_column_names(["Python"])


async def test_skill_columns_follow_the_champion_rows(
    app_client: AsyncClient, app_auth_headers: dict, offline_matching
):
    job = await _create(app_client, app_auth_headers, await _client())
    url = f"/api/jobs/{job['id']}"

    refused = await app_client.patch(
        url, json={"must_skills": ["Java"]}, headers=app_auth_headers
    )
    assert refused.status_code == 409, refused.text
    # Okno edycji odsyła niezmienione kolumny — to nie jest zmiana.
    same = await app_client.patch(
        url, json={"must_skills": ["Python"]}, headers=app_auth_headers
    )
    assert same.status_code == 200, same.text

    criteria = await app_client.post(
        f"/api/jobs/{job['id']}/refresh-criteria", headers=app_auth_headers
    )
    assert criteria.status_code == 409, criteria.text


async def test_template_from_another_client_carries_only_the_requirement_notes(
    app_client: AsyncClient, app_auth_headers: dict, offline_matching
):
    from tests._job_factory import ready_champion

    champion = ready_champion()
    champion["stack"]["notes"] = "Java 17+, Spring Boot 3."
    template = await _create(
        app_client, app_auth_headers, await _client(), champion_profile=champion
    )
    other_client = await _client()
    from tests._job_factory import complete_job_payload

    # Formularz nie przysyła opisu wymagań — zostaje ten z szablonu; reszta
    # profilu (budżet, projekt, pytania) jest z żądania, nie od innego klienta.
    payload = await complete_job_payload(other_client, from_job_id=template["id"])
    created = await app_client.post("/api/jobs", json=payload, headers=app_auth_headers)
    assert created.status_code == 201, created.text
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, created.json()["id"])
    assert job.champion_profile["stack"].get("notes") == "Java 17+, Spring Boot 3."


async def test_explicit_null_headcount_is_not_one(
    app_client: AsyncClient, app_auth_headers: dict, offline_matching
):
    from tests._job_factory import complete_job_payload

    payload = await complete_job_payload(await _client(), headcount=None)
    refused = await app_client.post("/api/jobs", json=payload, headers=app_auth_headers)
    assert refused.status_code == 422, refused.text
    codes = [b["code"] for b in refused.json()["detail"]["blockers"]]
    assert codes == ["headcount"]

    payload.pop("headcount")
    created = await app_client.post("/api/jobs", json=payload, headers=app_auth_headers)
    assert created.status_code == 201, created.text
    assert created.json()["headcount"] == 1


pytestmark = pytest.mark.asyncio
