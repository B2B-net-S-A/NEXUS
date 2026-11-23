"""Raport T4T z maila (Nordea, 23.11.2026): arkusz wchodzi jako wersja raportu
miesiąca, ten sam plik drugi raz to duplikat, a bez jednego klienta z regułą T4T
plik zostaje zwykłym dokumentem. Osoby, numery i godziny fikcyjne."""

from __future__ import annotations

import base64
from datetime import date

import pytest

from app.core.database import AsyncSessionLocal
from app.services.client_settlements import t4t_mail, time_reports
from tests.test_client_audit_2026_09_24 import _client
from tests.test_client_time_reports_db import MONTH, _drop, _person, _rows, _view, _xlsx

pytestmark = pytest.mark.asyncio

FILE = "#microsoft.graph.fileAttachment"


def _files(content: bytes) -> list[dict]:
    return [
        {
            "@odata.type": FILE,
            "name": "B2B_net_SA_T4T_September_01.10.2026.xlsx",
            "isInline": False,
            "contentBytes": base64.b64encode(content).decode("ascii"),
        },
        {
            "@odata.type": FILE,
            "name": "image001.png",
            "isInline": True,
            "contentBytes": "",
        },
    ]


async def _ingest(files: list[dict]) -> t4t_mail.T4tMailResult:
    async with AsyncSessionLocal() as db:
        result = await t4t_mail.ingest(db, files, received_on=date(2026, 10, 1))
        await db.commit()
    return result


async def test_raport_z_maila_to_wersja_raportu_a_powtorka_to_duplikat(monkeypatch):
    client_id = await _client()
    jan = await _person(client_id, "Jan", "Mailowy")
    try:

        async def only_this(db, month):
            assert month == MONTH
            return [client_id]

        monkeypatch.setattr(time_reports, "enabled_clients", only_this)
        content = _xlsx(_rows("M000101", "Jan Mailowy"))
        first = await _ingest(_files(content))
        assert first.consumed == {0} and first.versions == 1 and first.duplicates == 0
        again = await _ingest(_files(content))
        assert again.consumed == {0} and again.versions == 0 and again.duplicates == 1
        view = await _view(client_id)
        assert [v["version_no"] for v in view["versions"]] == [1]
        assert view["versions"][0]["hours_approved"] == "176.00"
    finally:
        await _drop(client_id, [jan])


async def test_bez_jednego_klienta_z_regula_plik_zostaje_dokumentem(monkeypatch):
    async def nobody(db, month):
        return []

    monkeypatch.setattr(time_reports, "enabled_clients", nobody)
    content = _xlsx(_rows("M000102", "Ewa Mailowa"))
    result = await _ingest(_files(content))
    assert result.consumed == set() and result.versions == 0


async def test_arkusz_spoza_t4t_nie_jest_raportem(monkeypatch):
    async def boom(db, month):
        raise AssertionError("zwykły arkusz nie pyta o klienta")

    monkeypatch.setattr(time_reports, "enabled_clients", boom)
    import io

    import openpyxl

    workbook = openpyxl.Workbook()
    workbook.active.append(["Data", "Godziny", "Opis"])
    workbook.active.append(["2026-09-01", 8, "praca"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    result = await _ingest(_files(buffer.getvalue()))
    assert result.consumed == set()
