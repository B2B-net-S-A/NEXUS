"""Trasy `/api/admin/traffit/*` po wyłączeniu Traffita (14.10.2026) — przez HTTP.

Uzupełnia `test_fix48_ws08_traffit_retired.py` o pełną ścieżkę: logowanie
admina, bramka uprawnień przed 410 i odczyt stanu, który zostaje. Wymaga
Postgresa (fixture `app_client` zakłada admina w bazie testowej).
"""

from __future__ import annotations

import pytest

from app.core.config import settings

MESSAGE = (
    "Traffit jest wyłączony od 14.10.2026 — NEXUS nie importuje już danych z Traffita."
)

IMPORT_ROUTES = [
    "/api/admin/traffit/sync",
    "/api/admin/traffit/sync?mode=full",
    "/api/admin/traffit/notes-repair",
    "/api/admin/traffit/notes-repair?dry_run=false",
    "/api/admin/traffit/notes-repair/recruitments",
    "/api/admin/traffit/file-dates-repair",
    "/api/admin/traffit/added-dates-repair",
    "/api/admin/traffit/added-dates-repair?dry_run=false",
    "/api/admin/traffit/transfer?client_id=1",
    "/api/admin/traffit/twins-merge",
    "/api/admin/traffit/twins-merge?dry_run=false&job_ids=1",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", IMPORT_ROUTES)
async def test_admin_gets_410_on_every_import_route(
    app_client, app_auth_headers, monkeypatch, path
) -> None:
    # Flaga „włączona” i sekrety ustawione — 410 nie może zależeć od env.
    monkeypatch.setattr(settings, "TRAFFIT_SYNC_ENABLED", True)
    monkeypatch.setenv("TRAFFIT_TENANT", "fikcyjny")
    monkeypatch.setenv("TRAFFIT_CLIENT_ID", "id")
    monkeypatch.setenv("TRAFFIT_CLIENT_SECRET", "sekret")

    resp = await app_client.post(path, headers=app_auth_headers)

    assert resp.status_code == 410, resp.text
    assert resp.json()["detail"] == MESSAGE


@pytest.mark.asyncio
async def test_anonymous_caller_still_meets_the_permission_gate_first(
    app_client,
) -> None:
    resp = await app_client.post("/api/admin/traffit/sync")
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_status_stays_readable_and_says_retired(
    app_client, app_auth_headers
) -> None:
    resp = await app_client.get(
        "/api/admin/traffit/sync/status", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enabled"] is False
    assert body["retired_on"] == "2026-10-14"
    assert body["retired_message"] == MESSAGE
    assert "states" in body
