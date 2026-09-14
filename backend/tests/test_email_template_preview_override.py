"""B14 — podgląd istniejącego szablonu renderował wiersz z bazy, więc edycja
w formularzu była w podglądzie niewidoczna aż do zapisu.
``POST /api/email-templates/{id}/preview`` przyjmuje opcjonalne body
z niezapisaną treścią; bez body zachowanie jest dotychczasowe.
"""

import uuid

import pytest
from httpx import AsyncClient


async def _create_template(app_client: AsyncClient, headers: dict[str, str]) -> int:
    unique = uuid.uuid4().hex[:8]
    resp = await app_client.post(
        "/api/email-templates",
        headers=headers,
        json={
            "name": f"preview-override-{unique}",
            "subject": f"Zapisany temat {unique}",
            "body": "Zapisana treść {{candidate_name}}",
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_preview_renders_unsaved_form_content_when_body_is_sent(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    template_id = await _create_template(app_client, app_auth_headers)

    resp = await app_client.post(
        f"/api/email-templates/{template_id}/preview",
        headers=app_auth_headers,
        json={
            "subject": "QA PODGLĄD — temat niezapisany",
            "body": "QA PODGLĄD — TEKST NIEZAPISANY {{job_title}}",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["subject"] == "QA PODGLĄD — temat niezapisany"
    # Zmienne poza nazwą kandydata zostają nierozwiązane (P0.2) — to pola do
    # uzupełnienia, nie „przykładowe dane".
    assert data["body"] == "QA PODGLĄD — TEKST NIEZAPISANY {{job_title}}"


@pytest.mark.asyncio
async def test_preview_without_body_still_renders_stored_template(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    template_id = await _create_template(app_client, app_auth_headers)

    resp = await app_client.post(
        f"/api/email-templates/{template_id}/preview", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["subject"].startswith("Zapisany temat")
    assert data["body"] == "Zapisana treść {{candidate_name}}"


@pytest.mark.asyncio
async def test_preview_partial_override_keeps_other_stored_field(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    template_id = await _create_template(app_client, app_auth_headers)

    resp = await app_client.post(
        f"/api/email-templates/{template_id}/preview",
        headers=app_auth_headers,
        json={"body": "Tylko treść z formularza"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["subject"].startswith("Zapisany temat")
    assert data["body"] == "Tylko treść z formularza"
