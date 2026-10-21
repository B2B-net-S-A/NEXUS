"""Zakładka „Zużycie” przy zamówieniu kosztowym (ticket 21.10.2026).

* Ręczny wpis kwoty za miesiąc schodzi ze WSPÓLNEGO budżetu zamówienia,
  przelicza „zafakturowano” i zdejmuje „Brak zejścia za {miesiąc}”.
* Przekroczenie wolno zapisać: nadwyżka zostaje nierozliczona, zamówienie
  przechodzi w „Wyczerpane”; usunięcie wpisu cofa oba skutki.
* Import Finansów nie nadpisuje ręcznego wpisu za ten sam miesiąc (decyzja
  Artura 21.10.2026) — wiersz arkusza dostaje ``manual_kept``.
* Każda liczba zakładki jest kwotą: bez dostępu do finansów 403.

Nazwiska, numery i kwoty są zmyślone (repo jest publiczne).
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0493_cost_consumption_manual_entry.py"


# ── Testy bez bazy ──────────────────────────────────────────────────────────


def test_manual_kept_status_and_columns_are_mirrored_in_entrypoint_and_migration():
    entrypoint = re.sub(r"\s+", " ", (BACKEND / "entrypoint.sh").read_text())
    migration = MIGRATION.read_text()
    assert "'manual_kept'" in entrypoint
    assert "'manual_kept'" in migration
    for column in ("status VARCHAR(16)", "note VARCHAR(255)"):
        assert (
            f"ALTER TABLE client_order_invoice_consumptions ADD COLUMN IF NOT EXISTS {column}"
            in entrypoint
        ), column
    assert "ck_invoice_consumptions_status" in entrypoint
    assert "ck_invoice_consumptions_status" in migration


def test_format_pln_is_polish():
    from decimal import Decimal

    from app.services.cost_orders import format_pln

    assert format_pln(Decimal("1540.000")) == "1 540,00 zł"
    assert format_pln(36310) == "36 310,00 zł"
    assert format_pln("0") == "0,00 zł"


# ── Testy z bazą ────────────────────────────────────────────────────────────

from tests.test_order_group_budget_redaction import _headers_for_role  # noqa: E402
from tests.test_order_lifecycle_and_cost import (  # noqa: E402
    _cost_line,
    _create_group,
    _enable_cost,
    _enable_multi,
    _finance_headers,
    _import_sheet,
    _md_line,
    _period,
    _seed_client_with_contracts,
    _sheet,
)


def _number() -> str:
    return f"450{uuid.uuid4().int % 10**7:07d}"


def _url(client_id: int, group: dict, line_id: int, month: str | None = None) -> str:
    base = (
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines/{line_id}"
        "/cost-consumptions"
    )
    return f"{base}/{month}" if month else base


async def _cost_group(app_client, headers, monkeypatch, *, people: int, budget: int):
    client_id, contracts, names = await _seed_client_with_contracts(people)
    _enable_multi(monkeypatch, client_id)
    _enable_cost(monkeypatch, client_id)
    number = _number()
    group = await _create_group(
        app_client,
        headers,
        client_id,
        [_cost_line(contract) for contract in contracts],
        order_number=number,
        is_cost_based=True,
        budget_amount=budget,
    )
    line_by_contract = {line["contract_id"]: line["id"] for line in group["lines"]}
    line_ids = [line_by_contract[contract] for contract in contracts]
    return client_id, group, line_ids, names, number


async def _group_row(app_client, headers, client_id: int, group_id: int) -> dict:
    resp = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return next(g for g in resp.json()["groups"] if g["id"] == group_id)


@pytest.mark.asyncio
async def test_manual_entry_takes_from_the_shared_budget_and_clears_missing_month(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, group, (line_a, line_b), names, number = await _cost_group(
        app_client, app_auth_headers, monkeypatch, people=2, budget=60000
    )
    finance = await _finance_headers(app_client)
    # Import za miesiąc ma fakturę tylko drugiej osoby — pierwsza dostaje
    # „Brak zejścia” (tak było z zamówieniem z ticketu).
    await _import_sheet(app_client, finance, _sheet([(names[1], 0, number, 18500)]))
    before = await _group_row(app_client, app_auth_headers, client_id, group["id"])
    flags = {line["id"]: line["missing_consumption_month"] for line in before["lines"]}
    assert flags[line_a] == _period()
    assert flags[line_b] is None

    resp = await app_client.put(
        _url(client_id, group, line_a, _period()),
        json={"invoice_amount": 23500, "status": "accepted", "note": "faktura 10/2026"},
        headers=app_auth_headers,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["budget_pool"] == pytest.approx(60000)
    assert body["budget_used"] == pytest.approx(42000)
    assert body["budget_remaining"] == pytest.approx(18000)
    [row] = body["rows"]
    assert row["source"] == "manual"
    assert row["status"] == "accepted"
    assert row["note"] == "faktura 10/2026"
    # Saldo ZAMÓWIENIA po miesiącu — z fakturą drugiej osoby, nie 36 500.
    assert row["balance_after"] == pytest.approx(18000)
    assert {p["order_id"]: p["invoiced"] for p in body["people"]} == {
        line_a: pytest.approx(23500),
        line_b: pytest.approx(18500),
    }
    assert len(body["group_rows"]) == 2

    after = await _group_row(app_client, app_auth_headers, client_id, group["id"])
    lines = {line["id"]: line for line in after["lines"]}
    assert lines[line_a]["missing_consumption_month"] is None
    assert lines[line_a]["invoiced_total"] == pytest.approx(23500)
    assert after["budget_remaining"] == pytest.approx(18000)

    history = await app_client.get(
        f"/api/clients/{client_id}/order-groups/{group['id']}/history",
        headers=app_auth_headers,
    )
    assert history.status_code == 200, history.text
    assert "23 500,00 zł" in history.text


@pytest.mark.asyncio
async def test_overflow_is_saved_exhausts_the_order_and_delete_restores_it(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, group, (line,), _names, _number_ = await _cost_group(
        app_client, app_auth_headers, monkeypatch, people=1, budget=10000
    )

    resp = await app_client.put(
        _url(client_id, group, line, _period()),
        json={"invoice_amount": 12000},
        headers=app_auth_headers,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["budget_remaining"] == pytest.approx(0)
    assert body["rows"][0]["settled_amount"] == pytest.approx(10000)
    assert body["rows"][0]["unsettled_amount"] == pytest.approx(2000)
    row = await _group_row(app_client, app_auth_headers, client_id, group["id"])
    assert row["status"] == "exhausted"

    removed = await app_client.delete(
        _url(client_id, group, line, _period()), headers=app_auth_headers
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["budget_remaining"] == pytest.approx(10000)
    assert removed.json()["rows"] == []
    row = await _group_row(app_client, app_auth_headers, client_id, group["id"])
    assert row["status"] == "active"

    again = await app_client.delete(
        _url(client_id, group, line, _period()), headers=app_auth_headers
    )
    assert again.status_code == 404


@pytest.mark.asyncio
async def test_finance_import_does_not_overwrite_the_manual_entry(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, group, (line,), names, number = await _cost_group(
        app_client, app_auth_headers, monkeypatch, people=1, budget=37850
    )
    resp = await app_client.put(
        _url(client_id, group, line, _period()),
        json={"invoice_amount": 1540},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    finance = await _finance_headers(app_client)

    # 1,75 MD jak w realnym wierszu arkusza: osoba bez linii MD, więc wiersz
    # jest „niedopasowany” po MD i dostaje opis z dopasowania kosztowego.
    detail = await _import_sheet(
        app_client, finance, _sheet([(names[0], 1.75, number, 9999)])
    )

    [import_row] = detail["rows"]
    assert import_row["cost_status"] == "manual_kept", detail
    assert "ręczny wpis" in (import_row["status_reason"] or ""), detail
    view = await app_client.get(_url(client_id, group, line), headers=app_auth_headers)
    assert view.status_code == 200, view.text
    [row] = view.json()["rows"]
    assert row["invoice_amount"] == pytest.approx(1540)
    assert row["source"] == "manual"
    assert view.json()["budget_remaining"] == pytest.approx(36310)


@pytest.mark.asyncio
async def test_role_without_finance_gets_403(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, group, (line,), _names, _number_ = await _cost_group(
        app_client, app_auth_headers, monkeypatch, people=1, budget=10000
    )
    headers = await _headers_for_role(app_client, "talent_community_manager", client_id)

    read = await app_client.get(_url(client_id, group, line), headers=headers)
    write = await app_client.put(
        _url(client_id, group, line, _period()),
        json={"invoice_amount": 100},
        headers=headers,
    )

    assert read.status_code == 403, read.text
    assert write.status_code == 403, write.text


@pytest.mark.asyncio
async def test_md_order_has_no_cost_consumptions(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contracts, _names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0])]
    )
    line = group["lines"][0]["id"]

    resp = await app_client.get(_url(client_id, group, line), headers=app_auth_headers)

    assert resp.status_code == 422, resp.text
