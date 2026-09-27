"""Runda 8 audytu (MONEY) — testy na bazie: kwoty i cykl życia kontraktów."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit

pytestmark = pytest.mark.asyncio


async def _seed_dl(*client_ids: int) -> int:
    from app.core.security import hash_password
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import User, UserRole

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        dl = User(
            email=f"r8-dl-{suffix}@example.com",
            password_hash=hash_password(f"T3st_{suffix}!P"),
            name=f"R8 DL {suffix}",
            role=UserRole.delivery_lead,
            is_active=True,
            profile_completed=True,
        )
        db.add(dl)
        await db.flush()
        for client_id in client_ids:
            db.add(
                DeliveryLeadClientAssignment(
                    client_id=client_id, delivery_lead_user_id=dl.id
                )
            )
        await db.commit()
        return dl.id


async def test_by_dl_flags_partial_margin_and_keeps_zero_revenue(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """R8-N13-4: wiersz DL z klientem, którego obecny kontrakt nie ma stawki
    klienta, niesie licznik klientów bez wyceny, a DL bez zamówień ma
    przychód 0 — nie „—", który wyglądał jak brak kursu albo redakcja."""
    marker = uuid.uuid4().hex[:8]
    today = business_today()
    async with AsyncSessionLocal() as db:
        priced = Client(name=f"R8 wyceniony {marker}")
        unpriced = Client(name=f"R8 bez wyceny {marker}")
        person_a = Candidate(name="Wyceniony", lastname=f"R8{marker}")
        person_b = Candidate(name="Bezwyceny", lastname=f"R8{marker}")
        db.add_all([priced, unpriced, person_a, person_b])
        await db.flush()
        db.add_all(
            [
                Contract(
                    candidate_id=person_a.id,
                    client_id=priced.id,
                    contract_type=ContractType.b2b,
                    status=ContractStatus.active,
                    start_date=today - timedelta(days=30),
                    rate_unit=RateUnit.monthly,
                    rate_client=Decimal("20000"),
                    rate_candidate=Decimal("15000"),
                ),
                Contract(
                    candidate_id=person_b.id,
                    client_id=unpriced.id,
                    contract_type=ContractType.b2b,
                    status=ContractStatus.active,
                    start_date=today - timedelta(days=30),
                    rate_unit=RateUnit.monthly,
                    rate_client=None,
                    rate_candidate=Decimal("15000"),
                ),
            ]
        )
        await db.commit()
        priced_id, unpriced_id = priced.id, unpriced.id
    dl_id = await _seed_dl(priced_id, unpriced_id)

    resp = await app_client.get(
        "/api/admin/clients-overview/by-dl", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    row = next(r for r in resp.json() if r["dl_user_id"] == dl_id)
    assert row["monthly_margin_total"] == 5000
    assert row["monthly_margin_unpriced_clients"] == 1
    # Żadnych zamówień → przychód z zamówień to policzone zero.
    assert row["total_revenue"] is not None
    assert float(row["total_revenue"]) == 0


# ── R8-V1-1: kontrakt usuniętego klienta nie wraca ──────────────────────────


async def _seed_ended_contract(*, client_deleted: bool) -> int:
    from datetime import datetime, timezone

    marker = uuid.uuid4().hex[:8]
    today = business_today()
    async with AsyncSessionLocal() as db:
        client = Client(name=f"R8 usunięty {marker}")
        if client_deleted:
            now = datetime.now(timezone.utc)
            client.deleted_at = now
            client.archived_at = now
        person = Candidate(name="Zakonczony", lastname=f"R8{marker}")
        db.add_all([client, person])
        await db.flush()
        contract = Contract(
            candidate_id=person.id,
            client_id=client.id,
            contract_type=ContractType.uzlecenie,
            status=ContractStatus.ended,
            start_date=today - timedelta(days=200),
            end_date=today - timedelta(days=20),
            rate_unit=RateUnit.monthly,
            rate_client=Decimal("20000"),
            rate_candidate=Decimal("15000"),
        )
        db.add(contract)
        await db.commit()
        return contract.id


def _code(resp) -> str | None:
    detail = resp.json().get("detail")
    return detail.get("code") if isinstance(detail, dict) else None


async def test_return_after_break_refuses_a_deleted_client(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    contract_id = await _seed_ended_contract(client_deleted=True)
    resp = await app_client.post(
        f"/api/contracts/{contract_id}/return-after-break",
        json={"start_date": (business_today() + timedelta(days=1)).isoformat()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert _code(resp) == "client_deleted"


async def test_termination_reversal_is_blocked_for_a_deleted_client(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    contract_id = await _seed_ended_contract(client_deleted=True)
    resp = await app_client.get(
        f"/api/contracts/{contract_id}/termination-reversal",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    codes = {b["code"] for b in resp.json()["blockers"]}
    assert "client_deleted" in codes

    post = await app_client.post(
        f"/api/contracts/{contract_id}/termination-reversal",
        headers=app_auth_headers,
    )
    assert post.status_code == 409, post.text
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract.status == ContractStatus.ended


async def test_new_end_date_does_not_reopen_a_deleted_clients_contract(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    contract_id = await _seed_ended_contract(client_deleted=True)
    new_end = (business_today() + timedelta(days=90)).isoformat()
    patch = await app_client.patch(
        f"/api/contracts/{contract_id}",
        json={"end_date": new_end},
        headers=app_auth_headers,
    )
    assert patch.status_code == 422, patch.text
    assert _code(patch) == "client_deleted"

    amendment = await app_client.post(
        f"/api/contracts/{contract_id}/amendments",
        json={
            "amendment_type": "extension",
            "effective_date": business_today().isoformat(),
            "new_end_date": new_end,
        },
        headers=app_auth_headers,
    )
    assert amendment.status_code == 422, amendment.text
    assert _code(amendment) == "client_deleted"

    bulk = await app_client.post(
        f"/api/contracts/bulk-extend?ids={contract_id}&months=3",
        headers=app_auth_headers,
    )
    assert bulk.status_code == 200, bulk.text
    assert contract_id in bulk.json()["skipped_client_deleted"]

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract.status == ContractStatus.ended


async def test_live_client_contract_still_reopens_with_a_new_end_date(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    contract_id = await _seed_ended_contract(client_deleted=False)
    patch = await app_client.patch(
        f"/api/contracts/{contract_id}",
        json={"end_date": (business_today() + timedelta(days=90)).isoformat()},
        headers=app_auth_headers,
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["status"] in {"active", "ending"}


# ── R8-N6-4: dokument aneksu należy do kontraktu ────────────────────────────


async def test_amendment_refuses_a_document_of_another_contract(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from app.models.contract_document import ContractDocument

    own_id = await _seed_ended_contract(client_deleted=False)
    other_id = await _seed_ended_contract(client_deleted=False)
    async with AsyncSessionLocal() as db:
        doc = ContractDocument(
            contract_id=other_id,
            filename="aneks.pdf",
            file_path=f"contracts/{other_id}/aneks.pdf",
        )
        db.add(doc)
        await db.commit()
        foreign_doc_id = doc.id

    for document_id in (foreign_doc_id, 999_999_999):
        resp = await app_client.post(
            f"/api/contracts/{own_id}/amendments",
            json={
                "amendment_type": "extension",
                "effective_date": business_today().isoformat(),
                "new_end_date": (business_today() + timedelta(days=90)).isoformat(),
                "document_id": document_id,
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["reason"] == "amendment_document_not_on_contract"
