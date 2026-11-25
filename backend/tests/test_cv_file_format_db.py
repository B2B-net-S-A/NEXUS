"""Format pliku CV klienta: Word / PDF / oba (decyzja Artura z 25.11.2026).

- pole recepty ``cv_file_format``: domyślnie bez wymagań, wersja, diff
  w historii, kopia z innego klienta, odmowa nieznanej wartości,
- propozycja (bez zatwierdzenia) nie zmienia pobrania u rekrutera,
- zapis samego formatu przy zasadach centralnych (``PUT …/cv-rule/file-format``):
  409 bez nich, odmowa bez „Klienci: dodawanie i edycja”, nieaktualna rewizja,
- odpowiedź CV etapu niesie format klienta — także po zapisie (zmiana układu),
- ``rule-for-generation`` podaje format wynikowi generatora.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.client_cv_rule import ClientCvRule
from app.models.client_cv_rule_event import ClientCvRuleEvent
from app.models.job import Job
from app.services import cv_file_format
from tests.cv_rule_requests import rule_request
from tests.test_candidate_stage_cv_branded import _seed_draft, _seed_full_stage
from tests.test_client_cv_rules_recipe_api import (
    RULE_URL,
    _cleanup,
    _full_payload,
    _headers_for,
    _make_client,
)


async def _put_rule(app_client: AsyncClient, cid: int, headers, **overrides):
    return await rule_request(
        app_client,
        "PUT",
        RULE_URL.format(cid=cid),
        json=_full_payload(**overrides),
        headers=headers,
    )


@pytest.mark.asyncio
async def test_rule_format_defaults_versions_diffs_and_copies(app_client: AsyncClient):
    cid = await _make_client(f"Format rule {uuid.uuid4().hex[:6]}")
    other = await _make_client(f"Format copy {uuid.uuid4().hex[:6]}")
    try:
        headers = await _headers_for(app_client, "admin")
        first = await _put_rule(app_client, cid, headers)
        assert first.status_code == 200, first.text
        # Pominięte pole = bez wymagań, jak dotąd.
        assert first.json()["cv_file_format"] is None

        docx = await _put_rule(app_client, cid, headers, cv_file_format="docx")
        assert docx.status_code == 200, docx.text
        assert docx.json()["cv_file_format"] == "docx"
        assert docx.json()["version"] == first.json()["version"] + 1
        async with AsyncSessionLocal() as db:
            assert await cv_file_format.for_client(db, cid) == "docx"

        both = await _put_rule(app_client, cid, headers, cv_file_format="both")
        assert both.json()["version"] == docx.json()["version"] + 1
        history = await app_client.get(
            RULE_URL.format(cid=cid) + "/history", headers=headers
        )
        assert history.json()[0]["changes"]["cv_file_format"] == {
            "from": "docx",
            "to": "both",
        }

        copied = await rule_request(
            app_client,
            "POST",
            RULE_URL.format(cid=other) + f"/copy-from/{cid}",
            headers=headers,
        )
        assert copied.status_code == 200, copied.text
        assert copied.json()["cv_file_format"] == "both"
        # Kopia to propozycja — rekruter dalej pobiera „bez wymagań”.
        async with AsyncSessionLocal() as db:
            assert await cv_file_format.for_client(db, other) is None

        refused = await _put_rule(app_client, cid, headers, cv_file_format="xls")
        assert refused.status_code == 422
        async with AsyncSessionLocal() as db:
            assert await cv_file_format.for_client(db, cid) == "both"
    finally:
        await _cleanup([cid, other])


@pytest.mark.asyncio
async def test_draft_format_does_not_change_the_download(app_client: AsyncClient):
    cid = await _make_client(f"Format draft {uuid.uuid4().hex[:6]}")
    try:
        headers = await _headers_for(app_client, "admin")
        await _put_rule(app_client, cid, headers, cv_file_format="pdf")
        draft = await _put_rule(
            app_client, cid, headers, cv_file_format="docx", confirm=False
        )
        assert draft.status_code == 200, draft.text
        async with AsyncSessionLocal() as db:
            assert await cv_file_format.for_client(db, cid) == "pdf"
    finally:
        await _cleanup([cid])


@pytest.mark.asyncio
async def test_format_route_works_only_under_central_policies(
    app_client: AsyncClient, monkeypatch
):
    from app.services.cv_generator_b2b import central_policies

    cid = await _make_client(f"Format central {uuid.uuid4().hex[:6]}")
    url = RULE_URL.format(cid=cid) + "/file-format"
    try:
        headers = await _headers_for(app_client, "admin")
        refused = await app_client.put(
            url, json={"cv_file_format": "pdf", "expected_revision": 0}, headers=headers
        )
        assert refused.status_code == 409
        assert "Zapisz i włącz regułę" in refused.json()["detail"]

        monkeypatch.setattr(central_policies, "enabled", lambda: True)
        # Format nie zależy od flagi „Nowego CV”.
        monkeypatch.setattr(settings, "CV_NEW_LAYOUT_ENABLED", False)
        recruiter = await _headers_for(app_client, "recruiter")
        denied = await app_client.put(
            url,
            json={"cv_file_format": "pdf", "expected_revision": 0},
            headers=recruiter,
        )
        assert denied.status_code == 403

        saved = await app_client.put(
            url, json={"cv_file_format": "pdf", "expected_revision": 0}, headers=headers
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["cv_file_format"] == "pdf"
        async with AsyncSessionLocal() as db:
            rule = await db.scalar(
                select(ClientCvRule).where(ClientCvRule.client_id == cid)
            )
            assert rule.cv_file_format == "pdf" and rule.confirmed_at is not None
            event = await db.scalar(
                select(ClientCvRuleEvent).where(ClientCvRuleEvent.client_id == cid)
            )
            assert event.changes == {"cv_file_format": {"from": None, "to": "pdf"}}
            assert await cv_file_format.for_client(db, cid) == "pdf"

        stale = await app_client.put(
            url, json={"cv_file_format": None, "expected_revision": 0}, headers=headers
        )
        assert stale.status_code == 409

        reset = await app_client.put(
            url,
            json={
                "cv_file_format": None,
                "expected_revision": saved.json()["edit_revision"],
            },
            headers=headers,
        )
        assert reset.status_code == 200, reset.text
        assert reset.json()["cv_file_format"] is None
        assert reset.json()["version"] == saved.json()["version"] + 1
    finally:
        await _cleanup([cid])


async def _confirmed_format(client_id: int, value: str | None) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            ClientCvRule(
                client_id=client_id,
                version=1,
                edit_revision=1,
                confirmed_at=datetime.now(timezone.utc),
                cv_file_format=value,
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_stage_cv_response_carries_the_client_format(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    monkeypatch.setattr(settings, "CV_NEW_LAYOUT_ENABLED", True)
    sid, _cand, job_id = await _seed_full_stage()
    async with AsyncSessionLocal() as db:
        client_id = (await db.get(Job, job_id)).client_id
    base = f"/api/candidates/stages/{sid}/cv"

    empty = await app_client.get(f"{base}/branded", headers=app_auth_headers)
    assert empty.status_code == 200, empty.text
    assert empty.json()["status"] == "none"
    assert empty.json()["client_file_format"] is None

    await _confirmed_format(client_id, "docx")
    none_state = await app_client.get(f"{base}/branded", headers=app_auth_headers)
    assert none_state.json()["client_file_format"] == "docx"

    await _seed_draft(sid)
    draft = await app_client.get(f"{base}/branded", headers=app_auth_headers)
    assert draft.json()["client_file_format"] == "docx"

    # Karta podmienia pamięć odpowiedzią zapisu — format nie może z niej zniknąć.
    switched = await app_client.patch(
        f"{base}/layout", json={"cv_layout": "new"}, headers=app_auth_headers
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["cv_layout"] == "new"
    assert switched.json()["client_file_format"] == "docx"


@pytest.mark.asyncio
async def test_rule_for_generation_reports_the_format(app_client: AsyncClient):
    cid = await _make_client(f"Format gen {uuid.uuid4().hex[:6]}")
    try:
        headers = await _headers_for(app_client, "admin")
        url = f"/api/cv-generator/clients/{cid}/rule-for-generation"
        before = await app_client.get(url, headers=headers)
        assert before.status_code == 200, before.text
        assert before.json()["cv_file_format"] is None

        await _put_rule(app_client, cid, headers, cv_file_format="pdf")
        after = await app_client.get(url, headers=headers)
        assert after.json()["cv_file_format"] == "pdf"
    finally:
        await _cleanup([cid])
