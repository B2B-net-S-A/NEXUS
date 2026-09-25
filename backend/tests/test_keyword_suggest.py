"""Podpowiedzi słów kluczowych (``GET /api/candidates/keywords/suggest``).

Pokrywa:

- dobór ze słownika: początek nazwy, słowo nazwy, alias, bez polskich znaków,
  kolejność (początek nazwy przed aliasem i słowem, krótsza nazwa pierwsza);
- wzorzec „jav*” tylko przy rdzeniu co najmniej 3 znaków;
- trasa nie wpada w ``/{candidate_id}``, liczy osoby z indeksu
  pełnotekstowego, a w trakcie wypełniania korpusu oddaje ``count: null``;
- błąd liczenia (np. limit czasu) daje ``null`` i nie psuje sesji.

Baza testowa jest wspólna: słowa w testach z bazą są jednorazowe (``NONCE``).
"""

from __future__ import annotations

import uuid

import pytest

from app.services import keyword_corpus, keyword_suggest

NONCE = "zs" + "".join(chr(97 + int(c, 16)) for c in uuid.uuid4().hex[:10])

_SKILLS = [
    (1, "Java", "language"),
    (2, "JavaScript", "language"),
    (3, "Java EE", "framework"),
    (4, "Kubernetes", "devops"),
    (5, "Spring Boot", "framework"),
    (6, "Zarządzanie projektem", "methodology"),
    (7, NONCE.capitalize(), "language"),
]
_ALIASES = [(2, "js"), (4, "k8s"), (5, "springboot")]


@pytest.fixture
def catalog():
    saved = keyword_suggest._catalog
    keyword_suggest.load_catalog(_SKILLS, _ALIASES)
    keyword_suggest.clear_count_cache()
    yield
    keyword_suggest._catalog = saved
    keyword_suggest.clear_count_cache()


def _labels(query: str, limit: int = 6) -> list[str]:
    return [m.entry.label for m in keyword_suggest.match_skills(query, limit)]


def test_prefix_of_name_comes_first_and_shorter_first(catalog):
    assert _labels("jav") == ["Java", "Java EE", "JavaScript"]


def test_alias_and_word_matches(catalog):
    matches = keyword_suggest.match_skills("k8", 6)
    assert [m.entry.label for m in matches] == ["Kubernetes"]
    assert matches[0].alias == "k8s"
    assert _labels("boot") == ["Spring Boot"]


def test_polish_letters_are_folded(catalog):
    assert _labels("zarzadz") == ["Zarządzanie projektem"]
    assert _labels("projekt") == ["Zarządzanie projektem"]


def test_empty_query_gives_nothing(catalog):
    assert keyword_suggest.match_skills("   ", 6) == []


def test_wildcard_needs_three_letters():
    assert keyword_suggest.wildcard_for("ja") is None
    assert keyword_suggest.wildcard_for("jav") == "jav*"
    assert keyword_suggest.wildcard_for("spring boot") is None


async def _seed_candidate() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Podpowiedz",
            lastname="Slowna",
            email=f"kw-suggest-{uuid.uuid4().hex[:10]}@example.com",
            status=CandidateStatus.active,
            raw_cv_text=f"Programista {NONCE} od lat.",
        )
        db.add(cand)
        await db.commit()
        return cand.id


@pytest.mark.asyncio
async def test_endpoint_counts_from_the_fulltext_index(
    app_client, app_auth_headers, catalog, monkeypatch
):
    await _seed_candidate()
    monkeypatch.setattr(keyword_corpus, "_ready", True)
    resp = await app_client.get(
        "/api/candidates/keywords/suggest",
        params={"q": NONCE[:6]},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    first = body["items"][0]
    assert first["label"] == NONCE.capitalize()
    assert first["kind"] == "skill"
    assert first["insert"] == NONCE.capitalize()
    assert first["count"] == 1
    assert body["wildcard"]["insert"] == NONCE[:6] + "*"
    assert body["wildcard"]["count"] == 1


@pytest.mark.asyncio
async def test_count_is_null_while_the_corpus_backfills(
    app_client, app_auth_headers, catalog, monkeypatch
):
    monkeypatch.setattr(keyword_corpus, "_ready", False)
    resp = await app_client.get(
        "/api/candidates/keywords/suggest",
        params={"q": "jav"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert [i["label"] for i in items[:3]] == ["Java", "Java EE", "JavaScript"]
    assert all(i["count"] is None for i in items)


@pytest.mark.asyncio
async def test_real_timeout_inside_count_candidates_returns_nulls(catalog, monkeypatch):
    from app.core.database import AsyncSessionLocal

    monkeypatch.setattr(keyword_corpus, "_ready", True)

    class _Boom(Exception):
        pass

    async with AsyncSessionLocal() as db:
        real_execute = db.execute
        calls = {"n": 0}

        async def execute(stmt, *args, **kwargs):
            calls["n"] += 1
            if "count(*) FILTER" in str(stmt):
                raise _Boom("canceling statement due to statement timeout")
            return await real_execute(stmt, *args, **kwargs)

        monkeypatch.setattr(db, "execute", execute)
        result = await keyword_suggest.count_candidates(db, ["Kubernetes"])
        assert result == {"Kubernetes": None}
        monkeypatch.setattr(db, "execute", real_execute)
        # Sesja nadal przyjmuje zapytania (savepoint wycofany, nie transakcja).
        from sqlalchemy import text

        assert (await db.execute(text("SELECT 1"))).scalar_one() == 1
