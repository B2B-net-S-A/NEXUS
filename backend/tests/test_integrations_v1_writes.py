"""API integracyjne v1 — zapis zamówień i kontraktów (PR 2B, ``WritePolicy``).

Każda trasa: ze scope'em 200, bez scope'u 403, sam odczyt 403. Do tego
powtórka z tym samym ``Idempotency-Key``, kwoty tylko z ``amounts:write``,
ślad konta serwisowego w dzienniku zmian zamówienia i w historii zamówienia,
przedłużenie → zakończenie i odmowy maszyny stanów kontraktu.

Dane są zmyślone (repo jest publiczne). Rok fixture'ów 2042 — baza testowa
jest wspólna dla przebiegu, a 2041 zajmuje ``test_integrations_v1_api``.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import (
    GROUP_STATUS_ACTIVE,
    ClientOrderGroup,
    ClientOrderGroupEvent,
)
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
from app.models.order_change_event import OrderChangeEvent
from app.models.order_type import OrderType
from app.services.multi_consultant_orders import EVENT_ORDER_CLOSED
from tests.test_service_accounts import _account_with_key

pytestmark = pytest.mark.asyncio

V1 = "/api/integrations/v1"
_PDF = b"%PDF-1.4\n% zamowienie testowe\n"


async def _key(app_client: AsyncClient, headers: dict, scopes: list[str]):
    account, api_key, _ = await _account_with_key(app_client, headers, scopes)
    return account, api_key


def _h(api_key: str, idem: str | None = None) -> dict:
    out = {"X-API-Key": api_key}
    out["Idempotency-Key"] = idem or str(uuid.uuid4())
    return out


async def _seed_periodic(
    *, tag: str, contract_type: ContractType = ContractType.uop
) -> dict:
    """Aktywny kontrakt + aktywne zamówienie okresowe na 2042."""
    u = f"{tag}-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        client = Client(name=f"V1W Client {u}")
        cand = Candidate(
            name="Iga", lastname=f"Zapisowa-{u}", email=f"v1w-{u}@example.com"
        )
        db.add_all([client, cand])
        await db.flush()
        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            contract_type=contract_type,
            status=ContractStatus.active,
            start_date=date(2042, 1, 1),
        )
        db.add(contract)
        await db.flush()
        order = ClientOrder(
            contract_id=contract.id,
            client_id=client.id,
            title=f"ZAM-W-{u}",
            status=ClientOrderStatus.active,
            start_date=date(2042, 1, 1),
            end_date=date(2042, 12, 31),
            rate_candidate=Decimal("100.00"),
            rate_client=Decimal("150.00"),
        )
        db.add(order)
        await db.commit()
        return {
            "client_id": client.id,
            "contract_id": contract.id,
            "order_id": order.id,
        }


async def _seed_md_group(*, tag: str) -> dict:
    """Zamówienie MD z budżetem per osoba (2042) i jedną aktywną linią."""
    u = f"{tag}-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        client = Client(name=f"V1W MD {u}")
        cand = Candidate(
            name="Ola", lastname=f"Liniowa-{u}", email=f"v1md-{u}@example.com"
        )
        db.add_all([client, cand])
        await db.flush()
        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            contract_type=ContractType.uop,
            status=ContractStatus.active,
            start_date=date(2042, 1, 1),
            rate_candidate=Decimal("90"),
            rate_unit=RateUnit.hourly,
        )
        db.add(contract)
        await db.flush()
        group = ClientOrderGroup(
            client_id=client.id,
            order_number=f"MD/2042/{u}",
            start_date=date(2042, 1, 1),
            end_date=date(2042, 12, 31),
            status=GROUP_STATUS_ACTIVE,
            order_type=OrderType.md,
            md_budget_mode="per_person",
            is_md_budget_based=False,
        )
        db.add(group)
        await db.flush()
        line = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            order_group_id=group.id,
            order_type=OrderType.md,
            title=f"Zamówienie {group.order_number} — Ola",
            status=ClientOrderStatus.active,
            start_date=date(2042, 1, 1),
            end_date=date(2042, 12, 31),
            md_rate_cost=Decimal("720.000"),
            md_rate_revenue=Decimal("800.000"),
            rate_unit=RateUnit.daily,
            billing_hours_per_month=168,
            currency="PLN",
            rate_client_currency="PLN",
            rate_candidate_currency="PLN",
            md_input_mode="md",
            md_input_value=Decimal("100"),
            md_total=Decimal("100"),
            md_remaining=Decimal("100"),
            md_manual_adjustment=Decimal("0"),
        )
        db.add(line)
        await db.commit()
        return {
            "client_id": client.id,
            "contract_id": contract.id,
            "group_id": group.id,
            "line_id": line.id,
        }


# ── Scope'y: każda trasa zapisu ─────────────────────────────────────────────


class TestScopes:
    async def test_order_close_requires_orders_write(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_periodic(tag="close-scope")
        body = {"closure_date": "2042-06-30"}
        url = f"{V1}/orders/{seeded['order_id']}/close"
        for scopes in (["orders:read"], ["contracts:write"]):
            _, api_key = await _key(app_client, app_auth_headers, scopes)
            resp = await app_client.post(url, headers=_h(api_key), json=body)
            assert resp.status_code == 403, resp.text
            assert resp.json()["error"]["code"] == "insufficient_scope"
        resp = await app_client.post(url, headers=app_auth_headers, json=body)
        assert resp.status_code == 401, resp.text

        _, api_key = await _key(app_client, app_auth_headers, ["orders:write"])
        resp = await app_client.post(url, headers=_h(api_key), json=body)
        assert resp.status_code == 200, resp.text
        assert resp.json()["end_date"] == "2042-06-30"

    @pytest.mark.parametrize(
        "suffix,body",
        [
            ("close", {"closure_date": "2042-06-30"}),
            ("cancel", {"reason": "zamówienie nie doszło do skutku"}),
            ("extend", {"order_number": "MD/EXT", "start_date": "2043-01-01"}),
        ],
    )
    async def test_group_writes_require_orders_write(
        self, app_client: AsyncClient, app_auth_headers: dict, suffix: str, body: dict
    ):
        seeded = await _seed_md_group(tag=f"g-{suffix}")
        url = f"{V1}/order-groups/{seeded['group_id']}/{suffix}"
        _, read_key = await _key(app_client, app_auth_headers, ["orders:read"])
        resp = await app_client.post(url, headers=_h(read_key), json=body)
        assert resp.status_code == 403, resp.text

        _, api_key = await _key(app_client, app_auth_headers, ["orders:write"])
        if suffix == "extend":
            body = {**body, "order_number": f"MD/EXT/{uuid.uuid4().hex[:6]}"}
        resp = await app_client.post(url, headers=_h(api_key), json=body)
        assert resp.status_code == (201 if suffix == "extend" else 200), resp.text

    async def test_order_patch_and_file_require_orders_write(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_periodic(tag="patch-scope")
        _, read_key = await _key(app_client, app_auth_headers, ["orders:read"])
        patch = await app_client.patch(
            f"{V1}/orders/{seeded['order_id']}",
            headers=_h(read_key),
            json={"notes": "z automatyzacji"},
        )
        assert patch.status_code == 403, patch.text
        upload = await app_client.put(
            f"{V1}/orders/{seeded['order_id']}/file",
            headers=_h(read_key),
            files={"file": ("zamowienie.pdf", _PDF, "application/pdf")},
        )
        assert upload.status_code == 403, upload.text

    async def test_contract_writes_require_contracts_write(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_periodic(tag="contract-scope")
        cid = seeded["contract_id"]
        for scopes in (["contracts:read"], ["orders:write"]):
            _, api_key = await _key(app_client, app_auth_headers, scopes)
            patch = await app_client.patch(
                f"{V1}/contracts/{cid}", headers=_h(api_key), json={"end_date": None}
            )
            assert patch.status_code == 403, patch.text
            status = await app_client.post(
                f"{V1}/contracts/{cid}/status",
                headers=_h(api_key),
                json={"status": "active"},
            )
            assert status.status_code == 403, status.text


# ── Zamówienia okresowe ─────────────────────────────────────────────────────


class TestOrderWrites:
    async def test_close_replays_and_leaves_an_integration_change_event(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_periodic(tag="close")
        account, api_key = await _key(app_client, app_auth_headers, ["orders:write"])
        idem = str(uuid.uuid4())
        body = {"closure_date": "2042-06-30", "closure_reason": "koniec projektu"}
        url = f"{V1}/orders/{seeded['order_id']}/close"
        first = await app_client.post(url, headers=_h(api_key, idem), json=body)
        assert first.status_code == 200, first.text
        # Dzień zakończenia jeszcze nie nadszedł — data tak, status jeszcze nie.
        assert first.json()["status"] == "active"
        assert first.json()["amounts_redacted"] is True

        again = await app_client.post(url, headers=_h(api_key, idem), json=body)
        assert again.status_code == 200, again.text
        assert again.headers.get("Idempotent-Replayed") == "true"
        assert again.json() == first.json()

        async with AsyncSessionLocal() as db:
            event = await db.scalar(
                select(OrderChangeEvent)
                .where(
                    OrderChangeEvent.order_id == seeded["order_id"],
                    OrderChangeEvent.field == "end_date",
                )
                .order_by(OrderChangeEvent.id.desc())
            )
        assert event is not None
        assert event.source == "integration"
        assert event.created_by_service_account_id == account["id"]
        assert event.created_by_user_id is None

    async def test_close_of_a_group_line_is_409(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_md_group(tag="close-line")
        _, api_key = await _key(app_client, app_auth_headers, ["orders:write"])
        resp = await app_client.post(
            f"{V1}/orders/{seeded['line_id']}/close",
            headers=_h(api_key),
            json={"closure_date": "2042-06-30"},
        )
        assert resp.status_code == 409, resp.text
        assert resp.json()["error"]["code"] == "order_belongs_to_group"

    async def test_patch_end_date_and_notes_without_amounts(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_periodic(tag="patch")
        _, api_key = await _key(app_client, app_auth_headers, ["orders:write"])
        resp = await app_client.patch(
            f"{V1}/orders/{seeded['order_id']}",
            headers=_h(api_key),
            json={"end_date": "2042-09-30", "notes": "aneks terminowy"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["end_date"] == "2042-09-30"
        async with AsyncSessionLocal() as db:
            order = await db.get(ClientOrder, seeded["order_id"])
        assert order.notes == "aneks terminowy"

    async def test_rate_change_needs_amounts_write(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_periodic(tag="rates")
        url = f"{V1}/orders/{seeded['order_id']}"
        _, no_amounts = await _key(
            app_client, app_auth_headers, ["orders:write", "amounts:read"]
        )
        denied = await app_client.patch(
            url, headers=_h(no_amounts), json={"rate_client": "175.00"}
        )
        assert denied.status_code == 403, denied.text
        error = denied.json()["error"]
        assert error["code"] == "insufficient_scope"
        assert error["details"]["missing"] == ["amounts:write"]
        assert error["details"]["fields"] == ["rate_client"]

        _, with_amounts = await _key(
            app_client, app_auth_headers, ["orders:write", "amounts:write"]
        )
        ok = await app_client.patch(
            url, headers=_h(with_amounts), json={"rate_client": "175.00"}
        )
        assert ok.status_code == 200, ok.text
        # amounts:write obejmuje amounts:read — odpowiedź niesie stawkę.
        assert ok.json()["amounts_redacted"] is False
        assert ok.json()["rate_revenue"] == "175.00"

    async def test_patch_rejects_other_fields_and_group_lines(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_periodic(tag="patch-422")
        _, api_key = await _key(app_client, app_auth_headers, ["orders:write"])
        other = await app_client.patch(
            f"{V1}/orders/{seeded['order_id']}",
            headers=_h(api_key),
            json={"title": "inny numer"},
        )
        assert other.status_code == 422, other.text
        assert other.json()["error"]["code"] == "validation_error"
        empty = await app_client.patch(
            f"{V1}/orders/{seeded['order_id']}", headers=_h(api_key), json={}
        )
        assert empty.status_code == 422, empty.text

        group = await _seed_md_group(tag="patch-line")
        line = await app_client.patch(
            f"{V1}/orders/{group['line_id']}",
            headers=_h(api_key),
            json={"notes": "x"},
        )
        assert line.status_code == 409, line.text
        assert line.json()["error"]["code"] == "order_belongs_to_group"

    async def test_file_upload_replays_without_a_second_write(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_periodic(tag="file")
        _, api_key = await _key(app_client, app_auth_headers, ["orders:write"])
        idem = str(uuid.uuid4())
        url = f"{V1}/orders/{seeded['order_id']}/file"
        files = {"file": ("zamowienie.pdf", _PDF, "application/pdf")}
        first = await app_client.put(url, headers=_h(api_key, idem), files=files)
        assert first.status_code == 200, first.text
        assert first.json()["has_file"] is True
        again = await app_client.put(url, headers=_h(api_key, idem), files=files)
        assert again.status_code == 200, again.text
        assert again.headers.get("Idempotent-Replayed") == "true"

        not_pdf = await app_client.put(
            url,
            headers=_h(api_key),
            files={"file": ("zamowienie.pdf", b"nie pdf", "application/pdf")},
        )
        assert not_pdf.status_code == 415, not_pdf.text


# ── Zamówienia MD / kosztowe ────────────────────────────────────────────────


class TestGroupWrites:
    async def test_extend_then_close_round_trip(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_md_group(tag="extend")
        account, api_key = await _key(
            app_client, app_auth_headers, ["orders:write", "amounts:write"]
        )
        number = f"MD/2043/{uuid.uuid4().hex[:6]}"
        extended = await app_client.post(
            f"{V1}/order-groups/{seeded['group_id']}/extend",
            headers=_h(api_key),
            json={
                "order_number": number,
                "start_date": "2043-01-01",
                "end_date": "2043-12-31",
                "lines": [
                    {
                        "contract_id": seeded["contract_id"],
                        "rate_cost": "720.00",
                        "rate_revenue": "800.00",
                        "input_mode": "md",
                        "input_value": "120",
                        "start_date": "2043-01-01",
                    }
                ],
            },
        )
        assert extended.status_code == 201, extended.text
        new_group = extended.json()
        assert new_group["order_number"] == number
        assert new_group["status"] == "scheduled"
        assert len(new_group["lines"]) == 1
        assert new_group["lines"][0]["contract_id"] == seeded["contract_id"]

        closed = await app_client.post(
            f"{V1}/order-groups/{new_group['id']}/close",
            headers=_h(api_key),
            json={"closure_date": "2043-06-30", "closure_reason": "skrócenie"},
        )
        assert closed.status_code == 200, closed.text
        assert closed.json()["status"] == "completed"
        assert closed.json()["end_date"] == "2043-06-30"
        assert closed.json()["lines"][0]["end_date"] == "2043-06-30"

        async with AsyncSessionLocal() as db:
            events = (
                await db.scalars(
                    select(ClientOrderGroupEvent).where(
                        ClientOrderGroupEvent.group_id == new_group["id"]
                    )
                )
            ).all()
        assert events
        assert all(ev.created_by_user_id is None for ev in events)
        closing = [ev for ev in events if ev.event_type == EVENT_ORDER_CLOSED]
        assert closing and closing[0].payload["actor"] == (
            f"Integracja: {account['name']}"
        )

    async def test_extend_with_people_needs_amounts_write(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_md_group(tag="extend-amounts")
        _, api_key = await _key(app_client, app_auth_headers, ["orders:write"])
        resp = await app_client.post(
            f"{V1}/order-groups/{seeded['group_id']}/extend",
            headers=_h(api_key),
            json={
                "order_number": f"MD/X/{uuid.uuid4().hex[:6]}",
                "start_date": "2043-01-01",
                "lines": [
                    {
                        "contract_id": seeded["contract_id"],
                        "rate_cost": "1",
                        "rate_revenue": "2",
                        "input_mode": "md",
                        "input_value": "1",
                        "start_date": "2043-01-01",
                    }
                ],
            },
        )
        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["details"]["missing"] == ["amounts:write"]

    async def test_extension_person_must_have_a_contract_not_a_candidate(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_md_group(tag="extend-cand")
        _, api_key = await _key(
            app_client, app_auth_headers, ["orders:write", "amounts:write"]
        )
        resp = await app_client.post(
            f"{V1}/order-groups/{seeded['group_id']}/extend",
            headers=_h(api_key),
            json={
                "order_number": f"MD/C/{uuid.uuid4().hex[:6]}",
                "start_date": "2043-01-01",
                "lines": [
                    {
                        "candidate_id": 1,
                        "rate_cost": "1",
                        "rate_revenue": "2",
                        "start_date": "2043-01-01",
                    }
                ],
            },
        )
        assert resp.status_code == 422, resp.text

    async def test_cancel_and_second_cancel_is_409(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_md_group(tag="cancel")
        _, api_key = await _key(app_client, app_auth_headers, ["orders:write"])
        url = f"{V1}/order-groups/{seeded['group_id']}/cancel"
        first = await app_client.post(url, headers=_h(api_key), json={"reason": "x"})
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "cancelled"
        second = await app_client.post(url, headers=_h(api_key), json={})
        assert second.status_code == 409, second.text


# ── Kontrakty ───────────────────────────────────────────────────────────────


class TestContractWrites:
    async def test_past_end_date_on_live_contract_needs_contracts_status(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_periodic(tag="c-past")
        _, api_key = await _key(app_client, app_auth_headers, ["contracts:write"])
        past = (business_today() - timedelta(days=1)).isoformat()
        resp = await app_client.patch(
            f"{V1}/contracts/{seeded['contract_id']}",
            headers=_h(api_key),
            json={"end_date": past},
        )
        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["details"]["missing"] == ["contracts:status"]

    async def test_end_date_shortens_open_orders(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_periodic(tag="c-end")
        _, api_key = await _key(app_client, app_auth_headers, ["contracts:write"])
        resp = await app_client.patch(
            f"{V1}/contracts/{seeded['contract_id']}",
            headers=_h(api_key),
            json={"end_date": "2042-06-30"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["end_date"] == "2042-06-30"
        async with AsyncSessionLocal() as db:
            order = await db.get(ClientOrder, seeded["order_id"])
        assert order.end_date == date(2042, 6, 30)

    async def test_patch_rejects_other_fields(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_periodic(tag="c-422")
        _, api_key = await _key(app_client, app_auth_headers, ["contracts:write"])
        resp = await app_client.patch(
            f"{V1}/contracts/{seeded['contract_id']}",
            headers=_h(api_key),
            json={"end_date": "2042-06-30", "rate_client": "1"},
        )
        assert resp.status_code == 422, resp.text

    async def test_b2b_end_date_without_termination_is_422(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_periodic(tag="c-b2b", contract_type=ContractType.b2b)
        _, api_key = await _key(app_client, app_auth_headers, ["contracts:write"])
        resp = await app_client.patch(
            f"{V1}/contracts/{seeded['contract_id']}",
            headers=_h(api_key),
            json={"end_date": "2042-06-30"},
        )
        assert resp.status_code == 422, resp.text

    async def test_status_change_follows_the_state_machine(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_periodic(tag="c-status")
        cid = seeded["contract_id"]
        _, write_only = await _key(app_client, app_auth_headers, ["contracts:write"])
        denied = await app_client.post(
            f"{V1}/contracts/{cid}/status",
            headers=_h(write_only),
            json={"status": "active"},
        )
        # Status = osobny scope, jak uprawnienie ludzi „Status kontraktu”.
        assert denied.status_code == 403, denied.text
        _, api_key = await _key(app_client, app_auth_headers, ["contracts:status"])

        ended = await app_client.post(
            f"{V1}/contracts/{cid}/status",
            headers=_h(api_key),
            json={"status": "ended"},
        )
        assert ended.status_code == 409, ended.text
        assert ended.json()["error"]["details"]["reason"] == "termination_required"

        # Umowa bezterminowa nie może być „Kończąca się”.
        ending = await app_client.post(
            f"{V1}/contracts/{cid}/status",
            headers=_h(api_key),
            json={"status": "ending"},
        )
        assert ending.status_code == 409, ending.text
        assert ending.json()["error"]["details"]["reason"] == "ending_requires_end_date"

        bad = await app_client.post(
            f"{V1}/contracts/{cid}/status",
            headers=_h(api_key),
            json={"status": "void"},
        )
        assert bad.status_code == 422, bad.text

        async with AsyncSessionLocal() as db:
            contract = await db.get(Contract, cid)
        assert contract.status == ContractStatus.active
