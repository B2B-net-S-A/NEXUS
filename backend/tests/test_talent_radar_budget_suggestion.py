"""Talent Radar suggests the budget and remote hint from the pasted request.

``POST /api/talent-radar/interpret`` returns ``suggestions`` (17.09.2026): the
upper PLN/h budget stated in the text (the front fills an EMPTY budget field)
and ``remote_only`` when the text says the work is remote (a hint under the
field, never a filter). Rate reading reuses ``pln_hourly_bounds`` — the same
grammar the Champion intake trusts — so a phrase it rejects suggests nothing.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services.champion_intake import budget_max_pln_hour


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Szukamy Java Dev, stawka do 160 zl/h, Warszawa", 160),
        ("Budżet: 140–160 zł/h netto B2B", 160),
        ("PLN 140/h, praca hybrydowa", 140),
        ("od 120 do 150 zł za godzinę", 150),
        ("Senior: 120 zł/h i 160 zł/h dla leada", None),
        ("Szukamy Java Developera, Kraków, B2B", None),
        ("stawka 1000 zł/MD", None),
        ("", None),
        (None, None),
    ],
)
def test_budget_suggestion_from_pasted_text(text, expected):
    assert budget_max_pln_hour(text) == expected



@pytest.mark.parametrize(
    "text",
    [
        "1" + " " * 20000 + "x",
        "Stawka: 150" + "\n" * 5000,
        "150" + " \u00a0" * 5000,
        ("do 160 zl " + " " * 300) * 60,
    ],
)
def test_budget_suggestion_is_linear_on_hostile_whitespace(text):
    """A request pasted from Word with long blank runs must not stall the API.

    The previous pattern backtracked cubically on whitespace (a 2 000-space
    run took ~42 s) inside an async handler on a single uvicorn process.
    """
    import time

    started = time.perf_counter()
    budget_max_pln_hour(text)
    assert time.perf_counter() - started < 0.5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "budget", "remote_only"),
    [
        ("Java Developer, 100% zdalnie, do 160 zl/h", 160, True),
        ("Java Developer, hybrydowo Warszawa", None, None),
    ],
)
async def test_interpret_returns_suggestions(
    app_client: AsyncClient,
    app_auth_headers: dict,
    text: str,
    budget,
    remote_only,
):
    resp = await app_client.post(
        "/api/talent-radar/interpret",
        headers=app_auth_headers,
        json={"client_id": 1, "text": text},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["suggestions"] == {
        "budget_max_pln_hour": budget,
        "remote_only": remote_only,
    }
    # The requirements preview keeps its keys next to the suggestions.
    assert "must" in body
