"""Tests for the client "Materiały" sub-tab API.

Covers:
  - One-pager upload (PDF happy path, MIME rejection, oversize rejection)
  - One-pager list / download / delete (including on-disk file cleanup)
  - Contract terms GET returns null when none
  - Contract terms PUT creates, then updates (singleton upsert)
  - Singleton enforcement at DB level
  - RBAC: non-TacPlus roles cannot mutate
"""

from __future__ import annotations

import io
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


_PDF_BYTES = b"%PDF-1.4\n%minimal-test-pdf\n%%EOF"


async def _create_client(app_client: AsyncClient, headers: dict) -> int:
    name = f"PytestMaterials-{uuid.uuid4().hex[:8]}"
    resp = await app_client.post(
        "/api/clients",
        headers=headers,
        json={"name": name, "industry": "Test", "status": "active"},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def test_list_one_pagers_empty(
    app_client: AsyncClient, app_auth_headers: dict
):
    client_id = await _create_client(app_client, app_auth_headers)
    resp = await app_client.get(
        f"/api/clients/{client_id}/one-pagers", headers=app_auth_headers
    )
    assert resp.status_code == 200
    assert resp.json() == []


async def test_upload_one_pager_pdf(
    app_client: AsyncClient, app_auth_headers: dict
):
    client_id = await _create_client(app_client, app_auth_headers)
    resp = await app_client.post(
        f"/api/clients/{client_id}/one-pagers",
        headers=app_auth_headers,
        files={"file": ("deck.pdf", io.BytesIO(_PDF_BYTES), "application/pdf")},
        data={"title": "Oferta B2B", "description": "v1 bazowa", "version": "1.0"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["title"] == "Oferta B2B"
    assert body["version"] == "1.0"
    assert body["filename"] == "deck.pdf"
    assert body["size_bytes"] == len(_PDF_BYTES)
    assert body["client_id"] == client_id
    assert body["uploaded_by_email"]


async def test_upload_one_pager_rejects_exe(
    app_client: AsyncClient, app_auth_headers: dict
):
    client_id = await _create_client(app_client, app_auth_headers)
    resp = await app_client.post(
        f"/api/clients/{client_id}/one-pagers",
        headers=app_auth_headers,
        files={
            "file": ("payload.exe", io.BytesIO(b"MZ\x90\x00"), "application/x-msdownload")
        },
        data={"title": "zły plik"},
    )
    assert resp.status_code == 415, resp.text


async def test_upload_one_pager_rejects_oversize(
    app_client: AsyncClient, app_auth_headers: dict
):
    client_id = await _create_client(app_client, app_auth_headers)
    big = b"\x00" * (21 * 1024 * 1024)  # 21 MB
    resp = await app_client.post(
        f"/api/clients/{client_id}/one-pagers",
        headers=app_auth_headers,
        files={"file": ("huge.pdf", io.BytesIO(big), "application/pdf")},
        data={"title": "za duży"},
    )
    assert resp.status_code == 413, resp.text

    # DB row must NOT have been created
    list_resp = await app_client.get(
        f"/api/clients/{client_id}/one-pagers", headers=app_auth_headers
    )
    assert list_resp.status_code == 200
    assert list_resp.json() == []


async def test_download_one_pager(
    app_client: AsyncClient, app_auth_headers: dict
):
    client_id = await _create_client(app_client, app_auth_headers)
    create = await app_client.post(
        f"/api/clients/{client_id}/one-pagers",
        headers=app_auth_headers,
        files={"file": ("x.pdf", io.BytesIO(_PDF_BYTES), "application/pdf")},
        data={"title": "t"},
    )
    assert create.status_code == 201, create.text
    opid = create.json()["id"]

    resp = await app_client.get(
        f"/api/clients/{client_id}/one-pagers/{opid}/download",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200
    assert resp.content == _PDF_BYTES


async def test_delete_one_pager_removes_row_and_file(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.services import storage_service

    client_id = await _create_client(app_client, app_auth_headers)
    create = await app_client.post(
        f"/api/clients/{client_id}/one-pagers",
        headers=app_auth_headers,
        files={"file": ("x.pdf", io.BytesIO(_PDF_BYTES), "application/pdf")},
        data={"title": "t"},
    )
    assert create.status_code == 201, create.text
    opid = create.json()["id"]

    # Capture file_path via DB lookup
    from app.core.database import AsyncSessionLocal
    from app.models.client_one_pager import ClientOnePager

    async with AsyncSessionLocal() as db:
        op = await db.scalar(
            select(ClientOnePager).where(ClientOnePager.id == opid)
        )
        assert op is not None
        rel_path = op.file_path

    abs_path = storage_service.get_client_one_pager_path(rel_path)
    assert abs_path.is_file()

    resp = await app_client.delete(
        f"/api/clients/{client_id}/one-pagers/{opid}",
        headers=app_auth_headers,
    )
    assert resp.status_code == 204

    # File and DB row are gone
    assert not abs_path.exists()
    list_resp = await app_client.get(
        f"/api/clients/{client_id}/one-pagers", headers=app_auth_headers
    )
    assert list_resp.json() == []


async def test_get_contract_terms_none(
    app_client: AsyncClient, app_auth_headers: dict
):
    client_id = await _create_client(app_client, app_auth_headers)
    resp = await app_client.get(
        f"/api/clients/{client_id}/contract-terms", headers=app_auth_headers
    )
    assert resp.status_code == 200
    assert resp.json() is None


async def test_upsert_contract_terms_creates_then_updates(
    app_client: AsyncClient, app_auth_headers: dict
):
    client_id = await _create_client(app_client, app_auth_headers)

    first = await app_client.put(
        f"/api/clients/{client_id}/contract-terms",
        headers=app_auth_headers,
        json={
            "off_limits_months": 12,
            "off_limits_scope": "cała grupa",
            "internalization_fee_pct": "20.00",
            "payment_net_days": 30,
            "payment_currency": "PLN",
            "other_clauses": "pierwsza wersja",
        },
    )
    assert first.status_code == 200, first.text
    row_id = first.json()["id"]

    # Second PUT overwrites — not a new row
    second = await app_client.put(
        f"/api/clients/{client_id}/contract-terms",
        headers=app_auth_headers,
        json={
            "off_limits_months": 6,
            "other_clauses": "zmiana",
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["id"] == row_id
    assert second.json()["off_limits_months"] == 6
    # Fields not included in PUT remain (exclude_unset)
    assert second.json()["payment_currency"] == "PLN"
    assert second.json()["other_clauses"] == "zmiana"

    # GET returns the latest
    got = await app_client.get(
        f"/api/clients/{client_id}/contract-terms", headers=app_auth_headers
    )
    assert got.status_code == 200
    body = got.json()
    assert body["id"] == row_id
    assert body["off_limits_months"] == 6


async def test_contract_terms_singleton_enforced_at_db(
    app_client: AsyncClient, app_auth_headers: dict
):
    """A second row for the same client must violate the UNIQUE constraint."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_contract_terms import ClientContractTerms

    client_id = await _create_client(app_client, app_auth_headers)

    first = await app_client.put(
        f"/api/clients/{client_id}/contract-terms",
        headers=app_auth_headers,
        json={"off_limits_months": 3},
    )
    assert first.status_code == 200

    async with AsyncSessionLocal() as db:
        dup = ClientContractTerms(client_id=client_id, off_limits_months=99)
        db.add(dup)
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_rbac_upload_forbidden_for_recruiter(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Recruiter cannot upload — only TacPlus can."""
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token, hash_password
    from app.models.user import User, UserRole
    from sqlalchemy import select

    client_id = await _create_client(app_client, app_auth_headers)

    # Seed a recruiter
    unique = uuid.uuid4().hex[:8]
    email = f"recruiter-{unique}@example.com"
    async with AsyncSessionLocal() as db:
        existing = await db.scalar(select(User).where(User.email == email))
        if existing is None:
            u = User(
                email=email,
                password_hash=hash_password("whatever"),
                name="Recruiter",
                role=UserRole.recruiter,
                is_active=True,
            )
            db.add(u)
            await db.commit()
            await db.refresh(u)
            uid = u.id
        else:
            uid = existing.id

    token = create_access_token(subject=uid, role="recruiter")
    headers = {"Authorization": f"Bearer {token}"}

    resp = await app_client.post(
        f"/api/clients/{client_id}/one-pagers",
        headers=headers,
        files={"file": ("x.pdf", io.BytesIO(_PDF_BYTES), "application/pdf")},
        data={"title": "nope"},
    )
    assert resp.status_code == 403, resp.text
