"""Oś konsultanta (D15) — ``GET /api/care/contracts/{id}/timeline``.

Zakres: rekrutacja, z której przyszedł, start, rozmowy opieki, karta
technologiczna, opinia klienta, zamówienie z końcem i sygnał „Do przepięcia”
na jednej osi; ŻADNYCH stawek (kontrakt i zamówienie mają zmyślone kwoty, które
nie mogą wyjść w odpowiedzi); Finanse widzą oś bez opinii klienta (D11);
cudzy klient Delivery Leada i rola bez sekcji Delivery — 403.

Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import update

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today, local_now
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, RateUnit
from app.models.job import Job, JobStatus
from app.models.user import UserRole
from app.services.hr_foundation_schema import HR_MODULE_KEYS
from tests.test_care_api import (
    _previous_modules,
    headers,
    make_client,
    make_contract,
    make_user,
    set_modules,
)
from tests.test_care_client_people import add_session, make_contact

pytestmark = pytest.mark.asyncio

# Zmyślone stawki: kontrakt (``make_contract``) i zamówienie z ``_seed_history``.
RATE_VALUES = ("100.0", "130.0", "123.45", "321.99")


@pytest_asyncio.fixture
async def care_on():
    previous = await _previous_modules()
    await set_modules({key: True for key in HR_MODULE_KEYS})
    yield
    await set_modules(previous or {key: False for key in HR_MODULE_KEYS})


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


async def _seed_history(client_id: int, contract_id: int, lead_id: int) -> int:
    today = business_today()
    async with AsyncSessionLocal() as db:
        job = Job(
            title="QA Engineer (przykład)",
            status=JobStatus.published,
            client_id=client_id,
            delivery_lead_id=lead_id,
            opened_at=local_now() - timedelta(days=90),
        )
        db.add(job)
        await db.flush()
        await db.execute(
            update(Contract).where(Contract.id == contract_id).values(job_id=job.id)
        )
        db.add(
            ClientOrder(
                client_id=client_id,
                contract_id=contract_id,
                title="Zamówienie testowe 1/2026",
                status=ClientOrderStatus.active,
                start_date=today - timedelta(days=60),
                end_date=today + timedelta(days=40),
                rate_client=Decimal("321.990"),
                rate_candidate=Decimal("123.450"),
                rate_unit=RateUnit.hourly,
            )
        )
        await db.commit()
        return job.id


async def test_timeline_from_recruitment_to_orders_without_rates(
    app_client, care_on
) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    contract_id, _ = await make_contract(client_id, started_days_ago=60)
    job_id = await _seed_history(client_id, contract_id, dl.id)
    manager = await make_contact(client_id, "Michał Rogalski-Przykładowy")
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id == contract_id)
            .values(client_pm_contact_id=manager)
        )
        await db.commit()
    await add_session(
        client_id, manager, business_today() - timedelta(days=5), {contract_id: 4}
    )
    talk = await app_client.post(
        f"/api/care/contracts/{contract_id}/conversations",
        headers=headers(dl),
        json={
            "occurred_on": business_today().isoformat(),
            "channel": "phone",
            "satisfaction": 4,
            "wants_change": True,
            "note": "Chce pracy z automatyzacją testów.",
        },
    )
    assert talk.status_code == 201, talk.text

    response = await app_client.get(
        f"/api/care/contracts/{contract_id}/timeline", headers=headers(dl)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    kinds = [event["kind"] for event in body["events"]]
    for kind in (
        "recruitment",
        "start",
        "order_start",
        "conversation",
        "feedback",
        "redeploy",
        "order_end",
    ):
        assert kind in kinds, (kind, kinds)
    # Historia przed przyszłością: rekrutacja pierwsza, koniec zamówienia na końcu.
    assert kinds[0] == "recruitment"
    recruitment = body["events"][0]
    assert recruitment["title"] == "Rekrutacja „QA Engineer (przykład)”"
    assert recruitment["link"] == f"/jobs/{job_id}"
    order_end = next(e for e in body["events"] if e["kind"] == "order_end")
    assert order_end["future"] is True
    conversation = next(e for e in body["events"] if e["kind"] == "conversation")
    # Makieta P2: forma, ocena i sygnały w tytule, cytat z notatki w dopisku.
    assert conversation["title"].startswith("Rozmowa · ")
    assert "chce zmiany projektu" in conversation["title"]
    assert conversation["detail"].startswith("„")
    feedback = next(e for e in body["events"] if e["kind"] == "feedback")
    assert feedback["title"].startswith("Opinia menedżera · 4,0")
    assert feedback["detail"] == "Michał Rogalski-Przykładowy"
    assert body["manager"]["id"] == manager
    assert body["signals"] == ["wants_change"]
    assert body["front_office_reasons"] == ["wants_change"]
    assert body["feedback_visible"] is True

    # Bez stawek: żadnego pola o stawce i żadnej z zasianych kwot.
    assert not {key for key in _keys(body) if "rate" in key}
    for value in RATE_VALUES:
        assert value not in response.text


async def test_finance_timeline_without_feedback_and_refusals(
    app_client, care_on
) -> None:
    dl = await make_user(UserRole.delivery_lead)
    other_dl = await make_user(UserRole.delivery_lead)
    finance = await make_user(UserRole.finance)
    recruiter = await make_user(UserRole.recruiter)
    client_id = await make_client(dl=dl)
    contract_id, _ = await make_contract(client_id, started_days_ago=20)
    manager = await make_contact(client_id, "Anna Opiniująca")
    await add_session(
        client_id, manager, business_today() - timedelta(days=2), {contract_id: 5}
    )
    url = f"/api/care/contracts/{contract_id}/timeline"

    seen = await app_client.get(url, headers=headers(finance))
    assert seen.status_code == 200, seen.text
    assert seen.json()["feedback_visible"] is False
    assert "feedback" not in {e["kind"] for e in seen.json()["events"]}
    assert seen.json()["can_edit"] is False

    foreign = await app_client.get(url, headers=headers(other_dl))
    assert foreign.status_code == 403
    blocked = await app_client.get(url, headers=headers(recruiter))
    assert blocked.status_code == 403
    missing = await app_client.get(
        "/api/care/contracts/2000000000/timeline", headers=headers(dl)
    )
    assert missing.status_code == 404
