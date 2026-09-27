"""Runda 9 audytu (27.09.2026) — zamówienia i kontrakty (kod MONEY).

Każdy test odtwarza jedno znalezisko (R9-V1-1..6, R9-N9-8). Testy z bazą
zakładają dane przez ``_seed`` z ``test_order_line_takeover`` (zamówienie MD
per osoba: Konrad + Kamila).
"""

from __future__ import annotations

import ast
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.core.scheduling import business_today
from app.models.client_order import ClientOrderStatus
from app.models.contract import Contract, ContractStatus, ContractType

_BACKEND = Path(__file__).resolve().parents[1]


def _functions(path: str) -> dict[str, ast.AST]:
    tree = ast.parse((_BACKEND / path).read_text())
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
    }


def _calls(fn: ast.AST, name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == name
    ]


def _has_true_kw(call: ast.Call, kw: str) -> bool:
    return any(
        k.arg == kw and isinstance(k.value, ast.Constant) and k.value.value is True
        for k in call.keywords
    )


class _ScalarDb:
    """Atrapa sesji: kolejne ``scalar`` zwracają kolejne wartości."""

    def __init__(self, *values) -> None:
        self._values = list(values)
        self.added: list[object] = []

    async def scalar(self, *_args, **_kwargs):
        return self._values.pop(0) if self._values else None

    def add(self, row: object) -> None:
        self.added.append(row)


def _client(**overrides):
    base = {
        "id": 7,
        "name": "Duplikat Sp. z o.o.",
        "deleted_at": None,
        "merged_into_client_id": None,
        "hidden": False,
        "display_name": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ── R9-V1-1: zapisy zamówień u klienta SCALONEGO ────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "module_path", ["app.api.client_orders", "app.api.client_order_groups"]
)
async def test_order_write_refuses_a_merged_client_but_read_does_not(module_path):
    import importlib

    module = importlib.import_module(module_path)
    merged = _client(merged_into_client_id=9)
    target = _client(id=9, name="Główny S.A.")

    # Odczyt — historia scalonego klienta zostaje dostępna.
    assert await module._assert_client(_ScalarDb(merged), 7) is merged

    with pytest.raises(HTTPException) as exc:
        await module._assert_client(
            _ScalarDb(merged, merged, target), 7, for_write=True
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "client_merged"
    assert exc.value.detail["merged_into_client_id"] == 9


def test_every_order_write_route_asks_for_a_writable_client():
    """Zapisy (POST/PATCH zamówień, grup, linii, przedłużenie) — ``for_write``."""
    writes = {
        "app/api/client_orders.py": {
            "create_order_extension",
            "update_order",
            "create_contract_with_order",
            "replace_order_po",
        },
        "app/api/client_order_groups.py": {
            "create_order_group",
            "update_order_group",
            "replace_order_group_file",
            "_group_accepting_lines",
            "update_line",
            "take_over_consultant",
            "swap_consultant",
        },
    }
    for path, names in writes.items():
        functions = _functions(path)
        for name in names:
            calls = _calls(functions[name], "_assert_client")
            assert calls, f"{path}:{name} nie pyta o klienta"
            assert all(_has_true_kw(c, "for_write") for c in calls), (
                f"{path}:{name} przyjmuje zapis u scalonego klienta"
            )
    groups = _functions("app/api/client_order_groups.py")
    for name in ("reopen_order_group", "restore_order_group", "extend_order_group"):
        calls = _calls(groups[name], "_require_order_lifecycle")
        assert calls and all(_has_true_kw(c, "for_write") for c in calls), name
    # Odczyty zostają bez bramki scalenia.
    for name in ("_require_group_read", "_require_safe_group_read"):
        assert not any(
            _has_true_kw(c, "for_write") for c in _calls(groups[name], "_assert_client")
        )


# ── R9-V1-2: aktywacja kontraktu usuniętego / scalonego klienta ─────────────


def _complete_draft(**overrides) -> Contract:
    contract = Contract(
        id=overrides.pop("id", 990001),
        client_id=overrides.pop("client_id", 7),
        status=overrides.pop("status", ContractStatus.draft),
        start_date=business_today(),
        rate_candidate=150,
        rate_client=200,
        contract_type=ContractType.b2b,
    )
    return contract


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "gone_client, code",
    [
        (_client(deleted_at=date(2026, 9, 1)), "client_deleted"),
        (_client(merged_into_client_id=9), "client_merged"),
    ],
)
async def test_activation_refuses_a_contract_of_a_gone_client(gone_client, code):
    from app.services import contract_lifecycle as lifecycle

    contract = _complete_draft()
    db = _ScalarDb(gone_client)
    with pytest.raises(HTTPException) as exc:
        await lifecycle.activate_contract(db, contract, actor_id=1)  # type: ignore[arg-type]
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == code
    assert contract.status == ContractStatus.draft
    assert db.added == []


