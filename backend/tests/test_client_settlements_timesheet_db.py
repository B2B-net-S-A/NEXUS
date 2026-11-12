"""Rozliczenie klienta w godzinach na bazie (roadmapa E6.2). Dane fikcyjne.

Time Sheet z panelu → MD z godzin → przyjęcie → pozycje faktury do klienta
w euro (stawka klienta z linii zamówienia) → potwierdzenie usług per projekt.
Plik w trwającym miesiącu z regułą ``cl.estimate`` to plan: dokument ma etap
FORECAST, a faktura idzie z planu.
"""

from __future__ import annotations

import io
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import openpyxl
import pytest

from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now
from app.models.client_order import ClientOrder
from app.models.contract import RateUnit
from app.services.client_settlements import (
    client_invoice,
    service,
    service_confirmation,
)
from tests.test_client_settlements_client_invoice_db import _month, _rules
from tests.test_client_settlements_consultant_db import _module, _restore
from tests.test_client_settlements_service_db import _cleanup, _world

pytestmark = pytest.mark.asyncio

ACTOR = SimpleNamespace(id=None)
RULES = {
    "proof.month": {"level": "block", "params": {}},
    "proof.excel_with_mail": {"level": "off", "params": {"domain": ""}},
    "proof.name_match": {"level": "off", "params": {}},
    "fields.md_hours": {"level": "block", "params": {"hours": "8"}},
    "fields.md_month_limit": {"level": "off", "params": {}},
}


def _timesheet(month: str, rows: list[tuple[int, str, str, int, str | None]]) -> bytes:
    year, mon = (int(x) for x in month.split("-"))
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([None, "Time Sheet"])
    ws.append([None, "Project Name", "ALFA"])
    ws.append([None, "Consultant(s)", "Osoba Testowa"])
    ws.append([None, "Date from", datetime(year, mon, 1)])
    ws.append(
        [
            None,
            "Date",
            "Project",
            "Description",
            "Total Hours",
            "Billable",
            "Non-billable",
            "Nr strumienia",
        ]
    )
    for day, project, description, hours, task in rows:
        ws.append(
            [
                None,
                datetime(year, mon, day),
                project,
                description,
                hours,
                hours,
                None,
                task,
            ]
        )
    ws.append([None, None, None, "Total Hours (This Week)", None, None])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


async def _euro_line(line_id: int) -> None:
    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, line_id)
        line.rate_client = Decimal("250")
        line.rate_client_currency = "EUR"
        line.rate_unit = RateUnit.daily
        line.md_rate_revenue = Decimal("1075")
        line.md_rate_cost = Decimal("800")
        await db.commit()


async def _store(contract_id: int, month: str, content: bytes) -> None:
    from app.services.consultant_portal import documents

    year, mon = (int(x) for x in month.split("-"))
    async with AsyncSessionLocal() as db:
        await documents.store(
            db,
            contract_id=contract_id,
            kind="report",
            year=year,
            month=mon,
            content=content,
            file_name="Time Sheet.xlsx",
            channel="portal",
            now=local_now(),
        )
        await db.commit()


