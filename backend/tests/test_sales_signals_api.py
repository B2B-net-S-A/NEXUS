"""Kanał sygnałów z bota researchu: przyjęcie raportu z tokenem biegu i odczyty Sprzedaży."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.client import Client
from app.models.sales import (
    SalesCompany,
    SalesCompanyBriefing,
    SalesLead,
    SalesSignalRun,
)
from app.services.company_names import normalize_company_name
from app.services.sales import signals
from tests.test_sales_companies_api import _headers, _user

URL = "/api/integrations/sales-signals/runs"


async def _company(name: str, **fields) -> int:
    async with AsyncSessionLocal() as db:
        company = SalesCompany(
            name=name, normalized_name=normalize_company_name(name), **fields
        )
        db.add(company)
        await db.commit()
        return company.id


async def _run(
    company_ids: list[int], *, kind: str = "signals", **over
) -> tuple[int, str]:
    async with AsyncSessionLocal() as db:
        run, token = signals.new_run(
            kind,
            company_ids,
            now=datetime.now(timezone.utc),
            modes=over.pop("modes", None),
        )
        for key, value in over.items():
            setattr(run, key, value)
        db.add(run)
        await db.commit()
        return run.id, token


def _signal(company_id: int, tag: str, **over) -> dict:
    base = {
        "company_ref": company_id,
        "type": "program",
        "title": f"Program AI {tag}",
        "summary": "Asystent przejmuje część obsługi",
        "why_now": "Wdrożenie potrzebuje testerów",
        "url": f"https://example.com/{tag}",
        "published": (business_today() - timedelta(days=10)).isoformat(),
        "strength": "medium",
    }
    return {**base, **over}


@pytest.mark.asyncio
async def test_report_creates_leads_and_points_once(app_client) -> None:
    tag = uuid.uuid4().hex[:8]
    owner = await _user("sales_edit")
    company = await _company(f"Sygnał Bank {tag}", owner_user_id=owner.id)
    quiet = await _company(f"Cisza Sp {tag}")
    outsider = await _company(f"Obca Firma {tag}")
    run_id, token = await _run([company, quiet], modes={company: "ongoing"})

    report = {
        "checked_firms": 2,
        "signals": [
            _signal(company, tag),
            _signal(company, tag + "old", published="2025-01-01"),
            _signal(outsider, tag + "x"),
        ],
        "briefings": [
            {"company_ref": company, "points": [{"text": "Nowy dyrektor IT"}]}
        ],
        "no_signal": [quiet],
    }
    sent = await app_client.post(
        f"{URL}/{run_id}", json=report, headers={"X-Run-Token": token}
    )
    assert sent.status_code == 200, sent.text
    body = sent.json()
    assert (body["leads"], body["leads_new"], body["briefings"]) == (1, 1, 1)
    assert body["dropped"] == {
        "outside_window": 1,
        "nexus_clients": 0,
        "unknown_company": 1,
        "duplicates": 0,
    }

    async with AsyncSessionLocal() as db:
        lead = (
            await db.execute(select(SalesLead).where(SalesLead.company_id == company))
        ).scalar_one()
        assert (lead.source, lead.status, lead.score) == ("research", "new", 60)
        assert lead.assignee_user_id == owner.id
        assert lead.payload["strength"] == "medium"
        assert (
            await db.execute(select(SalesLead).where(SalesLead.company_id == outsider))
        ).first() is None
        briefing = await db.get(SalesCompanyBriefing, company)
        assert (briefing.mode, briefing.points[0]["text"]) == (
            "ongoing",
            "Nowy dyrektor IT",
        )
        run = await db.get(SalesSignalRun, run_id)
        assert (run.status, run.token_hash) == ("received", None)
        assert run.report["quiet"] == [f"Cisza Sp {tag}"]

    again = await app_client.post(
        f"{URL}/{run_id}", json=report, headers={"X-Run-Token": token}
    )
    assert again.status_code == 401  # token jest jednorazowy


@pytest.mark.asyncio
async def test_rerun_keeps_status_set_by_salesperson(app_client) -> None:
    tag = uuid.uuid4().hex[:8]
    company = await _company(f"Powtórka {tag}")
    first, token = await _run([company])
    report = {"checked_firms": 1, "signals": [_signal(company, tag)]}
    assert (
        await app_client.post(
            f"{URL}/{first}", json=report, headers={"X-Run-Token": token}
        )
    ).status_code == 200
    async with AsyncSessionLocal() as db:
        lead = (
            await db.execute(select(SalesLead).where(SalesLead.company_id == company))
        ).scalar_one()
        lead.status, lead.dismissed_reason = "dismissed", "Już wiemy"
        await db.commit()

    second, token2 = await _run([company])
    report["signals"][0]["strength"] = "strong"
    resp = await app_client.post(
        f"{URL}/{second}", json=report, headers={"X-Run-Token": token2}
    )
    assert resp.json()["leads_new"] == 0
    async with AsyncSessionLocal() as db:
        lead = (
            await db.execute(select(SalesLead).where(SalesLead.company_id == company))
        ).scalar_one()
        assert (lead.status, lead.score) == ("dismissed", 85)


@pytest.mark.asyncio
async def test_client_company_signal_is_not_a_lead(app_client) -> None:
    tag = uuid.uuid4().hex[:8]
    name = f"Klientowy Bank {tag}"
    async with AsyncSessionLocal() as db:
        db.add(Client(name=name))
        await db.commit()
    company = await _company(name)
    run_id, token = await _run([company])
    resp = await app_client.post(
        f"{URL}/{run_id}",
        json={"checked_firms": 1, "signals": [_signal(company, tag)]},
        headers={"X-Run-Token": token},
    )
    assert resp.status_code == 200, resp.text
    assert (resp.json()["leads"], resp.json()["dropped"]["nexus_clients"]) == (0, 1)


@pytest.mark.asyncio
async def test_wrong_expired_or_missing_token_gets_the_same_401(app_client) -> None:
    company = await _company(f"Token {uuid.uuid4().hex[:8]}")
    run_id, token = await _run([company])
    expired_id, expired_token = await _run(
        [company], token_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)
    )
    body = {"checked_firms": 0}
    cases = [
        (run_id, {"X-Run-Token": "zly"}),
        (run_id, {}),
        (expired_id, {"X-Run-Token": expired_token}),
        (run_id + 100_000, {"X-Run-Token": token}),
    ]
    for rid, headers in cases:
        resp = await app_client.post(f"{URL}/{rid}", json=body, headers=headers)
        assert resp.status_code == 401, (rid, resp.text)
        assert resp.json()["detail"] == signals.INVALID_TOKEN_DETAIL
    # Użytkownik z sesją nie zastąpi tokenu biegu.
    admin = await _user("sales_edit", role="admin")
    resp = await app_client.post(f"{URL}/{run_id}", json=body, headers=_headers(admin))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_sales_reads_follow_the_flag(app_client, monkeypatch) -> None:
    viewer = await _user("sales_view")
    company = await _company(f"Odczyt {uuid.uuid4().hex[:8]}", owner_user_id=viewer.id)
    run_id, token = await _run(
        [company], kind="briefing", modes={company: "first_call"}
    )
    await app_client.post(
        f"{URL}/{run_id}",
        json={
            "checked_firms": 1,
            "signals": [_signal(company, uuid.uuid4().hex[:8])],
            "briefings": [
                {"company_ref": company, "points": [{"text": "Raport roczny"}]}
            ],
        },
        headers={"X-Run-Token": token},
    )

    monkeypatch.setattr(settings, "SALES_SIGNALS_ENABLED", False)
    off = await app_client.get(
        f"/api/sales/signals/briefings/{company}", headers=_headers(viewer)
    )
    assert off.json() == {"enabled": False, "briefing": None}
    day = (await app_client.get("/api/sales/my-day", headers=_headers(viewer))).json()
    assert day["signals"] == []

    monkeypatch.setattr(settings, "SALES_SIGNALS_ENABLED", True)
    on = (
        await app_client.get(
            f"/api/sales/signals/briefings/{company}", headers=_headers(viewer)
        )
    ).json()
    assert on["briefing"]["points"][0]["text"] == "Raport roczny"
    latest = (
        await app_client.get(
            "/api/sales/signals/latest-run",
            params={"kind": "briefing"},
            headers=_headers(viewer),
        )
    ).json()
    assert latest["run"]["status"] == "received"
    assert "Inna firma" in latest["reject_reasons"]
    day = (await app_client.get("/api/sales/my-day", headers=_headers(viewer))).json()
    assert [s["company"]["id"] for s in day["signals"]] == [company]
    leads = (
        await app_client.get(
            "/api/sales/leads",
            params={"company_id": company, "source": "research"},
            headers=_headers(viewer),
        )
    ).json()
    assert (leads["total"], leads["signals_enabled"]) == (1, True)

    async with AsyncSessionLocal() as db:
        lead = (
            await db.execute(select(SalesLead).where(SalesLead.company_id == company))
        ).scalar_one()
        lead.status = "dismissed"
        await db.commit()
    only_new = (
        await app_client.get(
            "/api/sales/leads",
            params={"company_id": company, "source": "research"},
            headers=_headers(viewer),
        )
    ).json()
    every = (
        await app_client.get(
            "/api/sales/leads",
            params={
                "company_id": company,
                "source": "research",
                "all_statuses": "true",
            },
            headers=_headers(viewer),
        )
    ).json()
    assert (only_new["total"], every["total"]) == (0, 1)


@pytest.mark.asyncio
async def test_sales_reads_need_sales_view(app_client) -> None:
    stranger = await _user()
    resp = await app_client.get(
        "/api/sales/signals/latest-run", headers=_headers(stranger)
    )
    assert resp.status_code == 403
