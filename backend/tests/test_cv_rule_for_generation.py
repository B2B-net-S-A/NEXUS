"""Wąski odczyt reguły CV dla osoby generującej CV (audyt 17.09.2026, §4 P2).

Pełny odczyt `GET /api/clients/{id}/cv-rule` stoi za grafem klienta: rekruter
bez rekrutacji u klienta dostawał 403, a serwer i tak stosował regułę przy
generacji. `GET /api/cv-generator/clients/{id}/rule-for-generation` stoi za tą
samą bramką co generacja (`CandidateWriteAccess`) i niesie tylko pola
formularza.

Kontrakty:
1. Rekruter bez żadnej rekrutacji u klienta dostaje 200 i wąski kształt
   (bez instrukcji EN, słownika, polityki prezentacji, szkicu edytora).
2. Niezatwierdzona propozycja nie obowiązuje — jej treść nie wychodzi.
3. Viewer (`user`) → 403; nieznany klient → 404.
4. Brak zrzutu zgody przy zapisie → wiersz „failed" z konkretnym komunikatem,
   nie wyjątek poza `try` workera.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

URL = "/api/cv-generator/clients/{cid}/rule-for-generation"

SLIM_KEYS = {
    "client_id",
    "client_name",
    "is_active",
    "client_policy",
    "version",
    "cv_language",
    "requires_en_copy",
    "auto_second_language",
    "requires_rodo_consent_block",
    "content_mode",
    "content_mode_locked",
    "require_screening_notes_min_chars",
    "require_project_ref",
    "require_position",
    "require_champion",
    "filename_pattern",
    "filename_preview",
    "notes",
    "generator_instructions",
}


async def _headers_for(app_client: AsyncClient, role_value: str) -> dict[str, str]:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    email = f"rule-gen-{role_value}-{uuid.uuid4().hex[:8]}@example.com"
    password = f"P4ss_{uuid.uuid4().hex[:6]}!"
    async with AsyncSessionLocal() as db:
        role = UserRole(role_value)
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"Rule gen {role_value}",
                role=role,
                roles=[role.value],
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()
    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _make_client_with_rule(*, confirmed: bool) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client, ClientStatus
    from app.models.client_cv_rule import ClientCvRule

    async with AsyncSessionLocal() as db:
        client = Client(
            name=f"Rule gen {uuid.uuid4().hex[:8]}",
            status=ClientStatus.active,
            hidden=False,
        )
        db.add(client)
        await db.flush()
        db.add(
            ClientCvRule(
                client_id=client.id,
                filename_pattern="B2B_{IMIE_NAZWISKO}_{PROJEKT}",
                spaces_to_underscores=True,
                cv_language="en",
                requires_rodo_consent_block=True,
                content_mode="basic",
                content_mode_locked=True,
                require_project_ref=True,
                require_position=True,
                notes="Klient ceni bankowość.",
                generator_instructions="Bez sekcji zainteresowań.",
                generator_instructions_en="No hobbies section.",
                glossary=[{"from": "Business Analyst", "to": "Analityk"}],
                max_roles=4,
                confirmed_at=datetime.now(timezone.utc) if confirmed else None,
            )
        )
        await db.commit()
        return client.id


async def _cleanup(client_ids: list[int]) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.client_cv_rule import ClientCvRule

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ClientCvRule).where(ClientCvRule.client_id.in_(client_ids))
        )
        await db.execute(delete(Client).where(Client.id.in_(client_ids)))
        await db.commit()


@pytest.mark.asyncio
async def test_recruiter_without_job_at_client_reads_slim_rule(
    app_client: AsyncClient,
) -> None:
    cid = await _make_client_with_rule(confirmed=True)
    try:
        headers = await _headers_for(app_client, "recruiter")
        response = await app_client.get(URL.format(cid=cid), headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body) == SLIM_KEYS
        assert body["client_id"] == cid
        assert body["is_active"] is True
        assert body["cv_language"] == "en"
        assert body["requires_rodo_consent_block"] is True
        assert body["content_mode"] == "basic"
        assert body["content_mode_locked"] is True
        assert body["require_project_ref"] is True
        assert body["filename_pattern"] == "B2B_{IMIE_NAZWISKO}_{PROJEKT}"
        assert body["filename_preview"] and body["filename_preview"].endswith(".docx")
        assert body["client_policy"]
        # Rekruter bez rekrutacji u klienta nie ma zakresu klienta: notatka
        # i instrukcje DL to wiedza o kliencie, nie wymóg formularza.
        assert body["notes"] is None
        assert body["generator_instructions"] is None
    finally:
        await _cleanup([cid])


@pytest.mark.asyncio
async def test_admin_with_client_scope_sees_dl_notes_and_instructions(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    cid = await _make_client_with_rule(confirmed=True)
    try:
        response = await app_client.get(URL.format(cid=cid), headers=app_auth_headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["notes"] == "Klient ceni bankowość."
        assert body["generator_instructions"] == "Bez sekcji zainteresowań."
    finally:
        await _cleanup([cid])


@pytest.mark.asyncio
async def test_unconfirmed_proposal_content_is_not_exposed(
    app_client: AsyncClient,
) -> None:
    cid = await _make_client_with_rule(confirmed=False)
    try:
        headers = await _headers_for(app_client, "sourcer")
        response = await app_client.get(URL.format(cid=cid), headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["is_active"] is False
        assert body["client_policy"] == ""
        assert body["cv_language"] is None
        assert body["filename_pattern"] is None
        assert body["requires_rodo_consent_block"] is False
        assert body["notes"] is None
    finally:
        await _cleanup([cid])


@pytest.mark.asyncio
async def test_viewer_is_denied_and_unknown_client_is_404(
    app_client: AsyncClient,
) -> None:
    cid = await _make_client_with_rule(confirmed=True)
    try:
        viewer = await _headers_for(app_client, "user")
        denied = await app_client.get(URL.format(cid=cid), headers=viewer)
        assert denied.status_code == 403, denied.text
        recruiter = await _headers_for(app_client, "recruiter")
        missing = await app_client.get(URL.format(cid=2_000_000_000), headers=recruiter)
        assert missing.status_code == 404, missing.text
    finally:
        await _cleanup([cid])


@pytest.mark.asyncio
async def test_unavailable_consent_marks_row_failed_instead_of_raising(
    monkeypatch,
) -> None:
    from app.api import cv_generator_b2b as api
    from app.services import object_storage

    monkeypatch.setattr(
        object_storage, "download_cv", Mock(side_effect=OSError("storage down"))
    )
    render = Mock(side_effect=AssertionError("Renderer must not run without consent"))
    monkeypatch.setattr(api, "rerender_docx_from_payload", render)
    row = SimpleNamespace(status="processing", error_message=None, job_id=None)
    db = AsyncMock()
    db.get.return_value = row
    result = SimpleNamespace(
        docx_bytes=b"without-consent",
        render_payload={"name": "Synthetic"},
        candidate_name="Synthetic",
        job_id=None,
        filename="cv.docx",
        warnings=[],
    )
    finalized = await api._finalize_success(
        db, 11, result=result, consent_screenshot={"storage_key": "synthetic/consent"}
    )
    assert finalized is False
    assert row.status == "failed"
    assert row.error_message == api.CONSENT_ATTACH_FAILED_MESSAGE
    assert "zrzutu zgody" in row.error_message
    render.assert_not_called()
    # Wiersz nie dostał treści dokumentu, którego nie da się wysłać klientowi.
    assert not hasattr(row, "docx_content")