async def test_time_sheet_godziny_faktura_w_euro_i_dokument_per_projekt(
    tmp_path, monkeypatch
) -> None:
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    client_id, contract_id, line_id = await _world(md_total="60")
    month = _month(-1)
    previous = await _module(True)
    try:
        await _euro_line(line_id)
        await _rules(
            client_id,
            {
                **RULES,
                "cl.client_document": {
                    "level": "warn",
                    "params": {
                        "kind": "Service Delivery Confirmation",
                        "per": "projekt",
                        "from": month,
                    },
                },
            },
        )
        await _store(
            contract_id,
            month,
            _timesheet(
                month,
                [
                    (3, "", "Moduł A", 8, "ST-1"),
                    (4, "", "Moduł A", 8, "ST-1"),
                    (5, "", "Przegląd", 5, None),
                    (6, "BETA", "Wsparcie", 19, None),
                ],
            ),
        )
        async with AsyncSessionLocal() as db:
            view = await service.month_view(db, client_id, month, amounts=True)
            row = next(r for r in view["rows"] if r["contract_id"] == contract_id)
            assert row["md_regular"] == "5.000"  # 40 h / 8
            assert row["status"] == "ok", row
            await service.accept(db, contract_id, month, actor=ACTOR, now=local_now())
            await db.commit()

        async with AsyncSessionLocal() as db:
            invoice = await client_invoice.invoice_month(
                db, client_id, month, amounts=True
            )
        item = next(r for r in invoice["rows"] if r["contract_id"] == contract_id)
        assert item["currency"] == "EUR"
        assert [
            (p["quantity"], p["unit_price"], p["currency"]) for p in item["positions"]
        ] == [("5", "250.00", "EUR")]
        assert item["net"] == "1250.00"
        # Marża w zł: 5 × 1075 − 5 × 800.
        assert item["margin"] == "1375.00"

        async with AsyncSessionLocal() as db:
            docs = await service_confirmation.collect(db, client_id, month)
            assert docs["enabled"] and docs["stage"] == "ACTUAL"
            by_project = {p["project"]: p for p in docs["projects"]}
            assert set(by_project) == {"ALFA", "BETA"}
            assert by_project["ALFA"]["md"] == "2.625"
            assert by_project["ALFA"]["tasks"] == 2
            assert by_project["BETA"]["hours"] == "19.00"
            assert "net" not in by_project["BETA"]

            monkeypatch.setattr(
                service_confirmation, "render_pdf", lambda html: html.encode()
            )
            content, name = await service_confirmation.document(
                db, client_id, month, "ALFA"
            )
        html = content.decode()
        assert name == f"SDC_ALFA_{month}.pdf"
        assert "<td>ST-1</td><td>Moduł A</td>" in html
        assert "<td>5h</td><td>Przegląd</td>" in html
        assert "TOTAL MDs: 2.625" in html
        assert "Osoba" not in html
        with pytest.raises(service.SettlementError):
            async with AsyncSessionLocal() as db:
                await service_confirmation.document(db, client_id, month, "GAMMA")
    finally:
        await _restore(previous)
        await _cleanup(client_id)


async def test_plan_trwajacego_miesiaca_daje_forecast_i_fakture_z_planu(
    tmp_path, monkeypatch
) -> None:
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    client_id, contract_id, line_id = await _world(md_total="60")
    before, month = _month(-1), _month(0)
    previous = await _module(True)
    try:
        await _euro_line(line_id)
        await _rules(
            client_id,
            {
                **RULES,
                "cl.estimate": {
                    "level": "warn",
                    "params": {"months": month.split("-")[1], "deadline": ""},
                },
                "cl.client_document": {
                    "level": "warn",
                    "params": {"kind": "SDC", "per": "projekt", "from": before},
                },
            },
        )
        await _store(
            contract_id,
            before,
            _timesheet(before, [(d, "", "Moduł A", 8, None) for d in range(1, 11)]),
        )
        async with AsyncSessionLocal() as db:
            await service.accept(db, contract_id, before, actor=ACTOR, now=local_now())
            await db.commit()
        await _store(
            contract_id,
            month,
            _timesheet(month, [(d, "", "Plan", 8, None) for d in range(1, 16)]),
        )
        async with AsyncSessionLocal() as db:
            plan = await service._settlement(
                db, contract_id, month, kind=service.ESTIMATE
            )
            assert plan is not None and plan.md_regular == Decimal("15.000")
            await service.accept(
                db,
                contract_id,
                month,
                actor=ACTOR,
                now=local_now(),
                kind=service.ESTIMATE,
            )
            await db.commit()
        async with AsyncSessionLocal() as db:
            invoice = await client_invoice.invoice_month(
                db, client_id, month, amounts=True
            )
            docs = await service_confirmation.collect(db, client_id, month)
            estimates = await client_invoice.estimates(
                db, client_id, month, amounts=True
            )
        item = next(r for r in invoice["rows"] if r["contract_id"] == contract_id)
        assert item["kind"] == "estimate" and item["net"] == "3750.00"
        assert docs["stage"] == "FORECAST"
        assert docs["projects"][0]["md"] == "15.000"
        plan_row = next(r for r in estimates["rows"] if r["contract_id"] == contract_id)
        # Dwie osobne faktury, obie w euro: 10 MD za poprzedni miesiąc i 15 MD planu.
        assert plan_row["currency"] == "EUR"
        assert (plan_row["previous_invoice"], plan_row["plan_invoice"]) == (
            "2500.00",
            "3750.00",
        )
    finally:
        await _restore(previous)
        await _cleanup(client_id)
