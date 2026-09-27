"""Szablony procesów: konflikty zapisu i stan wynikowy PATCH-a (runda 9).

- R9-N13-5: 409 niosło surowy ``IntegrityError`` (SQL i parametry), a
  ``except Exception`` podpisywał każdą awarię bazy jako „konflikt”.
- R9-N13-6: ``{"is_default": true, "archived": true}`` dawał domyślny szablon
  w archiwum.

Testy z ``app_client`` biegną na prawdziwym Postgresie w CI (baza wspólna,
nazwy z uuid). Testy helpera nie potrzebują bazy.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError

from app.api import pipeline_templates


class _Orig(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__("duplicate key value violates unique constraint ... (name)=(x)")
        self.sqlstate = sqlstate


class _FakeDb:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.rolled_back = False

    async def commit(self) -> None:
        raise self.exc

    async def flush(self) -> None:
        raise self.exc

    async def rollback(self) -> None:
        self.rolled_back = True


@pytest.mark.asyncio
async def test_integrity_error_becomes_polish_409_without_sql():
    exc = IntegrityError("INSERT INTO pipeline_templates ...", {}, _Orig("23505"))
    db = _FakeDb(exc)
    with pytest.raises(HTTPException) as raised:
        await pipeline_templates._write_or_conflict(db, "Nazwa zajęta.")
    assert raised.value.status_code == 409
    assert raised.value.detail == "Nazwa zajęta."
    assert "INSERT" not in raised.value.detail
    assert db.rolled_back


@pytest.mark.asyncio
async def test_missing_reference_is_named_as_such():
    exc = IntegrityError("INSERT ...", {}, _Orig("23503"))
    with pytest.raises(HTTPException) as raised:
        await pipeline_templates._write_or_conflict(_FakeDb(exc), "Nazwa zajęta.", flush=True)
    assert raised.value.status_code == 409
    assert "nie istnieje" in raised.value.detail


@pytest.mark.asyncio
async def test_other_database_failures_are_not_reported_as_conflict():
    with pytest.raises(RuntimeError):
        await pipeline_templates._write_or_conflict(
            _FakeDb(RuntimeError("connection lost")), "Nazwa zajęta."
        )


@pytest.mark.asyncio
async def test_duplicate_template_name_is_409_in_polish(
    app_client: AsyncClient, app_auth_headers: dict
):
    name = f"Dup-{uuid.uuid4().hex[:8]}"
    first = await app_client.post(
        "/api/pipeline-templates", headers=app_auth_headers, json={"name": name}
    )
    assert first.status_code == 201, first.text
    second = await app_client.post(
        "/api/pipeline-templates", headers=app_auth_headers, json={"name": name}
    )
    assert second.status_code == 409, second.text
    detail = second.json()["detail"]
    assert "już istnieje" in detail
    assert "INSERT" not in detail and "duplicate key" not in detail


@pytest.mark.asyncio
async def test_patch_cannot_make_template_default_and_archived(
    app_client: AsyncClient, app_auth_headers: dict
):
    created = await app_client.post(
        "/api/pipeline-templates",
        headers=app_auth_headers,
        json={"name": f"DefArch-{uuid.uuid4().hex[:8]}"},
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]

    resp = await app_client.patch(
        f"/api/pipeline-templates/{template_id}",
        headers=app_auth_headers,
        json={"is_default": True, "archived": True},
    )
    assert resp.status_code == 409, resp.text
    assert "zarchiwizowany" in resp.json()["detail"]

    detail = await app_client.get(
        f"/api/pipeline-templates/{template_id}", headers=app_auth_headers
    )
    body = detail.json()
    assert body["is_default"] is False
    assert body["archived"] is False
