"""Kreator metryk: kontrakty i zamówienia zawężone do portfela DL (runda 6 audytu).

Decyzja Artura 26.09.2026: pulpit Delivery Leada liczy kontrakty i zamówienia
wyłącznie jego klientów — tak samo jak moduły Delivery od 25.09.2026. Do tej
rundy źródła ``contracts``/``orders`` nie miały zakresu klienta, więc kafelki
„Aktywne kontrakty" i „Kończące się zamówienia" pokazywały całą firmę, a
filtr z klientem spoza portfela zwracał jego liczby.

Testy jednostkowe podstawiają resolvery i przechwytują SQL (bez bazy), test
na końcu przechodzi całą ścieżkę API na PostgreSQL.
"""

from __future__ import annotations

import os
import uuid
from datetime import date
from types import SimpleNamespace

import pytest

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"
)

TODAY = date(2026, 9, 26)


class _FakeResult:
    def scalar(self):
        return 0


class _FakeDb:
    def __init__(self):
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _FakeResult()


def _sql(stmt) -> str:
    from sqlalchemy.dialects import postgresql

    return str(
        stmt.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def _definition(source: str, **filters):
    from app.services.custom_metrics.definition import MetricDefinition

    measure = "active_now" if source == "contracts" else "ending_30_days"
    return MetricDefinition.model_validate(
        {
            "source": source,
            "measure": measure,
            "filters": {"author": "all", **filters},
            "group_by": "none",
            "period": "last_30_days",
        }
    )


def _patch(monkeypatch, *, portfolio, whole=False, assigned_scope=True):
    from app.services.custom_metrics import engine

    monkeypatch.setattr(engine, "source_denial", lambda user, source: None)
    monkeypatch.setattr(
        engine, "delivery_lead_scope_is_assigned", lambda: assigned_scope
    )
    monkeypatch.setattr(engine, "delivery_lead_sees_whole_delivery", lambda user: whole)

    async def _assigned(user, db):
        return portfolio

    monkeypatch.setattr(engine, "resolve_delivery_lead_assigned_client_ids", _assigned)


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["contracts", "orders"])
async def test_delivery_lead_counts_only_portfolio_clients(monkeypatch, source):
    from app.services.custom_metrics.engine import evaluate_metric

    _patch(monkeypatch, portfolio=frozenset({501, 502}))
    db = _FakeDb()
    result = await evaluate_metric(
        db, SimpleNamespace(id=7), _definition(source), today=TODAY
    )

    sql = _sql(db.statements[0])
    assert "client_id IN (501, 502)" in sql, sql
    assert result.scope_applied == "portfolio"


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["contracts", "orders"])
async def test_client_outside_portfolio_is_denied_not_counted(monkeypatch, source):
    from app.services.custom_metrics.engine import (
        MetricAccessDenied,
        evaluate_metric,
    )

    _patch(monkeypatch, portfolio=frozenset({501}))
    db = _FakeDb()
    with pytest.raises(MetricAccessDenied, match="portfela"):
        await evaluate_metric(
            db,
            SimpleNamespace(id=7),
            _definition(source, client_ids=[501, 999]),
            today=TODAY,
        )
    assert db.statements == []


@pytest.mark.asyncio
async def test_delivery_lead_without_clients_is_denied_not_zeroed(monkeypatch):
    from app.services.custom_metrics.engine import (
        MetricAccessDenied,
        evaluate_metric,
    )

    _patch(monkeypatch, portfolio=frozenset())
    with pytest.raises(MetricAccessDenied):
        await evaluate_metric(
            _FakeDb(), SimpleNamespace(id=7), _definition("contracts"), today=TODAY
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"portfolio": None},  # admin/Finanse albo rola bez DL
        {"portfolio": frozenset({501}), "whole": True},  # TCM + DL
        {"portfolio": frozenset({501}), "assigned_scope": False},  # DL_CLIENT_SCOPE=all
    ],
)
async def test_whole_company_personas_keep_every_client(monkeypatch, kwargs):
    from app.services.custom_metrics.engine import evaluate_metric

    _patch(monkeypatch, **kwargs)
    db = _FakeDb()
    result = await evaluate_metric(
        db, SimpleNamespace(id=7), _definition("contracts"), today=TODAY
    )
    assert "client_id IN" not in _sql(db.statements[0])
    assert result.scope_applied == "all"


@pytest.mark.asyncio
async def test_previous_period_uses_the_same_portfolio(monkeypatch):
    from app.services.custom_metrics.definition import MetricDefinition
    from app.services.custom_metrics.engine import evaluate_metric

    _patch(monkeypatch, portfolio=frozenset({501}))
    db = _FakeDb()
    definition = MetricDefinition.model_validate(
        {
            "source": "contracts",
            "measure": "started",
            "filters": {"author": "all"},
            "group_by": "none",
            "period": "last_30_days",
            "compare_previous": True,
        }
    )
    await evaluate_metric(db, SimpleNamespace(id=7), definition, today=TODAY)
    assert len(db.statements) == 2
    assert all("client_id IN (501)" in _sql(s) for s in db.statements)


@needs_db
@pytest.mark.asyncio
async def test_active_contracts_tile_counts_only_the_dl_portfolio(app_client):
    import app.models  # noqa: F401
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import User, UserRole

    marker = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"metric-dl-{marker}@example.com",
            name=f"DL {marker}",
            role=UserRole.delivery_lead,
            roles=["delivery_lead"],
            is_active=True,
            profile_completed=True,
        )
        mine = Client(name=f"dl-mine-{marker}")
        foreign = Client(name=f"dl-foreign-{marker}")
        cand = Candidate(name="Ala", lastname=f"Dl{marker}")
        db.add_all([user, mine, foreign, cand])
        await db.flush()
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=user.id, client_id=mine.id
            )
        )
        for client in (mine, foreign):
            db.add(
                Contract(
                    candidate_id=cand.id,
                    client_id=client.id,
                    status=ContractStatus.active,
                )
            )
        await db.commit()
        uid, mine_id, foreign_id = user.id, mine.id, foreign.id
    headers = {"Authorization": f"Bearer {create_access_token(uid, 'delivery_lead')}"}
    body = {
        "source": "contracts",
        "measure": "active_now",
        "filters": {"author": "all"},
        "group_by": "client",
        "period": "last_30_days",
    }
    resp = await app_client.post(
        "/api/dashboard-metrics/evaluate", headers=headers, json=body
    )
    assert resp.status_code == 200, resp.text
    keys = {s["key"] for s in resp.json()["series"]}
    assert str(mine_id) in keys
    assert str(foreign_id) not in keys

    body["filters"]["client_ids"] = [foreign_id]
    denied = await app_client.post(
        "/api/dashboard-metrics/evaluate", headers=headers, json=body
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "metric_scope_denied"
