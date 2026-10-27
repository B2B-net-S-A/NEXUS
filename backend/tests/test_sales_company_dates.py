"""Sprzedaż: uzupełnianie dat osób z firmy (D3) — kto wchodzi do biegu i stan przy firmie."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.database import AsyncSessionLocal
from app.models.sales import SalesCompany
from app.services.company_names import normalize_company_name
from app.services.sales import company_dates
from tests.test_integrations_companies_db import _candidate
from tests.test_sales_companies_api import _headers, _user

NOW = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)


def test_needs_run_once_and_again_after_thirty_days() -> None:
    assert company_dates.needs_run(None, now=NOW)
    assert not company_dates.needs_run(
        {"status": "running", "started_at": (NOW - timedelta(minutes=5)).isoformat()},
        now=NOW,
    )
    fresh = {"status": "done", "finished_at": (NOW - timedelta(days=3)).isoformat()}
    stale = {"status": "done", "finished_at": (NOW - timedelta(days=31)).isoformat()}
    assert not company_dates.needs_run(fresh, now=NOW)
    assert company_dates.needs_run(stale, now=NOW)
    assert company_dates.needs_run({"status": "failed"}, now=NOW)


def test_run_orphaned_by_a_restart_is_not_running_forever() -> None:
    """Wdrożenie restartuje kontener w trakcie biegu — stan „running” zostaje,
    a zadania już nie ma. Bez tej reguły firma nigdy nie dostałaby dat."""
    live = {
        "status": "running",
        "started_at": (NOW - timedelta(minutes=20)).isoformat(),
    }
    orphaned = {
        "status": "running",
        "started_at": (NOW - timedelta(hours=3)).isoformat(),
    }
    assert not company_dates.needs_run(live, now=NOW)
    assert company_dates.needs_run(orphaned, now=NOW)
    assert company_dates.is_running(live, now=NOW)
    assert not company_dates.is_running(orphaned, now=NOW)
    assert not company_dates.is_running({"status": "running"}, now=NOW)
    assert company_dates.visible_state(orphaned, now=NOW)["status"] == "failed"
    assert company_dates.visible_state(live, now=NOW) == live


@pytest.mark.asyncio
async def test_run_sends_only_undated_people_and_records_the_state() -> None:
    tag = uuid.uuid4().hex[:8]
    name = f"Bocian Energia {tag}"
    async with AsyncSessionLocal() as db:
        undated = await _candidate(
            db, f"BezDat{tag}", experience=[{"company": name, "role": "Inżynier"}]
        )
        dated = await _candidate(
            db,
            f"ZDatami{tag}",
            experience=[
                {"company": name, "role": "PM", "start": "2020", "end": "2021"}
            ],
        )
        company = SalesCompany(name=name, normalized_name=normalize_company_name(name))
        db.add(company)
        await db.commit()
        company_id, undated_id, dated_id = company.id, undated.id, dated.id

    seen: list[list[int]] = []

    async def fake_backfill(db, *, candidate_ids, feature_key):
        seen.append(list(candidate_ids))
        return {"processed": len(candidate_ids), "updated": 1, "stopped_reason": "done"}

    state = await company_dates.run_company_dates(company_id, backfill=fake_backfill)
    assert seen == [[undated_id]]
    assert dated_id not in seen[0]
    assert (state["status"], state["total"], state["updated"]) == ("done", 1, 1)
    async with AsyncSessionLocal() as db:
        stored = (await db.get(SalesCompany, company_id)).dates_backfill
    assert stored["status"] == "done" and stored["finished_at"]


@pytest.mark.asyncio
async def test_failed_or_stopped_run_is_not_reported_as_done() -> None:
    tag = uuid.uuid4().hex[:8]
    name = f"Czapla Dane {tag}"
    async with AsyncSessionLocal() as db:
        await _candidate(db, f"Bez{tag}", experience=[{"company": name, "role": "QA"}])
        company = SalesCompany(name=name, normalized_name=normalize_company_name(name))
        db.add(company)
        await db.commit()
        company_id = company.id

    async def quota_out(db, *, candidate_ids, feature_key):
        return {"processed": 0, "updated": 0, "stopped_reason": "quota_exceeded"}

    async def broken(db, *, candidate_ids, feature_key):
        raise RuntimeError("model nie odpowiada")

    assert (await company_dates.run_company_dates(company_id, backfill=quota_out))[
        "status"
    ] == "partial"
    assert (await company_dates.run_company_dates(company_id, backfill=broken))[
        "status"
    ] == "failed"


@pytest.mark.asyncio
async def test_button_needs_edit_and_reports_disabled_switch(
    app_client, monkeypatch
) -> None:
    viewer = await _user("sales_view")
    rep = await _user("sales_edit")
    async with AsyncSessionLocal() as db:
        company = SalesCompany(name=f"Daty {uuid.uuid4().hex[:6]}", normalized_name="x")
        db.add(company)
        await db.commit()
        company_id = company.id
    url = f"/api/sales/companies/{company_id}/people/dates"
    assert (await app_client.post(url, headers=_headers(viewer))).status_code == 403
    # conftest wyłącza bieg w tle — odpowiedź mówi to wprost, zamiast udawać start.
    assert (await app_client.post(url, headers=_headers(rep))).status_code == 409
    monkeypatch.setattr(company_dates, "schedule_company_dates", lambda _id: True)
    ok = await app_client.post(url, headers=_headers(rep))
    assert ok.json()["scheduled"] is True
