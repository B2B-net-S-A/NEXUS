"""Lista ``GET /api/candidates`` po połączeniu ekranów „Kandydaci" (22.09.2026).

1. Tekst ``q`` w trybie SEMANTYCZNYM — tylko v2 z jawnym ``text_mode``
   auto/semantic; pula retrievalu (``hybrid_candidates``) zastępuje dopasowanie
   dosłowne, kolejność = ranking puli. Osoba / ``literal`` / brak ``text_mode``
   / v1 — dosłownie, jak dotąd.
2. Filtr języków ``?languages=kod[:POZIOM]`` — ta sama reguła co ``languages``
   wyszukiwarki (``candidate_search_predicates.language_clause``).

Retrieval wektorowy jest podstawiany (bez sieci). Baza testowa jest wspólna
i nie jest czyszczona, więc każde żądanie zawęża się własną frazą ``NONCE``
(w ``linkedin_current_company``), a asercje patrzą na własne id.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

NONCE = "zq" + "".join(chr(97 + int(c, 16)) for c in uuid.uuid4().hex[:10])
_IDS: dict[str, int] = {}


async def _seed() -> dict[str, int]:
    if _IDS:
        return _IDS
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.candidate_language import CandidateLanguage

    def person(key: str, **kw: Any) -> Candidate:
        return Candidate(
            name=kw.pop("name", key.capitalize()),
            lastname=kw.pop("lastname", f"Listowy{key}"),
            email=f"{key}-{uuid.uuid4().hex[:10]}@example.com",
            status=CandidateStatus.active,
            linkedin_current_company=NONCE,
            **kw,
        )

    def lang(cand: Candidate, code: str, level: str | None, native: bool = False):
        return CandidateLanguage(
            candidate_id=cand.id,
            language_code=code,
            language_name=code.upper(),
            cefr_level=level,
            is_native=native,
            is_level_unknown=False,
            provenance="manual",
            manual_lock=False,
            version=1,
        )

    async with AsyncSessionLocal() as db:
        rows = {
            "a": person("a", skills=["Python"]),
            "b": person("b", skills=["Kotlin"]),
            "c": person("c", skills=["Java"]),
            "d": person("d", name="Łucja", lastname=f"Żółć{NONCE}"),
        }
        db.add_all(rows.values())
        await db.flush()
        db.add_all(
            [
                lang(rows["a"], "en", "C1"),
                lang(rows["a"], "de", "A2"),
                lang(rows["b"], "en", "B1"),
                lang(rows["c"], "en", None, native=True),
                lang(rows["c"], "de", "B2"),
                CandidateLanguage(
                    candidate_id=rows["d"].id,
                    language_code="en",
                    language_name="EN",
                    cefr_level=None,
                    is_native=False,
                    is_level_unknown=True,
                    provenance="manual",
                    manual_lock=False,
                    version=1,
                ),
            ]
        )
        await db.commit()
        for key, row in rows.items():
            _IDS[key] = row.id
    return _IDS


async def _list_raw(client, headers, **params: Any) -> tuple[int, dict]:
    await _seed()
    query: list[tuple[str, Any]] = [("q_all", NONCE), ("page_size", 100)]
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            query.extend((key, v) for v in value)
        else:
            query.append((key, value))
    resp = await client.get("/api/candidates", params=query, headers=headers)
    return resp.status_code, resp.json()


async def _list(client, headers, **params: Any) -> dict:
    status, body = await _list_raw(client, headers, **params)
    assert status == 200, body
    return body


def _ids(body: dict) -> list[int]:
    own = set(_IDS.values())
    return [item["id"] for item in body["items"] if item["id"] in own]


def _fake_pool(monkeypatch, pairs_fn, *, degraded: bool = False) -> dict:
    from app.services import hybrid_search
    from app.services.hybrid_search import HybridResult

    seen: dict[str, Any] = {"calls": 0}

    async def _fake(db, query, **kwargs):
        seen["calls"] += 1
        seen["query"] = query
        seen["kwargs"] = kwargs
        return HybridResult(pairs=pairs_fn(), degraded=degraded)

    monkeypatch.setattr(hybrid_search, "hybrid_candidates", _fake)
    return seen


def _no_retrieval(monkeypatch) -> None:
    from app.services import hybrid_search

    async def _boom(*args, **kwargs):  # pragma: no cover - nie może zostać zawołane
        raise AssertionError("ta ścieżka nie może wołać retrievalu wektorowego")

    monkeypatch.setattr(hybrid_search, "hybrid_candidates", _boom)


# ── Tryb semantyczny ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_semantyczny_zaweza_do_puli_i_szereguje_jej_rankingiem(
    app_client, app_auth_headers, monkeypatch
):
    ids = await _seed()
    seen = _fake_pool(
        monkeypatch, lambda: [(ids["c"], 0.9), (ids["a"], 0.8), (ids["b"], 0.1)]
    )
    body = await _list(
        app_client,
        app_auth_headers,
        q="doświadczony programista backendu fintech",
        text_mode="auto",
        semantics_version=2,
    )
    assert seen["query"] == "doświadczony programista backendu fintech"
    assert seen["kwargs"]["pool"] == seen["kwargs"]["final_top_k"]
    # „d" jest poza pulą — nie wraca, choć spełnia pozostałe filtry
    assert _ids(body) == [ids["c"], ids["a"], ids["b"]]
    assert body["total"] == 3
    assert body["text_mode_applied"] == "semantic"
    assert body["search_degraded"] is False
    assert body["result_cap_reached"] is False


@pytest.mark.asyncio
async def test_semantyczny_z_jawnym_sortem_sortuje_w_obrebie_puli(
    app_client, app_auth_headers, monkeypatch
):
    ids = await _seed()
    _fake_pool(monkeypatch, lambda: [(ids["c"], 0.9), (ids["a"], 0.8)])
    body = await _list(
        app_client,
        app_auth_headers,
        q="programista",
        text_mode="semantic",
        semantics_version=2,
        sort="oldest",
    )
    # oldest = kolejność zakładania (a przed c), zbiór = pula
    assert _ids(body) == [ids["a"], ids["c"]]
    assert body["text_mode_applied"] == "semantic"


@pytest.mark.asyncio
async def test_semantyczny_pozostale_filtry_dzialaja_na_puli(
    app_client, app_auth_headers, monkeypatch
):
    ids = await _seed()
    _fake_pool(monkeypatch, lambda: [(ids["b"], 0.9), (ids["a"], 0.8)])
    body = await _list(
        app_client,
        app_auth_headers,
        q="programista",
        text_mode="auto",
        semantics_version=2,
        skills_required=["Python"],
    )
    assert _ids(body) == [ids["a"]]
    assert body["total"] == 1


@pytest.mark.asyncio
async def test_pusta_pula_to_zero_wynikow_nie_cala_baza(
    app_client, app_auth_headers, monkeypatch
):
    await _seed()
    _fake_pool(monkeypatch, lambda: [])
    body = await _list(
        app_client,
        app_auth_headers,
        q="programista",
        text_mode="semantic",
        semantics_version=2,
    )
    assert body["items"] == []
    assert body["total"] == 0
    assert body["text_mode_applied"] == "semantic"


@pytest.mark.asyncio
async def test_degradacja_i_sufit_puli_trafiaja_do_odpowiedzi(
    app_client, app_auth_headers, monkeypatch
):
    from app.core.config import settings

    ids = await _seed()
    monkeypatch.setattr(settings, "SEARCH_HYBRID_POOL_SIZE", 2)
    _fake_pool(monkeypatch, lambda: [(ids["a"], 0.9), (ids["b"], 0.8)], degraded=True)
    body = await _list(
        app_client,
        app_auth_headers,
        q="programista",
        text_mode="auto",
        semantics_version=2,
    )
    assert body["search_degraded"] is True
    assert body["result_cap_reached"] is True
    assert _ids(body) == [ids["a"], ids["b"]]


@pytest.mark.asyncio
async def test_tekst_wygladajacy_na_osobe_zostaje_doslowny(
    app_client, app_auth_headers, monkeypatch
):
    ids = await _seed()
    _no_retrieval(monkeypatch)
    body = await _list(
        app_client,
        app_auth_headers,
        q=f"Łucja Żółć{NONCE}",
        text_mode="auto",
        semantics_version=2,
    )
    assert body["text_mode_applied"] == "literal"
    assert _ids(body) == [ids["d"]]
    assert body["search_degraded"] is False


@pytest.mark.asyncio
async def test_jawne_literal_nie_woła_retrievalu(
    app_client, app_auth_headers, monkeypatch
):
    ids = await _seed()
    _no_retrieval(monkeypatch)
    body = await _list(
        app_client,
        app_auth_headers,
        q="kotlin",
        text_mode="literal",
        semantics_version=2,
    )
    assert body["text_mode_applied"] == "literal"
    assert _ids(body) == [ids["b"]]


@pytest.mark.asyncio
async def test_bez_text_mode_v2_zostaje_doslowne(
    app_client, app_auth_headers, monkeypatch
):
    ids = await _seed()
    _no_retrieval(monkeypatch)
    body = await _list(app_client, app_auth_headers, q="kotlin", semantics_version=2)
    assert body["text_mode_applied"] == "literal"
    assert _ids(body) == [ids["b"]]


@pytest.mark.asyncio
async def test_v1_z_text_mode_zostaje_doslowne(
    app_client, app_auth_headers, monkeypatch
):
    """v1 (alerty zapisanych wyszukiwań) — DOKŁADNIE dotychczasowe zachowanie."""
    ids = await _seed()
    _no_retrieval(monkeypatch)
    for mode in ("auto", "semantic"):
        body = await _list(app_client, app_auth_headers, q="kotlin", text_mode=mode)
        assert body["text_mode_applied"] == "literal"
        assert _ids(body) == [ids["b"]]
        assert body["search_degraded"] is False
        assert body["result_cap_reached"] is False


# ── Języki ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_filtr_jezykow_prog_poziomu(app_client, app_auth_headers):
    ids = await _seed()
    # sam kod = próg B2 (jak domyślny `min_level` wyszukiwarki); native spełnia
    # każdy próg, poziom nieznany żadnego
    body = await _list(app_client, app_auth_headers, languages=["en"])
    assert set(_ids(body)) == {ids["a"], ids["c"]}
    body = await _list(app_client, app_auth_headers, languages=["en:B1"])
    assert set(_ids(body)) == {ids["a"], ids["b"], ids["c"]}
    body = await _list(app_client, app_auth_headers, languages=["EN:c2"])
    assert set(_ids(body)) == {ids["c"]}
    body = await _list(app_client, app_auth_headers, languages=["en:native"])
    assert set(_ids(body)) == {ids["c"]}
    # kilka wpisów = każdy wymagany (AND)
    body = await _list(app_client, app_auth_headers, languages=["en:B1", "de:A2"])
    assert set(_ids(body)) == {ids["a"], ids["c"]}


@pytest.mark.asyncio
async def test_filtr_jezykow_zgodny_z_wyszukiwarka(app_client, app_auth_headers):
    ids = await _seed()
    from_list = set(
        _ids(await _list(app_client, app_auth_headers, languages=["en:B1", "de"]))
    )
    resp = await app_client.post(
        "/api/search/candidates",
        json={
            "q_all": [NONCE],
            "page": 1,
            "page_size": 100,
            "semantics_version": 2,
            "languages": [{"code": "EN", "min_level": "B1"}, {"code": "DE"}],
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    own = set(ids.values())
    from_search = {i["id"] for i in resp.json()["items"] if i["id"] in own}
    assert from_list == from_search == {ids["c"]}


@pytest.mark.parametrize("value", ["e", "en:Z9", "en:", "12:B2", "en:B2:C1"])
@pytest.mark.asyncio
async def test_bledny_filtr_jezyka_to_422_po_polsku(
    app_client, app_auth_headers, value
):
    status, body = await _list_raw(app_client, app_auth_headers, languages=[value])
    assert status == 422
    assert "język" in str(body["detail"]).lower()


# ── Eksport „z filtra” = ten sam zbiór co lista ───────────────────────────


@pytest.mark.asyncio
async def test_eksport_z_filtra_w_trybie_semantycznym_zgodny_z_lista(
    app_client, app_auth_headers, monkeypatch
):
    """Połączony ekran eksportuje to, co pokazuje: eksport z filtra z tym samym
    `q` i `text_mode` idzie tą samą pulą retrievalu i tą samą kolejnością."""
    import csv
    import io

    ids = await _seed()
    _fake_pool(monkeypatch, lambda: [(ids["b"], 0.9), (ids["a"], 0.5)])
    q = "doświadczony programista backendu fintech"
    body = await _list(
        app_client, app_auth_headers, q=q, text_mode="auto", semantics_version=2
    )
    list_ids = _ids(body)
    assert list_ids == [ids["b"], ids["a"]]

    resp = await app_client.post(
        "/api/candidates/export",
        json={
            "format": "csv",
            "scope": "filtered",
            "filters": {
                "q": q,
                "q_all": [NONCE],
                "text_mode": "auto",
                "semantics_version": 2,
            },
            "candidate_ids": [],
            "limit": 100_000,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    exported = [
        int(row["id"])
        for row in csv.DictReader(io.StringIO(resp.text))
        if int(row["id"]) in set(ids.values())
    ]
    assert exported == list_ids
