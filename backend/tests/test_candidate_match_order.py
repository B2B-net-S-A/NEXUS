"""Kolejność „Dopasowanie” listy kandydatów (``sort=match``) i górne pole.

Decyzje Artura (25.09.2026): „Szukaj ręcznie” i lista z wierszami wymagań
domyślnie według dopasowania; „Mile widziane” najpierw, osoby z brakami danych
za osobami z danymi; awaria wektorów = „najnowsi” z informacją w odpowiedzi.
Qdrant i Voyage są tu atrapami — liczy się kolejność, pamięć i awaria.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.services import candidate_match_order as cmo

NONCE = "zm" + "".join(chr(97 + int(c, 16)) for c in uuid.uuid4().hex[:10])
_IDS: dict[str, int] = {}


# ── Czyste reguły ────────────────────────────────────────────────────────────


def test_order_rows_puts_preferred_then_known_then_similarity_then_newest():
    rows = [
        # (id, mile_widziane, braki, dodano)
        (1, 0, 0, 100.0),
        (2, 1, 0, 50.0),  # „Mile widziane” wygrywa z podobieństwem
        (3, 0, 1, 300.0),  # braki danych idą za osobami z danymi
        (4, 0, 0, 200.0),  # bez wektora — za osobami z wektorem
        (5, 0, 0, 10.0),
    ]
    scores = {1: 0.5, 2: 0.1, 3: 0.99, 5: 0.9}
    assert cmo.order_rows(rows, scores) == [2, 5, 1, 4, 3]


def test_job_scope_needs_exactly_one_recruitment_and_not_assigned():
    class F:
        recruitment_id = [7]
        recruitment_match = "not_assigned"

    assert cmo.job_scope(F) == 7
    F.recruitment_match = "assigned"
    assert cmo.job_scope(F) is None
    F.recruitment_match = "not_assigned"
    F.recruitment_id = [7, 8]
    assert cmo.job_scope(F) is None


def test_requirement_words_join_rows_and_drop_stars():
    class F:
        q_all = ["spring boot"]
        q_any = None

    assert cmo.requirement_words(F, [["java", "kotlin"], ["java*"]]) == (
        "java kotlin spring boot"
    )


def test_classify_skills_needs_every_word_to_be_a_skill():
    from app.services import keyword_suggest

    previous = keyword_suggest.catalog()
    try:
        keyword_suggest.load_catalog(
            [(1, "Java", "lang"), (2, "Spring Boot", "fw"), (3, "Go", "lang")],
            [(3, "golang")],
        )
        both = keyword_suggest.classify_skills("Java, spring boot")
        assert both.all_skills and both.skills == ("Java", "Spring Boot")
        assert keyword_suggest.classify_skills("golang").skills == ("Go",)
        sentence = keyword_suggest.classify_skills("senior java z bankowością")
        assert not sentence.all_skills
    finally:
        keyword_suggest._catalog = previous


# ── Przez endpoint ───────────────────────────────────────────────────────────


async def _seed() -> dict[str, int]:
    if _IDS:
        return _IDS
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus

    people = {
        "oldest_best": ([{"name": "Java"}], "Java."),
        "middle": ([{"name": "Java"}, {"name": "Kotlin"}], "Java, Kotlin."),
        "newest_weak": ([{"name": "Java"}], "Java."),
    }
    async with AsyncSessionLocal() as db:
        for key, (skills, cv) in people.items():
            row = Candidate(
                name=key.replace("_", ""),
                lastname="Dopasowany",
                email=f"{key}-{uuid.uuid4().hex[:10]}@example.com",
                status=CandidateStatus.active,
                linkedin_current_company=NONCE,
                raw_cv_text=cv,
                skills=skills,
            )
            db.add(row)
            await db.flush()
            _IDS[key] = row.id
        await db.commit()
    return _IDS


async def _ids(client, headers, **params: Any) -> tuple[list[str], dict]:
    await _seed()
    query: list[tuple[str, Any]] = [
        ("q", NONCE),
        ("text_mode", "literal"),
        ("semantics_version", 2),
        ("q_any_group", "java"),
    ]
    for key, value in params.items():
        query.append((key, value))
    resp = await client.get("/api/candidates", params=query, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_id = {v: k for k, v in _IDS.items()}
    return [by_id[i["id"]] for i in body["items"] if i["id"] in by_id], body


@pytest.fixture
def fake_vectors(monkeypatch):
    from app.core import cache

    ids = {}

    async def fake_resolve(db, user, filters, groups):
        return cmo.MatchVector(
            vector=[1.0], key=f"test:{uuid.uuid4().hex}", kind="rows"
        )

    def fake_scores(vector, candidate_ids):
        return {
            ids["oldest_best"]: 0.9,
            ids["middle"]: 0.5,
            ids["newest_weak"]: 0.1,
        }

    monkeypatch.setattr(cmo, "resolve_vector", fake_resolve)
    monkeypatch.setattr(cmo, "_qdrant_scores", fake_scores)
    monkeypatch.setattr(cache, "_cache", {})
    return ids


@pytest.mark.asyncio
async def test_match_sort_orders_by_similarity(
    app_client, app_auth_headers, fake_vectors
):
    fake_vectors.update(await _seed())
    order, body = await _ids(app_client, app_auth_headers, sort="match")
    assert order == ["oldest_best", "middle", "newest_weak"]
    assert body["sort_applied"] == "match"
    assert body["total"] >= 3


@pytest.mark.asyncio
async def test_preferred_skill_leads_the_match_order(
    app_client, app_auth_headers, fake_vectors
):
    fake_vectors.update(await _seed())
    order, _ = await _ids(
        app_client, app_auth_headers, sort="match", skills_preferred="kotlin"
    )
    assert order[0] == "middle"


@pytest.mark.asyncio
async def test_without_a_vector_the_list_says_it_fell_back_to_newest(
    app_client, app_auth_headers, monkeypatch
):
    async def no_vector(*args, **kwargs):
        return None

    monkeypatch.setattr(cmo, "resolve_vector", no_vector)
    order, body = await _ids(app_client, app_auth_headers, sort="match")
    assert body["sort_applied"] == "newest"
    assert order == ["newest_weak", "middle", "oldest_best"]


@pytest.mark.asyncio
async def test_qdrant_failure_falls_back_to_newest(
    app_client, app_auth_headers, fake_vectors, monkeypatch
):
    fake_vectors.update(await _seed())

    def broken(vector, ids):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(cmo, "_qdrant_scores", broken)
    order, body = await _ids(app_client, app_auth_headers, sort="match")
    assert body["sort_applied"] == "newest"
    assert order == ["newest_weak", "middle", "oldest_best"]


@pytest.mark.asyncio
async def test_switch_off_means_newest(app_client, app_auth_headers, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "CANDIDATE_MATCH_SORT", False)
    _, body = await _ids(app_client, app_auth_headers, sort="match")
    assert body["sort_applied"] == "newest"


@pytest.mark.asyncio
async def test_classify_endpoint(app_client, app_auth_headers):
    resp = await app_client.get(
        "/api/candidates/keywords/classify",
        params={"q": "senior java z bankowością"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["as_requirements"] is False
