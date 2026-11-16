"""Cennik umowy ramowej, dopłaty i kategoria na kontrakcie — trasy (F1, 15.11.2026).

Reguła zakresu klienta siedzi w handlerze (``can_read_client_finance``), więc
macierz uprawnień jej nie widzi: ten test sprawdza ją wprost. Dane fikcyjne,
baza wspólna i nieczyszczona — asercje tylko na własnych wierszach.
"""

from __future__ import annotations

import io
import uuid
from datetime import timedelta
from decimal import Decimal

from docx import Document
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.rate_card import RateCard, RateCardAdder


async def _headers(app_client: AsyncClient, role_value: str, *, assigned_client_id: int | None = None) -> dict[str, str]:
    from app.core.security import hash_password
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import User, UserRole

    email = f"fa-{role_value}-{uuid.uuid4().hex[:8]}@example.com"
    password = f"P4ss_{uuid.uuid4().hex[:6]}!"
    async with AsyncSessionLocal() as db:
        role = UserRole(role_value)
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Fa {role_value}",
            role=role,
            roles=[role.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.flush()
        if assigned_client_id is not None:
            db.add(DeliveryLeadClientAssignment(delivery_lead_user_id=user.id, client_id=assigned_client_id))
        await db.commit()
    login = await app_client.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _seed() -> tuple[int, int, int]:
    """Klient z cennikiem (Senior 100, Expert 110) i dopłatą Kafka 20% dla Seniora."""
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Bank Ramowy {suffix}")
        candidate = Candidate(name="Ola", lastname=f"Testowa {suffix}", email=f"fa-{suffix}@example.com")
        db.add_all([client, candidate])
        await db.flush()
        senior = RateCard(client_id=client.id, role="IT Developer", seniority="Senior", rate_client_max=100, rate_unit=RateUnit.hourly)
        expert = RateCard(client_id=client.id, role="IT Developer", seniority="Expert", rate_client_max=110, rate_unit=RateUnit.hourly)
        db.add_all([senior, expert])
        db.add(RateCardAdder(client_id=client.id, technology="Kafka", percent=Decimal("20"), eligible=[{"role": "IT Developer", "seniority": "Senior"}]))
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=business_today() - timedelta(days=200),
            rate_candidate=Decimal("80"),
            rate_client=Decimal("115"),
        )
        db.add(contract)
        await db.commit()
        return client.id, contract.id, senior.id


async def test_delivery_lead_of_another_client_gets_403(app_client: AsyncClient):
    client_id, contract_id, _ = await _seed()
    other_client, _, _ = await _seed()
    headers = await _headers(app_client, "delivery_lead", assigned_client_id=other_client)
    assert (await app_client.get(f"/api/clients/{client_id}/framework-terms", headers=headers)).status_code == 403
    assert (await app_client.get(f"/api/contracts/{contract_id}/framework-category", headers=headers)).status_code == 403
    put = await app_client.put(
        f"/api/contracts/{contract_id}/framework-category", headers=headers, json={"rate_card_id": 1}
    )
    assert put.status_code == 403


