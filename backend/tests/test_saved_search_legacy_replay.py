"""Zapisane wyszukiwania sprzed ujednolicenia silników zwracają TO SAMO.

Dwa formaty zapisu żyją w bazie:

* lista — ``{version: 2, qs, api}`` (``frontend/src/lib/candidate-saved-search.ts``);
  alerty odtwarzają ``api`` przez prawdziwe ``GET /api/candidates``,
* wyszukiwarka — ciało ``CandidateSearchRequest``
  (``frontend/src/lib/candidate-search-request.ts``).

Każdy przypadek niesie reprezentatywny ładunek legacy (WYŁĄCZNIE stare pola)
i zbiór oczekiwany wyprowadzony z dotychczasowego znaczenia pól. Ten plik
przechodzi bez zmian na kodzie SPRZED ujednolicenia (sprawdzone na
``origin/main`` @ adc2421d0) i po nim — to jest dowód „przed = po".

Świadomie POZA tym plikiem są decyzje, które wynik zmieniają celowo (stawka
bez danych przechodzi, „Otwarty na" = LUB w wyszukiwarce, kategoria poboczna,
cały tag, zapas Traffita dla stażu, `q` wyglądające na osobę) — te przypina
``test_search_engines_contract.py``.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

NONCE = "zr" + "".join(chr(97 + int(c, 16)) for c in uuid.uuid4().hex[:10])
_IDS: dict[str, int] = {}
_CC: dict[str, int] = {}
ALL = set("abcdefg")


async def _seed() -> dict[str, int]:
    if _IDS:
        return _IDS
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import AvailabilityStatus, Candidate, CandidateStatus
    from app.models.competence_category import CompetenceCategory

    def person(key: str, **kw: Any) -> Candidate:
        kw.setdefault("status", CandidateStatus.active)
        return Candidate(
            name=key.capitalize(),
            lastname=f"Legacy{key}",
            email=f"lg-{key}-{uuid.uuid4().hex[:10]}@example.com",
            linkedin_current_company=NONCE,
            **kw,
        )

    async with AsyncSessionLocal() as db:
        cat = CompetenceCategory(
            slug=f"lg-{NONCE[:20]}",
            name_pl="Legacy",
            name_en="Legacy",
            description="test",
            keywords=[],
        )
        db.add(cat)
        await db.flush()
        _CC["one"] = cat.id
        rows = {
            "a": person(
                "a",
                skills=["Python", "React"],
                location="Gdansk Wrzeszcz",
                country="PL",
                years_it_experience=6,
                competence_category_id=cat.id,
                open_to_side_projects=True,
                availability_status=AvailabilityStatus.actively_looking,
            ),
            "b": person(
                "b",
                skills=["Python", "Go"],
                location="Gdansk Oliwa",
                country="PL",
                years_it_experience=2,
                open_to_sales_support=True,
            ),
            "c": person(
                "c",
                skills=[{"name": "Java"}],
                years_it_experience=9,
                ai_summary="Backend java, bankowość.",
            ),
            "d": person(
                "d", skills=["Kotlin", "Java"], location="Berlin", country="DE"
            ),
            "e": person("e", skills=["Rust"], status=CandidateStatus.passive),
            "f": person("f", skills=["Django", "MongoDB"], years_it_experience=4),
            "g": person("g"),
        }
        db.add_all(rows.values())
        await db.commit()
        for key, row in rows.items():
            _IDS[key] = row.id
    return _IDS


def _own(found: list[int]) -> set[str]:
    reverse = {v: k for k, v in _IDS.items()}
    return {reverse[i] for i in found if i in reverse}


async def _replay_list(client, headers, api: dict[str, Any]) -> set[str]:
    """Tak samo jak skaner alertów: `api` → parametry GET, listy powtarzane."""
    await _seed()
    query: list[tuple[str, Any]] = [("q_all", NONCE), ("page_size", 100)]
    for key, value in api.items():
        if isinstance(value, list):
            query.extend((key, v) for v in value)
        else:
            query.append((key, value))
    resp = await client.get("/api/candidates", params=query, headers=headers)
    assert resp.status_code == 200, resp.text
    return _own([item["id"] for item in resp.json()["items"]])


async def _replay_search(client, headers, body: dict[str, Any]) -> set[str]:
    await _seed()
    payload = {"q_all": [NONCE], "page": 1, "page_size": 200, **body}
    resp = await client.post("/api/search/candidates", json=payload, headers=headers)
    assert resp.status_code == 200, resp.text
    return _own([item["id"] for item in resp.json()["items"]])


LIST_PAYLOADS: list[tuple[str, dict[str, Any], set[str]]] = [
    (
        "must + not (twarde)",
        {"skills": ["Python", "React"], "skill_combine": "and", "skills_none": ["Go"]},
        {"a"},
    ),
    ("sama negacja", {"skills_none": ["Go"]}, ALL - {"b"}),
    ("grupa LUB", {"skills_any": ["java|go"]}, {"b", "c", "d"}),
    (
        "dwie grupy LUB",
        {"skills_any": ["java|go", "python|kotlin"]},
        {"b", "d"},
    ),
    (
        "legacy skill_combine=or",
        {"skills": ["Rust", "React"], "skill_combine": "or"},
        {"a", "e"},
    ),
    ("negacja grupy", {"skills_none": ["java|python"]}, {"e", "f", "g"}),
    (
        "status + dostępność",
        {"status": ["active"], "availability": ["actively_looking"]},
        {"a"},
    ),
    (
        "lokalizacja + staż (wartości znane)",
        {"location": "Gdansk", "min_experience": 3, "max_experience": 10},
        {"a"},
    ),
    ("staż: brak danych odpada", {"min_experience": 1}, {"a", "b", "c", "f"}),
    ("otwarty na (LUB)", {"open_to": ["side_projects", "sales_support"]}, {"a", "b"}),
    (
        "grupy boolowskie",
        {"q_any_group": ["kotlin|rust"], "q_none": ["java"]},
        {"e"},
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "label,api,expected", LIST_PAYLOADS, ids=[p[0] for p in LIST_PAYLOADS]
)
async def test_zapisane_wyszukiwanie_listy(
    app_client, app_auth_headers, label, api, expected
):
    assert await _replay_list(app_client, app_auth_headers, api) == expected


@pytest.mark.asyncio
async def test_zapisane_wyszukiwanie_listy_z_kategoria(app_client, app_auth_headers):
    await _seed()
    found = await _replay_list(
        app_client, app_auth_headers, {"competence_category_id": [_CC["one"]]}
    )
    assert found == {"a"}


SEARCH_PAYLOADS: list[tuple[str, dict[str, Any], set[str]]] = [
    ("chipy umiejętności tylko szeregują", {"skills_must": ["Python"]}, ALL),
    (
        "chipy + wykluczenie",
        {"skills_must": ["Python"], "skills_any": ["React"], "skills_none": ["Go"]},
        ALL - {"b"},
    ),
    ("status", {"status": ["passive"]}, {"e"}),
    (
        "staż: brak danych zostaje",
        {"experience_years_min": 3, "experience_years_max": 10},
        {"a", "c", "f", "d", "e", "g"},
    ),
    (
        "miasto + kraj: brak danych zostaje",
        {"location_cities": ["Gdansk"], "location_countries": ["PL"]},
        {"a", "b", "c", "e", "f", "g"},
    ),
    ("jeden przełącznik otwarty-na", {"open_to_side_projects": True}, {"a"}),
    (
        "grupy boolowskie",
        {"q_any": ["kotlin", "rust"], "q_any_groups": [["java", "rust"]]},
        {"d", "e"},
    ),
    ("słowa kluczowe z wykluczeniem", {"q": "java -kotlin"}, {"c"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "label,body,expected", SEARCH_PAYLOADS, ids=[p[0] for p in SEARCH_PAYLOADS]
)
async def test_zapisane_wyszukiwanie_wyszukiwarki(
    app_client, app_auth_headers, label, body, expected
):
    assert await _replay_search(app_client, app_auth_headers, body) == expected
