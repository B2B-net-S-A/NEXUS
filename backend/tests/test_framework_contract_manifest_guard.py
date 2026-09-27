"""Runda 10 (R10-N12-1): umowa ramowa z manifestu portfela jest chroniona.

``get_client_portfolio_import_health`` wymaga, żeby umowy ``client_excel``
istniały i miały daty z manifestu. PATCH dat i trwałe usunięcie szkicu
z UI przestawiały ``/api/health/deep`` na 503 bez samonaprawy — lustro
reguły zakresów portfela (``client_directory.py``).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api import client_framework_contracts as api
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractStatus,
)
from app.schemas.client_framework_contract import ClientFrameworkContractUpdate


def _fc(*, source_system: str, status=FrameworkContractStatus.active):
    fc = ClientFrameworkContract(
        client_id=7,
        name="MSA",
        status=status,
        currency="PLN",
        source_system=source_system,
        effective_date=date(2026, 1, 1),
        expiry_date=date(2027, 12, 31),
    )
    fc.id = 41
    return fc


def _db(fc):
    db = MagicMock()
    db.scalar = AsyncMock(return_value=fc)
    db.commit = AsyncMock()
    db.delete = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.fixture(autouse=True)
def _writable(monkeypatch):
    monkeypatch.setattr(api, "assert_client_writable", AsyncMock())
    monkeypatch.setattr(api, "_validate_references", AsyncMock())


@pytest.mark.asyncio
async def test_patch_dates_of_manifest_contract_is_refused():
    fc = _fc(source_system="client_excel")
    db = _db(fc)
    with pytest.raises(HTTPException) as exc:
        await api.update_framework_contract(
            7,
            41,
            ClientFrameworkContractUpdate(expiry_date=date(2030, 1, 1)),
            SimpleNamespace(id=1),
            db,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "framework_contract_from_manifest"
    assert exc.value.detail["fields"] == ["expiry_date"]
    assert fc.expiry_date == date(2027, 12, 31)
    db.commit.assert_not_awaited()


def test_manifest_contract_accepts_unchanged_dates_from_full_form():
    fc = _fc(source_system="client_excel")
    # Formularz odsyła komplet pól — te same daty nie są zmianą.
    api._assert_manifest_dates_untouched(
        fc,
        {
            "effective_date": date(2026, 1, 1),
            "expiry_date": date(2027, 12, 31),
            "name": "MSA 2",
        },
    )


@pytest.mark.parametrize("source_system", ["manual", "ezdrowie_seed"])
def test_dates_of_other_contracts_stay_editable(source_system):
    fc = _fc(source_system=source_system)
    api._assert_manifest_dates_untouched(fc, {"expiry_date": date(2030, 1, 1)})


@asynccontextmanager
async def _fake_audit(*_args, **_kwargs):
    yield SimpleNamespace(describe=lambda **_k: None, result_note=None)


@pytest.mark.asyncio
async def test_hard_delete_of_manifest_draft_is_refused(monkeypatch):
    monkeypatch.setattr(api, "audited_deletion", _fake_audit)
    fc = _fc(source_system="client_excel", status=FrameworkContractStatus.draft)
    db = _db(fc)
    with pytest.raises(HTTPException) as exc:
        await api.delete_framework_contract(7, 41, SimpleNamespace(id=1), db)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "framework_contract_from_manifest"
    db.delete.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_manifest_active_contract_can_still_be_superseded(monkeypatch):
    monkeypatch.setattr(api, "audited_deletion", _fake_audit)
    fc = _fc(source_system="client_excel")
    db = _db(fc)
    await api.delete_framework_contract(7, 41, SimpleNamespace(id=1), db)
    assert fc.status == FrameworkContractStatus.superseded
    db.delete.assert_not_awaited()
