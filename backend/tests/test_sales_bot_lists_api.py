"""Bot Listy z bazą (decyzje Artura 13.11.2026): brief, budowa listy, dosypka.

Baza testowa jest wspólna, więc segment to unikalne słowo w branży kart z testu
(``include_unknown=False``): bot widzi tylko firmy tego testu. Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.sales import SalesCallRecord
from tests.test_sales_calling_queue import _campaign, _company, _contact, _record
from tests.test_sales_companies_api import _headers, _user

URL = "/api/sales/bot-lists"


async def _segment(tag: str) -> dict[str, int]:
    """Pięć firm z Managerem/Headem, jedna dzwoniona niedawno, jedna z samym prezesem."""

    ids: dict[str, int] = {}
    for index in range(5):
        company = await _company(f"Segment {index}", industry=f"bankowość {tag}")
        await _contact(
            company,
            full_name=f"Osoba {index}",
            title="IT Manager" if index % 2 else "Head of IT",
            phone=f"600 200 {300 + index}",
        )
        ids[f"ok{index}"] = company
    called = await _company("Dzwoniona", industry=f"bankowość {tag}")
    await _contact(called, full_name="Osoba X", title="IT Manager", phone="600 200 399")
    ids["called"] = called
    board = await _company("Zarząd", industry=f"bankowość {tag}")
    await _contact(
        board, full_name="Osoba Y", title="Prezes Zarządu", phone="600 200 398"
    )
    ids["board"] = board
    return ids


@pytest.mark.asyncio
async def test_brief_and_build_split_the_list_between_callers(
    app_client, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "SALES_BOT_LISTS_ENABLED", True)
    tag = uuid.uuid4().hex[:8]
    editor = await _user("sales_edit")
    first = await _user("sales_edit")
    second = await _user("sales_edit")
    viewer = await _user("sales_view")
    ids = await _segment(tag)
    campaign = await _campaign("Bot Listy")
    # Firma dzwoniona 10 dni temu w innej kampanii nie wraca na listę.
    other = await _campaign("Stara")
    await _record(first.id, other, ids["called"], state="no_answer")

    brief = {
        "roles": ["manager", "head"],
        "industries": [tag],
        "include_unknown": False,
        "per_caller": 2,
        "caller_ids": [first.id, second.id],
    }
    assert (
        await app_client.put(
            f"{URL}/campaigns/{campaign}/brief", json=brief, headers=_headers(viewer)
        )
    ).status_code == 403
    saved = await app_client.put(
        f"{URL}/campaigns/{campaign}/brief", json=brief, headers=_headers(editor)
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["brief"]["per_caller"] == 2

    built = await app_client.post(
        f"{URL}/campaigns/{campaign}/build", headers=_headers(editor)
    )
    assert built.status_code == 200, built.text
    body = built.json()
    assert body["added"] == 4
    assert body["per_caller"] == {str(first.id): 2, str(second.id): 2}
    async with AsyncSessionLocal() as db:
        records = (
            (
                await db.execute(
                    select(SalesCallRecord).where(
                        SalesCallRecord.campaign_id == campaign
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(records) == 4
    assert {r.company_id for r in records} <= {ids[f"ok{i}"] for i in range(5)}
    assert all(r.contact_source == "Bot Listy · baza NEXUSA" for r in records)
    assert all((r.note or "").startswith("Bot Listy:") for r in records)

    # Druga budowa w tym samym tygodniu: paczka pełna, nic nie dochodzi.
    again = await app_client.post(
        f"{URL}/campaigns/{campaign}/build", headers=_headers(editor)
    )
    assert again.json()["added"] == 0

    state = await app_client.get(
        f"{URL}/campaigns/{campaign}", headers=_headers(viewer)
    )
    assert state.status_code == 200
    assert state.json()["built_at"] is not None


@pytest.mark.asyncio
async def test_refill_tops_up_to_the_batch_after_calls(app_client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "SALES_BOT_LISTS_ENABLED", True)
    tag = uuid.uuid4().hex[:8]
    caller = await _user("sales_edit")
    await _segment(tag)
    campaign = await _campaign("Dosypka")
    brief = {
        "industries": [tag],
        "include_unknown": False,
        "per_caller": 2,
        "caller_ids": [caller.id],
    }
    resp = await app_client.put(
        f"{URL}/campaigns/{campaign}/brief", json=brief, headers=_headers(caller)
    )
    assert resp.status_code == 200, resp.text
    from app.services.sales import bot_lists
    from app.models.sales import SalesCallCampaign

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        assert await bot_lists.refill_campaigns(db, now=now) >= 2
        rows = (
            (
                await db.execute(
                    select(SalesCallRecord).where(
                        SalesCallRecord.campaign_id == campaign
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2
        # Osoba obdzwoniła jeden rekord: za tydzień dosypka do dwóch nowych.
        rows[0].state = "no_answer"
        await db.commit()
        row = await db.get(SalesCallCampaign, campaign)
        week_later = now + timedelta(days=7)
        assert await bot_lists.refill_campaigns(db, now=week_later) >= 1
        new = (
            (
                await db.execute(
                    select(SalesCallRecord).where(
                        SalesCallRecord.campaign_id == campaign,
                        SalesCallRecord.state == "new",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(new) == 2 and row is not None


@pytest.mark.asyncio
async def test_brief_refusals(app_client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "SALES_BOT_LISTS_ENABLED", True)
    editor = await _user("sales_edit")
    campaign = await _campaign("Odmowy")
    bad_pkd = await app_client.put(
        f"{URL}/campaigns/{campaign}/brief",
        json={"caller_ids": [editor.id], "pkd": ["abc"]},
        headers=_headers(editor),
    )
    assert bad_pkd.status_code == 422
    assert "PKD" in bad_pkd.json()["detail"]
    missing = await app_client.put(
        f"{URL}/campaigns/{campaign}/brief",
        json={"caller_ids": [999999999]},
        headers=_headers(editor),
    )
    assert missing.status_code == 422
    no_brief = await app_client.post(
        f"{URL}/campaigns/{campaign}/build", headers=_headers(editor)
    )
    assert no_brief.status_code == 409
    monkeypatch.setattr(settings, "SALES_BOT_LISTS_ENABLED", False)
    off = await app_client.post(
        f"{URL}/campaigns/{campaign}/build", headers=_headers(editor)
    )
    assert off.status_code == 409


@pytest.mark.asyncio
async def test_bot_report_lands_in_the_campaign_through_import_gates(
    app_client, monkeypatch
) -> None:
    """L3: raport ``lists`` (rejestr.io) trafia do kampanii od razu, przez bramki importu."""

    from tests.test_sales_signals_api import URL as RUNS
    from tests.test_sales_signals_api import _run

    monkeypatch.setattr(settings, "SALES_BOT_LISTS_ENABLED", True)
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    caller = await _user("sales_edit")
    campaign = await _campaign("Rejestr")
    brief = {
        "sources": ["rejestr"],
        "roles": ["manager"],
        "per_caller": 3,
        "caller_ids": [caller.id],
    }
    resp = await app_client.put(
        f"{URL}/campaigns/{campaign}/brief", json=brief, headers=_headers(caller)
    )
    assert resp.status_code == 200, resp.text
    tag = uuid.uuid4().hex[:8]
    run_id, token = await _run([], kind="lists", request={"campaign_id": campaign})
    src = "https://rejestr.example/firma"
    report = {
        "firms": [
            {
                "company": f"Rejestr A {tag}",
                "phone": "22 123 45 67",
                "phone_source": src,
                "pkd": "64.19.Z",
                "source": "rejestr",
                "source_url": src,
            },
            {
                "company": f"Rejestr B {tag}",
                "phone": "22 765 43 21",
                "source": "rejestr",
                "source_url": src,
            },
        ]
    }
    sent = await app_client.post(
        f"{RUNS}/{run_id}", json=report, headers={"X-Run-Token": token}
    )
    assert sent.status_code == 200, sent.text
    async with AsyncSessionLocal() as db:
        records = (
            (
                await db.execute(
                    select(SalesCallRecord).where(
                        SalesCallRecord.campaign_id == campaign
                    )
                )
            )
            .scalars()
            .all()
        )
    # Firma B nie ma telefonu ze źródłem: bramka „brak telefonu”.
    assert len(records) == 1
    assert records[0].contact_source == "Bot Listy · rejestr.io"
    assert records[0].assigned_user_id == caller.id
    assert "PKD 64.19.Z" in (records[0].note or "")
