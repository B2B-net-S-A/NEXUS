"""API integracyjne v1 (``/api/integrations/v1``, 0443) — testy na bazie.

Każdy scope strzeże prawdziwej trasy (reguła z ``test_service_accounts``):
bez scope'u 403, ze scope'em 200, JWT użytkownika 401. Do tego kwoty
w dwóch poziomach (sprzedaż ze ``sales_amounts:read``, koszty i marża tylko
z ``amounts:read``), idempotencja zapisów, ``dry_run`` bez śladu w bazie,
duplikaty, autor zapisu = konto serwisowe.

Dane są zmyślone (repo jest publiczne). Rok fixture'ów 2041 — baza testowa
jest wspólna dla przebiegu, więc rok zajęty przez sąsiada wracałby jako
„regresja”.
"""

from __future__ import annotations

import io
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
from app.models.contract import Contract, ContractStatus
from app.models.contract_candidate_rate import ContractCandidateRate
from app.models.contract_client_rate import ContractClientRate
from app.models.critical_event import CriticalEvent
from app.models.finance import FinanceImportRun, FinanceMonthlyResult
from app.models.md_consumption import MdConsumptionImport
from app.models.order_change_event import OrderChangeEvent
from tests.test_service_accounts import ACCOUNTS_URL, _account_with_key

pytestmark = pytest.mark.asyncio

V1 = "/api/integrations/v1"


async def _key(
    app_client: AsyncClient, headers: dict, scopes: list[str]
) -> tuple[dict, str]:
    account, api_key, _ = await _account_with_key(app_client, headers, scopes)
    return account, api_key


def _h(api_key: str, idem: str | None = None) -> dict:
    out = {"X-API-Key": api_key}
    if idem is not None:
        out["Idempotency-Key"] = idem
    return out


async def _seed_order(*, tag: str) -> dict:
    u = f"{tag}-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        client = Client(name=f"V1 Client {u}")
        cand = Candidate(
            name="Ola", lastname=f"Testowa-{u}", email=f"v1-{u}@example.com"
        )
        db.add_all([client, cand])
        await db.flush()
        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=date(2041, 1, 1),
        )
        db.add(contract)
        await db.flush()
        order = ClientOrder(
            contract_id=contract.id,
            client_id=client.id,
            title=f"ZAM-{u}",
            status=ClientOrderStatus.active,
            start_date=date(2041, 1, 1),
            end_date=date(2041, 12, 31),
            rate_candidate=Decimal("100.50"),
            rate_client=Decimal("150.25"),
        )
        db.add(order)
        await db.commit()
        return {
            "client_id": client.id,
            "contract_id": contract.id,
            "order_id": order.id,
        }


# ── Meta ─────────────────────────────────────────────────────────────────────


