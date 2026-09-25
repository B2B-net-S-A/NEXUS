"""Lista kandydatów „najpierw identyfikatory” (``CANDIDATE_LIST_IDS_FIRST``).

Audyt szybkości (25.09.2026): ``count(*) OVER()`` na pełnych wierszach
przepuszczał przez sortowanie cały wynik ze wszystkimi kolumnami. Nowa ścieżka
liczy i sortuje same identyfikatory — musi dawać DOKŁADNIE te same osoby,
w tej samej kolejności i z tą samą liczbą, co stara, dla każdego sortowania.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

NONCE = "zi" + "".join(chr(97 + int(c, 16)) for c in uuid.uuid4().hex[:10])
_SEEDED: list[int] = []


async def _seed() -> None:
    if _SEEDED:
        return
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus

    people = [
        ("Adam", "Nowak", "Java, Spring.", [{"name": "Java"}]),
        ("Beata", "Ącka", "Python, Django.", [{"name": "Python"}]),
        ("Cezary", "Zieliński", "Java, Kotlin.", [{"name": "Kotlin"}]),
        ("Dorota", "Łuczak", "Java 17.", []),
        ("Ewa", "Kowalska", "Tester.", [{"name": "Selenium"}]),
    ]
    async with AsyncSessionLocal() as db:
        rows = [
            Candidate(
                name=name,
                lastname=last,
                email=f"{name.lower()}-{uuid.uuid4().hex[:10]}@example.com",
                status=CandidateStatus.active,
                linkedin_current_company=NONCE,
                raw_cv_text=cv,
                skills=skills,
            )
            for name, last, cv, skills in people
        ]
        db.add_all(rows)
        await db.commit()
        _SEEDED.extend(row.id for row in rows)


async def _page(client, headers, monkeypatch, ids_first: bool, **params: Any):
    from app.core.config import settings

    monkeypatch.setattr(settings, "CANDIDATE_LIST_IDS_FIRST", ids_first)
    query: list[tuple[str, Any]] = [
        ("q", NONCE),
        ("text_mode", "literal"),
        ("semantics_version", 2),
    ]
    for key, value in params.items():
        if isinstance(value, (list, tuple)):
            query.extend((key, v) for v in value)
        else:
            query.append((key, value))
    resp = await client.get("/api/candidates", params=query, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return [item["id"] for item in body["items"]], body["total"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"page_size": 50},
        {"page_size": 2, "page": 2},
        {"sort": "oldest", "page_size": 50},
        {"sort": "name", "page_size": 50},
        {"sort": "relevance", "page_size": 50},
        {"q_any_group": "java", "page_size": 50},
        {"skills_preferred": "kotlin", "page_size": 50},
        {"page_size": 2, "page": 9},
    ],
    ids=[
        "newest",
        "page-2",
        "oldest",
        "name",
        "relevance",
        "keyword",
        "preferred-rank",
        "page-past-end",
    ],
)
async def test_ids_first_matches_window_count(
    app_client, app_auth_headers, monkeypatch, params
):
    await _seed()
    old = await _page(app_client, app_auth_headers, monkeypatch, False, **params)
    new = await _page(app_client, app_auth_headers, monkeypatch, True, **params)
    assert new == old


@pytest.mark.asyncio
async def test_page_past_end_still_reports_the_total(
    app_client, app_auth_headers, monkeypatch
):
    await _seed()
    ids, total = await _page(
        app_client, app_auth_headers, monkeypatch, True, page_size=2, page=9
    )
    assert ids == []
    assert total == len(_SEEDED)
