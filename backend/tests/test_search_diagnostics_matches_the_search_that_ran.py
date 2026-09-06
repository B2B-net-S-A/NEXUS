"""Wodospad „na którym filtrze odpadli" ma diagnozować TO zapytanie, które padło.

Panel `ExclusionWaterfall` otwiera się WYŁĄCZNIE przy zerze wyników — to jedyny
ekran, na którym rekruter szuka przyczyny pustki. Do teraz diagnostyka stosowała
`websearch_to_tsquery` (koniunkcja leksemów) także wtedy, gdy prawdziwe
wyszukiwanie poszło trybem semantycznym (domyślnym w `CandidateSearchView`)
i tej klauzuli w ogóle nie użyło.

Skutek: „senior python architekt danych" pokazywało się jako etap zerujący
i dostawało czerwony pasek „to ten filtr" — diagnoza wskazująca element, którego
w wyszukiwaniu nie było, i milcząca o tym, co naprawdę zawęziło wynik.
"""

from __future__ import annotations

import uuid

import pytest

NONCE = uuid.uuid4().hex[:10]


async def _seed_two() -> list[int]:
    """Dwóch kandydatów z tagiem `NONCE`; ANI JEDEN nie ma słów zapytania."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus

    async with AsyncSessionLocal() as db:
        rows = [
            Candidate(
                name=f"Diag{i}",
                lastname=f"Wodospad-{uuid.uuid4().hex[:6]}",
                email=f"diag-{uuid.uuid4().hex[:8]}@example.com",
                status=CandidateStatus.active,
                tags=[NONCE],
            )
            for i in range(2)
        ]
        db.add_all(rows)
        await db.commit()
        for r in rows:
            await db.refresh(r)
        return [r.id for r in rows]


@pytest.mark.asyncio
async def test_hybrid_diagnostics_reports_the_semantic_pool_not_a_conjunction(
    app_client, app_auth_headers, monkeypatch
):
    """W trybie semantycznym etap „zapytanie" liczy PULĘ, nie koniunkcję FTS.

    Pula zawiera obu zaseedowanych kandydatów, choć żaden z nich nie ma w tekście
    ani jednego słowa zapytania. FTS dałby tu 0 (koniunkcja czterech leksemów,
    których nikt nie ma) i oskarżył zapytanie; pula daje 2, więc wodospad idzie
    dalej i pokazuje filtr, który naprawdę zawęża.
    """
    from app.services import hybrid_search
    from app.services.hybrid_search import HybridResult

    pool_ids = await _seed_two()

    async def _fake(db, query, **kwargs):
        assert kwargs.get("use_rerank") is False, (
            "wodospad pyta o członkostwo, nie o kolejność — reranker jest tu "
            "kosztem bez efektu"
        )
        return HybridResult(pairs=[(cid, 1.0) for cid in pool_ids])

    monkeypatch.setattr(hybrid_search, "hybrid_candidates", _fake)

    resp = await app_client.post(
        "/api/search/candidates/diagnostics",
        json={
            "q": "senior python architekt danych",
            "search_mode": "hybrid",
            "tags": [NONCE],
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    query_stage = next(s for s in data["stages"] if s["key"] == "query")
    assert query_stage["count"] == len(pool_ids), (
        "etap zapytania ma liczyć pulę semantyczną, a nie koniunkcję leksemów; "
        f"dostaliśmy {query_stage['count']}"
    )
    assert data["first_zeroing_stage"] != "query", (
        "zapytanie semantyczne znalazło ludzi — nie wolno go oskarżać o pustkę"
    )
    assert "semantyczne" in query_stage["label"].lower(), (
        "etykieta ma mówić, co naprawdę zastosowano"
    )


@pytest.mark.asyncio
async def test_boolean_mode_still_diagnoses_with_full_text_search(
    app_client, app_auth_headers, monkeypatch
):
    """Kontrola negatywna: w trybie boolowskim nic się nie zmienia.

    Bez tego „naprawa" polegająca na wywaleniu FTS z diagnostyki przechodziłaby
    na zielono, a tryb boolowski przestałby diagnozować własne zapytanie.
    """
    from app.services import hybrid_search

    await _seed_two()

    async def _explode(*a, **k):  # pragma: no cover — nie wolno
        raise AssertionError("tryb boolowski nie może wołać retrievalu")

    monkeypatch.setattr(hybrid_search, "hybrid_candidates", _explode)

    resp = await app_client.post(
        "/api/search/candidates/diagnostics",
        json={
            "q": f"nieistniejacyleksem{uuid.uuid4().hex[:8]}",
            "search_mode": "boolean",
            "tags": [NONCE],
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    query_stage = next(s for s in data["stages"] if s["key"] == "query")
    assert query_stage["count"] == 0
    assert data["first_zeroing_stage"] == "query"
    assert query_stage["label"] == "Zapytanie tekstowe"
