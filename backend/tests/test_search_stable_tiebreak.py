"""Wyszukiwarka: remisy w sortowaniu nie mogą przestawiać ludzi między stronami.

`POST /api/search/candidates` kończył sortowanie na `updated_at` albo na
nazwisku i imieniu. Przy remisie kolejność wybierał plan zapytania, a każda
strona ma inny `OFFSET + LIMIT`, czyli inny przebieg sortowania. Ta sama osoba
trafiała wtedy na dwie strony, a inna nie pojawiała się na żadnej (staging,
kopia z 08.11.2026: 600 wierszy z trzech stron, 594 różne id).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

_TIED = 50
_LEADERS = 10
_POPULATION = _TIED + _LEADERS
_PAGE_SIZE = 20
_TIE_MOMENT = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
_LEADER_MOMENT = datetime(2026, 2, 15, 12, 0, tzinfo=timezone.utc)


async def _seed_ties() -> tuple[str, list[int], list[int]]:
    """Remis i ludzie przed nim, dodani do tabeli po remisie.

    Sam remis błędu nie pokaże: przy jednakowych kluczach Postgres w sortowaniu
    z limitem i bez niego zostawia tych samych pierwszych N. Dopiero późniejsze
    wiersze z lepszym kluczem wypychają z kopca przypadkowe osoby z remisu,
    a strona bez kopca bierze inne.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus

    nonce = uuid.uuid4().hex[:10]

    def person(name: str, moment: datetime) -> Candidate:
        return Candidate(
            name=name,
            lastname=f"remis{nonce}",
            email=f"tie-{uuid.uuid4().hex[:8]}@example.com",
            status=CandidateStatus.active,
            tags=[nonce],
            updated_at=moment,
        )

    async with AsyncSessionLocal() as db:
        tied = [person("Remis", _TIE_MOMENT) for _ in range(_TIED)]
        db.add_all(tied)
        await db.flush()
        leaders = [person("Aaa", _LEADER_MOMENT) for _ in range(_LEADERS)]
        db.add_all(leaders)
        await db.commit()
        return nonce, [row.id for row in tied], [row.id for row in leaders]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sort", "free_text"),
    [("recent", False), ("name", False), ("relevance", False), ("relevance", True)],
)
async def test_tied_candidates_never_repeat_across_pages(
    app_client, app_auth_headers, sort: str, free_text: bool
) -> None:
    nonce, tied, leaders = await _seed_ties()
    body = (
        {"q": f"remis{nonce}"}
        if free_text
        else {"semantics_version": 2, "tags": [nonce]}
    )

    seen: list[int] = []
    for page in range(1, 4):
        resp = await app_client.post(
            "/api/search/candidates",
            json={**body, "sort": sort, "page": page, "page_size": _PAGE_SIZE},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["total"] == _POPULATION
        seen.extend(item["id"] for item in resp.json()["items"])

    assert len(seen) == len(set(seen)), "ta sama osoba na więcej niż jednej stronie"
    assert sorted(seen) == sorted(tied + leaders), "ktoś nie trafił na żadną stronę"


@pytest.mark.asyncio
async def test_bm25_leg_breaks_ties_by_id() -> None:
    """Noga BM25 zasila pulę hybrydy, a pula liczy się od nowa na każdej stronie."""
    from app.core.database import AsyncSessionLocal
    from app.services.hybrid_search import bm25_candidates

    nonce, tied, leaders = await _seed_ties()
    async with AsyncSessionLocal() as db:
        found = await bm25_candidates(db, f"remis{nonce}", limit=_PAGE_SIZE)

    assert found == sorted(leaders) + sorted(tied)[: _PAGE_SIZE - _LEADERS]
