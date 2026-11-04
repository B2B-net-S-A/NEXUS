"""Sprzedaż → KPI tygodniowe i cele (``/api/sales/kpi``).

Cele ustawia tylko admin; KPI widzi każdy z „Sprzedaż: podgląd”. Liczby
sprawdzamy na świeżym koncie handlowca — baza testowa jest wspólna, więc
asercje dotyczą tylko jego wiersza.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today, local_day_start_utc
from app.models.sales import SalesActivity, SalesOpportunity
from app.services.sales.kpi import week_start
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_opportunities_api import _company, _stages

KPI = "/api/sales/kpi"
OPPS = "/api/sales/opportunities"


async def _opportunity(app_client, user, company_id: int, **fields) -> dict:
    resp = await app_client.post(
        OPPS,
        json={"company_id": company_id, "title": "Szansa KPI", **fields},
        headers=_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _move(app_client, user, opp_id: int, stage_id: int) -> None:
    resp = await app_client.post(
        f"{OPPS}/{opp_id}/move", json={"stage_id": stage_id}, headers=_headers(user)
    )
    assert resp.status_code == 200, resp.text


def _row(body: dict, user_id: int) -> dict:
    return next(p for p in body["people"] if p["user_id"] == user_id)


@pytest.mark.asyncio
async def test_only_admin_edits_targets(app_client) -> None:
    rep = await _user("sales_edit")
    for method, url, payload in (
        ("get", f"{KPI}/targets", None),
        ("put", f"{KPI}/targets/company", {"net_mrr_goal": "1"}),
        (
            "put",
            f"{KPI}/targets/{rep.id}",
            {"meetings": 1, "qualified": 1, "offers_stage": 1},
        ),
        ("delete", f"{KPI}/targets/{rep.id}", None),
    ):
        kwargs = {"headers": _headers(rep)}
        if payload is not None:
            kwargs["json"] = payload
        resp = await getattr(app_client, method)(url, **kwargs)
        assert resp.status_code == 403, (method, url, resp.text)

    # KPI czyta każdy z podglądem Sprzedaży, bez niego — 403.
    assert (await app_client.get(KPI, headers=_headers(rep))).status_code == 200
    outsider = await _user()
    resp = await app_client.get(KPI, headers=_headers(outsider))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "permission_denied"


@pytest.mark.asyncio
async def test_admin_sets_person_and_company_targets(app_client) -> None:
    admin = await _user(role="admin")
    rep = await _user("sales_edit")

    resp = await app_client.put(
        f"{KPI}/targets/{rep.id}",
        json={
            "meetings": 4,
            "qualified": 2,
            "offers_stage": 1,
            "margin_goal_amount": "1000.00",
            "margin_goal_deadline": "2026-12-31",
            "team": "  Drużyna A  ",
        },
        headers=_headers(admin),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["team"] == "Drużyna A"
    resp = await app_client.put(
        f"{KPI}/targets/company",
        json={"net_mrr_goal": "5000.00", "goal_deadline": "2027-03-31"},
        headers=_headers(admin),
    )
    assert resp.status_code == 200, resp.text

    targets = (await app_client.get(f"{KPI}/targets", headers=_headers(admin))).json()
    assert Decimal(targets["company"]["net_mrr_goal"]) == Decimal("5000")
    person = next(p for p in targets["people"] if p["user_id"] == rep.id)
    assert person["has_targets"] is True and person["meetings"] == 4

    # Ujemny cel i zbyt długa nazwa drużyny — 422.
    bad = await app_client.put(
        f"{KPI}/targets/{rep.id}",
        json={"meetings": -1, "qualified": 0, "offers_stage": 0},
        headers=_headers(admin),
    )
    assert bad.status_code == 422

    kpi = (await app_client.get(KPI, headers=_headers(rep))).json()
    row = _row(kpi, rep.id)
    assert row["targets"] == {"meetings": 4, "qualified": 2, "offers_stage": 1}
    assert row["team"] == "Drużyna A"
    assert kpi["company"]["goal_deadline"] == "2027-03-31"

    deleted = await app_client.delete(
        f"{KPI}/targets/{rep.id}", headers=_headers(admin)
    )
    assert deleted.status_code == 204
    kpi = (await app_client.get(KPI, headers=_headers(rep))).json()
    assert all(p["user_id"] != rep.id for p in kpi["people"])


@pytest.mark.asyncio
async def test_weekly_counts_follow_atlas_definitions(app_client) -> None:
    admin = await _user(role="admin")
    rep = await _user("sales_edit")
    await app_client.put(
        f"{KPI}/targets/{rep.id}",
        json={"meetings": 4, "qualified": 3, "offers_stage": 1},
        headers=_headers(admin),
    )
    stages = await _stages(app_client, rep)
    company_id = await _company(app_client, rep)
    first = await _opportunity(app_client, rep, company_id)
    second = await _opportunity(app_client, rep, company_id)
    archived = await _opportunity(app_client, rep, company_id)

    # Lead kwalifikowany = qualified_at w tygodniu (skok od razu na „Oferta
    # wysłana” też kwalifikuje); dwie szanse jednej firmy na „Oferta wysłana”
    # w tym samym tygodniu to jedna „oferta”.
    await _move(app_client, rep, first["id"], stages["qualified"])
    await _move(app_client, rep, first["id"], stages["offer-sent"])
    await _move(app_client, rep, second["id"], stages["offer-sent"])

    monday = local_day_start_utc(week_start(business_today()))
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                # Notatka ze spotkania + transkrypcja Fireflies 7 min później
                # + wydarzenie z kalendarza = jedno spotkanie.
                SalesActivity(
                    kind="meeting",
                    opportunity_id=first["id"],
                    company_id=company_id,
                    occurred_at=monday + timedelta(hours=9),
                ),
                SalesActivity(
                    kind="meeting",
                    opportunity_id=first["id"],
                    company_id=company_id,
                    occurred_at=monday + timedelta(hours=9, minutes=7),
                    external_source="fireflies",
                ),
                SalesActivity(
                    kind="meeting",
                    company_id=company_id,
                    occurred_at=monday + timedelta(hours=9, minutes=12),
                    external_source="msgraph-event",
                    created_by_user_id=rep.id,
                    subject="Spotkanie",
                ),
                # Osobne spotkanie po południu, zaplanowane (bez occurred_at).
                SalesActivity(
                    kind="meeting",
                    opportunity_id=second["id"],
                    company_id=company_id,
                    due_at=monday + timedelta(hours=14),
                ),
                # Nie liczą się: odwołane wydarzenie, telefon, spotkanie
                # przy zarchiwizowanej szansie.
                SalesActivity(
                    kind="meeting",
                    company_id=company_id,
                    occurred_at=monday + timedelta(days=1, hours=10),
                    external_source="msgraph-event",
                    created_by_user_id=rep.id,
                    subject="Anulowano: Spotkanie",
                ),
                SalesActivity(
                    kind="call",
                    opportunity_id=first["id"],
                    company_id=company_id,
                    occurred_at=monday + timedelta(days=1, hours=12),
                ),
                SalesActivity(
                    kind="meeting",
                    opportunity_id=archived["id"],
                    company_id=company_id,
                    occurred_at=monday + timedelta(days=2, hours=12),
                ),
            ]
        )
        opp = await db.get(SalesOpportunity, archived["id"])
        opp.archived_at = monday
        await db.commit()

    kpi = (await app_client.get(KPI, params={"weeks": 2}, headers=_headers(rep))).json()
    assert len(kpi["weeks"]) == 2
    this_week = _row(kpi, rep.id)["weeks"][-1]
    assert this_week["meetings"] == {"actual": 2, "target": 4, "light": "yellow"}
    assert this_week["qualified"] == {"actual": 2, "target": 3, "light": "yellow"}
    assert this_week["offers_stage"] == {"actual": 1, "target": 1, "light": "green"}
    last_week = _row(kpi, rep.id)["weeks"][0]
    assert last_week["meetings"] == {"actual": 0, "target": 4, "light": "red"}
    assert kpi["offers_history_since"] is not None


@pytest.mark.asyncio
async def test_won_net_mrr_skips_body_leasing(app_client) -> None:
    rep = await _user("sales_edit")
    stages = await _stages(app_client, rep)
    company_id = await _company(app_client, rep)
    await _opportunity(
        app_client,
        rep,
        company_id,
        stage_id=stages["won"],
        service_line="subscription",
        mrr_value="1000.00",
        margin_pct="20.00",
    )
    await _opportunity(
        app_client,
        rep,
        company_id,
        stage_id=stages["won"],
        service_line="bodyleasing",
        mrr_value="9000.00",
        margin_pct="10.00",
    )
    admin = await _user(role="admin")
    await app_client.put(
        f"{KPI}/targets/{rep.id}",
        json={"meetings": 0, "qualified": 0, "offers_stage": 0},
        headers=_headers(admin),
    )
    kpi = (await app_client.get(KPI, headers=_headers(rep))).json()
    assert Decimal(_row(kpi, rep.id)["margin_actual"]) == Decimal("200")
    today = business_today()
    months = kpi["company"]["months"]
    assert months[-1]["month"] == today.replace(day=1).isoformat()
    assert Decimal(months[-1]["cum_net_mrr"]) >= Decimal("200")
