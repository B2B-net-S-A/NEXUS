"""„Warto wrócić” (G-E) i „Nowe centra IT” (G-D) z bazą: wybór firm, raport, decyzje.

Baza testowa jest wspólna dla przebiegu: każdy test ma własne firmy i konta
i patrzy tylko na nie.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.sales import (
    SalesBotResult,
    SalesCompany,
    SalesLead,
    SalesOpportunity,
    SalesOpportunityEvent,
)
from app.services.sales import signal_targets as targets
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_factories import MAP_DONE, _stage_ids
from tests.test_sales_offers import _stage
from tests.test_sales_signals_api import URL, _company, _run

LEADS = "/api/sales/leads"
RESULTS = "/api/sales/bot-results"
REASON = targets.WINBACK_LOST_REASONS[0]


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _lost(
    company_id: int,
    *,
    owner_id: Optional[int] = None,
    reason: str = REASON,
    days_ago: int = 60,
    status: str = "lost",
) -> int:
    pipeline_id, stage_id = await _stage("offer-sent")
    async with AsyncSessionLocal() as db:
        opportunity = SalesOpportunity(
            company_id=company_id,
            pipeline_id=pipeline_id,
            stage_id=stage_id,
            title=f"Przegrana {uuid.uuid4().hex[:6]}",
            owner_user_id=owner_id,
            status=status,
            lost_reason=reason if status == "lost" else None,
            lost_at=_now() - timedelta(days=days_ago) if status == "lost" else None,
        )
        db.add(opportunity)
        await db.commit()
        return opportunity.id


def _signal(company_id: int, tag: str, **over: Any) -> dict:
    return {
        "company_ref": company_id,
        "type": "program",
        "title": f"Nowy program {tag}",
        "summary": "Przenoszą aplikacje do chmury",
        "why_now": "Program potrzebuje zespołu",
        "url": f"https://example.com/winback/{tag}",
        "published": (business_today() - timedelta(days=5)).isoformat(),
        "strength": "medium",
        **over,
    }


@pytest.mark.asyncio
async def test_winback_targets_only_lost_with_reason_and_nothing_open() -> None:
    tag = uuid.uuid4().hex[:8]
    good = await _company(f"Powrót {tag}")
    other_reason = await _company(f"Inny powód {tag}")
    still_open = await _company(f"Otwarta {tag}")
    too_old = await _company(f"Stara {tag}")
    archived = await _company(f"Archiwum {tag}", archived_at=_now())
    deal = await _lost(good, days_ago=30)
    await _lost(good, days_ago=200)  # starsza przegrana tej samej firmy
    await _lost(other_reason, reason="Wybrali konkurencję")
    await _lost(still_open)
    await _lost(still_open, status="open")
    await _lost(too_old, days_ago=14 * 31 + 5)
    await _lost(archived)

    async with AsyncSessionLocal() as db:
        deals = await targets.winback_deals(
            db,
            now=_now(),
            company_ids=[good, other_reason, still_open, too_old, archived],
        )
    assert list(deals) == [good]
    assert deals[good].opportunity_id == deal
    assert deals[good].lost_reason == REASON


@pytest.mark.asyncio
async def test_winback_report_becomes_a_lead_and_take_over(
    app_client, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    tag = uuid.uuid4().hex[:8]
    gone = await _user()  # bez uprawnień Sprzedaży: „nie pracuje w Sprzedaży”
    company = await _company(f"Wróć {tag}", owner_user_id=gone.id)
    lost_id = await _lost(company, owner_id=gone.id)
    run_id, token = await _run([company], kind="winback")

    sent = await app_client.post(
        f"{URL}/{run_id}",
        json={"checked_firms": 1, "signals": [_signal(company, tag)], "no_signal": []},
        headers={"X-Run-Token": token},
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["leads_new"] == 1

    viewer = await _user("sales_view")
    listed = (
        await app_client.get(
            LEADS,
            params={"origin": "winback", "company_id": company, "all_statuses": True},
            headers=_headers(viewer),
        )
    ).json()
    assert listed["bot_tasks_enabled"] is True
    [lead] = listed["items"]
    assert lead["payload"]["origin"] == "winback"
    assert lead["payload"]["lost_opportunity_id"] == lost_id
    assert lead["payload"]["lost_reason"] == REASON
    assert lead["assignee"] is None and lead["assignee_in_sales"] is False

    # Sygnały bota („grok”) nie pokazują leadów „Warto wrócić”.
    grok = (
        await app_client.get(
            LEADS,
            params={"origin": "grok", "company_id": company, "all_statuses": True},
            headers=_headers(viewer),
        )
    ).json()
    assert grok["items"] == []

    assert (
        await app_client.post(
            f"{LEADS}/{lead['id']}/take-over", headers=_headers(viewer)
        )
    ).status_code == 403
    editor = await _user("sales_edit")
    taken = await app_client.post(
        f"{LEADS}/{lead['id']}/take-over", headers=_headers(editor)
    )
    assert taken.status_code == 200, taken.text
    assert taken.json()["assignee"]["id"] == editor.id
    assert taken.json()["assignee_in_sales"] is True

    # Lead ma już osobę w Sprzedaży: drugi handlowiec go nie zabierze.
    other = await _user("sales_edit")
    refused = await app_client.post(
        f"{LEADS}/{lead['id']}/take-over", headers=_headers(other)
    )
    assert refused.status_code == 409


@pytest.mark.asyncio
async def test_winback_lead_goes_to_the_company_owner_in_sales(
    app_client, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    tag = uuid.uuid4().hex[:8]
    owner = await _user("sales_edit")
    deal_owner = await _user("sales_edit")
    company = await _company(f"Opiekun {tag}", owner_user_id=owner.id)
    await _lost(company, owner_id=deal_owner.id)
    run_id, token = await _run([company], kind="winback")
    sent = await app_client.post(
        f"{URL}/{run_id}",
        json={"checked_firms": 1, "signals": [_signal(company, tag)]},
        headers={"X-Run-Token": token},
    )
    assert sent.status_code == 200, sent.text
    async with AsyncSessionLocal() as db:
        lead = await db.scalar(select(SalesLead).where(SalesLead.company_id == company))
    assert lead.assignee_user_id == owner.id


@pytest.mark.asyncio
async def test_discovery_results_and_account_in_it_factories(
    app_client, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    pipeline_id, stages = await _stage_ids()
    tag = uuid.uuid4().hex[:8]
    known = await _company(f"Znane Centrum {tag}", domain=f"znane-{tag}.pl")
    run_id, token = await _run([], kind="discovery")
    published = (business_today() - timedelta(days=20)).isoformat()
    report = {
        "items": [
            {
                "company": f"Znane Centrum {tag} Polska",
                "domain": f"https://www.znane-{tag}.pl",
                "city": "Kraków",
                "what": "Rozbudowa centrum R&D",
                "url": f"https://example.com/d/{tag}/1",
                "published": published,
            },
            {
                "company": f"Nowe Centrum {tag}",
                "city": "Wrocław",
                "what": "Nowe centrum usług IT",
                "scale": "200 miejsc pracy",
                "why": "Buduje zespół od zera",
                "url": f"https://example.com/d/{tag}/2",
                "published": published,
            },
            {
                "company": f"Stare Centrum {tag}",
                "what": "Otwarcie biura",
                "url": f"https://example.com/d/{tag}/3",
                "published": (business_today() - timedelta(days=400)).isoformat(),
            },
        ]
    }
    sent = await app_client.post(
        f"{URL}/{run_id}", json=report, headers={"X-Run-Token": token}
    )
    assert sent.status_code == 200, sent.text
    body = sent.json()
    assert (body["results"], body["in_base"], body["dropped"]["outside_window"]) == (
        2,
        1,
        1,
    )

    editor = await _user("sales_edit")
    items = (
        await app_client.get(
            RESULTS,
            params={"kind": "discovery", "limit": 200},
            headers=_headers(editor),
        )
    ).json()["items"]
    mine = {
        item["payload"]["company"]: item
        for item in items
        if tag in item["payload"]["company"]
    }
    matched = mine[f"Znane Centrum {tag} Polska"]
    fresh = mine[f"Nowe Centrum {tag}"]
    assert matched["company"]["id"] == known
    assert matched["payload"]["match"] == "domain"
    assert fresh["company"] is None

    accepted = await app_client.post(
        f"{RESULTS}/{fresh['id']}/accept", headers=_headers(editor)
    )
    assert accepted.status_code == 200, accepted.text
    outcome = accepted.json()
    assert outcome["company_created"] is True and outcome["existed"] is False
    async with AsyncSessionLocal() as db:
        card = await db.get(SalesCompany, outcome["company_id"])
        opportunity = await db.get(SalesOpportunity, outcome["opportunity_id"])
        events = (
            await db.scalars(
                select(SalesOpportunityEvent).where(
                    SalesOpportunityEvent.opportunity_id == opportunity.id
                )
            )
        ).all()
        result = await db.get(SalesBotResult, fresh["id"])
    assert (card.name, card.hq_city, card.owner_user_id) == (
        f"Nowe Centrum {tag}",
        "Wrocław",
        editor.id,
    )
    assert opportunity.pipeline_id == pipeline_id
    assert opportunity.owner_user_id == editor.id
    assert opportunity.stage_id == stages[MAP_DONE] or opportunity.status == "open"
    assert events, "założenie szansy idzie do historii"
    assert (result.status, result.decided_by_user_id, result.company_id) == (
        "accepted",
        editor.id,
        card.id,
    )

    again = await app_client.post(
        f"{RESULTS}/{fresh['id']}/accept", headers=_headers(editor)
    )
    assert again.status_code == 409

    # Karta ma już otwarte konto w lejku: drugiego nie zakładamy.
    async with AsyncSessionLocal() as db:
        db.add(
            SalesOpportunity(
                company_id=known,
                pipeline_id=pipeline_id,
                stage_id=stages[MAP_DONE],
                title="Konto",
            )
        )
        await db.commit()
    existed = await app_client.post(
        f"{RESULTS}/{matched['id']}/accept", headers=_headers(editor)
    )
    assert existed.status_code == 200, existed.text
    assert existed.json()["existed"] is True
    assert existed.json()["company_id"] == known


@pytest.mark.asyncio
async def test_discovery_reject_and_flag_off(app_client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    tag = uuid.uuid4().hex[:8]
    run_id, token = await _run([], kind="discovery")
    sent = await app_client.post(
        f"{URL}/{run_id}",
        json={
            "items": [
                {
                    "company": f"Odrzucone Centrum {tag}",
                    "what": "Nowe biuro",
                    "url": f"https://example.com/r/{tag}",
                    "published": business_today().isoformat(),
                }
            ]
        },
        headers={"X-Run-Token": token},
    )
    assert sent.status_code == 200, sent.text
    editor = await _user("sales_edit")
    async with AsyncSessionLocal() as db:
        result_id = await db.scalar(
            select(SalesBotResult.id).where(SalesBotResult.run_id == run_id)
        )
    rejected = await app_client.post(
        f"{RESULTS}/{result_id}/reject",
        json={"reason": "Nie nasza usługa"},
        headers=_headers(editor),
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"

    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", False)
    off = (await app_client.get(RESULTS, headers=_headers(editor))).json()
    assert off == {"enabled": False, "items": []}
    leads = (
        await app_client.get(LEADS, params={"limit": 1}, headers=_headers(editor))
    ).json()
    assert leads["bot_tasks_enabled"] is False