@pytest.mark.asyncio
async def test_activation_of_a_live_client_contract_still_works():
    from app.services import contract_lifecycle as lifecycle

    contract = _complete_draft()
    db = _ScalarDb(_client())
    await lifecycle.activate_contract(db, contract, actor_id=1)  # type: ignore[arg-type]
    assert contract.status == ContractStatus.active


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "gone_client",
    [_client(deleted_at=date(2026, 9, 1)), _client(merged_into_client_id=9)],
)
async def test_auto_activation_skips_a_gone_client_without_raising(gone_client):
    """Zapis kontraktu i synchronizacja (także nocna) nie mogą paść na 422."""
    from app.services import contract_lifecycle as lifecycle

    contract = _complete_draft()
    changed = await lifecycle.auto_activate_complete_draft(
        _ScalarDb(gone_client),  # type: ignore[arg-type]
        contract,
        actor_id=None,
        status_explicit=False,
    )
    assert changed is False
    assert contract.status == ContractStatus.draft


# ── R9-V1-4: sync_md_line_status a umowa unieważniona ───────────────────────


@pytest.mark.asyncio
async def test_md_line_of_a_void_contract_is_not_revived(monkeypatch):
    from app.services import client_order_lines

    async def _no(*_args, **_kwargs):
        return False

    monkeypatch.setattr(client_order_lines, "_has_successor_line", _no)
    monkeypatch.setattr(client_order_lines, "_has_open_offboarding_case", _no)

    class _Db:
        async def get(self, *_args, **_kwargs):
            return SimpleNamespace(status=ContractStatus.void)

        async def scalar(self, *_args, **_kwargs):
            return 0

    line = SimpleNamespace(
        id=1,
        contract_id=2,
        md_total=Decimal("10"),
        md_remaining=Decimal("5"),
        status=ClientOrderStatus.completed,
        end_date=None,
    )
    assert await client_order_lines.sync_md_line_status(_Db(), line) is False  # type: ignore[arg-type]
    assert line.status == ClientOrderStatus.completed


# ── R9-V1-5: przedłużenie a zakończona umowa wykonawcza ─────────────────────


def test_extension_inherits_only_an_active_executive_contract():
    fn = _functions("app/api/client_order_groups.py")["extend_order_group"]
    assert _calls(fn, "inheritable_executive_contract_id"), (
        "przedłużenie kopiuje umowę wykonawczą bez sprawdzenia, czy trwa"
    )


# ── R9-V1-6: etykieta etapu `interview` w kreatorze metryk ──────────────────


def test_interview_milestone_is_labelled_qc_cv_on_both_sides():
    from app.services.custom_metrics.definition import STAGE_LABELS_PL

    assert STAGE_LABELS_PL["interview"] == "QC CV"
    describe = (
        _BACKEND.parent / "frontend/src/lib/dashboard-tiles/describe.ts"
    ).read_text()
    assert 'interview: "QC CV"' in describe


