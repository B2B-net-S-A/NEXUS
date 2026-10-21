"""Panel „Ranking kandydatów”: pomiar w tle, bramka publikacji, „Przywróć”.

Na prawdziwej bazie. Sam pomiar (Qdrant, Voyage) jest podmieniony — tu
sprawdzamy reguły: bez aktualnego pomiaru nie ma publikacji, spadek > 2 pkt
wymaga powodu, publikacja zmienia profil ogólny, próg i historię. Fixture
przywraca profil ogólny i klucze ``app_settings`` — baza jest wspólna dla
innych testów w shardzie.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.scoring_weight_change import (
    ScoringWeightChange,
    ScoringWeightMeasurement,
)
from app.models.scoring_weight_profile import ScoringWeightProfile
from app.models.user import User, UserRole
from app.services import ranking_lab
from app.services import ranking_weights as rw

BASE = "/api/scoring-weights/panel"


def _result(*, drop: float = 0.0) -> dict:
    before = {
        "page1_hit": 85.8,
        "median_first": 4,
        "top50_share": 61.0,
        "mrr": 0.4,
        "proposals": 100,
    }
    after = {**before, "page1_hit": round(85.8 - drop, 1)}
    return {
        "jobs": 120,
        "before": before,
        "after": after,
        "max_drop_pt": drop,
        "needs_reason": drop > ranking_lab.MAX_DROP_PT,
        "biggest_changes": [],
        "duration_s": 1,
    }


@pytest_asyncio.fixture
async def restore_world():
    async with AsyncSessionLocal() as db:
        globals_before = {
            row.id: (dict(row.weights), row.active, row.name)
            for row in (
                await db.execute(
                    select(ScoringWeightProfile).where(
                        ScoringWeightProfile.user_id.is_(None),
                        ScoringWeightProfile.client_id.is_(None),
                    )
                )
            ).scalars()
        }
        await db.execute(
            delete(AppSetting).where(
                AppSetting.key.in_([rw.DRAFT_KEY, rw.THRESHOLD_KEY])
            )
        )
        await db.commit()
    yield
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(ScoringWeightProfile).where(
                    ScoringWeightProfile.user_id.is_(None),
                    ScoringWeightProfile.client_id.is_(None),
                )
            )
        ).scalars()
        for row in rows:
            if row.id not in globals_before:
                await db.delete(row)
            else:
                row.weights, row.active, row.name = globals_before[row.id]
        await db.execute(
            delete(AppSetting).where(
                AppSetting.key.in_([rw.DRAFT_KEY, rw.THRESHOLD_KEY])
            )
        )
        await db.commit()


async def _hor() -> dict[str, str]:
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"ranking-publish-{marker}@example.com",
            name=f"HoR {marker}",
            role=UserRole.head_of_recruitment,
            roles=["head_of_recruitment"],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _wait_done(client: AsyncClient, headers: dict) -> dict:
    for _ in range(100):
        state = (await client.get(f"{BASE}/measurement", headers=headers)).json()
        measurement = state["measurement"]
        if measurement and measurement["status"] in ("done", "failed"):
            return measurement
        await asyncio.sleep(0.05)
    raise AssertionError("pomiar nie skończył się")


async def _draft(client: AsyncClient, headers: dict, **values) -> dict:
    published = (await client.get(BASE, headers=headers)).json()["published"]["weights"]
    body = {**published, **values}
    resp = await client.put(f"{BASE}/draft", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return body


async def test_publish_requires_fresh_measurement_then_publishes(
    app_client: AsyncClient, restore_world, monkeypatch
):
    async def fake_measure(*_args, **_kwargs):
        return _result(drop=0.5)

    monkeypatch.setattr(ranking_lab, "measure", fake_measure)
    hor = await _hor()

    # Bez szkicu nie ma czego mierzyć.
    nothing = await app_client.post(f"{BASE}/measurements", headers=hor)
    assert nothing.status_code == 409
    assert "szkicu" in nothing.json()["detail"]

    draft = await _draft(app_client, hor, skills=30, threshold=75)
    blocked = await app_client.post(f"{BASE}/publish", json={}, headers=hor)
    assert blocked.status_code == 409
    assert "pomiaru" in blocked.json()["detail"]

    started = await app_client.post(f"{BASE}/measurements", headers=hor)
    assert started.status_code == 202, started.text
    measurement = await _wait_done(app_client, hor)
    assert measurement["status"] == "done"
    assert measurement["fresh"] is True

    # Zmiana szkicu po pomiarze = pomiar nieaktualny.
    await _draft(app_client, hor, skills=35, threshold=75)
    stale = await app_client.post(f"{BASE}/publish", json={}, headers=hor)
    assert stale.status_code == 409
    await _draft(app_client, hor, skills=30, threshold=75)

    published = await app_client.post(
        f"{BASE}/publish", json={"reason": "więcej wagi dla stacku"}, headers=hor
    )
    assert published.status_code == 200, published.text
    state = published.json()
    assert state["draft"] is None
    assert state["published"]["weights"] == draft
    assert state["published"]["threshold_source"] == "setting"
    assert state["history"][0]["kind"] == "publish"
    assert state["history"][0]["reason"] == "więcej wagi dla stacku"
    assert state["history"][0]["measurement"]["jobs"] == 120

    async with AsyncSessionLocal() as db:
        assert await rw.nightly_min_score(db) == 75.0
        row = await rw.published_profile_row(db)
        assert row.weights == rw.engine_weights(rw.PanelWeights.from_dict(draft))


async def test_drop_over_two_points_needs_reason(
    app_client: AsyncClient, restore_world, monkeypatch
):
    async def fake_measure(*_args, **_kwargs):
        return _result(drop=3.0)

    monkeypatch.setattr(ranking_lab, "measure", fake_measure)
    hor = await _hor()
    await _draft(app_client, hor, location=40)
    assert (
        await app_client.post(f"{BASE}/measurements", headers=hor)
    ).status_code == 202
    await _wait_done(app_client, hor)

    no_reason = await app_client.post(
        f"{BASE}/publish", json={"reason": "  "}, headers=hor
    )
    assert no_reason.status_code == 422
    assert "powód" in no_reason.json()["detail"]
    ok = await app_client.post(
        f"{BASE}/publish",
        json={"reason": "świadomie: miasto ważniejsze u klienta"},
        headers=hor,
    )
    assert ok.status_code == 200, ok.text


async def test_failed_measurement_reads_as_failed(
    app_client: AsyncClient, restore_world, monkeypatch
):
    async def broken(*_args, **_kwargs):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(ranking_lab, "measure", broken)
    hor = await _hor()
    await _draft(app_client, hor, skills=25)
    assert (
        await app_client.post(f"{BASE}/measurements", headers=hor)
    ).status_code == 202
    measurement = await _wait_done(app_client, hor)
    assert measurement["status"] == "failed"
    assert "nie powiódł się" in measurement["error"]
    assert "qdrant" not in measurement["error"]
    blocked = await app_client.post(f"{BASE}/publish", json={}, headers=hor)
    assert blocked.status_code == 409


async def test_restore_makes_a_draft_from_history(
    app_client: AsyncClient, restore_world
):
    hor = await _hor()
    async with AsyncSessionLocal() as db:
        change = ScoringWeightChange(
            kind="publish",
            before={},
            after={
                "panel": {"semantic": 45, "skills": 25, "location": 8},
                "threshold": 65,
                "weights": {},
            },
        )
        db.add(change)
        await db.commit()
        change_id = change.id
    resp = await app_client.post(f"{BASE}/history/{change_id}/restore", headers=hor)
    assert resp.status_code == 200, resp.text
    draft = resp.json()["draft"]
    assert draft["weights"] == {
        "semantic": 45,
        "skills": 25,
        "location": 8,
        "threshold": 65,
    }
    assert draft["restored_from"] == change_id
    missing = await app_client.post(f"{BASE}/history/999999999/restore", headers=hor)
    assert missing.status_code == 404
    async with AsyncSessionLocal() as db:
        scoped = ScoringWeightChange(
            kind="admin_edit",
            before={},
            after={
                "name": "Profil klienta",
                "client_id": 42,
                "user_id": None,
                "active": True,
                "weights": {"semantic": 30, "skills": 50, "salary": 10, "location": 10},
            },
        )
        db.add(scoped)
        await db.commit()
        scoped_id = scoped.id
    refused = await app_client.post(f"{BASE}/history/{scoped_id}/restore", headers=hor)
    assert refused.status_code == 422
    assert "klienta" in refused.json()["detail"]
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ScoringWeightChange).where(
                ScoringWeightChange.id.in_([change_id, scoped_id])
            )
        )
        await db.execute(delete(ScoringWeightMeasurement))
        await db.commit()


async def test_dl_cannot_measure_publish_or_restore(
    app_client: AsyncClient, restore_world
):
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"ranking-dl-{marker}@example.com",
            name=f"DL {marker}",
            role=UserRole.delivery_lead,
            roles=["delivery_lead"],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    dl = {
        "Authorization": f"Bearer {create_access_token(subject=user.id, role='delivery_lead')}"
    }
    assert (
        await app_client.post(f"{BASE}/measurements", headers=dl)
    ).status_code == 403
    assert (
        await app_client.post(f"{BASE}/publish", json={}, headers=dl)
    ).status_code == 403
    assert (
        await app_client.post(f"{BASE}/history/1/restore", headers=dl)
    ).status_code == 403
    assert (await app_client.get(f"{BASE}/measurement", headers=dl)).status_code == 200
