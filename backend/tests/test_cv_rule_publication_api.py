"""Hosted DB/API acceptance for CV-17 publication and concurrent editors."""

import asyncio
import uuid

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.client_cv_rule_publication import ClientCvRulePublication
from app.services.cv_generator_b2b.client_rules import resolve_client_rule
from tests.test_client_cv_rules_recipe_api import _cleanup, _headers_for, _make_client


async def test_draft_publish_restore_preserves_runtime_and_immutable_versions(
    app_client,
):
    cid = await _make_client(f"Publication {uuid.uuid4().hex[:8]}")
    url = f"/api/clients/{cid}/cv-rule"
    try:
        headers = await _headers_for(
            app_client, "delivery_lead", assigned_client_id=cid
        )
        initial = {
            "filename_pattern": "V1_{IMIE_NAZWISKO}",
            "cv_language": "pl",
            "cv_content_mode_cap": "tailored",
            "cv_interactive_enabled": True,
            "confirm": True,
            "expected_revision": 0,
        }
        response = await app_client.put(url, headers=headers, json=initial)
        assert response.status_code == 200, response.text
        assert response.json()["edit_revision"] == 1
        draft = {
            **initial,
            "filename_pattern": "V2_{IMIE_NAZWISKO}",
            "cv_language": "en",
            "cv_content_mode_cap": "basic",
            "cv_interactive_enabled": False,
            "confirm": False,
            "expected_revision": 1,
        }
        response = await app_client.put(url, headers=headers, json=draft)
        assert response.status_code == 200, response.text
        assert response.json()["is_active"] is True
        assert response.json()["version"] == 1
        assert response.json()["cv_language"] == "pl"
        assert response.json()["draft_payload"]["cv_language"] == "en"
        async with AsyncSessionLocal() as db:
            effective = await resolve_client_rule(db, cid)
            client = await db.get(Client, cid)
            assert effective.cv_language == "pl"
            assert client.cv_content_mode_cap == "tailored"
            assert client.cv_interactive_enabled is True

        stale = await app_client.put(url, headers=headers, json=draft)
        assert stale.status_code == 409, stale.text
        response = await app_client.post(
            url + "/confirm", headers=headers, params={"expected_revision": 2}
        )
        assert response.status_code == 200, response.text
        assert response.json()["version"] == 2
        assert response.json()["cv_language"] == "en"
        assert response.json()["cv_interactive_enabled"] is False
        assert response.json()["draft_payload"] is None

        response = await app_client.post(
            url + "/versions/1/restore",
            headers=headers,
            params={"expected_revision": 3},
        )
        assert response.status_code == 200, response.text
        assert response.json()["cv_language"] == "en"
        assert response.json()["draft_payload"]["cv_language"] == "pl"
        response = await app_client.post(
            url + "/confirm", headers=headers, params={"expected_revision": 4}
        )
        assert response.status_code == 200, response.text
        assert response.json()["version"] == 3
        assert response.json()["cv_language"] == "pl"
        assert response.json()["cv_interactive_enabled"] is True
        async with AsyncSessionLocal() as db:
            versions = (
                await db.scalars(
                    select(ClientCvRulePublication)
                    .where(ClientCvRulePublication.client_id == cid)
                    .order_by(ClientCvRulePublication.version)
                )
            ).all()
            assert [v.recipe["cv_language"] for v in versions] == ["pl", "en", "pl"]
            assert [v.recipe["cv_interactive_enabled"] for v in versions] == [
                True,
                False,
                True,
            ]
    finally:
        await _cleanup([cid])


async def test_two_first_saves_cannot_silently_overwrite_each_other(app_client):
    cid = await _make_client(f"Concurrent recipe {uuid.uuid4().hex[:8]}")
    url = f"/api/clients/{cid}/cv-rule"
    try:
        headers = await _headers_for(app_client, "admin")
        responses = await asyncio.gather(
            *[
                app_client.put(
                    url,
                    headers=headers,
                    json={
                        "filename_pattern": f"{prefix}_{{IMIE_NAZWISKO}}",
                        "confirm": True,
                        "expected_revision": 0,
                    },
                )
                for prefix in ("A", "B")
            ]
        )
        assert sorted(r.status_code for r in responses) == [200, 409]
        current = await app_client.get(url, headers=headers)
        winner = next(r.json() for r in responses if r.status_code == 200)
        assert current.json()["filename_pattern"] == winner["filename_pattern"]
        assert current.json()["edit_revision"] == 1
    finally:
        await _cleanup([cid])
