"""Blocking analytics API contract and authorization checks for CI.

These tests intentionally inspect the generated OpenAPI document rather than a
hand-maintained copy.  A response-model or router change therefore cannot ship
without updating the frontend contract in the same pull request.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.analytics.schemas import (
    CallsData,
    OverviewData,
    PipelineSnapshotData,
    RecruitmentFunnelData,
    SourcesData,
)


VIEWER_SAFE_MODELS = (
    OverviewData,
    PipelineSnapshotData,
    RecruitmentFunnelData,
    SourcesData,
    CallsData,
)

FORBIDDEN_VIEWER_FIELDS = {
    "candidate_id",
    "candidate_name",
    "user_id",
    "user_name",
    "email",
    "client_id",
    "client_name",
    "entity_id",
    "rate_client",
    "rate_candidate",
    "salary",
    "currency",
    "amount",
    "margin",
    "revenue",
    "profit",
    "pnl",
}

VIEWER_SAFE_PATHS = {
    "/api/analytics/v1/overview",
    "/api/analytics/v1/pipeline/snapshot",
    "/api/analytics/v1/recruitment/funnel",
    "/api/analytics/v1/sources",
    "/api/analytics/v1/calls/aggregate",
}

REQUIRED_ANALYTICS_PATHS = VIEWER_SAFE_PATHS | {
    "/api/analytics/v1/recruitment/recent-hires",
    "/api/analytics/v1/me/kpis",
    "/api/analytics/v1/me/calls",
    "/api/analytics/v1/team/kpis",
    "/api/analytics/v1/team/calls",
    "/api/analytics/v1/clients/{client_id}/operations",
    "/api/analytics/v1/clients/{client_id}/finance",
    "/api/analytics/v1/finance/summary",
    "/api/analytics/v1/finance/trend",
    "/api/analytics/v1/finance/clients",
    "/api/analytics/v1/finance/adjustments",
    "/api/analytics/v1/executive/board",
    "/api/analytics/v1/commercial/tenders",
    "/api/analytics/v1/delivery-leads/performance",
    "/api/analytics/v1/recruitment/users/{user_id}",
    "/api/analytics/v1/meta/metrics",
}


def _property_names(value: Any) -> set[str]:
    """Collect JSON-schema property names recursively, including ``$defs``."""

    names: set[str] = set()
    if isinstance(value, dict):
        properties = value.get("properties")
        if isinstance(properties, dict):
            names.update(str(name) for name in properties)
        for nested in value.values():
            names.update(_property_names(nested))
    elif isinstance(value, list):
        for nested in value:
            names.update(_property_names(nested))
    return names


def _resolve_openapi_schema(spec: dict[str, Any], schema: dict[str, Any]) -> dict:
    seen: set[str] = set()
    while "$ref" in schema:
        reference = str(schema["$ref"])
        assert reference.startswith("#/components/schemas/")
        assert reference not in seen, f"cyclic OpenAPI schema reference: {reference}"
        seen.add(reference)
        name = reference.rsplit("/", 1)[-1]
        schema = spec["components"]["schemas"][name]
    return schema


def test_all_viewer_safe_schemas_exclude_pii_ids_and_finance() -> None:
    for model in VIEWER_SAFE_MODELS:
        fields = _property_names(model.model_json_schema())
        leaked = fields & FORBIDDEN_VIEWER_FIELDS
        assert not leaked, f"{model.__name__} leaks viewer-forbidden fields: {leaked}"


def test_generated_openapi_contains_versioned_authenticated_envelopes() -> None:
    from app.main import app

    spec = app.openapi()
    assert REQUIRED_ANALYTICS_PATHS <= set(spec["paths"])

    envelope_fields = {
        "schema_version",
        "metric_version",
        "generated_at",
        "scope",
        "period",
        "quality",
        "data",
    }
    for path in REQUIRED_ANALYTICS_PATHS:
        operation = spec["paths"][path]["get"]
        # Bearer auth must be present in the generated contract; this catches
        # accidentally removing the capability dependency from a route.
        assert operation.get("security"), f"{path} is missing auth security"
        response_schema = operation["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        resolved = _resolve_openapi_schema(spec, response_schema)
        assert envelope_fields <= set(resolved.get("properties", {})), path


@pytest.mark.asyncio
async def test_passive_viewer_cannot_receive_team_analytics_2xx(app_client) -> None:
    """A forbidden response must be an explicit 403, never a 2xx or a 500."""

    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token, hash_password
    from app.models.user import User, UserRole

    email = f"analytics-viewer-{uuid.uuid4().hex[:12]}@example.com"
    async with AsyncSessionLocal() as db:
        viewer = User(
            email=email,
            password_hash=hash_password("ViewerOnly-CI-Password!"),
            name="Analytics CI Viewer",
            role=UserRole.user,
            roles=[UserRole.user.value],
            is_active=True,
        )
        db.add(viewer)
        await db.commit()
        await db.refresh(viewer)
        viewer_id = viewer.id

    try:
        token = create_access_token(viewer_id, UserRole.user.value)
        response = await app_client.get(
            "/api/analytics/v1/team/kpis?period=month",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert not 200 <= response.status_code < 300, response.text
        assert response.status_code == 403, response.text
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(User).where(User.id == viewer_id))
            await db.commit()
