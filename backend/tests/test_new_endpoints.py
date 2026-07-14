"""Integration tests for Phase B1/B3/C1/D1 endpoints (in-process ASGI).

Uses `app_client` + `app_auth_headers` fixtures from conftest.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


# ── Skill taxonomy (Phase B1) ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skills_autocomplete_finds_python(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    r = await app_client.get(
        "/api/skills/autocomplete", params={"q": "pyth"}, headers=app_auth_headers
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(s["name"].lower() == "python" for s in items)


@pytest.mark.asyncio
async def test_skills_autocomplete_matches_alias(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Alias 'k8s' should surface 'kubernetes'."""
    r = await app_client.get(
        "/api/skills/autocomplete", params={"q": "k8s"}, headers=app_auth_headers
    )
    assert r.status_code == 200
    names = [s["name"].lower() for s in r.json()["items"]]
    assert "kubernetes" in names


@pytest.mark.asyncio
async def test_skills_list_returns_all(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    r = await app_client.get("/api/skills", headers=app_auth_headers)
    assert r.status_code == 200
    payload = r.json()
    assert payload["total"] >= 10
    assert any("aliases" in s for s in payload["items"])


# ── Scoring weight profiles CRUD (Phase D1) ─────────────────────────────────


@pytest.mark.asyncio
async def test_scoring_weights_rejects_sum_not_100(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    r = await app_client.post(
        "/api/scoring-weights",
        headers=app_auth_headers,
        json={
            "name": "Broken 99",
            "weights": {
                "semantic": 20,
                "skills": 20,
                "salary": 20,
                "location": 20,
                "availability": 19,  # sum = 99
            },
        },
    )
    # Pydantic v2 returns 422 for field_validator failures
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_scoring_weights_create_list_delete(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    # Create
    payload = {
        "name": "Pytest Profile",
        "weights": {
            "semantic": 30,
            "skills": 40,
            "salary": 15,
            "location": 10,
            "availability": 5,
        },
        "active": True,
    }
    r = await app_client.post(
        "/api/scoring-weights", headers=app_auth_headers, json=payload
    )
    assert r.status_code == 201, r.text
    created = r.json()
    pid = created["id"]
    assert created["name"] == "Pytest Profile"
    assert created["weights"]["skills"] == 40

    # List
    r = await app_client.get("/api/scoring-weights", headers=app_auth_headers)
    assert r.status_code == 200
    assert any(p["id"] == pid for p in r.json())

    # Cleanup
    r = await app_client.delete(f"/api/scoring-weights/{pid}", headers=app_auth_headers)
    assert r.status_code == 204


# ── Candidates filter stack (Phase A1 + B3) ─────────────────────────────────


@pytest.mark.asyncio
async def test_candidates_include_match_stats_populates_field(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    r = await app_client.get(
        "/api/candidates",
        params={"include_match_stats": "true", "page_size": 3, "match_threshold": 35},
        headers=app_auth_headers,
    )
    assert r.status_code == 200
    items = r.json()["items"]
    if not items:  # DB may be empty in CI
        return
    # All items should have match_stats populated (even if open_count=0)
    for it in items:
        assert "match_stats" in it
        if it["match_stats"] is not None:
            assert {"open_count", "total_open", "top_score"} <= set(
                it["match_stats"].keys()
            )


@pytest.mark.asyncio
async def test_candidates_skills_filter_narrows_result_set(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    baseline = await app_client.get(
        "/api/candidates", params={"page_size": 50}, headers=app_auth_headers
    )
    assert baseline.status_code == 200
    total_all = baseline.json()["total"]

    filtered = await app_client.get(
        "/api/candidates",
        params={"skills": "python", "page_size": 50},
        headers=app_auth_headers,
    )
    assert filtered.status_code == 200
    total_py = filtered.json()["total"]
    assert 0 <= total_py <= total_all


# ── Candidates last-activity inline fields (Phase „Search inline visibility") ──


@pytest.mark.asyncio
async def test_candidates_include_last_activity_adds_triage_fields(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Smoke test: `include_last_activity=true` returns the 3 new fields on every
    item (None when no signal exists). Combined with active_recruitments so we
    catch any accidental cross-blocking between the two aggregation blocks.
    """
    r = await app_client.get(
        "/api/candidates",
        params={
            "include_last_activity": "true",
            "include_active_recruitments": "true",
            "page_size": 3,
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    if not items:  # DB may be empty in CI
        return
    for it in items:
        assert "last_note_preview" in it
        assert "last_rejection_reason" in it
        assert "last_rate" in it
        # Each is either None or a non-empty string.
        for key in ("last_note_preview", "last_rejection_reason", "last_rate"):
            value = it[key]
            assert value is None or (isinstance(value, str) and len(value) > 0), (
                f"{key} must be None or non-empty str, got {value!r}"
            )
        # Preview length cap is 120 chars + optional ellipsis
        if isinstance(it["last_note_preview"], str):
            assert len(it["last_note_preview"]) <= 121


@pytest.mark.asyncio
async def test_candidates_default_omits_last_activity(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Without `include_last_activity`, the 3 fields default to None (cheaper
    response — keeps the flag opt-in for other callers)."""
    r = await app_client.get(
        "/api/candidates",
        params={"page_size": 3},
        headers=app_auth_headers,
    )
    assert r.status_code == 200
    items = r.json()["items"]
    if not items:
        return
    for it in items:
        assert it.get("last_note_preview") is None
        assert it.get("last_rejection_reason") is None
        assert it.get("last_rate") is None


def test_format_helpers_strip_html_truncate_and_format_rate():
    """Unit-test the 3 pure helpers — they don't touch DB so we don't need a
    DB fixture. Keeps regression coverage cheap."""
    from app.api.candidates import (
        _format_note_preview,
        _format_rate,
        _format_rejection_reason,
    )

    assert (
        _format_note_preview(
            "<p>Świetny <strong>Python</strong> dev. &nbsp;Idzie do klienta.</p>"
        )
        == "Świetny Python dev. Idzie do klienta."
    )
    long_note = "a" * 200
    # Pin truncation mechanics independently of the product's wider UI default.
    preview = _format_note_preview(long_note, max_chars=120)
    assert preview.endswith("…")
    assert len(preview) <= 121

    # Tiptap JSON doc — should extract just the text leaves.
    tiptap_doc = (
        '{"type":"doc","content":['
        '{"type":"paragraph","content":[{"type":"text","text":"Hello"},'
        '{"type":"text","text":" world"}]}]}'
    )
    assert _format_note_preview(tiptap_doc) == "Hello world"

    # Legacy shape used by older notes: {"content": "raw text"}.
    assert (
        _format_note_preview('{"content":"Quick chat z kandydatem"}')
        == "Quick chat z kandydatem"
    )

    # User mentions are placeholders — replaced with @user so the preview
    # doesn't leak internal ids.
    assert (
        _format_note_preview("Dziś $$user_37$$ ustalił z $$user_204$$ rate.")
        == "Dziś @user ustalił z @user rate."
    )

    # Malformed JSON falls back to plain text (no exception leakage).
    assert _format_note_preview("{broken") == "{broken"

    assert _format_rate(150, "hourly", "PLN") == "150 PLN/h"
    assert _format_rate(1500, "daily", None) == "1 500 PLN/d"
    assert _format_rate(30000, "monthly", "EUR") == "30 000 EUR/mc"
    # Non-integer Decimal-like value
    assert "150.50" in _format_rate(150.5, "hourly", "PLN").replace(" ", "")

    # Sama kategoria gdy nie ma notatki rekrutera — BEZ " · job (client)".
    assert (
        _format_rejection_reason(
            reason_name="Cena za wysoka",
            stage_notes=None,
            rejection_note=None,
        )
        == "Cena za wysoka"
    )
    # rejection_note (np. zbackfillowane z Traffit "Po CV") gdy brak reason_name.
    assert (
        _format_rejection_reason(
            reason_name=None,
            stage_notes=None,
            rejection_note="Po CV",
        )
        == "Po CV"
    )
    # Decyzja 2026-06-10: kategoria + notatka rekrutera razem ("DLACZEGO" obok
    # bucketu). To jest CORE tej zmiany — rekruter chce widzieć swoją notatkę.
    # NEXUS-native: kategoria z FK (reason_name), notatka w notes.
    assert (
        _format_rejection_reason(
            reason_name="Po CV",
            stage_notes="Kandydat nie jest zainteresowany tą ofertą",
            rejection_note=None,
        )
        == "Po CV — Kandydat nie jest zainteresowany tą ofertą"
    )
    # Import z Traffita: kategoria w rejection_note (backfill nazwy), notatka =
    # content.description zbackfillowany do notes. Też łączymy w jedną linię.
    assert (
        _format_rejection_reason(
            reason_name=None,
            stage_notes="<p>brak upgrade <b>java/spring boot</b></p>",
            rejection_note="Po CV",
        )
        == "Po CV — brak upgrade java/spring boot"
    )
    # Notatka, która tylko powtarza kategorię, nie jest duplikowana.
    assert (
        _format_rejection_reason(
            reason_name="Po CV",
            stage_notes="po cv",
            rejection_note=None,
        )
        == "Po CV"
    )
    # Fallback chain — no reason_name + no rejection_note → stage_notes used
    assert (
        _format_rejection_reason(
            reason_name=None,
            stage_notes="<p>Brak match na seniority</p>",
            rejection_note=None,
        )
        == "Brak match na seniority"
    )
    # Pełna treść — powód dłuższy niż 120 zn. (cap notatki) NIE jest ucinany do 120;
    # rekruter chce widzieć całość. Cap bezpiecznika to _REJECTION_REASON_MAX_CHARS.
    long_reason = "Odrzucony bo " + ("za mało doświadczenia, " * 12)
    assert len(long_reason) > 120
    long_formatted = _format_rejection_reason(
        reason_name=long_reason,
        stage_notes=None,
        rejection_note=None,
    )
    assert long_formatted is not None and len(long_formatted) > 120
    # All-empty case → "Odrzucony" placeholder
    assert (
        _format_rejection_reason(
            reason_name=None,
            stage_notes=None,
            rejection_note=None,
        )
        == "Odrzucony"
    )
