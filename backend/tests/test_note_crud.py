"""Integration tests dla edycji i usuwania notatek (Note PATCH/DELETE).

Pokrywa autoryzację `_can_modify_note` (autor albo admin) oraz efekty:
    1. author_can_edit_own_note
    2. author_can_delete_own_note (kaskada NoteMention)
    3. non_author_cannot_edit_note (403, treść bez zmian)
    4. non_author_cannot_delete_note (403, notatka zostaje)
    5. admin_can_edit_and_delete_any_note
    6. edit_missing_note_returns_404
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.note import Note
from app.models.note_mention import NoteMention
from app.models.user import User, UserRole


pytestmark = pytest.mark.asyncio


async def _new_user(db, role: UserRole) -> tuple[User, str]:
    suffix = uuid.uuid4().hex[:8]
    pwd = f"T3st_{suffix}!"
    u = User(
        email=f"crud-{role.value}-{suffix}@example.com",
        password_hash=hash_password(pwd),
        name=f"Crud {role.value} {suffix}",
        role=role,
        is_active=True,
    )
    db.add(u)
    await db.flush()
    return u, pwd


async def _new_candidate(db) -> Candidate:
    suffix = uuid.uuid4().hex[:8]
    c = Candidate(name=f"Cand{suffix}", lastname="Crud", email=f"crud-{suffix}@x.com")
    db.add(c)
    await db.flush()
    return c


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def setup(app_client: AsyncClient) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        author, author_pwd = await _new_user(db, UserRole.recruiter)
        other, other_pwd = await _new_user(db, UserRole.recruiter)
        admin, admin_pwd = await _new_user(db, UserRole.admin)
        candidate = await _new_candidate(db)
        await db.commit()
        return {
            "author_email": author.email,
            "author_password": author_pwd,
            "other_email": other.email,
            "other_password": other_pwd,
            "admin_email": admin.email,
            "admin_password": admin_pwd,
            "candidate_id": candidate.id,
        }


async def _create_note(client: AsyncClient, headers: dict, candidate_id: int) -> int:
    resp = await client.post(
        "/api/notes",
        headers=headers,
        json={
            "content": "treść pierwotna",
            "note_type": "general",
            "candidate_id": candidate_id,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ── Author happy-path ────────────────────────────────────────────────────────


async def test_author_can_edit_own_note(app_client: AsyncClient, setup):
    headers = await _login(app_client, setup["author_email"], setup["author_password"])
    note_id = await _create_note(app_client, headers, setup["candidate_id"])

    resp = await app_client.patch(
        f"/api/notes/{note_id}",
        headers=headers,
        json={"content": "treść poprawiona"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["content"] == "treść poprawiona"

    async with AsyncSessionLocal() as db:
        note = await db.get(Note, note_id)
        assert note is not None
        assert note.content == "treść poprawiona"


async def test_author_can_delete_own_note(app_client: AsyncClient, setup):
    headers = await _login(app_client, setup["author_email"], setup["author_password"])
    note_id = await _create_note(app_client, headers, setup["candidate_id"])

    resp = await app_client.delete(f"/api/notes/{note_id}", headers=headers)
    assert resp.status_code == 204, resp.text

    async with AsyncSessionLocal() as db:
        assert await db.get(Note, note_id) is None
        # Kaskada — NoteMention rows znikają razem z notatką.
        mentions = (
            (
                await db.execute(
                    select(NoteMention).where(NoteMention.note_id == note_id)
                )
            )
            .scalars()
            .all()
        )
        assert mentions == []


# ── Non-author forbidden ─────────────────────────────────────────────────────


async def test_non_author_cannot_edit_note(app_client: AsyncClient, setup):
    author_headers = await _login(
        app_client, setup["author_email"], setup["author_password"]
    )
    note_id = await _create_note(app_client, author_headers, setup["candidate_id"])

    other_headers = await _login(
        app_client, setup["other_email"], setup["other_password"]
    )
    resp = await app_client.patch(
        f"/api/notes/{note_id}",
        headers=other_headers,
        json={"content": "próba cudzej edycji"},
    )
    assert resp.status_code == 403, resp.text

    async with AsyncSessionLocal() as db:
        note = await db.get(Note, note_id)
        assert note is not None
        assert note.content == "treść pierwotna"


async def test_non_author_cannot_delete_note(app_client: AsyncClient, setup):
    author_headers = await _login(
        app_client, setup["author_email"], setup["author_password"]
    )
    note_id = await _create_note(app_client, author_headers, setup["candidate_id"])

    other_headers = await _login(
        app_client, setup["other_email"], setup["other_password"]
    )
    resp = await app_client.delete(f"/api/notes/{note_id}", headers=other_headers)
    assert resp.status_code == 403, resp.text

    async with AsyncSessionLocal() as db:
        assert await db.get(Note, note_id) is not None


# ── Admin override ───────────────────────────────────────────────────────────


async def test_admin_can_edit_and_delete_any_note(app_client: AsyncClient, setup):
    author_headers = await _login(
        app_client, setup["author_email"], setup["author_password"]
    )
    note_id = await _create_note(app_client, author_headers, setup["candidate_id"])

    admin_headers = await _login(
        app_client, setup["admin_email"], setup["admin_password"]
    )
    edit = await app_client.patch(
        f"/api/notes/{note_id}",
        headers=admin_headers,
        json={"content": "edycja przez admina"},
    )
    assert edit.status_code == 200, edit.text
    assert edit.json()["content"] == "edycja przez admina"

    delete = await app_client.delete(f"/api/notes/{note_id}", headers=admin_headers)
    assert delete.status_code == 204, delete.text

    async with AsyncSessionLocal() as db:
        assert await db.get(Note, note_id) is None


# ── Not found ────────────────────────────────────────────────────────────────


async def test_edit_missing_note_returns_404(app_client: AsyncClient, setup):
    headers = await _login(app_client, setup["author_email"], setup["author_password"])
    resp = await app_client.patch(
        "/api/notes/99999999", headers=headers, json={"content": "x"}
    )
    assert resp.status_code == 404, resp.text
