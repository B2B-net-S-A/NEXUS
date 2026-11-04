"""Ustawienia → Ocena prepów (0505) — trasy na prawdziwej bazie.

Tabela ``prep_review_configs`` jest wspólna dla sharda: fixture czyści ją
przed i po teście, inaczej opublikowana wersja zmieniłaby progi ocen
w innych testach.
"""

from __future__ import annotations

import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.prep_meeting import PrepReviewConfigVersion
from app.models.user import User, UserRole
from app.services import prep_review_config as cfg

URL = "/api/prep-review-config"


async def _clear() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(PrepReviewConfigVersion))
        await db.commit()


@pytest_asyncio.fixture
async def clean_configs():
    await _clear()
    yield
    await _clear()


async def _user(role: UserRole) -> User:
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"prep-config-{role.value}-{marker}@example.com",
            name=f"Prep Config {role.value} {marker}",
            role=role,
            roles=[role.value],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


def _config(**changes) -> dict:
    data = cfg.defaults().model_dump()
    data.update(changes)
    return data


async def test_hor_publishes_new_version_and_history(
    app_client: AsyncClient, clean_configs
):
    hor = _headers(await _user(UserRole.head_of_recruitment))

    start = await app_client.get(URL, headers=hor)
    assert start.status_code == 200, start.text
    body = start.json()
    assert body["can_edit"] is True
    assert body["version"] is None
    assert body["history"] == []

    saved = await app_client.put(
        URL,
        headers=hor,
        json={"config": _config(max_client_questions=6), "reason": "za dużo punktów"},
    )
    assert saved.status_code == 200, saved.text
    state = saved.json()
    assert state["saved"] is True
    assert state["version"] is not None
    assert state["config"]["max_client_questions"] == 6
    assert state["history"][0]["reason"] == "za dużo punktów"
    assert "Najwięcej pytań klienta: 20 → 6" in state["history"][0]["changes"]

    again = await app_client.put(
        URL, headers=hor, json={"config": _config(max_client_questions=6)}
    )
    assert again.json()["saved"] is False
    assert again.json()["version"] == state["version"]


async def test_dl_and_recruiter_read_without_edit(
    app_client: AsyncClient, clean_configs
):
    for role in (UserRole.delivery_lead, UserRole.recruiter):
        headers = _headers(await _user(role))
        read = await app_client.get(URL, headers=headers)
        assert read.status_code == 200, read.text
        assert read.json()["can_edit"] is False
        write = await app_client.put(URL, headers=headers, json={"config": _config()})
        assert write.status_code == 403, write.text


async def test_finance_cannot_read(app_client: AsyncClient, clean_configs):
    finance = _headers(await _user(UserRole.finance))
    response = await app_client.get(URL, headers=finance)
    assert response.status_code == 403


async def test_invalid_weights_are_refused_in_polish(
    app_client: AsyncClient, clean_configs
):
    hor = _headers(await _user(UserRole.head_of_recruitment))
    bad = _config()
    bad["prep1"]["weights"]["topics"] = 90
    response = await app_client.put(URL, headers=hor, json={"config": bad})
    assert response.status_code == 422
    assert "100%" in response.text
