"""Integration tests dla @mention w ScreeningNote.

Pokrywa scenariusze:
    1. screening_note_concats_three_fields — mention w red_flags + personality_notes
       + closing_strategy → 3 NoteMention rows
    2. screening_note_filters_self_mention
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
from app.models.notification import Notification, NotificationType
from app.models.screening_note_mention import ScreeningNoteMention
from app.models.user import User, UserRole


pytestmark = pytest.mark.asyncio


async def _new_user(db, role: UserRole) -> tuple[User, str]:
    suffix = uuid.uuid4().hex[:8]
    pwd = f"T3st_{suffix}!"
    u = User(
        email=f"scr-{role.value}-{suffix}@example.com",
        password_hash=hash_password(pwd),
        name=f"Scr {role.value} {suffix}",
        role=role,
        is_active=True,
    )
    db.add(u)
    await db.flush()
    return u, pwd


async def _new_candidate(db) -> Candidate:
    suffix = uuid.uuid4().hex[:8]
    c = Candidate(
        name=f"Cand{suffix}", lastname="Scr", email=f"cand-{suffix}@x.com"
    )
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
async def scr_setup(app_client: AsyncClient) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        author, pwd = await _new_user(db, UserRole.recruiter)
        t1, _ = await _new_user(db, UserRole.delivery_lead)
        t2, _ = await _new_user(db, UserRole.delivery_lead)
        t3, _ = await _new_user(db, UserRole.delivery_lead)
        candidate = await _new_candidate(db)
        await db.commit()
        return {
            "author_id": author.id,
            "author_email": author.email,
            "author_password": pwd,
            "t1_email": t1.email,
            "t1_id": t1.id,
            "t2_email": t2.email,
            "t2_id": t2.id,
            "t3_email": t3.email,
            "t3_id": t3.id,
            "candidate_id": candidate.id,
        }


async def test_screening_note_concats_three_fields(
    app_client: AsyncClient, scr_setup
):
    """Mention w 3 osobnych polach → 3 ScreeningNoteMention rows."""
    headers = await _login(
        app_client, scr_setup["author_email"], scr_setup["author_password"]
    )
    resp = await app_client.post(
        "/api/screenings",
        headers=headers,
        json={
            "candidate_id": scr_setup["candidate_id"],
            "screening_type": "initial_screening",
            "red_flags": f"Brak commitmentu — pytaj @{scr_setup['t1_email']}",
            "personality_notes": f"Kontakt z @{scr_setup['t2_email']} feedback",
            "closing_strategy": f"Confirm @{scr_setup['t3_email']} zgoda",
            "salary_currency": "PLN",
            "salary_negotiable": False,
        },
    )
    assert resp.status_code == 201, resp.text
    note_id = resp.json()["id"]

    async with AsyncSessionLocal() as db:
        mentions = (
            await db.execute(
                select(ScreeningNoteMention).where(
                    ScreeningNoteMention.screening_note_id == note_id
                )
            )
        ).scalars().all()
        notifs = (
            await db.execute(
                select(Notification).where(
                    Notification.notification_type == NotificationType.note_mention,
                    Notification.related_entity_type == "screening_note",
                    Notification.related_entity_id == note_id,
                )
            )
        ).scalars().all()

    user_ids = {m.user_id for m in mentions}
    assert user_ids == {
        scr_setup["t1_id"],
        scr_setup["t2_id"],
        scr_setup["t3_id"],
    }
    assert len(notifs) == 3


async def test_screening_note_filters_self_mention(
    app_client: AsyncClient, scr_setup
):
    """Author oznacza siebie + t1 → tylko t1 dostaje mention."""
    headers = await _login(
        app_client, scr_setup["author_email"], scr_setup["author_password"]
    )
    resp = await app_client.post(
        "/api/screenings",
        headers=headers,
        json={
            "candidate_id": scr_setup["candidate_id"],
            "screening_type": "initial_screening",
            "red_flags": (
                f"@{scr_setup['author_email']} self + "
                f"@{scr_setup['t1_email']} target"
            ),
            "salary_currency": "PLN",
            "salary_negotiable": False,
        },
    )
    assert resp.status_code == 201
    note_id = resp.json()["id"]

    async with AsyncSessionLocal() as db:
        mentions = (
            await db.execute(
                select(ScreeningNoteMention).where(
                    ScreeningNoteMention.screening_note_id == note_id
                )
            )
        ).scalars().all()
    user_ids = {m.user_id for m in mentions}
    assert user_ids == {scr_setup["t1_id"]}
