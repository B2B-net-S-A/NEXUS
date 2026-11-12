"""Haczyk i teczka z bazą: przyjęcie haczyków, odczyt na karcie i wybór firm.

Baza testowa jest wspólna dla przebiegu, więc testy wyboru patrzą tylko na własne
firmy. Dane są fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.sales import (
    SalesActivity,
    SalesBotResult,
    SalesCompanyBriefing,
)
from app.services.sales import calling, hook_prep_targets, my_day
from tests.test_sales_calling_queue import _campaign, _record
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_signals_api import URL, _company, _run


def _hook(company: int, tag: str) -> dict:
    return {
        "company_ref": company,
        "sentence": f"Gratuluję wdrożenia asystenta {tag}.",
        "facts": [
            {
                "text": "Firma uruchomiła asystenta AI w obsłudze klienta",
                "url": f"https://example.com/{tag}",
                "published": (business_today() - timedelta(days=20)).isoformat(),
            }
        ],
    }


@pytest.mark.asyncio
async def test_hook_lands_in_bot_results_and_never_overwrites_points(
    app_client, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "SALES_SIGNALS_ENABLED", True)
    tag = uuid.uuid4().hex[:8]
    viewer = await _user("sales_view")
    hooked = await _company(f"Haczyk {tag}")
    prepped = await _company(f"Teczka {tag}")
    async with AsyncSessionLocal() as db:
        db.add(
            SalesCompanyBriefing(
                company_id=hooked,
                mode="ongoing",
                points=[{"text": "Punkt do szansy", "url": None, "published": None}],
                generated_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
    run_id, token = await _run(
        [hooked, prepped],
        kind="briefing",
        modes={hooked: "call_hook", prepped: "meeting_prep"},
    )
    sent = await app_client.post(
        f"{URL}/{run_id}",
        json={
            "checked_firms": 2,
            "briefings": [
                {"company_ref": hooked, "points": [{"text": "Nadpisałby punkty"}]},
                {"company_ref": prepped, "points": [{"text": "Nowy program IT"}]},
            ],
            "hooks": [_hook(hooked, tag), _hook(prepped, tag)],
        },
        headers={"X-Run-Token": token},
    )
    assert sent.status_code == 200, sent.text
    body = sent.json()
    assert (body["briefings"], body["hooks"], body["hooks_dropped"]) == (1, 1, 1)

    async with AsyncSessionLocal() as db:
        kept = await db.get(SalesCompanyBriefing, hooked)
        assert (kept.mode, kept.points[0]["text"]) == ("ongoing", "Punkt do szansy")
        prep = await db.get(SalesCompanyBriefing, prepped)
        assert prep.mode == "meeting_prep"
        hooks = (
            (
                await db.execute(
                    select(SalesBotResult).where(
                        SalesBotResult.company_id.in_([hooked, prepped])
                    )
                )
            )
            .scalars()
            .all()
        )
        assert [(row.kind, row.company_id, row.status) for row in hooks] == [
            ("call_hook", hooked, "new")
        ]
        assert hooks[0].payload["facts"][0]["url"] == f"https://example.com/{tag}"
        fresh = await hook_prep_targets.call_hook.fresh_company_ids(
            db, now=datetime.now(timezone.utc)
        )
        assert hooked in fresh and prepped not in fresh

    path = f"/api/sales/signals/briefings/{hooked}"
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", False)
    off = (await app_client.get(path, headers=_headers(viewer))).json()
    assert off["call_hook"] is None and off["briefing"]["mode"] == "ongoing"
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    on = (await app_client.get(path, headers=_headers(viewer))).json()
    assert on["call_hook"]["sentence"] == f"Gratuluję wdrożenia asystenta {tag}."
    assert on["call_hook"]["facts"][0]["published"]
    nobody = await _user()
    assert (await app_client.get(path, headers=_headers(nobody))).status_code == 403


@pytest.mark.asyncio
async def test_queue_companies_due_next_business_day_take_turns_per_person() -> None:
    first = await _user("sales_edit")
    second = await _user("sales_edit")
    campaign = await _campaign()
    today = business_today()
    day = calling.next_business_day(today)
    names = ("due", "later", "today", "new-a1", "new-a2", "new-b1", "skipped")
    ids = {name: await _company(f"Plan {name}") for name in names}
    await _record(first.id, campaign, ids["due"], state="call_back", callback_on=day)
    await _record(
        first.id,
        campaign,
        ids["later"],
        state="call_back",
        callback_on=day + timedelta(days=7),
    )
    await _record(
        first.id, campaign, ids["today"], state="no_answer", callback_on=today
    )
    await _record(first.id, campaign, ids["new-a1"])
    await _record(first.id, campaign, ids["new-a2"])
    await _record(second.id, campaign, ids["skipped"])
    await _record(second.id, campaign, ids["new-b1"])

    async with AsyncSessionLocal() as db:
        chosen = await calling.companies_due_by(
            db, day, today, exclude={ids["skipped"]}, limit=10_000
        )
    mine = [cid for cid in chosen if cid in ids.values()]
    assert mine[0] == ids["due"]
    assert ids["later"] not in mine and ids["today"] not in mine
    assert ids["skipped"] not in mine
    # Nowe rekordy po kolei od każdej osoby: pierwszy pierwszej, pierwszy drugiej, ...
    assert [cid for cid in mine[1:]] == [ids["new-a1"], ids["new-b1"], ids["new-a2"]]


@pytest.mark.asyncio
async def test_meeting_companies_tomorrow_skip_automats_and_other_days() -> None:
    owner = await _user("sales_edit")
    today = business_today()
    start, end = hook_prep_targets.prep_window(today)
    inside = await _company("Spotkanie jutro")
    automat = await _company("Automat jutro")
    outside = await _company("Spotkanie później")
    async with AsyncSessionLocal() as db:
        for company, subject, at in (
            (inside, "Spotkanie kwalifikujące", start + timedelta(hours=10)),
            (automat, "Accepted: Spotkanie", start + timedelta(hours=11)),
            (outside, "Spotkanie", end + timedelta(hours=10)),
        ):
            db.add(
                SalesActivity(
                    kind="meeting",
                    company_id=company,
                    subject=subject,
                    occurred_at=at,
                    created_by_user_id=owner.id,
                )
            )
        await db.commit()
        ids = await my_day.meeting_company_ids(db, start, end)
    assert inside in ids
    assert automat not in ids and outside not in ids
