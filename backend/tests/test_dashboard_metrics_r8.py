"""Kreator metryk pulpitu — poprawki rundy 8 audytu.

* R8-N10-2 — Delivery Lead z odebraną sekcją Delivery nie liczy kwot portfela,
* R8-N10-4 — uprawnienia do źródła i granica klientów idą PRZED cache
  (odebrany klient nie przeżywa w wyniku zapamiętanym na 2 minuty),
* R8-N10-7 — podział po rekruterach przy „cała firma” mówi, że liczy kredyt KPI.

Testy jednostkowe bez bazy; testy ``needs_db`` przechodzą całe API na PostgreSQL.
"""

from __future__ import annotations

import os
import uuid

import pytest

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"
)

URL = "/api/dashboard-metrics/evaluate"


def _dl_user(delivery: str):
    from app.models.user import User, UserRole
    from app.services.section_permissions import ProductSection

    user = User(
        id=91,
        email="dl-r8@example.com",
        name="DL",
        role=UserRole.delivery_lead,
        roles=["delivery_lead"],
        is_active=True,
    )
    user.effective_section_access = {
        section.value: "none" for section in ProductSection
    } | {"delivery": delivery, "pipeline": "write"}
    return user


def _finance_definition():
    from app.services.custom_metrics.definition import MetricDefinition

    return MetricDefinition.model_validate(
        {"source": "finance", "measure": "revenue", "period": "this_month"}
    )


def test_dl_without_delivery_section_cannot_count_money():
    from app.services.custom_metrics.engine import source_denial

    reason = source_denial(_dl_user("none"), "finance")
    assert reason and "Delivery" in reason


def test_dl_with_delivery_read_counts_money():
    from app.services.custom_metrics.engine import source_denial

    assert source_denial(_dl_user("read"), "finance") is None


@pytest.mark.asyncio
async def test_access_fingerprint_raises_before_cache_and_tracks_portfolio(
    monkeypatch,
):
    from app.services.custom_metrics import engine

    with pytest.raises(engine.MetricAccessDenied):
        await engine.access_fingerprint(None, _dl_user("none"), _finance_definition())

    portfolio = {"ids": frozenset({7, 3})}

    async def _finance_ids(user, db):
        return portfolio["ids"]

    monkeypatch.setattr(
        engine, "resolve_delivery_lead_finance_client_ids", _finance_ids
    )
    user = _dl_user("read")
    before = await engine.access_fingerprint(None, user, _finance_definition())
    assert before == "3,7"
    portfolio["ids"] = frozenset({7})
    after = await engine.access_fingerprint(None, user, _finance_definition())
    assert after == "7" and after != before


async def _login(role: str):
    import app.models  # noqa: F401
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token
    from app.models.user import User, UserRole

    marker = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"metric-r8-{marker}@example.com",
            name=f"Metryka {marker}",
            role=UserRole(role),
            roles=[role],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        uid = user.id
    return {"Authorization": f"Bearer {create_access_token(uid, role)}"}, uid


@needs_db
@pytest.mark.asyncio
async def test_removed_client_is_denied_even_with_a_cached_result(app_client):
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.team_structure import DeliveryLeadClientAssignment

    headers, uid = await _login("delivery_lead")
    async with AsyncSessionLocal() as db:
        mine = Client(name=f"dl-r8-{uuid.uuid4().hex[:8]}")
        db.add(mine)
        await db.flush()
        db.add(
            DeliveryLeadClientAssignment(delivery_lead_user_id=uid, client_id=mine.id)
        )
        await db.commit()
        client_id = mine.id

    body = {
        "source": "finance",
        "measure": "revenue",
        "filters": {"client_ids": [client_id]},
        "period": "this_month",
    }
    ok = await app_client.post(URL, headers=headers, json=body)
    assert ok.status_code == 200, ok.text

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(DeliveryLeadClientAssignment).where(
                DeliveryLeadClientAssignment.delivery_lead_user_id == uid
            )
        )
        await db.commit()

    denied = await app_client.post(URL, headers=headers, json=body)
    assert denied.status_code == 403, denied.text
    assert denied.json()["detail"]["code"] == "metric_scope_denied"


@needs_db
@pytest.mark.asyncio
async def test_recruiter_split_of_whole_company_says_it_counts_kpi_credit(app_client):
    headers, _ = await _login("admin")
    body = {
        "source": "pipeline_moves",
        "measure": "first_reach",
        "stage": "hired",
        "filters": {"author": "all"},
        "group_by": "recruiter",
        "period": "last_30_days",
    }
    resp = await app_client.post(URL, headers=headers, json=body)
    assert resp.status_code == 200, resp.text
    assert any("Moje KPI" in note for note in resp.json()["notes"])

    body["group_by"] = "none"
    plain = await app_client.post(URL, headers=headers, json=body)
    assert plain.status_code == 200, plain.text
    assert not any("Moje KPI" in note for note in plain.json()["notes"])
