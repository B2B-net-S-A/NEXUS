"""Wyszukiwanie AI kandydatów: strona wyników rozjeżdża się z licznikiem.

Ścieżka `search_mode="hybrid"` w `POST /api/search/candidates` (domyślny tryb
`CandidateSearchView`) składa wynik z DWÓCH niezależnych źródeł:

  * `hybrid_order` — do 200 id z retrievalu (BM25 + wektor + RRF),
  * `where_clause` — WSZYSTKIE pozostałe filtry (chipy strukturalne, kubełki
    boolowskie, wykluczenie z rekrutacji, blacklista).

`total` liczy PRZECIĘCIE obu (`COUNT` po `where_clause`, w którym siedzi
`Candidate.id.in_(hybrid_order)`), ale strona jest wycinana z `hybrid_order`
PRZED filtrowaniem i dopiero potem przepuszczana przez `where_clause`. Te dwie
liczby opisują więc różne zbiory.

Skutek u rekrutera: nagłówek mówi „N wyników", a strona pokazuje ich garść;
strony w środku listy bywają PUSTE, mimo że `total > 0`. Im więcej chipów, tym
gorzej — czyli dokładnie wtedy, gdy zapytanie jest najbardziej precyzyjne.
"""

from __future__ import annotations

import uuid

import pytest

# Termin, którego nie ma nikt inny w bazie — pula hybrydy jest tu podstawiana
# wprost, ale kandydaci muszą być odróżnialni od cudzych wierszy.
NONCE = uuid.uuid4().hex[:10]


