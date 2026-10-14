"""Umowa API integracyjnego v1 z automatyzacjami (bez bazy).

Automatyzacje (n8n, Power Automate, Make, skrypty) budują się na kształcie
odpowiedzi v1. Trasy ekranów zmieniają się kilka razy dziennie — v1 nie może
się zmienić po cichu. Dlatego:

* snapshot specyfikacji v1 (``tests/data/integrations_v1_openapi.json``):
  każda zmiana kształtu = czerwony test i diff w PR-ze. Dodanie pola jest
  zgodne wstecz; usunięcie albo zmiana znaczenia pola = nowa wersja (v2).
  Odświeżenie: ``INTEGRATIONS_V1_SNAPSHOT_WRITE=1 python -m pytest
  tests/test_integrations_v1_contract.py``;
* każda trasa v1 ma kopertę błędu v1, bramkę klucza API i NIE zależy od
  JWT użytkownika (``get_current_user``) — inaczej klucz dziedziczyłby
  ścieżkę ekranu.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi.routing import APIRoute

from app.api.integrations_v1.common import PREFIX, IntegrationRoute
from app.api.integrations_v1.meta import integrations_openapi
from app.main import app
from tests._route_introspection import iter_api_routes

SNAPSHOT = Path(__file__).parent / "data" / "integrations_v1_openapi.json"


def _v1_routes() -> list[tuple[str, APIRoute]]:
    return [
        (path, route) for path, route in iter_api_routes(app) if path.startswith(PREFIX)
    ]


def _dependency_names(dependant) -> set[str]:
    names: set[str] = set()
    stack = list(dependant.dependencies)
    while stack:
        dep = stack.pop()
        call = dep.call
        names.add(getattr(call, "__qualname__", repr(call)))
        stack.extend(dep.dependencies)
    return names


def test_v1_spec_matches_the_snapshot() -> None:
    spec = integrations_openapi(app.openapi())
    rendered = json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if os.environ.get("INTEGRATIONS_V1_SNAPSHOT_WRITE") == "1":
        SNAPSHOT.write_text(rendered, encoding="utf-8")
    assert SNAPSHOT.exists(), (
        "brak snapshotu — uruchom z INTEGRATIONS_V1_SNAPSHOT_WRITE=1"
    )
    assert rendered == SNAPSHOT.read_text(encoding="utf-8"), (
        "Kształt API v1 zmienił się. Zmiana zgodna wstecz (nowe pole, nowa trasa): "
        "odśwież snapshot (INTEGRATIONS_V1_SNAPSHOT_WRITE=1) i pokaż diff w PR-ze. "
        "Usunięcie albo zmiana znaczenia pola: to jest v2, nie v1."
    )


def test_every_v1_route_uses_the_v1_envelope_and_a_key_gate() -> None:
    routes = _v1_routes()
    assert len(routes) >= 30, "test przestał widzieć trasy v1"
    for path, route in routes:
        assert isinstance(route, IntegrationRoute), path
        names = _dependency_names(route.dependant)
        assert any("require_service_scope" in name for name in names), (path, names)
        assert not any(name.endswith("get_current_user") for name in names), (
            path,
            names,
        )
        assert not any(name.endswith("get_authenticated_user") for name in names), (
            path,
            names,
        )


def test_writes_are_documented_with_idempotency() -> None:
    """Każdy zapis v1 jest w specyfikacji — integrator wie, że potrzebuje
    ``Idempotency-Key`` (opis w ``info.description`` i w dokumentacji)."""
    spec = integrations_openapi(app.openapi())
    writes = [
        (path, method)
        for path, item in spec["paths"].items()
        for method in item
        if method in {"post", "put", "patch"}
    ]
    assert writes, "brak zapisów w specyfikacji v1"
    assert "Idempotency-Key" in spec["info"]["description"]


def _caller(*scopes: str):
    from app.api.deps import Caller
    from app.services.service_account_auth import ServicePrincipal

    return Caller(
        service=ServicePrincipal(
            account_id=1, slug="test", key_id="v2$00", scopes=frozenset(scopes)
        )
    )


def test_md_import_rows_hide_invoice_amounts_without_amounts_read() -> None:
    """``md:read`` jest operacyjny: kwoty faktur z wierszy kosztowych, surowe
    „Uwagi” i pominięte wiersze arkusza tylko z ``amounts:read`` (przegląd
    bezpieczeństwa PR 2A)."""
    from datetime import datetime, timezone
    from decimal import Decimal

    from app.api.integrations_v1.md import _without_amounts
    from app.schemas.md_consumption import ImportDetail, ImportRowRead

    detail = ImportDetail(
        id=1,
        period_month="2026-09",
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        rows=[
            ImportRowRead(
                id=1,
                row_number=2,
                consultant_name="Osoba Testowa",
                md_reported=Decimal("3"),
                status="cost_only",
                status_label="Koszt",
                notes_raw="faktura 12 300 zł",
                invoice_amount=Decimal("12300.00"),
            )
        ],
        skipped_rows=[{"row": 5, "values": ["x", "9 999 zł"]}],
    )
    hidden = _without_amounts(detail, _caller("md:read"))
    assert hidden.rows[0].invoice_amount is None
    assert hidden.rows[0].notes_raw is None
    assert hidden.skipped_rows == []
    assert hidden.rows[0].md_reported == Decimal("3")

    shown = _without_amounts(detail, _caller("md:read", "amounts:read"))
    assert shown.rows[0].invoice_amount == Decimal("12300.00")

    sales = _without_amounts(detail, _caller("md:read", "sales_amounts:read"))
    assert sales.rows[0].invoice_amount == Decimal("12300.00")
    assert sales.rows[0].notes_raw == "faktura 12 300 zł"


# ── Kwoty w dwóch poziomach (decyzja Artura 14.10.2026) ─────────────────────


def test_amount_level_from_scopes() -> None:
    """``amounts:read`` = wszystkie kwoty, także bez ``implied_scopes``."""
    from app.api.integrations_v1.common import AmountLevel, amount_level
    from app.models.service_account import implied_scopes

    assert amount_level(_caller("orders:read")) is AmountLevel.none
    assert amount_level(_caller("sales_amounts:read")) is AmountLevel.sales
    assert amount_level(_caller("amounts:read")) is AmountLevel.all
    assert amount_level(_caller(*implied_scopes(frozenset({"amounts:write"})))) is (
        AmountLevel.all
    )
    assert AmountLevel.none < AmountLevel.sales < AmountLevel.all


def _change(kind: str, **fields):
    from datetime import date
    from decimal import Decimal

    from app.schemas.finance_order_changes import OrderChangeItem

    defaults = dict(
        order_id=7,
        client_name="Klient Testowy",
        consultant_name="Osoba Testowa",
        order_number="ZAM/1",
        kind=kind,
        effective_date=date(2026, 10, 1),
        rate_cost=Decimal("1234.56"),
        rate_revenue=Decimal("1500.00"),
        rate_unit="md",
        currency="PLN",
        previous_order_number="ZAM/0",
        previous_end_date=date(2026, 9, 30),
        other_client_names=["Inny Klient"],
        previous_client_name="Inny Klient",
    )
    return OrderChangeItem(**{**defaults, **fields})


def test_change_descriptions_lose_the_cost_but_keep_the_sale() -> None:
    """Opisy budują prawdziwe funkcje ekranu — zmiana ich treści zapali ten
    test, zanim koszt wycieknie w opisie historii albo odhaczenia."""
    from decimal import Decimal

    from app.api.integrations_v1.finance import _summary_without_costs
    from app.models.order_change_event import OrderChangeEvent
    from app.services.order_change_checks import _event_summary, item_summary

    for kind in ("additional_project", "order_continuation", "client_change"):
        text = item_summary("changes", _change(kind))
        assert "1 234,56" in text, text
        hidden = _summary_without_costs(text)
        assert "1 234,56" not in hidden, hidden
        assert "koszt ukryty" in hidden
        assert "1 500,00" in hidden, hidden
        # Opis odhaczenia bywa ucięty w środku kwoty kosztu.
        cut = text[: text.index("1 234,56") + 4]
        assert "1 23" not in _summary_without_costs(cut)

    cost_change = _change(
        "rate_cost", old_amount=Decimal("1111.11"), new_amount=Decimal("2222.22")
    )
    for text in (
        item_summary("changes", cost_change),
        _event_summary(
            OrderChangeEvent(
                field="rate_cost",
                old_amount=Decimal("1111.11"),
                new_amount=Decimal("2222.22"),
                old_unit="md",
                new_unit="md",
                currency="PLN",
            )
        ),
    ):
        hidden = _summary_without_costs(text)
        assert "1 111,11" not in hidden and "2 222,22" not in hidden, hidden
        assert hidden.startswith("Zmiana stawki kosztowej")

    sale_change = item_summary(
        "changes",
        _change("rate_revenue", old_amount=Decimal("1500"), new_amount=Decimal("1600")),
    )
    assert _summary_without_costs(sale_change) == sale_change


def test_draft_item_key_hides_rates_and_only_the_hidden_key_checks() -> None:
    """Klucz szkicu niesie stawki — bez ``amounts:read`` idzie skrót, a pełny
    klucz nie jest przyjmowany (200/409 nie może zdradzać zgadniętej stawki)."""
    from datetime import date
    from decimal import Decimal

    from app.api.integrations_v1.finance import _find_item, _hidden_item_key
    from app.schemas.finance_order_changes import (
        OrderChangesCounts,
        OrderChangesPeriod,
        OrderChangesResponse,
        OrderEntryItem,
    )
    from app.services.order_change_checks import item_key

    entry = OrderEntryItem(
        order_id=9,
        client_name="Klient Testowy",
        consultant_name="Osoba Testowa",
        order_number="ZAM/9",
        start_date=date(2026, 10, 1),
        rate_cost=Decimal("987.65"),
        rate_revenue=Decimal("1200.00"),
        order_type="periodic",
        status="draft",
    )
    real = item_key("entries", entry)
    assert "987.65" in real
    hidden = _hidden_item_key(real)
    assert "987" not in hidden and hidden.startswith("entry:9:draft:h")
    assert _hidden_item_key("chg:ev:12") == "chg:ev:12"
    changed = entry.model_copy(update={"rate_cost": Decimal("987.66")})
    assert _hidden_item_key(item_key("entries", changed)) != hidden

    response = OrderChangesResponse(
        period=OrderChangesPeriod(year=2026, month=10, label="Październik 2026"),
        counts=OrderChangesCounts(changes=0, entries=1, exits=0, ending=0, gaps=0),
        changes=[],
        entries=[entry],
        exits=[],
        ending_orders=[],
        gaps=[],
        gaps_tracked_since=date(2026, 1, 1),
        open_gaps_total=0,
    )
    assert _find_item(response, hidden, costs=False) == ("entries", entry)
    assert _find_item(response, real, costs=False) is None
    assert _find_item(response, real, costs=True) == ("entries", entry)
    assert _find_item(response, hidden, costs=True) is None


def test_order_changes_without_costs() -> None:
    from decimal import Decimal

    from app.api.integrations_v1.finance import _changes_without_costs
    from app.schemas.finance_order_changes import OrderChangesResponse

    cost_change = _change(
        "rate_cost", old_amount=Decimal("1"), new_amount=Decimal("2"), event_id=3
    )
    sale_change = _change(
        "rate_revenue", old_amount=Decimal("5"), new_amount=Decimal("6"), event_id=4
    )
    response = OrderChangesResponse.model_construct(
        changes=[cost_change, sale_change],
        entries=[],
        exits=[],
        ending_orders=[],
        superseded=[],
    )
    hidden = _changes_without_costs(response)
    cost, sale = hidden["changes"]
    assert cost.old_amount is None and cost.new_amount is None
    assert cost.rate_cost is None and cost.rate_revenue == Decimal("1500.00")
    assert sale.old_amount == Decimal("5") and sale.new_amount == Decimal("6")
    assert sale.rate_cost is None


def test_finance_results_without_costs() -> None:
    from decimal import Decimal

    from app.api.integrations_v1.finance import _results_out
    from app.schemas.finance import (
        FinanceResultRow,
        FinanceResultsResponse,
        FinanceTotals,
    )

    result = FinanceResultsResponse(
        year=2026,
        month=9,
        run_id=1,
        rows=[
            FinanceResultRow(
                id=1,
                row_number=1,
                consultant_name="Osoba Testowa",
                cost_rate_md=Decimal("800"),
                md_count=Decimal("10"),
                compensation=Decimal("8000"),
                revenue_rate_md=Decimal("1000"),
                invoice_amount=Decimal("10000"),
                margin_pln=Decimal("2000"),
                margin_pct=Decimal("20"),
                margin_percent=Decimal("20"),
            )
        ],
        totals=FinanceTotals(
            cost=Decimal("8000"),
            revenue=Decimal("10000"),
            margin=Decimal("2000"),
            avg_margin_pct=Decimal("20"),
        ),
        needs_completion_count=0,
    )
    hidden = _results_out(result, costs=False).model_dump(mode="json")
    assert hidden["costs_redacted"] is True
    row = hidden["rows"][0]
    assert [row[f] for f in ("cost_rate_md", "compensation", "margin_pln")] == [
        None,
        None,
        None,
    ]
    assert row["margin_pct"] is None and row["margin_percent"] is None
    assert row["revenue_rate_md"] == 1000.0 and row["invoice_amount"] == 10000.0
    assert hidden["totals"]["revenue"] == 10000.0
    assert hidden["totals"]["cost"] is None and hidden["totals"]["margin"] is None
    assert hidden["totals"]["cost_without_margin"] is None

    shown = _results_out(result, costs=True).model_dump(mode="json")
    assert shown["costs_redacted"] is False
    assert shown["rows"][0]["compensation"] == 8000.0
    assert shown["totals"]["cost"] == 8000.0


def test_contractor_invoice_amount_only_with_all_amounts() -> None:
    from datetime import date, datetime, timezone
    from decimal import Decimal

    from app.api.integrations_v1.common import AmountLevel
    from app.api.integrations_v1.invoices import invoice_out
    from app.models.invoice import Invoice, InvoiceDirection, InvoiceStatus

    def invoice(direction: InvoiceDirection) -> Invoice:
        now = datetime(2026, 10, 14, tzinfo=timezone.utc)
        return Invoice(
            id=1,
            contract_id=2,
            direction=direction,
            invoice_number="FV/1",
            issue_date=date(2026, 10, 1),
            amount=Decimal("999.00"),
            currency="PLN",
            status=InvoiceStatus.issued,
            created_at=now,
            updated_at=now,
        )

    cost = invoice(InvoiceDirection.from_contractor)
    sale = invoice(InvoiceDirection.to_client)
    for level in (AmountLevel.none, AmountLevel.sales):
        assert invoice_out(cost, level=level).amount is None
        assert invoice_out(cost, level=level).costs_redacted is True
        assert invoice_out(sale, level=level).amount == Decimal("999.00")
    assert invoice_out(cost, level=AmountLevel.all).amount == Decimal("999.00")
    assert invoice_out(cost, level=AmountLevel.all).costs_redacted is False
    # Odpowiedź na zmianę: kierunek sprzed zmiany decyduje o ukryciu kwoty.
    assert invoice_out(sale, level=AmountLevel.sales, cost=True).amount is None


def test_contract_annex_pdfs_need_amounts_read() -> None:
    """Aneks przedłużający umowę bywa aneksem z konsultantem i może podawać
    jego stawkę — lista i ZIP pomijają go bez ``amounts:read``."""
    from types import SimpleNamespace

    from app.api.integrations_v1.finance import _visible_pdf_entries

    entries = [
        SimpleNamespace(kind="order", id=1),
        SimpleNamespace(kind="group", id=2),
        SimpleNamespace(kind="amendment", id=3),
    ]
    for scopes in (("finance:read",), ("finance:read", "sales_amounts:read")):
        visible = _visible_pdf_entries(entries, _caller(*scopes))
        assert [entry.kind for entry in visible] == ["order", "group"]
    full = _visible_pdf_entries(entries, _caller("finance:read", "amounts:read"))
    assert [entry.kind for entry in full] == ["order", "group", "amendment"]


async def test_contract_annex_pdf_file_is_refused_without_amounts_read() -> None:
    import pytest
    from fastapi import HTTPException
    from starlette.requests import Request

    from app.api.integrations_v1.finance import order_pdf_file

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/integrations/v1/finance/order-pdfs/amendment/3/file",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 1),
            "app": app,
        }
    )
    with pytest.raises(HTTPException) as refused:
        await order_pdf_file(
            request,
            kind="amendment",
            entry_id=3,
            caller=_caller("finance:read", "sales_amounts:read"),
            db=None,
        )
    assert refused.value.status_code == 403
    assert refused.value.detail["missing"] == ["amounts:read"]
