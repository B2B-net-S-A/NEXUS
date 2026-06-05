"""Regression test for pipeline-template stage route ordering.

`PATCH /api/pipeline-templates/{template_id}/stages/reorder` MUST resolve to
`reorder_stages`, not to the parameterized `update_stage` route
(`/stages/{stage_id}`). FastAPI matches routes in declaration order: if the
`{stage_id}` route is declared first, the literal segment "reorder" is parsed as
a stage_id and the request fails with HTTP 422 (`int_parsing`) instead of
reordering.

This shipped broken to production (confirmed 2026-06-05): admin drag-to-reorder
in Settings → Pipeline Templates returned 422 for every reorder. The fix is to
declare the static `/stages/reorder` route before `/stages/{stage_id}` in
`app/api/pipeline_templates.py`.

Uses the in-process `app_client` / `app_auth_headers` fixtures (real postgres in
CI). The admin seeded by `app_client` satisfies the ManagerOrAdmin guard.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient


async def _create_template_with_stages(
    app_client: AsyncClient, headers: dict
) -> tuple[int, list[int]]:
    """Create a template with three ordered stages.

    Returns ``(template_id, [stage_id_0, stage_id_1, stage_id_2])`` where the
    stages are created at orders 0, 1, 2 respectively.
    """
    r = await app_client.post(
        "/api/pipeline-templates",
        headers=headers,
        json={"name": f"Reorder-{uuid.uuid4().hex[:8]}"},
    )
    assert r.status_code == 201, r.text
    template_id = r.json()["id"]

    stage_ids: list[int] = []
    for i, name in enumerate(["New", "Screening", "Interview"]):
        rs = await app_client.post(
            f"/api/pipeline-templates/{template_id}/stages",
            headers=headers,
            json={"name": name, "order": i, "category": "internal"},
        )
        assert rs.status_code == 201, rs.text
        stage_ids.append(rs.json()["id"])
    return template_id, stage_ids


async def _stage_orders(
    app_client: AsyncClient, headers: dict, template_id: int
) -> dict[int, int]:
    r = await app_client.get(f"/api/pipeline-templates/{template_id}", headers=headers)
    assert r.status_code == 200, r.text
    return {s["id"]: s["order"] for s in r.json()["stages"]}


async def test_reorder_stages_returns_204_and_updates_orders(
    app_client: AsyncClient, app_auth_headers: dict
):
    """The static /stages/reorder route returns 204 and actually reorders.

    Pre-fix this returned 422 because the request was matched by the
    parameterized /stages/{stage_id} route with stage_id="reorder".
    """
    template_id, (s0, s1, s2) = await _create_template_with_stages(
        app_client, app_auth_headers
    )

    # Reverse the order: s0 -> 2, s1 -> 1, s2 -> 0.
    resp = await app_client.patch(
        f"/api/pipeline-templates/{template_id}/stages/reorder",
        headers=app_auth_headers,
        json=[
            {"stage_id": s0, "order": 2},
            {"stage_id": s1, "order": 1},
            {"stage_id": s2, "order": 0},
        ],
    )
    # The whole point of the fix: 204, not 422 int_parsing from the
    # {stage_id} route swallowing "reorder".
    assert resp.status_code == 204, resp.text

    orders = await _stage_orders(app_client, app_auth_headers, template_id)
    assert orders[s0] == 2
    assert orders[s1] == 1
    assert orders[s2] == 0


async def test_reorder_route_not_shadowed_by_stage_id_route(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Proof the request reaches `reorder_stages`, not `update_stage`.

    A reorder body referencing an unknown stage_id yields `reorder_stages`' own
    404 ("... not in template ..."). If the `{stage_id}` route had matched
    first, the path segment "reorder" would have failed int parsing with a 422
    before any request-body handling.
    """
    template_id, _ = await _create_template_with_stages(app_client, app_auth_headers)

    resp = await app_client.patch(
        f"/api/pipeline-templates/{template_id}/stages/reorder",
        headers=app_auth_headers,
        json=[{"stage_id": 999_999_999, "order": 0}],
    )
    assert resp.status_code == 404, resp.text
    assert "not in template" in resp.json()["detail"]


async def test_update_stage_by_int_id_still_works(
    app_client: AsyncClient, app_auth_headers: dict
):
    """The parameterized /stages/{stage_id} route still resolves for real ids.

    Moving reorder_stages above update_stage must not break the existing
    single-stage PATCH.
    """
    template_id, stage_ids = await _create_template_with_stages(
        app_client, app_auth_headers
    )
    stage_id = stage_ids[0]

    resp = await app_client.patch(
        f"/api/pipeline-templates/{template_id}/stages/{stage_id}",
        headers=app_auth_headers,
        json={"name": "Renamed"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == stage_id
    assert body["name"] == "Renamed"


async def test_reorder_requires_auth(app_client: AsyncClient):
    """The route is guarded; an unauthenticated call is 401/403 (never a 422
    from the literal "reorder" being parsed as a stage id)."""
    resp = await app_client.patch(
        "/api/pipeline-templates/1/stages/reorder",
        json=[{"stage_id": 1, "order": 0}],
    )
    assert resp.status_code in (401, 403)
