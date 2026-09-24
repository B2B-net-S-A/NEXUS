"""Generator v3: lista „Moje CV" — filtry ``mine`` / ``days`` / ``q`` i flagi zgody."""

# ruff: noqa: F811  (fixture `pv_client` importowana z sąsiedniego pliku)
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.user import User, UserRole
from tests.test_cv_auto_generate import _headers, _world
from tests.test_pending_gate_removed import pv_client  # noqa: F401

PKO_POLICY = {"requires_rodo_consent_block": True, "required_languages": ["pl"]}


async def _doc(world: dict, *, created_by: int, name: str, **extra) -> int:
    async with AsyncSessionLocal() as db:
        row = CvGeneratedDocument(
            candidate_id=world["candidate_id"],
            job_id=world["job_id"],
            client_id=world["client_id"],
            candidate_name=name,
            position=extra.pop("position", None),
            language="pl",
            mode="new",
            content_mode="polished",
            filename=extra.pop("filename", "cv.docx"),
            status="ready",
            render_payload=extra.pop("render_payload", {"name": name}),
            created_by=created_by,
            **extra,
        )
        db.add(row)
        await db.flush()
        created_at = extra.get("created_at")
        if created_at is not None:
            row.created_at = created_at
        await db.commit()
        return row.id


async def _colleague() -> int:
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"cv-list-{uuid.uuid4().hex[:8]}@example.com",
            name="Kolega",
            role=UserRole.admin,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id


async def _ids(client: AsyncClient, world: dict, **params) -> list[int]:
    response = await client.get(
        "/api/cv-generator/generated",
        params={"candidate_id": world["candidate_id"], **params},
        headers=_headers(world["user_id"]),
    )
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()]


@pytest.mark.asyncio
async def test_mine_days_and_query_filters(pv_client: AsyncClient):
    world = await _world()
    colleague = await _colleague()
    mine_recent = await _doc(
        world, created_by=world["user_id"], name="Żaneta Źdźbło", position="Tester"
    )
    mine_old = await _doc(
        world,
        created_by=world["user_id"],
        name="Stary Wpis",
        created_at=datetime.now(timezone.utc) - timedelta(days=40),
    )
    theirs = await _doc(world, created_by=colleague, name="Cudze CV")

    assert set(await _ids(pv_client, world)) >= {mine_recent, mine_old, theirs}
    assert set(await _ids(pv_client, world, mine="true")) == {mine_recent, mine_old}
    assert set(await _ids(pv_client, world, days=30)) == {mine_recent, theirs}
    # Bez polskich znaków i wielkości liter; po stanowisku i nazwie pliku też.
    assert await _ids(pv_client, world, q="zaneta zdzb") == [mine_recent]
    assert await _ids(pv_client, world, q="TESTER") == [mine_recent]
    # `%` szuka znaku, nie zwraca wszystkiego.
    assert await _ids(pv_client, world, q="%") == []


@pytest.mark.asyncio
async def test_days_out_of_range_is_rejected(pv_client: AsyncClient):
    world = await _world()
    response = await pv_client.get(
        "/api/cv-generator/generated",
        params={"days": 400},
        headers=_headers(world["user_id"]),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_rows_say_whether_the_consent_is_required_and_missing(
    pv_client: AsyncClient,
):
    world = await _world()
    missing = await _doc(
        world, created_by=world["user_id"], name="Bez zgody", central_policy=PKO_POLICY
    )
    attached = await _doc(
        world,
        created_by=world["user_id"],
        name="Ze zgodą",
        central_policy=PKO_POLICY,
        render_payload={
            "name": "Ze zgodą",
            "consent_screenshot": {"storage_key": "cv/test/zgoda.png"},
        },
    )
    plain = await _doc(world, created_by=world["user_id"], name="Zwykłe")
    response = await pv_client.get(
        "/api/cv-generator/generated",
        params={"candidate_id": world["candidate_id"]},
        headers=_headers(world["user_id"]),
    )
    flags = {
        item["id"]: (item["consent_required"], item["consent_missing"])
        for item in response.json()
    }
    assert flags[missing] == (True, True)
    assert flags[attached] == (True, False)
    assert flags[plain] == (False, False)


@pytest.mark.asyncio
async def test_kill_switch_clears_consent_missing_on_the_list(
    pv_client: AsyncClient, monkeypatch
):
    """Front chowa „Pobierz” po `consent_missing` — wyłącznik awaryjny musi ją
    zdjąć także na liście, inaczej zdjęcie blokady nic by nie zmieniło w UI."""
    from app.core.config import settings

    world = await _world()
    missing = await _doc(
        world, created_by=world["user_id"], name="Bez zgody", central_policy=PKO_POLICY
    )

    async def _flags():
        response = await pv_client.get(
            "/api/cv-generator/generated",
            params={"candidate_id": world["candidate_id"]},
            headers=_headers(world["user_id"]),
        )
        [item] = [i for i in response.json() if i["id"] == missing]
        return item["consent_required"], item["consent_missing"]

    monkeypatch.setattr(settings, "CV_CONSENT_DOWNLOAD_GATE_ENABLED", True)
    assert await _flags() == (True, True)
    monkeypatch.setattr(settings, "CV_CONSENT_DOWNLOAD_GATE_ENABLED", False)
    assert await _flags() == (True, False)
