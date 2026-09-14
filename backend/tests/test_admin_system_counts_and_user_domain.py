"""Ustawienia → Administracja: kafel „Klienci" i walidacja domeny nowego konta.

UAT M11-B04: kafel „Klienci" liczył wszystkie wiersze tabeli (także ukrytych,
zarchiwizowanych i scalonych), więc nie zgadzał się z listą `/api/clients`.
UAT M11-B10: admin mógł założyć konto w domenie spoza firmy, a duplikat
dostawał komunikat po angielsku.
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_system_clients_count_uses_list_visibility(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    before = await app_client.get("/api/admin/system", headers=app_auth_headers)
    assert before.status_code == 200, before.text
    base = before.json()["counts"]["clients"]

    sfx = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                Client(name=f"M11B04 widoczny {sfx}"),
                Client(name=f"M11B04 ukryty {sfx}", hidden=True),
                Client(
                    name=f"M11B04 archiwum {sfx}",
                    archived_at=datetime.now(timezone.utc),
                ),
            ]
        )
        await db.commit()

    after = await app_client.get("/api/admin/system", headers=app_auth_headers)
    body = after.json()
    # Tylko widoczny klient zwiększa licznik — jak lista `/api/clients`.
    assert body["counts"]["clients"] == base + 1
    assert "version" in body


async def test_admin_create_user_rejects_domain_outside_sso_list(
    app_client: AsyncClient, app_auth_headers: dict[str, str], monkeypatch
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "SSO_ALLOWED_DOMAINS", "firma.example")
    sfx = uuid.uuid4().hex[:8]

    rejected = await app_client.post(
        "/api/admin/users",
        headers=app_auth_headers,
        json={
            "email": f"obcy-{sfx}@inna.example",
            "password": "Haslo-testowe-123!",
            "name": "Konto Obce",
        },
    )
    assert rejected.status_code == 422, rejected.text
    assert "domenie firmy" in rejected.json()["detail"]

    payload = {
        "email": f"nowy-{sfx}@FIRMA.example",
        "password": "Haslo-testowe-123!",
        "name": "Konto Firmowe",
    }
    created = await app_client.post(
        "/api/admin/users", headers=app_auth_headers, json=payload
    )
    assert created.status_code == 201, created.text

    duplicate = await app_client.post(
        "/api/admin/users", headers=app_auth_headers, json=payload
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["detail"] == "Konto z tym adresem e-mail już istnieje."


async def test_admin_email_domain_check_is_off_without_sso_list(monkeypatch):
    from app.api.admin import admin_email_domain_error
    from app.core.config import settings

    monkeypatch.setattr(settings, "SSO_ALLOWED_DOMAINS", "")
    assert admin_email_domain_error("ktos@dowolna.example") is None
