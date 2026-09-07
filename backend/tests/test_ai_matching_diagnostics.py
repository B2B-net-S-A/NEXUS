"""Test the AI-matching diagnostics endpoint (read-only ops view)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_diagnostics_shape(app_client: AsyncClient, app_auth_headers: dict):
    resp = await app_client.get(
        "/api/admin/ai-matching/diagnostics", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # All subsystem sections present.
    for key in (
        "flags",
        "version_trace",
        "indexing_outbox",
        "telemetry",
        "score_cache",
    ):
        assert key in body, f"missing section {key}"

    # Flags include the plan's kill-switches (default off in CI).
    assert body["flags"]["AI_INDEX_OUTBOX_ENABLED"] is False
    assert body["flags"]["AI_SCORING_CONTRACT_V2"] is False

    # Version trace is fully populated.
    vt = body["version_trace"]
    assert vt["ranker_version"]
    assert vt["text_schema_version"]

    # The DB-backed sections resolved (real tables exist in CI) — no error note.
    assert "error" not in body["telemetry"]
    assert body["telemetry"]["impressions"] >= 0
    assert "error" not in body["score_cache"]


@pytest.mark.asyncio
async def test_retrieval_levers_are_observable(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Dźwignię, której nie da się zaobserwować, przestawia się na ślepo.

    `HYBRID_POOL_ENABLED` przełącza pulę dla CAŁEGO ruchu AI, a do 09.2026 nie
    było go w tej odpowiedzi — więc pytanie „czy produkcja liczy dziś hybrydą?"
    nie miało odpowiedzi inaczej niż przez zajrzenie do Coolify. Ten test broni
    obietnicy z docstringu modułu: rollout ma być operowany OBSERWACJĄ.

    Progi liczbowe są tu z tego samego powodu — ustawione w Coolify inaczej niż
    domyślnie zmieniają liczbę wyników widoczną dla rekrutera, a z zewnątrz nie
    widać, która wartość naprawdę obowiązuje.
    """
    resp = await app_client.get(
        "/api/admin/ai-matching/diagnostics", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    flags = resp.json()["flags"]

    for key in (
        "HYBRID_POOL_ENABLED",
        "HYBRID_BM25_POOL_LIMIT",
        "SEARCH_HYBRID_POOL_SIZE",
        "MULTI_QUERY_RETRIEVAL_ENABLED",
        "CV_PASSAGES_ENABLED",
        "RERANKER_ENABLED",
        # 0278: pula SQL-first po must-have — sprawdzana PRZED hybrydą/wektorem
        # w tej samej fasadzie, więc obowiązuje ta sama obietnica obserwacji.
        "STRUCTURED_POOL_ENABLED",
        "STRUCTURED_POOL_LIMIT",
        "STRUCTURED_POOL_MIN_MEMBERS",
        # Wspólny silnik pod `/ai-matches` — dźwignia bez obserwacji przestawia
        # się na ślepo.
        "AI_MATCHES_SHARED_ENGINE",
        "AI_MATCHES_RERANK_TOP_N",
    ):
        assert key in flags, f"dźwignia retrievalu {key} niewidoczna w diagnostyce"

    # Wartość, nie samo istnienie klucza: `None` znaczyłoby, że pole zniknęło
    # z `Settings` i `getattr` zwraca zaślepkę — czyli że diagnostyka pokazuje
    # dźwignię, której już nie ma.
    assert flags["HYBRID_POOL_ENABLED"] is not None
    assert isinstance(flags["SEARCH_HYBRID_POOL_SIZE"], int)
    assert flags["STRUCTURED_POOL_ENABLED"] is not None
    assert isinstance(flags["STRUCTURED_POOL_LIMIT"], int)
    assert isinstance(flags["STRUCTURED_POOL_MIN_MEMBERS"], int)
    assert flags["AI_MATCHES_SHARED_ENGINE"] is not None
    assert isinstance(flags["AI_MATCHES_RERANK_TOP_N"], int)


@pytest.mark.asyncio
async def test_diagnostics_requires_auth(app_client: AsyncClient):
    resp = await app_client.get("/api/admin/ai-matching/diagnostics")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_audit_shape(app_client: AsyncClient, app_auth_headers: dict):
    resp = await app_client.get(
        "/api/admin/ai-matching/audit", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    for key in ("alembic", "schema", "profile_budgets", "coverage"):
        assert key in body, f"missing section {key}"

    # CI DB was built by `alembic upgrade heads` → bookmark(s) exist.
    assert body["alembic"].get("bookmarks"), body["alembic"]
    # Schema inventory resolved (real pg_tables query).
    assert body["schema"].get("table_count", 0) > 0
    assert isinstance(body["schema"].get("unknown_tables"), list)
    # Profile budget detector returns the (possibly empty) lists.
    assert "profiles" in body["profile_budgets"]
    assert "over_budget" in body["profile_budgets"]
    # DB-side coverage counts resolved (Qdrant absent in CI → guarded keys).
    assert body["coverage"].get("db_candidates", -1) >= 0


@pytest.mark.asyncio
async def test_audit_requires_auth(app_client: AsyncClient):
    resp = await app_client.get("/api/admin/ai-matching/audit")
    assert resp.status_code in (401, 403)