# ── R9-N9-8: Compass — „bez projektu” liczy okres grupy ─────────────────────


def test_lacks_current_order_reads_the_group_period_of_a_dateless_line():
    from app.api.integrations_compass import _lacks_current_order

    today = date(2026, 9, 27)
    old_group = SimpleNamespace(start_date=date(2025, 1, 1), end_date=date(2025, 6, 30))
    line = SimpleNamespace(
        status=ClientOrderStatus.active,
        start_date=None,
        end_date=None,
        order_group_id=5,
        order_group=old_group,
    )
    contract = SimpleNamespace(client_orders=[line])
    assert _lacks_current_order(contract, today) is True

    line.order_group = SimpleNamespace(start_date=date(2026, 1, 1), end_date=None)
    assert _lacks_current_order(contract, today) is False

    standalone = SimpleNamespace(
        status=ClientOrderStatus.active,
        start_date=date(2026, 9, 1),
        end_date=None,
        order_group_id=None,
        order_group=None,
    )
    assert (
        _lacks_current_order(SimpleNamespace(client_orders=[standalone]), today)
        is False
    )


# ── Testy z bazą ────────────────────────────────────────────────────────────


def _group_url(seed: dict, suffix: str = "") -> str:
    return f"/api/clients/{seed['client_id']}/order-groups/{seed['group_id']}{suffix}"


async def _mark_client_merged(client_id: int) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        target = Client(name=f"R9Target-{uuid.uuid4().hex[:6]}")
        db.add(target)
        await db.flush()
        client = await db.get(Client, client_id)
        client.merged_into_client_id = target.id
        await db.commit()


