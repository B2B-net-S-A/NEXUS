"""Lista kandydatów „najpierw identyfikatory” (``CANDIDATE_LIST_IDS_FIRST``).

Audyt szybkości (25.09.2026): ``count(*) OVER()`` na pełnych wierszach
przepuszczał przez sortowanie cały wynik ze wszystkimi kolumnami. Nowa ścieżka
liczy i sortuje same identyfikatory — musi dawać DOKŁADNIE te same osoby,
w tej samej kolejności i z tą samą liczbą, co stara, dla każdego sortowania.

26.11.2026: okno liczy się w podzapytaniu, a ``ORDER BY … LIMIT`` stoi na
zewnątrz. Na jednym poziomie Postgres 16 brał przy „najnowsi” z filtrem
``IN (… UNION …)`` pętlę zagnieżdżoną po indeksie daty z filtrem złączenia
(kopia produkcji: 690 mln porównań, 83 s).
"""

from __future__ import annotations

import re
import uuid
from contextlib import contextmanager
from typing import Any

import pytest
from sqlalchemy import event

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
    return (
        [item["id"] for item in body["items"]],
        body["total"],
        body.get("known_match_count"),
    )


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
        {"q_any_group": "java", "sort": "oldest", "page_size": 1, "page": 2},
        {"q_any_group": "java", "sort": "name", "page_size": 50},
        {"skills_preferred": "kotlin", "page_size": 50},
        {"max_rate": 200, "page_size": 50},
        {"page_size": 2, "page": 9},
    ],
    ids=[
        "newest",
        "page-2",
        "oldest",
        "name",
        "relevance",
        "keyword",
        "keyword-oldest-page-2",
        "keyword-name",
        "preferred-rank",
        "known-count",
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
    ids, total, _known = await _page(
        app_client, app_auth_headers, monkeypatch, True, page_size=2, page=9
    )
    assert ids == []
    assert total == len(_SEEDED)


@contextmanager
def _capture_sql():
    from app.core.database import engine

    seen: list[str] = []

    def _on(conn, cursor, statement, parameters, context, executemany):
        seen.append(" ".join(statement.split()))

    event.listen(engine.sync_engine, "before_cursor_execute", _on)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _on)


@pytest.mark.asyncio
@pytest.mark.parametrize("sort", ["newest", "oldest", "relevance"])
async def test_window_count_runs_in_a_subquery_under_the_page_limit(
    app_client, app_auth_headers, monkeypatch, sort
):
    """Okno ``count(*) OVER ()`` w podzapytaniu, a kolejność i ``LIMIT`` na
    zewnątrz: zewnętrzne ``ORDER BY`` każe Postgresowi planować filtr na pełny
    odczyt, więc ``LIMIT`` nie wybiera już pętli po indeksie daty."""
    await _seed()
    with _capture_sql() as seen:
        await _page(
            app_client,
            app_auth_headers,
            monkeypatch,
            True,
            q_any_group="java",
            sort=sort,
            page_size=15,
        )
    [page] = [sql for sql in seen if "count(*) OVER ()" in sql]
    assert re.search(
        r"FROM \(SELECT candidates\.id(?: AS id)?, count\(\*\) OVER \(\)", page
    )
    assert re.search(r"\) AS page ORDER BY page\.sort_0 .* LIMIT", page)