async def _seed_pool() -> tuple[list[int], list[int]]:
    """Dwudziestu kandydatów; co CZWARTY jest oznaczony tagiem `NONCE`.

    Zwraca `(wszystkie_id_w_kolejnosci, id_z_tagiem)`. Kolejność zwracanej listy
    jest kolejnością, w jakiej podstawimy ją jako wynik retrievalu — dzięki temu
    wiadomo dokładnie, co powinno wylądować na której stronie.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus

    async with AsyncSessionLocal() as db:
        rows: list[Candidate] = []
        for i in range(20):
            rows.append(
                Candidate(
                    name=f"Pula{i:02d}",
                    lastname=f"Hybryda-{uuid.uuid4().hex[:6]}",
                    email=f"pool-{uuid.uuid4().hex[:8]}@example.com",
                    status=CandidateStatus.active,
                    # Co czwarty niesie tag — to będzie chip strukturalny,
                    # czyli filtr NIEZALEŻNY od puli retrievalu.
                    tags=[NONCE] if i % 4 == 0 else [],
                )
            )
        db.add_all(rows)
        await db.commit()
        for r in rows:
            await db.refresh(r)
        all_ids = [r.id for r in rows]
        tagged = [r.id for r in rows if r.tags]
        return all_ids, tagged


@pytest.fixture
def _stub_hybrid(monkeypatch):
    """Podstaw deterministyczną pulę retrievalu zamiast Voyage/Qdranta.

    Patch idzie na `app.services.hybrid_search.hybrid_candidates`, bo
    `api/search.py` importuje tę nazwę WEWNĄTRZ handlera (`noqa: PLC0415`) —
    czyli odczytuje atrybut modułu w czasie wywołania.
    """

    def _install(order: list[int]):
        from app.services import hybrid_search
        from app.services.hybrid_search import HybridResult

        async def _fake(db, query, **kwargs):
            return HybridResult(pairs=[(cid, 1.0) for cid in order])

        monkeypatch.setattr(hybrid_search, "hybrid_candidates", _fake)

    return _install


@pytest.mark.asyncio
async def test_hybrid_page_matches_the_total_it_reports(
    app_client, app_auth_headers, _stub_hybrid
):
    """`total` i wiersze na stronach MUSZĄ opisywać ten sam zbiór.

    Pula retrievalu = 20 osób, chip `tags` przepuszcza 5 z nich. Przy
    `page_size=2` uczciwy wynik to `total=5` i strony 2+2+1. Dziś strona jest
    wycinana z niefiltrowanej dwudziestki, więc pierwsze dwie pozycje puli
    (kandydaci bez tagu) dają PUSTĄ stronę pierwszą — przy `total=5`.
    """
    all_ids, tagged = await _seed_pool()
    _stub_hybrid(all_ids)

    body = {
        "q": "python",
        "search_mode": "hybrid",
        "tags": [NONCE],
        "page_size": 2,
    }

    seen: list[int] = []
    total = None
    for page in range(1, 5):
        resp = await app_client.post(
            "/api/search/candidates", json={**body, "page": page},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        total = data["total"]
        seen.extend(item["id"] for item in data["items"])

    assert total == len(tagged), (
        f"licznik ma mówić o kandydatach z tagiem: {total} != {len(tagged)}"
    )
    assert sorted(seen) == sorted(tagged), (
        "przewertowanie wszystkich stron musi oddać DOKŁADNIE ten zbiór, "
        f"o którym mówi licznik; dostaliśmy {len(seen)} z {len(tagged)}"
    )


@pytest.mark.asyncio
async def test_hybrid_first_page_is_not_empty_when_total_is_positive(
    app_client, app_auth_headers, _stub_hybrid
):
    """Pierwsza strona niepustego wyniku nie może być pusta.

    Najostrzejsza postać tego samego defektu i ta, którą użytkownik zgłasza:
    „wyszukiwarka AI mówi, że coś znalazła, a lista jest pusta". Pulę ustawiamy
    tak, żeby wszystkie trafienia chipa siedziały na KOŃCU puli retrievalu —
    układ typowy, gdy chip zawęża po czymś, czego wektor nie modeluje.
    """
    all_ids, tagged = await _seed_pool()
    untagged = [cid for cid in all_ids if cid not in tagged]
    _stub_hybrid(untagged + tagged)  # trafienia dopiero na pozycjach 15-19

    resp = await app_client.post(
        "/api/search/candidates",
        json={
            "q": "python",
            "search_mode": "hybrid",
            "tags": [NONCE],
            "page": 1,
            "page_size": 5,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["total"] > 0, "warunek wstępny testu: wynik ma być niepusty"
    assert data["items"], (
        f"licznik mówi o {data['total']} kandydatach, a pierwsza strona jest "
        "pusta — pustka czyta się jak brak ludzi w bazie"
    )


@pytest.mark.asyncio
async def test_meta_says_when_total_is_only_the_retrieval_ceiling(
    app_client, app_auth_headers, _stub_hybrid, monkeypatch
):
    """Pula wyczerpana ⇒ `total` to sufit retrievalu, i UI ma to wiedzieć.

    Bez tego sygnału przełączenie „Semantycznie" na zapytaniu ogólnym zamienia
    „11 091 wyników" w „200" i wygląda jak utrata bazy zamiast jak „200
    najtrafniejszych". Sufit obniżamy do rozmiaru zaseedowanej puli, żeby test
    nie zależał od 200 wierszy.
    """
    from app.api import search as search_api

    all_ids, _ = await _seed_pool()
    monkeypatch.setattr(search_api, "_HYBRID_POOL", len(all_ids))
    _stub_hybrid(all_ids)

    async def _ask(order: list[int]) -> dict:
        _stub_hybrid(order)
        resp = await app_client.post(
            "/api/search/candidates",
            json={"q": "python", "search_mode": "hybrid", "page_size": 5},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    full = await _ask(all_ids)
    assert full["meta"]["result_cap_reached"] is True, (
        "pula oddała komplet — `total` jest sufitem, nie liczbą osób w bazie"
    )

    partial = await _ask(all_ids[:-1])
    assert partial["meta"]["result_cap_reached"] is False, (
        "pula niewyczerpana ⇒ `total` naprawdę zlicza wszystkich pasujących"
    )