@pytest.mark.asyncio
async def test_merged_client_order_group_cannot_be_edited_but_can_be_read(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from tests.test_order_line_takeover import _enable_multi, _seed

    seed = await _seed(source_state="leaving", with_case=False)
    _enable_multi(monkeypatch, seed["client_id"])
    await _mark_client_merged(seed["client_id"])

    resp = await app_client.patch(
        _group_url(seed), json={"notes": "po scaleniu"}, headers=app_auth_headers
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "client_merged"

    listed = await app_client.get(
        f"/api/clients/{seed['client_id']}/order-groups", headers=app_auth_headers
    )
    assert listed.status_code == 200, listed.text


@pytest.mark.asyncio
async def test_restore_ends_only_the_restored_line_not_other_orders_of_the_person(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """R9-V1-3: przyszłe zamówienie tej osoby nie jest anulowane przy restore."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.models.contract import RateUnit
    from app.models.order_type import OrderType
    from tests.test_audit_r8_md_orders import (
        _cancel_group_with_active_line,
        _end_contract,
    )
    from tests.test_order_line_takeover import _enable_multi, _seed

    seed = await _seed(source_state="leaving")
    _enable_multi(monkeypatch, seed["client_id"])
    await _cancel_group_with_active_line(seed)
    async with AsyncSessionLocal() as db:
        future = ClientOrder(
            client_id=seed["client_id"],
            contract_id=seed["konrad_contract_id"],
            order_type=OrderType.periodic,
            title="Przedłużenie (szkic) — R9",
            status=ClientOrderStatus.draft,
            start_date=business_today() + timedelta(days=30),
            end_date=None,
            rate_unit=RateUnit.hourly,
            billing_hours_per_month=168,
            currency="PLN",
            rate_client_currency="PLN",
            rate_candidate_currency="PLN",
            md_manual_adjustment=Decimal("0"),
        )
        db.add(future)
        await db.commit()
        future_id = future.id
    yesterday = business_today() - timedelta(days=1)
    await _end_contract(seed["konrad_contract_id"], "ended", yesterday)

    resp = await app_client.post(_group_url(seed, "/restore"), headers=app_auth_headers)
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        konrad = await db.get(ClientOrder, seed["line_id"])
        other = await db.get(ClientOrder, future_id)
    assert konrad.status == ClientOrderStatus.completed
    assert other.status == ClientOrderStatus.draft
    assert other.end_date is None


async def _close_group_as_cost_order(seed: dict) -> None:
    """Zamówienie kosztowe zamknięte ręcznie; linia była aktywna do +10 dni."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.models.client_order_group import (
        GROUP_STATUS_COMPLETED,
        ClientOrderGroup,
        ClientOrderGroupEvent,
    )
    from app.models.md_consumption import ClientOrderMdConsumption
    from app.models.order_type import OrderType
    from app.services.multi_consultant_orders import EVENT_ORDER_CLOSED
    from sqlalchemy import delete

    today = business_today()
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ClientOrderMdConsumption).where(
                ClientOrderMdConsumption.order_id == seed["line_id"]
            )
        )
        group = await db.get(ClientOrderGroup, seed["group_id"])
        group.order_type = OrderType.cost
        group.md_budget_mode = None
        group.is_cost_based = True
        group.is_md_budget_based = False
        group.budget_amount = Decimal("10000")
        group.budget_remaining = Decimal("10000")
        group.status = GROUP_STATUS_COMPLETED
        group.closure_date = today
        group.closure_reason = "Test R9"
        line = await db.get(ClientOrder, seed["line_id"])
        line.order_type = OrderType.cost
        line.md_optional_total = None
        line.md_total = None
        line.md_remaining = None
        line.md_input_mode = None
        line.md_input_value = None
        line.status = ClientOrderStatus.completed
        line.end_date = today + timedelta(days=10)
        db.add(
            ClientOrderGroupEvent(
                group_id=group.id,
                event_type=EVENT_ORDER_CLOSED,
                description="Zakończono zamówienie (test R9)",
                payload={
                    "lines": [
                        {
                            "id": line.id,
                            "previous_status": "active",
                            "previous_end_date": line.end_date.isoformat(),
                        }
                    ]
                },
            )
        )
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("contract_status", ["void", "ended"])
async def test_reopen_does_not_revive_a_cost_line_of_a_void_or_ended_contract(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, contract_status
):
    """R9-V1-4: unieważniona zostaje zakończona, zakończona przechodzi offboarding."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from tests.test_audit_r8_md_orders import _end_contract
    from tests.test_order_line_takeover import _enable_multi, _seed

    seed = await _seed(source_state="leaving", with_case=False)
    _enable_multi(monkeypatch, seed["client_id"])
    await _close_group_as_cost_order(seed)
    yesterday = business_today() - timedelta(days=1)
    await _end_contract(
        seed["konrad_contract_id"],
        contract_status,
        None if contract_status == "void" else yesterday,
    )

    resp = await app_client.post(_group_url(seed, "/reopen"), headers=app_auth_headers)
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, seed["line_id"])
    assert line.status == ClientOrderStatus.completed
    if contract_status == "ended":
        assert line.end_date == yesterday


@pytest.mark.asyncio
async def test_reopen_does_not_revive_an_md_line_of_a_void_contract(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.models.client_order_group import (
        GROUP_STATUS_COMPLETED,
        ClientOrderGroup,
    )
    from tests.test_audit_r8_md_orders import _end_contract
    from tests.test_order_line_takeover import _enable_multi, _seed

    seed = await _seed(source_state="leaving", with_case=False)
    _enable_multi(monkeypatch, seed["client_id"])
    async with AsyncSessionLocal() as db:
        group = await db.get(ClientOrderGroup, seed["group_id"])
        group.status = GROUP_STATUS_COMPLETED
        group.closure_date = business_today()
        group.closure_reason = "Test R9"
        line = await db.get(ClientOrder, seed["line_id"])
        line.status = ClientOrderStatus.completed
        await db.commit()
    await _end_contract(seed["konrad_contract_id"], "void", None)

    resp = await app_client.post(_group_url(seed, "/reopen"), headers=app_auth_headers)
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, seed["line_id"])
    assert line.status == ClientOrderStatus.completed
