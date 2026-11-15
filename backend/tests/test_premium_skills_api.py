"""Wnioski o dopłatę za technologię premium i dzwonek prolongaty (F3). Dane fikcyjne."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.contract import Contract
from app.models.dl_alert import ALERT_FRAMEWORK_OVER_LIMIT, DlAlert
from tests.test_framework_rates_api import _headers, _seed


async def _with_skills_and_card(
    contract_id: int, senior_id: int, *, order_end_in_days: int = 20
) -> None:
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        candidate = await db.get(Candidate, contract.candidate_id)
        candidate.skills = [{"name": "Apache Kafka", "level": "senior"}]
        contract.client_order_end_date = business_today() + timedelta(
            days=order_end_in_days
        )
        await db.commit()


async def test_claim_path_grants_addon_and_raises_limit_not_rate(
    app_client: AsyncClient,
):
    client_id, contract_id, senior_id = await _seed()
    await _with_skills_and_card(contract_id, senior_id)
    dl = await _headers(app_client, "delivery_lead", assigned_client_id=client_id)
    today = business_today().isoformat()
    put = await app_client.put(
        f"/api/contracts/{contract_id}/framework-category",
        headers=dl,
        json={"rate_card_id": senior_id, "effective_from": today},
    )
    assert put.status_code == 200, put.text

    ev = await app_client.get(
        f"/api/contracts/{contract_id}/premium-skills", headers=dl
    )
    assert ev.status_code == 200, ev.text
    (kafka,) = ev.json()["evidence"]
    assert (kafka["technology"], kafka["knows"], kafka["uses"]) == (
        "Kafka",
        True,
        False,
    )
    assert kafka["sources"] == ["CV"]

    base = f"/api/contracts/{contract_id}/premium-skills/claims"
    created = await app_client.post(
        base,
        headers=dl,
        json={
            "technology": "kafka",
            "knows": True,
            "uses": True,
            "note": "codzienne strumienie",
        },
    )
    assert created.status_code == 200, created.text
    (claim,) = created.json()["claims"]
    assert (claim["technology"], claim["status"]) == ("Kafka", "approved")
    dup = await app_client.post(
        base, headers=dl, json={"technology": "Kafka", "knows": True, "uses": True}
    )
    assert dup.status_code == 422 and "już otwarty" in dup.json()["detail"]

    sent = await app_client.post(
        f"{base}/{claim['id']}/action", headers=dl, json={"action": "send"}
    )
    assert sent.json()["claims"][0]["status"] == "sent"
    no_confirmation = await app_client.post(
        f"{base}/{claim['id']}/action", headers=dl, json={"action": "grant"}
    )
    assert no_confirmation.status_code == 422
    granted = await app_client.post(
        f"{base}/{claim['id']}/action",
        headers=dl,
        json={
            "action": "grant",
            "confirmed_by": "LM klienta",
            "confirmed_on": today,
            "client_evidence": "mail",
        },
    )
    assert granted.status_code == 200, granted.text
    assert granted.json()["claims"][0]["status"] == "granted"
    category = (
        await app_client.get(
            f"/api/contracts/{contract_id}/framework-category", headers=dl
        )
    ).json()
    assert Decimal(category["framework_limit"]) == Decimal("120")
    assert Decimal(category["rate_client"]) == Decimal("115")
    assert category["status"] == "in_addon"


async def test_refusal_needs_a_reason_and_other_dl_is_refused(app_client: AsyncClient):
    client_id, contract_id, senior_id = await _seed()
    await _with_skills_and_card(contract_id, senior_id)
    dl = await _headers(app_client, "delivery_lead", assigned_client_id=client_id)
    await app_client.put(
        f"/api/contracts/{contract_id}/framework-category",
        headers=dl,
        json={"rate_card_id": senior_id},
    )
    base = f"/api/contracts/{contract_id}/premium-skills/claims"
    claim = (
        await app_client.post(
            base, headers=dl, json={"technology": "Kafka", "knows": True, "uses": True}
        )
    ).json()["claims"][0]
    no_reason = await app_client.post(
        f"{base}/{claim['id']}/action", headers=dl, json={"action": "refuse"}
    )
    assert no_reason.status_code == 422 and "powód" in no_reason.json()["detail"]
    refused = await app_client.post(
        f"{base}/{claim['id']}/action",
        headers=dl,
        json={"action": "refuse", "reason": "nice to have"},
    )
    assert refused.json()["claims"][0]["outcome_reason"] == "nice to have"

    other = await _headers(
        app_client, "delivery_lead", assigned_client_id=(await _seed())[0]
    )
    assert (
        await app_client.get(
            f"/api/contracts/{contract_id}/premium-skills", headers=other
        )
    ).status_code == 403
    assert (
        await app_client.post(
            base,
            headers=other,
            json={"technology": "Kafka", "knows": True, "uses": True},
        )
    ).status_code == 403
    assert (
        await app_client.get(
            f"/api/clients/{client_id}/framework-prolongations", headers=other
        )
    ).status_code == 403


async def test_prolongation_queue_and_bell_for_over_limit_before_order_end(
    app_client: AsyncClient,
):
    from app.tasks.dl_alerts_scanner import rule_framework_over_limit

    client_id, contract_id, senior_id = await _seed()
    await _with_skills_and_card(contract_id, senior_id, order_end_in_days=10)
    dl = await _headers(app_client, "delivery_lead", assigned_client_id=client_id)
    await app_client.put(
        f"/api/contracts/{contract_id}/framework-category",
        headers=dl,
        json={
            "rate_card_id": senior_id,
            "effective_from": business_today().isoformat(),
        },
    )
    queue = await app_client.get(
        f"/api/clients/{client_id}/framework-prolongations", headers=dl
    )
    assert queue.status_code == 200, queue.text
    (row,) = queue.json()
    assert row["contract_id"] == contract_id and row["days_left"] == 10
    assert [lv["kind"] for lv in row["levers"]] == ["addon"]

    async with AsyncSessionLocal() as db:
        await rule_framework_over_limit(db)
        await db.commit()
        alerts = (
            (
                await db.execute(
                    select(DlAlert).where(
                        DlAlert.alert_type == ALERT_FRAMEWORK_OVER_LIMIT,
                        DlAlert.client_id == client_id,
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(alerts) == 1
    assert alerts[0].link == f"/contracts/{contract_id}"
    assert "ponad stawką z umowy" in alerts[0].title
    _ = uuid  # dane fikcyjne z _seed