class TestMe:
    async def test_any_valid_key_sees_its_account_and_effective_scopes(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        account, api_key = await _key(app_client, app_auth_headers, ["md:write"])
        resp = await app_client.get(f"{V1}/me", headers=_h(api_key))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["account"] == account["slug"]
        values = {s["value"] for s in body["scopes"]}
        # Zapis obejmuje odczyt tego samego obszaru.
        assert values == {"md:write", "md:read"}
        assert body["key_expires_in_days"] is not None

    async def test_missing_key_and_user_jwt_are_401_in_the_v1_envelope(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        for headers in ({}, app_auth_headers):
            resp = await app_client.get(f"{V1}/me", headers=headers)
            assert resp.status_code == 401, resp.text
            assert resp.json()["error"]["code"] == "unauthenticated"

    async def test_openapi_lists_only_v1_paths(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        _, api_key = await _key(app_client, app_auth_headers, ["clients:read"])
        resp = await app_client.get(f"{V1}/openapi.json", headers=_h(api_key))
        assert resp.status_code == 200, resp.text
        spec = resp.json()
        assert spec["paths"]
        assert all(path.startswith(V1) for path in spec["paths"])
        assert "ApiKeyHeader" in spec["components"]["securitySchemes"]


# ── Scope'y: każdy strzeże prawdziwej trasy ─────────────────────────────────

_READS = [
    ("clients:read", "/clients"),
    ("contracts:read", "/contracts"),
    ("orders:read", "/orders"),
    ("orders:read", "/order-groups"),
    ("md:read", "/md/imports"),
    ("finance:read", "/finance/order-changes"),
    ("finance:read", "/finance/periods"),
    ("invoices:read", "/invoices"),
    ("invoices:read", "/invoices/dso"),
]


class TestReadScopes:
    @pytest.mark.parametrize("scope,path", _READS)
    async def test_scope_opens_its_route(
        self, app_client: AsyncClient, app_auth_headers: dict, scope: str, path: str
    ):
        _, api_key = await _key(app_client, app_auth_headers, [scope])
        resp = await app_client.get(f"{V1}{path}", headers=_h(api_key))
        assert resp.status_code == 200, resp.text

    @pytest.mark.parametrize("scope,path", _READS)
    async def test_other_scope_is_403_insufficient_scope(
        self, app_client: AsyncClient, app_auth_headers: dict, scope: str, path: str
    ):
        other = "contractors:read"
        _, api_key = await _key(app_client, app_auth_headers, [other])
        resp = await app_client.get(f"{V1}{path}", headers=_h(api_key))
        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "insufficient_scope"

    @pytest.mark.parametrize("scope,path", _READS)
    async def test_admin_jwt_is_not_accepted(
        self, app_client: AsyncClient, app_auth_headers: dict, scope: str, path: str
    ):
        resp = await app_client.get(f"{V1}{path}", headers=app_auth_headers)
        assert resp.status_code == 401, resp.text

    async def test_revoked_key_is_401(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        account, api_key, key = await _account_with_key(
            app_client, app_auth_headers, ["clients:read"]
        )
        from urllib.parse import quote

        resp = await app_client.post(
            f"{ACCOUNTS_URL}/{account['id']}/keys/{quote(key['key_id'], safe='')}/revoke",
            headers=app_auth_headers,
            json={"reason": "test"},
        )
        assert resp.status_code == 200, resp.text
        resp = await app_client.get(f"{V1}/clients", headers=_h(api_key))
        assert resp.status_code == 401

    async def test_validation_error_uses_the_envelope(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        _, api_key = await _key(app_client, app_auth_headers, ["clients:read"])
        resp = await app_client.get(
            f"{V1}/clients", headers=_h(api_key), params={"page": 0}
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "validation_error"


# ── Kwoty: sprzedaż ze sales_amounts:read, koszty tylko z amounts:read ──────


async def _seed_contract_rates(contract_id: int) -> None:
    """Harmonogramy stawek od startu kontraktu: konsultant 100,50, klient 150,25."""
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                ContractCandidateRate(
                    contract_id=contract_id,
                    rate=Decimal("100.50"),
                    effective_from=date(2041, 1, 1),
                ),
                ContractClientRate(
                    contract_id=contract_id,
                    rate=Decimal("150.25"),
                    effective_from=date(2041, 1, 1),
                ),
            ]
        )
        await db.commit()


class TestAmountsScope:
    async def test_order_amounts_hidden_without_amounts_read(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_order(tag="noamounts")
        _, api_key = await _key(app_client, app_auth_headers, ["orders:read"])
        resp = await app_client.get(
            f"{V1}/orders/{seeded['order_id']}", headers=_h(api_key)
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["amounts_redacted"] is True
        assert body["costs_redacted"] is True
        assert body["rate_cost"] is None and body["rate_revenue"] is None

    async def test_sales_amounts_show_the_client_rate_but_not_the_cost(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_order(tag="sales")
        _, api_key = await _key(
            app_client, app_auth_headers, ["orders:read", "sales_amounts:read"]
        )
        resp = await app_client.get(
            f"{V1}/orders/{seeded['order_id']}", headers=_h(api_key)
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["amounts_redacted"] is False
        assert body["costs_redacted"] is True
        assert body["rate_revenue"] == "150.25"
        assert body["rate_cost"] is None

    async def test_order_amounts_are_decimal_strings_with_amounts_read(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_order(tag="amounts")
        _, api_key = await _key(
            app_client, app_auth_headers, ["orders:read", "amounts:read"]
        )
        resp = await app_client.get(
            f"{V1}/orders/{seeded['order_id']}", headers=_h(api_key)
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["amounts_redacted"] is False
        assert body["costs_redacted"] is False
        assert body["rate_cost"] == "100.50"
        assert body["rate_revenue"] == "150.25"

    @pytest.mark.parametrize(
        "scopes,expected",
        [
            ([], None),
            (
                ["sales_amounts:read"],
                {"rate_client": "150.25", "rate_candidate": None, "margin": None},
            ),
            (
                ["amounts:read"],
                {
                    "rate_client": "150.25",
                    "rate_candidate": "100.50",
                    "margin": "49.75",
                },
            ),
        ],
    )
    async def test_contract_rates_by_amount_level(
        self,
        app_client: AsyncClient,
        app_auth_headers: dict,
        scopes: list[str],
        expected: dict | None,
    ):
        seeded = await _seed_order(tag="contract-rates")
        await _seed_contract_rates(seeded["contract_id"])
        _, api_key = await _key(
            app_client, app_auth_headers, ["contracts:read", *scopes]
        )
        resp = await app_client.get(
            f"{V1}/contracts/{seeded['contract_id']}",
            headers=_h(api_key),
            params={"as_of": "2041-06-01"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["amounts_redacted"] is (expected is None)
        assert body["costs_redacted"] is (scopes != ["amounts:read"])
        if expected is None:
            assert body["rates"] is None
            return
        rates = body["rates"]
        for field, value in expected.items():
            assert rates[field] == value, field
        if scopes == ["sales_amounts:read"]:
            assert rates["monthly_rate_candidate"] is None
            assert rates["monthly_margin"] is None

    async def test_rate_history_requires_amounts_read(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_order(tag="history")
        _, api_key = await _key(app_client, app_auth_headers, ["contracts:read"])
        resp = await app_client.get(
            f"{V1}/contracts/{seeded['contract_id']}/rate-history", headers=_h(api_key)
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "insufficient_scope"
        assert resp.json()["error"]["details"]["required"] == ["sales_amounts:read"]

    async def test_rate_history_with_sales_amounts_hides_consultant_steps(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_order(tag="history-sales")
        await _seed_contract_rates(seeded["contract_id"])
        url = f"{V1}/contracts/{seeded['contract_id']}/rate-history"

        _, sales_key = await _key(
            app_client, app_auth_headers, ["contracts:read", "sales_amounts:read"]
        )
        sales = await app_client.get(url, headers=_h(sales_key))
        assert sales.status_code == 200, sales.text
        assert sales.json()["costs_redacted"] is True
        assert sales.json()["candidate"] == []
        assert [step["rate"] for step in sales.json()["client"]] == ["150.25"]

        _, all_key = await _key(
            app_client, app_auth_headers, ["contracts:read", "amounts:read"]
        )
        full = await app_client.get(url, headers=_h(all_key))
        assert full.status_code == 200, full.text
        assert full.json()["costs_redacted"] is False
        assert [step["rate"] for step in full.json()["candidate"]] == ["100.50"]
        assert [step["rate"] for step in full.json()["client"]] == ["150.25"]

    async def test_contractor_invoice_amount_needs_amounts_read(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        """Faktura od kontraktora to koszt; faktura do klienta — sprzedaż."""
        seeded = await _seed_order(tag="inv-cost")
        _, writer = await _key(app_client, app_auth_headers, ["invoices:write"])
        cost = await app_client.post(
            f"{V1}/invoices",
            headers=_h(writer, str(uuid.uuid4())),
            json={
                **_invoice(seeded["contract_id"], f"K/{uuid.uuid4().hex[:6]}"),
                "direction": "from_contractor",
                "amount": "999.00",
            },
        )
        assert cost.status_code == 201, cost.text
        # Odpowiedź zapisu też według poziomu kwot klucza.
        assert cost.json()["amount"] is None
        assert cost.json()["costs_redacted"] is True
        sale = await app_client.post(
            f"{V1}/invoices",
            headers=_h(writer, str(uuid.uuid4())),
            json=_invoice(seeded["contract_id"], f"FV/{uuid.uuid4().hex[:6]}"),
        )
        assert sale.status_code == 201, sale.text

        params = {"contract_id": seeded["contract_id"]}
        _, reader = await _key(
            app_client, app_auth_headers, ["invoices:read", "sales_amounts:read"]
        )
        listed = await app_client.get(
            f"{V1}/invoices", headers=_h(reader), params=params
        )
        assert listed.status_code == 200, listed.text
        amounts = {i["direction"]: i["amount"] for i in listed.json()["items"]}
        assert amounts == {"from_contractor": None, "to_client": "1234.50"}
        one = await app_client.get(
            f"{V1}/invoices/{cost.json()['id']}", headers=_h(reader)
        )
        assert one.json()["amount"] is None

        _, full = await _key(
            app_client, app_auth_headers, ["invoices:read", "amounts:read"]
        )
        listed = await app_client.get(f"{V1}/invoices", headers=_h(full), params=params)
        amounts = {i["direction"]: i["amount"] for i in listed.json()["items"]}
        assert amounts == {"from_contractor": "999.00", "to_client": "1234.50"}
        assert all(i["costs_redacted"] is False for i in listed.json()["items"])

    async def test_direction_flip_cannot_reveal_a_contractor_invoice_amount(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        """Przegląd bezpieczeństwa: ``PATCH`` z ``direction: to_client`` na
        fakturze od kontraktora odsłaniał kwotę kosztu (i zostawał w bazie).
        Bez ``amounts:read`` zmiana kierunku z/na ``from_contractor`` = 403."""
        seeded = await _seed_order(tag="inv-flip")
        _, writer = await _key(app_client, app_auth_headers, ["invoices:write"])
        cost = await app_client.post(
            f"{V1}/invoices",
            headers=_h(writer, str(uuid.uuid4())),
            json={
                **_invoice(seeded["contract_id"], f"K/{uuid.uuid4().hex[:6]}"),
                "direction": "from_contractor",
                "amount": "777.00",
            },
        )
        assert cost.status_code == 201, cost.text
        cost_id = cost.json()["id"]
        sale = await app_client.post(
            f"{V1}/invoices",
            headers=_h(writer, str(uuid.uuid4())),
            json=_invoice(seeded["contract_id"], f"FV/{uuid.uuid4().hex[:6]}"),
        )
        assert sale.status_code == 201, sale.text

        for invoice_id, direction in (
            (cost_id, "to_client"),
            (cost_id, "from_contractor"),
            (sale.json()["id"], "from_contractor"),
        ):
            flip = await app_client.patch(
                f"{V1}/invoices/{invoice_id}",
                headers=_h(writer, str(uuid.uuid4())),
                json={"direction": direction},
            )
            assert flip.status_code == 403, flip.text
            assert flip.json()["error"]["code"] == "insufficient_scope"
            assert flip.json()["error"]["details"]["missing"] == ["amounts:read"]
            assert "777" not in flip.text

        # Inna zmiana przechodzi, a kwota kosztu dalej jest ukryta.
        noted = await app_client.patch(
            f"{V1}/invoices/{cost_id}",
            headers=_h(writer, str(uuid.uuid4())),
            json={"notes": "korekta opisu"},
        )
        assert noted.status_code == 200, noted.text
        assert noted.json()["amount"] is None
        stored = await app_client.get(f"{V1}/invoices/{cost_id}", headers=_h(writer))
        assert stored.json()["direction"] == "from_contractor"
        assert stored.json()["amount"] is None

        # Z amounts:read zmiana kierunku działa jak dotąd.
        _, full = await _key(
            app_client, app_auth_headers, ["invoices:write", "amounts:read"]
        )
        flipped = await app_client.patch(
            f"{V1}/invoices/{cost_id}",
            headers=_h(full, str(uuid.uuid4())),
            json={"direction": "to_client"},
        )
        assert flipped.status_code == 200, flipped.text
        assert flipped.json()["amount"] == "777.00"


# ── Finanse: koszty i marża tylko z amounts:read ────────────────────────────

_RESULTS_PERIOD = (2041, 11)


async def _seed_finance_results() -> None:
    """Jeden wiersz wyników za 11.2041 (poprzednie biegi okresu usunięte —
    indeks „jedna aktualna wersja miesiąca”, baza wspólna dla przebiegu)."""
    from sqlalchemy import delete

    year, month = _RESULTS_PERIOD
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(FinanceImportRun).where(
                FinanceImportRun.period_year == year,
                FinanceImportRun.period_month == month,
            )
        )
        run = FinanceImportRun(
            period_year=year,
            period_month=month,
            source_filename="wyniki-v1.xlsx",
            file_path="finance/v1-test/wyniki-v1.xlsx",
            row_count=1,
        )
        db.add(run)
        await db.flush()
        db.add(
            FinanceMonthlyResult(
                import_run_id=run.id,
                row_number=1,
                consultant_name="Osoba Testowa",
                client_name="Klient Testowy",
                cost_rate_md=Decimal("800.00"),
                md_count=Decimal("10"),
                compensation=Decimal("8000.00"),
                revenue_rate_md=Decimal("1000.00"),
                invoice_amount=Decimal("10000.00"),
                margin_pln=Decimal("2000.00"),
                margin_pct=Decimal("20.00"),
            )
        )
        await db.commit()


class TestFinanceCosts:
    @pytest.mark.parametrize(
        "extra", [[], ["sales_amounts:read"]], ids=["finance", "finance+sales"]
    )
    async def test_results_hide_costs_and_margin_without_amounts_read(
        self, app_client: AsyncClient, app_auth_headers: dict, extra: list[str]
    ):
        await _seed_finance_results()
        year, month = _RESULTS_PERIOD
        _, api_key = await _key(app_client, app_auth_headers, ["finance:read", *extra])
        resp = await app_client.get(
            f"{V1}/finance/results",
            headers=_h(api_key),
            params={"year": year, "month": month},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["costs_redacted"] is True
        row = body["rows"][0]
        for field in (
            "cost_rate_md",
            "compensation",
            "margin_pln",
            "margin_pct",
            "margin_percent",
        ):
            assert row[field] is None, field
        # Sprzedaż i liczba MD zostają — to moduł rozliczeń.
        assert row["revenue_rate_md"] == 1000.0
        assert row["invoice_amount"] == 10000.0
        assert row["md_count"] == 10.0
        totals = body["totals"]
        assert totals["revenue"] == 10000.0
        for field in ("cost", "margin", "avg_margin_pct", "cost_without_margin"):
            assert totals[field] is None, field

    async def test_results_with_amounts_read_show_costs(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        await _seed_finance_results()
        year, month = _RESULTS_PERIOD
        _, api_key = await _key(
            app_client, app_auth_headers, ["finance:read", "amounts:read"]
        )
        resp = await app_client.get(
            f"{V1}/finance/results",
            headers=_h(api_key),
            params={"year": year, "month": month},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["costs_redacted"] is False
        assert body["rows"][0]["compensation"] == 8000.0
        assert body["rows"][0]["margin_pln"] == 2000.0
        assert body["totals"]["cost"] == 8000.0
        assert body["totals"]["margin"] == 2000.0

    async def test_cost_rate_change_amounts_and_history_need_amounts_read(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        from app.services.order_change_audit import stamp_service_account

        today = business_today()
        u = uuid.uuid4().hex[:8]
        async with AsyncSessionLocal() as db:
            client = Client(name=f"V1 Koszt {u}")
            cand = Candidate(
                name="Iga", lastname=f"Koszt-{u}", email=f"v1k-{u}@example.com"
            )
            db.add_all([client, cand])
            await db.flush()
            contract = Contract(
                candidate_id=cand.id,
                client_id=client.id,
                status=ContractStatus.active,
                start_date=today - timedelta(days=60),
            )
            db.add(contract)
            await db.flush()
            order = ClientOrder(
                contract_id=contract.id,
                client_id=client.id,
                title=f"ZAM-KOSZT-{u}",
                status=ClientOrderStatus.active,
                start_date=today - timedelta(days=30),
                end_date=today + timedelta(days=60),
                rate_candidate=Decimal("100.00"),
                rate_client=Decimal("150.00"),
            )
            db.add(order)
            await db.commit()
            order_id = order.id
        async with AsyncSessionLocal() as db:
            stamp_service_account(db.info, 424244)
            stamped = await db.get(ClientOrder, order_id)
            stamped.rate_candidate = Decimal("110.00")
            await db.commit()

        params = {"year": today.year, "month": today.month}
        _, finance = await _key(app_client, app_auth_headers, ["finance:read"])
        audit = await app_client.get(
            f"{V1}/finance/order-changes", headers=_h(finance), params=params
        )
        assert audit.status_code == 200, audit.text
        assert audit.json()["costs_redacted"] is True
        mine = [
            i
            for i in audit.json()["changes"]
            if i["order_id"] == order_id and i["kind"] == "rate_cost"
        ]
        assert mine, "zmiana stawki kosztowej nie trafiła do audytu miesiąca"
        assert mine[0]["old_amount"] is None and mine[0]["new_amount"] is None

        history = await app_client.get(
            f"{V1}/finance/order-changes/history",
            headers=_h(finance),
            params={"order_id": order_id},
        )
        assert history.status_code == 200, history.text
        assert history.json()["costs_redacted"] is True
        text = " ".join(e["summary"] for e in history.json()["items"])
        assert "Zmiana stawki kosztowej" in text
        assert "110,00" not in text and "100,00" not in text

        _, full = await _key(
            app_client, app_auth_headers, ["finance:read", "amounts:read"]
        )
        audit = await app_client.get(
            f"{V1}/finance/order-changes", headers=_h(full), params=params
        )
        mine = [
            i
            for i in audit.json()["changes"]
            if i["order_id"] == order_id and i["kind"] == "rate_cost"
        ]
        assert audit.json()["costs_redacted"] is False
        assert mine[0]["new_amount"] == 110.0
        history = await app_client.get(
            f"{V1}/finance/order-changes/history",
            headers=_h(full),
            params={"order_id": order_id},
        )
        assert "110,00" in " ".join(e["summary"] for e in history.json()["items"])


# ── Faktury: idempotencja, duplikat, dry_run, ślad ───────────────────────────


def _invoice(contract_id: int, number: str) -> dict:
    return {
        "contract_id": contract_id,
        "direction": "to_client",
        "invoice_number": number,
        "issue_date": "2041-02-01",
        "due_date": "2041-03-01",
        "amount": "1234.50",
        "currency": "PLN",
    }


class TestInvoicesWrite:
    async def test_write_requires_idempotency_key(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_order(tag="inv-nokey")
        _, api_key = await _key(app_client, app_auth_headers, ["invoices:write"])
        resp = await app_client.post(
            f"{V1}/invoices",
            headers=_h(api_key),
            json=_invoice(seeded["contract_id"], "FV/1"),
        )
        assert resp.status_code == 400, resp.text
        assert resp.json()["error"]["code"] == "idempotency_key_required"

    async def test_replay_returns_the_same_invoice_once(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_order(tag="inv-replay")
        account, api_key = await _key(app_client, app_auth_headers, ["invoices:write"])
        idem = str(uuid.uuid4())
        payload = _invoice(seeded["contract_id"], f"FV/{uuid.uuid4().hex[:6]}")
        first = await app_client.post(
            f"{V1}/invoices", headers=_h(api_key, idem), json=payload
        )
        assert first.status_code == 201, first.text
        again = await app_client.post(
            f"{V1}/invoices", headers=_h(api_key, idem), json=payload
        )
        assert again.status_code == 201, again.text
        assert again.headers.get("Idempotent-Replayed") == "true"
        assert again.json()["id"] == first.json()["id"]
        assert first.json()["amount"] == "1234.50"

        listed = await app_client.get(
            f"{V1}/invoices",
            headers=_h(api_key),
            params={"contract_id": seeded["contract_id"]},
        )
        assert listed.json()["total"] == 1

        writes = await app_client.get(
            f"{ACCOUNTS_URL}/{account['id']}/writes", headers=app_auth_headers
        )
        assert writes.status_code == 200, writes.text
        assert [w["route"] for w in writes.json()] == [f"{V1}/invoices"]

        async with AsyncSessionLocal() as db:
            event = await db.scalar(
                select(CriticalEvent).where(
                    CriticalEvent.entity_type == "invoice",
                    CriticalEvent.entity_id == first.json()["id"],
                )
            )
        assert event is not None
        assert event.event_type == "invoice.create"
        assert event.actor_user_id is None
        assert event.actor_name == f"Integracja: {account['name']}"

    async def test_same_key_with_other_payload_is_409(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_order(tag="inv-reuse")
        _, api_key = await _key(app_client, app_auth_headers, ["invoices:write"])
        idem = str(uuid.uuid4())
        first = await app_client.post(
            f"{V1}/invoices",
            headers=_h(api_key, idem),
            json=_invoice(seeded["contract_id"], f"FV/{uuid.uuid4().hex[:6]}"),
        )
        assert first.status_code == 201, first.text
        other = await app_client.post(
            f"{V1}/invoices",
            headers=_h(api_key, idem),
            json=_invoice(seeded["contract_id"], f"FV/{uuid.uuid4().hex[:6]}"),
        )
        assert other.status_code == 409
        assert other.json()["error"]["code"] == "idempotency_key_reused"

    async def test_duplicate_number_is_409_and_dry_run_writes_nothing(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_order(tag="inv-dup")
        _, api_key = await _key(app_client, app_auth_headers, ["invoices:write"])
        number = f"FV/{uuid.uuid4().hex[:6]}"
        trial = await app_client.post(
            f"{V1}/invoices",
            headers=_h(api_key),
            params={"dry_run": "true"},
            json=_invoice(seeded["contract_id"], number),
        )
        assert trial.status_code == 200, trial.text
        assert trial.json() == {"valid": True, "dry_run": True}

        created = await app_client.post(
            f"{V1}/invoices",
            headers=_h(api_key, str(uuid.uuid4())),
            json=_invoice(seeded["contract_id"], number),
        )
        assert created.status_code == 201, created.text
        dup = await app_client.post(
            f"{V1}/invoices",
            headers=_h(api_key, str(uuid.uuid4())),
            json=_invoice(seeded["contract_id"], f" {number.lower()} "),
        )
        assert dup.status_code == 409, dup.text
        assert dup.json()["error"]["code"] == "duplicate_invoice"

    async def test_cancel_keeps_the_record(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_order(tag="inv-cancel")
        _, api_key = await _key(app_client, app_auth_headers, ["invoices:write"])
        created = await app_client.post(
            f"{V1}/invoices",
            headers=_h(api_key, str(uuid.uuid4())),
            json=_invoice(seeded["contract_id"], f"FV/{uuid.uuid4().hex[:6]}"),
        )
        invoice_id = created.json()["id"]
        resp = await app_client.post(
            f"{V1}/invoices/{invoice_id}/cancel",
            headers=_h(api_key, str(uuid.uuid4())),
            json={"reason": "błędny numer"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "cancelled"

    async def test_read_scope_cannot_write(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        seeded = await _seed_order(tag="inv-ro")
        _, api_key = await _key(app_client, app_auth_headers, ["invoices:read"])
        resp = await app_client.post(
            f"{V1}/invoices",
            headers=_h(api_key, str(uuid.uuid4())),
            json=_invoice(seeded["contract_id"], "FV/RO"),
        )
        assert resp.status_code == 403


# ── Import MD: dry_run, duplikat pliku, autor ───────────────────────────────


def _sheet(rows: list[tuple[str, float]]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Imię i nazwisko", "Ilość MD"])
    for name, md in rows:
        ws.append([name, md])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _period() -> str:
    today = business_today()
    return (date(today.year, today.month, 1) - timedelta(days=40)).strftime("%Y-%m")


class TestMdImport:
    async def test_dry_run_then_import_then_duplicate(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        account, api_key = await _key(app_client, app_auth_headers, ["md:write"])
        content = _sheet([(f"Nieznana Osoba {uuid.uuid4().hex[:6]}", 3)])
        files = {
            "file": (
                "raport.xlsx",
                content,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        }
        data = {"period_month": _period()}

        trial = await app_client.post(
            f"{V1}/md/imports",
            headers=_h(api_key),
            params={"dry_run": "true"},
            files=files,
            data=data,
        )
        assert trial.status_code == 200, trial.text
        assert trial.json()["dry_run"] is True
        assert trial.json()["rows_total"] == 1

        import hashlib

        digest = hashlib.sha256(content).hexdigest()
        async with AsyncSessionLocal() as db:
            assert (
                await db.scalar(
                    select(MdConsumptionImport.id).where(
                        MdConsumptionImport.file_sha256 == digest
                    )
                )
            ) is None

        real = await app_client.post(
            f"{V1}/md/imports",
            headers=_h(api_key, str(uuid.uuid4())),
            files=files,
            data=data,
        )
        assert real.status_code == 201, real.text
        assert real.json()["uploaded_by_service_account_id"] == account["id"]

        dup = await app_client.post(
            f"{V1}/md/imports",
            headers=_h(api_key, str(uuid.uuid4())),
            files=files,
            data=data,
        )
        assert dup.status_code == 409, dup.text
        assert dup.json()["error"]["code"] == "duplicate_import"
        assert dup.json()["error"]["details"]["import_id"] == real.json()["id"]

        forced = await app_client.post(
            f"{V1}/md/imports",
            headers=_h(api_key, str(uuid.uuid4())),
            params={"force": "true"},
            files=files,
            data=data,
        )
        assert forced.status_code == 201, forced.text


# ── Finanse ─────────────────────────────────────────────────────────────────


class TestFinanceChecks:
    async def test_check_replay_and_uncheck(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        """Ścieżka sukcesu — do przeglądu PR 2A zwracała 500 (``done`` był
        obiektem ``OrderItemCheck``/``None``, a schemat v1 oczekiwał bool)."""
        from app.services.order_change_audit import stamp_service_account

        today = business_today()
        u = uuid.uuid4().hex[:8]
        async with AsyncSessionLocal() as db:
            client = Client(name=f"V1 Check {u}")
            cand = Candidate(
                name="Ewa", lastname=f"Zmiana-{u}", email=f"v1c-{u}@example.com"
            )
            db.add_all([client, cand])
            await db.flush()
            contract = Contract(
                candidate_id=cand.id,
                client_id=client.id,
                status=ContractStatus.active,
                start_date=today - timedelta(days=60),
            )
            db.add(contract)
            await db.flush()
            order = ClientOrder(
                contract_id=contract.id,
                client_id=client.id,
                title=f"ZAM-CHK-{u}",
                status=ClientOrderStatus.active,
                start_date=today - timedelta(days=30),
                end_date=today + timedelta(days=60),
                rate_candidate=Decimal("100.00"),
                rate_client=Decimal("150.00"),
            )
            db.add(order)
            await db.commit()
            order_id = order.id
        async with AsyncSessionLocal() as db:
            stamp_service_account(db.info, 424243)
            stamped = await db.get(ClientOrder, order_id)
            stamped.rate_client = Decimal("155.00")
            await db.commit()

        account, api_key = await _key(app_client, app_auth_headers, ["finance:write"])
        audit = await app_client.get(
            f"{V1}/finance/order-changes",
            headers=_h(api_key),
            params={"year": today.year, "month": today.month},
        )
        assert audit.status_code == 200, audit.text
        mine = [i for i in audit.json()["changes"] if i["order_id"] == order_id]
        assert mine, "zmiana stawki nie trafiła do audytu miesiąca"
        assert mine[0]["source"] == "integration"
        key = mine[0]["item_key"]

        idem = str(uuid.uuid4())
        body = {"year": today.year, "month": today.month, "item_key": key, "done": True}
        done = await app_client.post(
            f"{V1}/finance/order-changes/checks", headers=_h(api_key, idem), json=body
        )
        assert done.status_code == 200, done.text
        assert done.json()["done"] is True
        assert done.json()["by_name"] == f"Integracja: {account['name']}"

        replay = await app_client.post(
            f"{V1}/finance/order-changes/checks", headers=_h(api_key, idem), json=body
        )
        assert replay.status_code == 200
        assert replay.headers.get("Idempotent-Replayed") == "true"

        undone = await app_client.post(
            f"{V1}/finance/order-changes/checks",
            headers=_h(api_key, str(uuid.uuid4())),
            json={**body, "done": False},
        )
        assert undone.status_code == 200, undone.text
        assert undone.json()["done"] is False

    async def test_error_after_receipt_is_not_remembered(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        """4xx po rezerwacji klucza wycofuje paragon — ta sama powtórka
        dostaje ten sam błąd, nie wieczne 409 „trwa” (przegląd PR 2A)."""
        _, api_key = await _key(app_client, app_auth_headers, ["invoices:write"])
        idem = str(uuid.uuid4())
        payload = _invoice(2_000_000_000, f"FV/{uuid.uuid4().hex[:6]}")
        first = await app_client.post(
            f"{V1}/invoices", headers=_h(api_key, idem), json=payload
        )
        assert first.status_code == 404, first.text
        again = await app_client.post(
            f"{V1}/invoices", headers=_h(api_key, idem), json=payload
        )
        assert again.status_code == 404, again.text

    async def test_unknown_item_is_409(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        _, api_key = await _key(app_client, app_auth_headers, ["finance:write"])
        today = business_today()
        resp = await app_client.post(
            f"{V1}/finance/order-changes/checks",
            headers=_h(api_key, str(uuid.uuid4())),
            json={
                "year": today.year,
                "month": today.month,
                "item_key": "chg:ev:0",
                "done": True,
            },
        )
        assert resp.status_code == 409, resp.text
        assert resp.json()["error"]["code"] == "item_not_in_month"


# ── Autor zmiany zamówienia = konto serwisowe ───────────────────────────────


class TestOrderChangeSource:
    async def test_rate_change_in_a_stamped_session_is_recorded_as_integration(self):
        from app.services.order_change_audit import stamp_service_account

        seeded = await _seed_order(tag="source")
        async with AsyncSessionLocal() as db:
            stamp_service_account(db.info, 424242)
            order = await db.get(ClientOrder, seeded["order_id"])
            order.rate_client = Decimal("160.00")
            await db.commit()
        async with AsyncSessionLocal() as db:
            event = await db.scalar(
                select(OrderChangeEvent)
                .where(OrderChangeEvent.order_id == seeded["order_id"])
                .order_by(OrderChangeEvent.id.desc())
            )
        assert event is not None
        assert event.source == "integration"
        assert event.created_by_service_account_id == 424242
        assert event.created_by_user_id is None
