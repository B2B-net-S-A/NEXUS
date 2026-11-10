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
from app.services.sales.merge import merge_companies
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


def _transport(handler):
    import httpx

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_webhook_timeout_keeps_run_open_and_error_never_overwrites_report(
    monkeypatch,
) -> None:
    import httpx

    monkeypatch.setattr(settings, "GROK_BOT_WEBHOOK_URL", "https://bot.example/hook")
    monkeypatch.setattr(settings, "GROK_BOT_WEBHOOK_KEY", "test-key")
    company = await _company(f"Webhook {uuid.uuid4().hex[:8]}")

    def timeout(_request):
        raise httpx.ReadTimeout("slow")

    async with AsyncSessionLocal() as db:
        run = await signals.start_run(
            db, "signals", [company], client=_transport(timeout)
        )
        run_id = run.id
    async with AsyncSessionLocal() as db:
        stored = await db.get(SalesSignalRun, run_id)
        assert (stored.status, stored.token_hash is not None) == ("started", True)

    # Bot odpowiada szybciej niż kończy się webhook, a webhook potem pada.
    async def report_then_fail(request):
        body = __import__("json").loads(request.content)
        async with AsyncSessionLocal() as other:
            fresh = await other.get(SalesSignalRun, body["run_id"])
            await signals.ingest(
                other,
                fresh,
                signals.RunReport(checked_firms=1),
                now=datetime.now(timezone.utc),
            )
            await other.commit()
        return httpx.Response(503)

    async with AsyncSessionLocal() as db:
        run = await signals.start_run(
            db, "signals", [company], client=_transport(report_then_fail)
        )
        second_id = run.id
    async with AsyncSessionLocal() as db:
        assert (await db.get(SalesSignalRun, second_id)).status == "received"

    def refused(_request):
        return httpx.Response(503)

    async with AsyncSessionLocal() as db:
        run = await signals.start_run(
            db, "signals", [company], client=_transport(refused)
        )
        third_id = run.id
    async with AsyncSessionLocal() as db:
        third = await db.get(SalesSignalRun, third_id)
        assert (third.status, third.error, third.token_hash) == (
            "failed",
            "webhook HTTP 503",
            None,
        )


@pytest.mark.asyncio
async def test_expiry_closes_only_open_runs(app_client) -> None:
    company = await _company(f"Wygasanie {uuid.uuid4().hex[:8]}")
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    open_id, _ = await _run([company], token_expires_at=past)
    done_id, _ = await _run([company], token_expires_at=past, status="received")
    async with AsyncSessionLocal() as db:
        assert await signals.expire_runs(db, now=datetime.now(timezone.utc)) >= 1
    async with AsyncSessionLocal() as db:
        assert (await db.get(SalesSignalRun, open_id)).status == "expired"
        assert (await db.get(SalesSignalRun, done_id)).status == "received"


# ── Scalenie kart firm: punkty do rozmowy idą za firmą ───────────────────


async def _briefing(company_id: int, point: str, generated_at: datetime) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            SalesCompanyBriefing(
                company_id=company_id,
                mode="ongoing",
                points=[{"text": point}],
                generated_at=generated_at,
            )
        )
        await db.commit()


async def _briefing_after_merge(target: int, source: int) -> tuple[str, datetime]:
    async with AsyncSessionLocal() as db:
        await merge_companies(
            db,
            target=await db.get(SalesCompany, target),
            source=await db.get(SalesCompany, source),
            now=datetime.now(timezone.utc),
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        row = await db.get(SalesCompanyBriefing, target)
        assert row is not None, "docelowa karta nie ma punktów do rozmowy"
        # Jeden wiersz na firmę: przy karcie w archiwum nic nie zostaje.
        assert await db.get(SalesCompanyBriefing, source) is None
        return row.points[0]["text"], row.generated_at


@pytest.mark.asyncio
async def test_company_merge_carries_talking_points_to_a_target_without_any(
    app_client,
) -> None:
    tag = uuid.uuid4().hex[:8]
    target = await _company(f"Cel {tag}")
    source = await _company(f"Źródło {tag}")
    generated = datetime.now(timezone.utc) - timedelta(days=3)
    await _briefing(source, "Punkty źródła", generated)

    assert await _briefing_after_merge(target, source) == ("Punkty źródła", generated)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_age_days", "kept"), [(1, "Punkty źródła"), (30, "Punkty docelowej")]
)
async def test_company_merge_keeps_the_newer_talking_points(
    app_client, source_age_days: int, kept: str
) -> None:
    tag = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    target = await _company(f"Cel {tag}")
    source = await _company(f"Źródło {tag}")
    await _briefing(target, "Punkty docelowej", now - timedelta(days=10))
    await _briefing(source, "Punkty źródła", now - timedelta(days=source_age_days))

    point, generated = await _briefing_after_merge(target, source)

    assert point == kept
    assert generated == now - timedelta(days=min(source_age_days, 10))
