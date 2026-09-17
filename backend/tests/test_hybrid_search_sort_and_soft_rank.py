"""Tryb semantyczny wyszukiwarki honoruje `sort` i chipy podbijające ranking.

Do 09.2026 `POST /api/search/candidates` w trybie `hybrid` wycinał stronę
z surowej kolejności RRF: przyciski „Alfabetycznie"/„Ostatnio aktualizowani"
i chipy skilli („podbijają ranking") działały WYŁĄCZNIE w trybie boolowskim,
choć UI pokazuje je w obu. Decyzja Artura (17.09.2026): sort + chipy działają
także w trybie semantycznym — jako przestawienie PRZEFILTROWANEJ puli hybrydy.

Pula retrievalu jest podstawiana wprost (jak w `test_hybrid_search_pagination`),
a kandydaci są odróżnialni od cudzych wierszy tagiem-nonce.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

NONCE = uuid.uuid4().hex[:10]


async def _seed(
    spec: list[tuple[str, list[str], int]],
) -> list[int]:
    """`spec` = (nazwisko-prefiks, skille, wiek `updated_at` w dniach).

    Zwraca id w kolejności `spec` — to będzie kolejność retrievalu.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        rows: list[Candidate] = []
        for i, (last, skills, age_days) in enumerate(spec):
            rows.append(
                Candidate(
                    name=f"Imie{i:02d}",
                    lastname=f"{last}-{NONCE}",
                    email=f"sort-{uuid.uuid4().hex[:8]}@example.com",
                    status=CandidateStatus.active,
                    tags=[NONCE],
                    skills=[{"name": s} for s in skills],
                    updated_at=now - timedelta(days=age_days),
                )
            )
        db.add_all(rows)
        await db.commit()
        for r in rows:
            await db.refresh(r)
        return [r.id for r in rows]


@pytest.fixture
def _stub_hybrid(monkeypatch):
    def _install(order: list[int]):
        from app.services import hybrid_search
        from app.services.hybrid_search import HybridResult

        async def _fake(db, query, **kwargs):
            return HybridResult(pairs=[(cid, 1.0) for cid in order])

        monkeypatch.setattr(hybrid_search, "hybrid_candidates", _fake)

    return _install


async def _search(app_client, headers, **extra) -> list[dict]:
    body = {
        "q": "python",
        "search_mode": "hybrid",
        "tags": [NONCE],
        "page": 1,
        "page_size": 50,
        **extra,
    }
    resp = await app_client.post("/api/search/candidates", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


@pytest.mark.asyncio
async def test_name_sort_orders_the_hybrid_page_alphabetically(
    app_client, app_auth_headers, _stub_hybrid
):
    """„Alfabetycznie" w trybie semantycznym daje stronę po nazwisku."""
    ids = await _seed([("Zeta", [], 1), ("Alfa", [], 1), ("Mika", [], 1)])
    _stub_hybrid(ids)  # retrieval: Zeta, Alfa, Mika

    items = await _search(app_client, app_auth_headers, sort="name")
    lastnames = [it["lastname"] for it in items]
    assert lastnames == sorted(lastnames, key=str.casefold), lastnames
    assert [it["id"] for it in items] == [ids[1], ids[2], ids[0]]


@pytest.mark.asyncio
async def test_recent_sort_orders_the_hybrid_page_by_updated_at(
    app_client, app_auth_headers, _stub_hybrid
):
    ids = await _seed([("Stary", [], 30), ("Nowy", [], 0), ("Sredni", [], 10)])
    _stub_hybrid(ids)

    items = await _search(app_client, app_auth_headers, sort="recent")
    assert [it["id"] for it in items] == [ids[1], ids[2], ids[0]]


@pytest.mark.asyncio
async def test_skill_chip_lifts_matchers_above_the_rest_of_the_pool(
    app_client, app_auth_headers, _stub_hybrid
):
    """Chip skilla podbija trafienia NAD resztę puli, a w obrębie grup
    zostaje kolejność retrievalu (stabilny tie-break)."""
    ids = await _seed(
        [
            ("Bez1", ["Java"], 1),
            ("Kube1", ["Kubernetes"], 1),
            ("Bez2", [], 1),
            ("Kube2", ["Kubernetes", "Go"], 1),
        ]
    )
    _stub_hybrid(ids)

    items = await _search(app_client, app_auth_headers, skills_must=["Kubernetes"])
    got = [it["id"] for it in items]
    assert got == [ids[1], ids[3], ids[0], ids[2]], got

    # Chip nie tnie: cała pula jest na stronie.
    assert set(got) == set(ids)


@pytest.mark.asyncio
async def test_relevance_without_chips_keeps_the_rrf_order(
    app_client, app_auth_headers, _stub_hybrid
):
    """Bez chipów i przy `sort=relevance` kolejność retrievalu zostaje
    bajt w bajt — przestawianie nie może „poprawiać" rerankera."""
    ids = await _seed([("Cc", [], 5), ("Aa", [], 1), ("Bb", [], 9)])
    _stub_hybrid(ids)

    items = await _search(app_client, app_auth_headers, sort="relevance")
    assert [it["id"] for it in items] == ids


@pytest.mark.asyncio
async def test_resort_respects_the_page_boundary(
    app_client, app_auth_headers, _stub_hybrid
):
    """Strona jest wycinana PO przestawieniu, więc druga strona to dalszy
    ciąg tej samej, przestawionej listy."""
    ids = await _seed(
        [("Delta", [], 1), ("Alfa", [], 1), ("Cezar", [], 1), ("Beta", [], 1)]
    )
    _stub_hybrid(ids)

    first = await _search(
        app_client, app_auth_headers, sort="name", page=1, page_size=2
    )
    second = await _search(
        app_client, app_auth_headers, sort="name", page=2, page_size=2
    )
    assert [it["id"] for it in first] == [ids[1], ids[3]]
    assert [it["id"] for it in second] == [ids[2], ids[0]]