async def test_delivery_lead_sets_addon_and_contract_comes_into_the_limit(app_client: AsyncClient):
    client_id, contract_id, senior_id = await _seed()
    headers = await _headers(app_client, "delivery_lead", assigned_client_id=client_id)

    terms = await app_client.get(f"/api/clients/{client_id}/framework-terms", headers=headers)
    assert terms.status_code == 200, terms.text
    assert [(c["label"], c["addons"]) for c in terms.json()["cards"]] == [
        ("IT Developer - Senior", ["Kafka 20%"]),
        ("IT Developer - Expert", []),
    ]

    today = business_today().isoformat()
    saved = await app_client.put(
        f"/api/contracts/{contract_id}/framework-category",
        headers=headers,
        json={
            "rate_card_id": senior_id,
            "addon_technology": "Kafka",
            "confirmed_by": "LM klienta",
            "confirmed_on": today,
            "evidence": "mail",
            "effective_from": today,
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert Decimal(body["framework_limit"]) == Decimal("120")
    assert body["status"] == "in_addon"
    assert body["source"] == "dl"
    # Dopłata nie rusza stawki przychodowej.
    assert Decimal(body["rate_client"]) == Decimal("115")


async def test_addon_outside_the_contract_and_without_confirmation_is_refused(app_client: AsyncClient):
    client_id, contract_id, _ = await _seed()
    async with AsyncSessionLocal() as db:
        expert_id = await db.scalar(
            select(RateCard.id).where(RateCard.client_id == client_id, RateCard.seniority == "Expert")
        )
    headers = await _headers(app_client, "delivery_lead", assigned_client_id=client_id)
    url = f"/api/contracts/{contract_id}/framework-category"
    outside = await app_client.put(url, headers=headers, json={"rate_card_id": expert_id, "addon_technology": "Kafka", "confirmed_by": "LM", "confirmed_on": business_today().isoformat()})
    assert outside.status_code == 422 and "nie przewiduje" in outside.json()["detail"]
    async with AsyncSessionLocal() as db:
        senior_id = await db.scalar(
            select(RateCard.id).where(RateCard.client_id == client_id, RateCard.seniority == "Senior")
        )
    unconfirmed = await app_client.put(url, headers=headers, json={"rate_card_id": senior_id, "addon_technology": "Kafka"})
    assert unconfirmed.status_code == 422 and "potwierdzeniem" in unconfirmed.json()["detail"]


def _appendix() -> bytes:
    doc = Document()
    table = doc.add_table(rows=0, cols=2)
    for label, rate in [("IT Tester - Senior", "90"), ("IT Developer - Senior", "105")]:
        cells = table.add_row().cells
        cells[0].text, cells[1].text = label, rate
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


async def test_only_finance_imports_the_appendix_and_preview_writes_nothing(app_client: AsyncClient):
    client_id, _, _ = await _seed()
    files = {"file": ("zalacznik.docx", _appendix(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    dl = await _headers(app_client, "delivery_lead", assigned_client_id=client_id)
    assert (await app_client.post(f"/api/clients/{client_id}/framework-terms/import", headers=dl, files=files)).status_code == 403

    admin = await _headers(app_client, "admin")
    preview = await app_client.post(f"/api/clients/{client_id}/framework-terms/import", headers=admin, files=files, data={"apply": "false"})
    assert preview.status_code == 200, preview.text
    assert {(r["label"], r["action"]) for r in preview.json()["rates"]} == {
        ("IT Tester - Senior", "create"),
        ("IT Developer - Senior", "update"),
    }
    terms = await app_client.get(f"/api/clients/{client_id}/framework-terms", headers=admin)
    assert len(terms.json()["cards"]) == 2

    applied = await app_client.post(f"/api/clients/{client_id}/framework-terms/import", headers=admin, files=files, data={"apply": "true"})
    assert applied.status_code == 200, applied.text
    labels = {c["label"]: c["rate_max"] for c in (await app_client.get(f"/api/clients/{client_id}/framework-terms", headers=admin)).json()["cards"]}
    assert labels["IT Developer - Senior"] == 105 and labels["IT Tester - Senior"] == 90


async def test_overview_counts_levers_and_governance_report(app_client: AsyncClient):
    client_id, contract_id, senior_id = await _seed()
    headers = await _headers(app_client, "delivery_lead", assigned_client_id=client_id)
    await app_client.put(
        f"/api/contracts/{contract_id}/framework-category",
        headers=headers,
        json={"rate_card_id": senior_id, "effective_from": business_today().isoformat()},
    )
    ov = await app_client.get(f"/api/clients/{client_id}/framework-overview", headers=headers)
    assert ov.status_code == 200, ov.text
    body = ov.json()
    assert body["counts"]["over"] == 1
    (row,) = body["rows"]
    # Stawka 115 przy limicie 100: dopłata Kafka 20% (120) albo awans na Expert (110 — za mało).
    assert [(l["kind"], l["label"]) for l in row["levers"]] == [("addon", "Dopłata +20% (Kafka)")]
    assert row["limit_mismatch"] is False
    assert len(body["trend"]) == 5

    report = await app_client.get(f"/api/clients/{client_id}/framework-overview/report.xlsx", headers=headers)
    assert report.status_code == 200
    assert report.content[:2] == b"PK"

    other = await _headers(app_client, "delivery_lead", assigned_client_id=(await _seed())[0])
    assert (await app_client.get(f"/api/clients/{client_id}/framework-overview", headers=other)).status_code == 403
    assert (await app_client.get(f"/api/clients/{client_id}/framework-overview/report.xlsx", headers=other)).status_code == 403
