"""Teczka leada z bazą: zamówienie biegów w tle i pole ``dossier`` listy leadów.

Baza testowa jest wspólna dla przebiegu, więc zamówienie liczy się w chwili daleko
w przyszłości (``_later()``): biegi innych testów nie wpadają w okna 1 godziny
i 7 dni, a każdy test zawęża firmy do własnych (``company_ids``).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import delete, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.sales import (
    SalesBotResult,
    SalesCompanyBriefing,
    SalesCompanyContact,
    SalesContact,
    SalesLead,
    SalesSignalRun,
)
from app.services.sales import lead_dossier, signals
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_signals_api import _company

LEADS = "/api/sales/leads"


def _later() -> datetime:
    """Chwila daleko w przyszłości, liczona w teście (nie przy imporcie modułu)."""

    return datetime.now(timezone.utc) + timedelta(days=400)


@pytest_asyncio.fixture(autouse=True)
async def _forget_the_future() -> AsyncIterator[None]:
    """Biegi, leady i punkty z przyszłości znikają: inne testy czytają „ostatni bieg”."""

    yield
    future = _later() - timedelta(days=30)
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(SalesSignalRun).where(SalesSignalRun.started_at > future)
        )
        await db.execute(delete(SalesLead).where(SalesLead.created_at > future))
        await db.execute(
            delete(SalesCompanyBriefing).where(
                SalesCompanyBriefing.generated_at > future
            )
        )
        await db.commit()


async def _lead(
    company_id: int | None, *, at: datetime | None = None, **over: Any
) -> int:
    tag = uuid.uuid4().hex
    at = at or _later()
    async with AsyncSessionLocal() as db:
        lead = SalesLead(
            source=over.pop("source", "manual"),
            title=f"Lead {tag[:6]}",
            company_name=f"Firma {tag[:6]}",
            company_id=company_id,
            fingerprint=f"test-dossier|{tag}",
            created_at=at - timedelta(hours=1),
            **over,
        )
        db.add(lead)
        await db.commit()
        return lead.id


def _capture(monkeypatch, calls: list) -> None:
    """``start_run`` bez webhooka: zapisuje bieg jak prawdziwy, żeby blokady go widziały."""

    async def start(db, kind, ids, *, now, modes=None, **_k):
        calls.append((kind, list(ids), dict(modes or {})))
        run, _token = signals.new_run(kind, list(ids), now=now, modes=modes)
        db.add(run)
        await db.commit()
        return run

    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    monkeypatch.setattr(lead_dossier.signals, "start_run", start)


@pytest.mark.asyncio
async def test_new_lead_orders_three_runs_once_per_company(monkeypatch) -> None:
    calls: list = []
    _capture(monkeypatch, calls)
    company = await _company(f"Teczka {uuid.uuid4().hex[:8]}", domain="teczka.example")
    await _lead(company)

    async with AsyncSessionLocal() as db:
        done = await lead_dossier.order(db, now=_later(), company_ids=[company])
    assert done == {"enrich": 1, "people": 1, "briefing": 1}
    assert [(kind, ids) for kind, ids, _ in calls] == [
        ("enrich", [company]),
        ("people", [company]),
        ("briefing", [company]),
    ]
    assert calls[2][2] == {company: "first_call"}

    # Drugi lead tej samej firmy po dwóch godzinach: teczka już zamówiona.
    calls.clear()
    later = _later() + timedelta(hours=2)
    await _lead(company, at=later)
    async with AsyncSessionLocal() as db:
        assert await lead_dossier.order(db, now=later, company_ids=[company]) == {
            "enrich": 0,
            "people": 0,
            "briefing": 0,
        }
    assert calls == []


@pytest.mark.asyncio
async def test_people_and_points_wait_for_company_data_without_domain(
    monkeypatch,
) -> None:
    calls: list = []
    _capture(monkeypatch, calls)
    company = await _company(f"Bez domeny {uuid.uuid4().hex[:8]}")
    await _lead(company)
    now = _later() + timedelta(days=1)

    async with AsyncSessionLocal() as db:
        await lead_dossier.order(db, now=now, company_ids=[company])
    assert [kind for kind, _, _ in calls] == ["enrich"]

    # Bot odesłał Dane firm: przy następnym obrocie idą Kontakty i Research.
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(SalesSignalRun)
            .where(SalesSignalRun.kind == "enrich", SalesSignalRun.started_at == now)
            .values(status="received", received_at=now)
        )
        await db.commit()
    calls.clear()
    later = now + timedelta(hours=1, minutes=5)
    async with AsyncSessionLocal() as db:
        await lead_dossier.order(db, now=later, company_ids=[company])
    assert [kind for kind, _, _ in calls] == ["people", "briefing"]


@pytest.mark.asyncio
async def test_nexus_client_do_not_contact_and_no_card_get_nothing(monkeypatch) -> None:
    calls: list = []
    _capture(monkeypatch, calls)
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Klient teczki {tag}")
        db.add(client)
        await db.commit()
        client_id = client.id
    client_company = await _company(f"Klient teczki {tag}", client_id=client_id)
    blocked = await _company(f"Zablokowana {tag}", status="do_not_contact")
    await _lead(client_company)
    await _lead(blocked)
    await _lead(None)
    now = _later() + timedelta(days=2)

    async with AsyncSessionLocal() as db:
        done = await lead_dossier.order(
            db, now=now, company_ids=[client_company, blocked]
        )
    assert done == {"enrich": 0, "people": 0, "briefing": 0}
    assert calls == []


@pytest.mark.asyncio
async def test_waiting_people_result_and_fresh_points_block_their_kind(
    monkeypatch,
) -> None:
    calls: list = []
    _capture(monkeypatch, calls)
    now = _later() + timedelta(days=3)
    company = await _company(f"Czeka {uuid.uuid4().hex[:8]}", domain="czeka.example")
    await _lead(company, at=now)
    async with AsyncSessionLocal() as db:
        run, _ = signals.new_run(
            "people", [company], now=now - timedelta(days=10), requested_by_user_id=None
        )
        run.status = "received"
        db.add(run)
        await db.flush()
        db.add(
            SalesBotResult(
                run_id=run.id, kind="people", company_id=company, status="new"
            )
        )
        db.add(
            SalesCompanyBriefing(
                company_id=company,
                mode="first_call",
                points=[{"text": "Nowy program"}],
                generated_at=now - timedelta(days=2),
            )
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        await lead_dossier.order(db, now=now, company_ids=[company])
    assert [kind for kind, _, _ in calls] == ["enrich"]


@pytest.mark.asyncio
async def test_lead_list_carries_the_company_dossier(app_client) -> None:
    viewer = await _user("sales_view")
    tag = uuid.uuid4().hex[:8]
    company = await _company(
        f"Odczyt teczki {tag}",
        owner_user_id=viewer.id,
        industry="Bankowość",
        hq_city="Warszawa",
        nip="5261021021",
        website_url="https://www.teczka-odczyt.example/o-nas",
    )
    empty = await _company(f"Pusta teczka {tag}")
    async with AsyncSessionLocal() as db:
        people = [
            SalesContact(
                company_id=company,
                full_name="Osoba A",
                title="CTO",
                email="a@x.example",
            ),
            SalesContact(company_id=company, full_name="Osoba B", title="Head of Data"),
            SalesContact(
                company_id=company,
                full_name="Osoba C",
                title="Prezes Zarządu",
                email="c@x.example",
                do_not_contact_at=datetime.now(timezone.utc),
            ),
            SalesContact(company_id=company, full_name="Osoba D", title="Analityk"),
            SalesContact(
                company_id=company,
                full_name="Osoba E",
                title="Director of IT",
                archived_at=datetime.now(timezone.utc),
            ),
            # Osoba z inną firmą główną, ale z bieżącym stanowiskiem w tej.
            SalesContact(company_id=empty, full_name="Osoba F", email="f@x.example"),
        ]
        db.add_all(people)
        await db.flush()
        db.add(
            SalesCompanyContact(
                company_id=company, contact_id=people[-1].id, title="VP Engineering"
            )
        )
        db.add(
            SalesCompanyBriefing(
                company_id=company,
                mode="first_call",
                points=[{"text": "Jeden"}, {"text": "Dwa"}, {"text": "Trzy"}],
            )
        )
        await db.commit()
    await _lead(company, at=datetime.now(timezone.utc))
    await _lead(empty, at=datetime.now(timezone.utc), source="research")

    by_company = {}
    for company_id in (company, empty):
        resp = await app_client.get(
            LEADS,
            params={"company_id": company_id, "all_statuses": True},
            headers=_headers(viewer),
        )
        assert resp.status_code == 200, resp.text
        by_company[company_id] = resp.json()["items"][0]
    dossier = by_company[company]["dossier"]
    assert dossier["industry"] == "Bankowość" and dossier["city"] == "Warszawa"
    assert dossier["nip"] == "5261021021"
    assert dossier["website"] == "teczka-odczyt.example"
    assert dossier["owner"] == viewer.name
    # A, B, C, D i F (E w archiwum); e-mail: A i F (C nie chce kontaktu).
    assert (dossier["known"], dossier["known_with_email"]) == (5, 2)
    assert dossier["decision_makers"] == ["CTO", "VP Engineering", "Head of Data"]
    assert dossier["points"] == 3 and dossier["points_at"]
    # Karta z samą osobą z innej firmy głównej ma teczkę („Znamy: 1”).
    assert by_company[empty]["dossier"]["known"] == 1


@pytest.mark.asyncio
async def test_lead_without_card_or_data_has_no_dossier(app_client) -> None:
    viewer = await _user("sales_view")
    tag = uuid.uuid4().hex[:8]
    bare = await _company(f"Goła karta {tag}")
    await _lead(bare, at=datetime.now(timezone.utc))
    async with AsyncSessionLocal() as db:
        lead = SalesLead(
            source="manual",
            title=f"Bez karty {tag}",
            company_name=f"Bez karty {tag}",
            fingerprint=f"test-dossier|{tag}",
        )
        db.add(lead)
        await db.commit()

    items = []
    for params in ({"company_id": bare}, {"q": f"Bez karty {tag}"}):
        resp = await app_client.get(
            LEADS, params={**params, "all_statuses": True}, headers=_headers(viewer)
        )
        assert resp.status_code == 200, resp.text
        items += resp.json()["items"]
    assert len(items) == 2 and all(item["dossier"] is None for item in items)
