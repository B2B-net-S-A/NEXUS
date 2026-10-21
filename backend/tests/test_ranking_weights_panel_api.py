"""Panel „Ranking kandydatów” — trasy na prawdziwej bazie (21.10.2026).

Baza testowa jest wspólna: testy nie zakładają profilu OGÓLNEGO (zmieniłby
„Dop.” w innych testach tego samego sharda), a klucze szkicu i progu
w ``app_settings`` sprząta fixture.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.client import Client
from app.models.scoring_weight_change import ScoringWeightChange
from app.models.scoring_weight_profile import ScoringWeightProfile
from app.models.user import User, UserRole
from app.services import ranking_weights as rw

PANEL = "/api/scoring-weights/panel"
DRAFT = "/api/scoring-weights/panel/draft"


async def _clear_keys() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(AppSetting).where(
                AppSetting.key.in_([rw.DRAFT_KEY, rw.THRESHOLD_KEY])
            )
        )
        await db.commit()


@pytest_asyncio.fixture
async def clean_keys():
    await _clear_keys()
    yield
    await _clear_keys()


async def _user(role: UserRole) -> User:
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"ranking-{role.value}-{marker}@example.com",
            name=f"Ranking {role.value} {marker}",
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


async def test_hor_reads_and_saves_draft_dl_only_reads(
    app_client: AsyncClient, clean_keys
):
    hor = _headers(await _user(UserRole.head_of_recruitment))
    dl = _headers(await _user(UserRole.delivery_lead))

    state = await app_client.get(PANEL, headers=hor)
    assert state.status_code == 200, state.text
    body = state.json()
    assert body["can_edit"] is True
    assert body["draft"] is None
    assert body["fixed"] == {"salary": 15, "availability": 0}

    read_dl = await app_client.get(PANEL, headers=dl)
    assert read_dl.status_code == 200
    assert read_dl.json()["can_edit"] is False

    published = body["published"]["weights"]
    draft = {**published, "skills": published["skills"] + 20}
    saved = await app_client.put(DRAFT, json=draft, headers=hor)
    assert saved.status_code == 200, saved.text
    assert saved.json()["draft"]["weights"] == draft
    assert saved.json()["draft"]["updated_by_name"].startswith("Ranking")

    denied = await app_client.put(DRAFT, json=draft, headers=dl)
    assert denied.status_code == 403
    denied_delete = await app_client.delete(DRAFT, headers=dl)
    assert denied_delete.status_code == 403

    # Szkic nic nie zmienia dla zespołu: opublikowane bez zmian.
    again = (await app_client.get(PANEL, headers=dl)).json()
    assert again["published"]["weights"] == published

    removed = await app_client.delete(DRAFT, headers=hor)
    assert removed.status_code == 204
    assert (await app_client.get(PANEL, headers=hor)).json()["draft"] is None


async def test_draft_equal_to_published_is_no_draft(
    app_client: AsyncClient, clean_keys
):
    hor = _headers(await _user(UserRole.head_of_recruitment))
    published = (await app_client.get(PANEL, headers=hor)).json()["published"]
    resp = await app_client.put(DRAFT, json=published["weights"], headers=hor)
    assert resp.status_code == 200
    assert resp.json()["draft"] is None


@pytest.mark.parametrize(
    ("patch", "fragment"),
    [
        ({"semantic": 120}, "od 0 do 100"),
        ({"semantic": 0, "skills": 0, "location": 0}, "co najmniej jedną"),
        ({"threshold": 30}, "od 50 do 90"),
    ],
)
async def test_invalid_draft_is_422_in_polish(
    app_client: AsyncClient, clean_keys, patch, fragment
):
    hor = _headers(await _user(UserRole.head_of_recruitment))
    draft = {"semantic": 60, "skills": 10, "location": 5, "threshold": 70, **patch}
    resp = await app_client.put(DRAFT, json=draft, headers=hor)
    assert resp.status_code == 422
    assert fragment in resp.json()["detail"]


@pytest.mark.parametrize("role", [UserRole.recruiter, UserRole.finance])
async def test_other_roles_do_not_see_the_panel(
    app_client: AsyncClient, clean_keys, role
):
    headers = _headers(await _user(role))
    assert (await app_client.get(PANEL, headers=headers)).status_code == 403
    draft = {"semantic": 60, "skills": 30, "location": 5, "threshold": 70}
    assert (await app_client.put(DRAFT, json=draft, headers=headers)).status_code == 403


async def test_threshold_setting_overrides_env(clean_keys, monkeypatch):
    monkeypatch.setattr(settings, "AUTO_FULL_REVIEW_MIN_SCORE", 70.0)
    async with AsyncSessionLocal() as db:
        assert await rw.nightly_min_score(db) == 70.0
        db.add(AppSetting(key=rw.THRESHOLD_KEY, value={"value": 80}))
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert await rw.nightly_min_score(db) == 80.0


async def test_admin_patch_sets_updated_at_and_leaves_history(
    app_client: AsyncClient, app_auth_headers: dict
):
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Klient Wag {marker}")
        db.add(client)
        await db.flush()
        # Profil klienta, nie ogólny — nie zmienia „Dop.” w innych testach.
        row = ScoringWeightProfile(
            name=f"Wagi klienta {marker}",
            client_id=client.id,
            weights={
                "semantic": 60,
                "skills": 10,
                "salary": 15,
                "location": 5,
                "availability": 0,
                "champion_fit": 10,
            },
            active=True,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        profile_id, created = row.id, row.updated_at

    payload = {
        "name": f"Wagi klienta {marker}",
        "weights": {
            "semantic": 50,
            "skills": 20,
            "salary": 15,
            "location": 5,
            "availability": 0,
            "champion_fit": 10,
        },
        "active": True,
    }
    resp = await app_client.patch(
        f"/api/scoring-weights/{profile_id}", json=payload, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        row = await db.get(ScoringWeightProfile, profile_id)
        assert row.updated_at > created
        assert row.client_id is not None
        change = await db.scalar(
            select(ScoringWeightChange)
            .where(ScoringWeightChange.profile_id == profile_id)
            .order_by(ScoringWeightChange.id.desc())
        )
        assert change.kind == "admin_edit"
        assert change.before["weights"]["semantic"] == 60
        assert change.after["weights"]["semantic"] == 50
        await db.delete(row)
        await db.commit()

    history = (await app_client.get(PANEL, headers=app_auth_headers)).json()["history"]
    assert any(item["profile_id"] == profile_id for item in history)
