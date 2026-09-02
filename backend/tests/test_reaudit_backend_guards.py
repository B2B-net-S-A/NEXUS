"""Re-audit backend guards — F-03 / F-07 / F-13 (2026-07-22).

Covers three confirmed re-audit findings (F-01 is a shell/boot change with no
in-process surface):

- **F-03** — ``resolve_application_submission`` locks the submission row
  (``SELECT ... FOR UPDATE``) before mutating its status, so two concurrent
  resolves cannot both pass the ``pending_review`` check and double-process.
- **F-07** — ``GET /api/pipeline/overview`` is gated to ``OperationalUser``:
  the read-only ``user`` viewer gets 403; operational roles get 200.
- **F-13** — the ``client_orders`` GET endpoints redact rate/margin fields for
  TCM, while assigned Delivery Leads retain their narrow client exception, and
  ``list_contracts`` ignores rate/margin FILTERS for non-finance callers so the
  filter cannot be used as an oracle to binary-search a hidden rate.

Pattern mirrors ``test_contract_finance_redaction.py`` and
``test_candidate_module_access.py``: run in-process via ``app_client``; for a
denied role assert exactly 403, for an allowed role assert *not* 403.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient

_TODAY = date.today()


# ── Shared helpers ───────────────────────────────────────────────────────────


async def _headers_for(
    app_client: AsyncClient,
    role_value: str,
    *,
    assigned_client_id: int | None = None,
) -> dict[str, str]:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.team_structure import (
        ClientTacAssignment,
        DeliveryLeadClientAssignment,
    )
    from app.models.user import User, UserRole

    email = f"guard-{role_value}-{uuid.uuid4().hex[:8]}@example.com"
    password = f"P4ss_{uuid.uuid4().hex[:6]}!"
    async with AsyncSessionLocal() as db:
        role = UserRole(role_value)
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Guard {role_value}",
            role=role,
            roles=[role.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.flush()
        if assigned_client_id is not None and role is UserRole.delivery_lead:
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=user.id,
                    client_id=assigned_client_id,
                )
            )
        elif assigned_client_id is not None and role is UserRole.tac:
            db.add(
                ClientTacAssignment(
                    tac_user_id=user.id,
                    client_id=assigned_client_id,
                )
            )
        await db.commit()
    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# ── F-03: resolve submission locks the row ───────────────────────────────────


def test_resolve_submission_selects_for_update() -> None:
    """The resolve handler must acquire a row lock before the read-check-write.

    Without ``.with_for_update()`` two concurrent resolves both read status
    ``pending_review``, both pass the guard, and both link/merge/create — the
    submission is processed twice. A focused source assertion is enough: the
    lock is on the single SELECT that feeds the status mutation.
    """
    from app.api import application_submissions

    src = inspect.getsource(application_submissions.resolve_application_submission)
    assert ".with_for_update()" in src, (
        "resolve_application_submission must SELECT ... FOR UPDATE the submission "
        "row before mutating its status (F-03 row-lock)"
    )


# ── F-07: /pipeline/overview gated to OperationalUser ────────────────────────

_OVERVIEW_ROLES = [
    "admin",
    "head_of_recruitment",
    "delivery_lead",
    "talent_community_manager",
    "finance",
    "tac",
    "recruiter",
    "sourcer",
    "user",
]
_OVERVIEW_OPERATIONAL = {
    "admin",
    "head_of_recruitment",
    "delivery_lead",
    "talent_community_manager",
    "finance",
    "tac",
    "recruiter",
    "sourcer",
}


async def test_pipeline_overview_viewer_forbidden(app_client: AsyncClient) -> None:
    viewer = await _headers_for(app_client, "user")
    resp = await app_client.get("/api/pipeline/overview", headers=viewer)
    assert resp.status_code == 403, (
        f"viewer must not read /pipeline/overview, got {resp.status_code}"
    )


async def test_pipeline_overview_operational_ok(app_client: AsyncClient) -> None:
    recruiter = await _headers_for(app_client, "recruiter")
    resp = await app_client.get("/api/pipeline/overview", headers=recruiter)
    assert resp.status_code == 200, (
        f"operational role must read /pipeline/overview, got {resp.status_code}: "
        f"{resp.text}"
    )
    body = resp.json()
    assert "jobs" in body and "stage_labels" in body


async def test_pipeline_overview_role_matrix(app_client: AsyncClient) -> None:
    for role in _OVERVIEW_ROLES:
        headers = await _headers_for(app_client, role)
        resp = await app_client.get("/api/pipeline/overview", headers=headers)
        if role in _OVERVIEW_OPERATIONAL:
            assert resp.status_code != 403, (
                f"[{role}] /pipeline/overview unexpectedly forbidden"
            )
        else:
            assert resp.status_code == 403, (
                f"[{role}] /pipeline/overview expected 403, got {resp.status_code}"
            )


# ── F-13: client_orders redaction ────────────────────────────────────────────


async def _seed_client_order() -> tuple[int, int, int]:
    """Seed client + candidate + active contract + one order with amounts.

    Returns (client_id, order_id, contract_id).
    """
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import Contract, ContractStatus, RateUnit

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Ord",
            lastname=f"C-{uuid.uuid4().hex[:6]}",
            email=f"ordc-{uuid.uuid4().hex[:8]}@example.com",
        )
        client = Client(name=f"OrdClient-{uuid.uuid4().hex[:6]}")
        db.add_all([cand, client])
        await db.commit()
        await db.refresh(cand)
        await db.refresh(client)

        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=_TODAY - timedelta(days=10),
            end_date=_TODAY + timedelta(days=90),
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("150.000"),
            rate_unit=RateUnit.monthly,
            currency="PLN",
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)

        order = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            title="PO-guard",
            status=ClientOrderStatus.active,
            start_date=_TODAY - timedelta(days=5),
            end_date=_TODAY + timedelta(days=80),
            rate_client=Decimal("150.000"),
            total_value=Decimal("18000.00"),
            currency="PLN",
        )
        db.add(order)
        await db.commit()
        await db.refresh(order)
        return client.id, order.id, contract.id


async def test_client_orders_list_redacted_for_non_finance(
    app_client: AsyncClient,
) -> None:
    client_id, _order_id, contract_id = await _seed_client_order()
    tcm = await _headers_for(app_client, "talent_community_manager")

    resp = await app_client.get(f"/api/clients/{client_id}/orders", headers=tcm)
    assert resp.status_code == 200, resp.text
    contractors = resp.json()["contractors"]
    row = next((c for c in contractors if c["contract_id"] == contract_id), None)
    assert row is not None, "seeded contractor missing from list"
    # Record visible operationally, amounts nulled.
    assert row["rate_candidate"] is None
    assert row["latest_order_rate_client"] is None
    assert row["latest_order_monthly_margin"] is None
    assert row["orders"], "orders timeline should still be present"
    order_row = row["orders"][0]
    assert order_row["rate_client"] is None
    assert order_row["total_value"] is None
    assert order_row["monthly_margin"] is None
    assert order_row["currency"] is None


async def test_client_orders_list_shows_finance_to_assigned_delivery_lead(
    app_client: AsyncClient,
) -> None:
    """Przypisany Delivery Lead WIDZI kwoty zamówień swojego klienta.

    Świadome poszerzenie reguły z F-13/P0.12 („tylko admin"): DL prowadzi
    zamówienia klienta na co dzień i to on uzupełnia draft, więc odsyłanie
    każdej stawki do admina zamieniało rejestr w prośbę o czynność, której
    adresat nie mógł wykonać. Zakres pozostaje wąski — patrz trzy testy niżej:
    NIEprzypisany DL, TAC i head_of_recruitment nadal nie dostają nic.
    """
    client_id, _order_id, contract_id = await _seed_client_order()
    dl = await _headers_for(
        app_client,
        "delivery_lead",
        assigned_client_id=client_id,
    )

    resp = await app_client.get(f"/api/clients/{client_id}/orders", headers=dl)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    row = next(
        (c for c in body["contractors"] if c["contract_id"] == contract_id),
        None,
    )
    assert row is not None
    assert row["rate_candidate"] is not None
    # Front bramkuje pola stawek tą flagą — bez niej renderowałby kontrolkę,
    # która na zapisie kończy się 403.
    assert body["can_manage_finance"] is True


async def test_client_orders_hidden_from_unassigned_delivery_lead(
    app_client: AsyncClient,
) -> None:
    """DL BEZ przypisania do klienta nie dostaje ani kwot, ani rekordów.

    To jest właściwy dowód domknięcia poszerzenia: samo posiadanie roli
    `delivery_lead` niczego nie otwiera — liczy się jawne przypisanie.
    """
    client_id, _order_id, _contract_id = await _seed_client_order()
    dl = await _headers_for(app_client, "delivery_lead", assigned_client_id=None)

    resp = await app_client.get(f"/api/clients/{client_id}/orders", headers=dl)
    assert resp.status_code == 403, resp.text


async def test_get_order_redacted_for_non_finance(app_client: AsyncClient) -> None:
    client_id, order_id, _contract_id = await _seed_client_order()
    tcm = await _headers_for(app_client, "talent_community_manager")

    resp = await app_client.get(
        f"/api/clients/{client_id}/orders/{order_id}", headers=tcm
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == order_id  # record visible
    assert body["rate_client"] is None
    assert body["total_value"] is None
    assert body["monthly_margin"] is None
    assert body["currency"] is None


async def test_get_order_shows_finance_to_assigned_delivery_lead(
    app_client: AsyncClient,
) -> None:
    client_id, order_id, _contract_id = await _seed_client_order()
    dl = await _headers_for(
        app_client,
        "delivery_lead",
        assigned_client_id=client_id,
    )

    resp = await app_client.get(
        f"/api/clients/{client_id}/orders/{order_id}", headers=dl
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rate_client"] is not None


async def test_head_of_recruitment_never_gains_order_finance(
    app_client: AsyncClient,
) -> None:
    """HoR nie zyskuje kwot ani ich zapisu przy poszerzeniu dla DL.

    Sekcja Delivery odcina HoR przed handlerem, a lokalny predykat pozostaje
    drugą warstwą: samo przekazanie ``dl_assigned=True`` nie może zmienić
    innej persony w Delivery Leada.
    """
    from app.api import client_orders
    from app.models.user import UserRole as Role

    class _FakeUser:
        def __init__(self, role: Role) -> None:
            self._roles = {role}

        def has_role(self, role: Role) -> bool:
            return role in self._roles

    for role in (Role.head_of_recruitment, Role.tac, Role.recruiter):
        assert (
            client_orders._can_manage_order_finance(_FakeUser(role), dl_assigned=True)
            is False
        ), f"{role.value} nie może zarządzać kwotami zamówień"

    # A przypisany DL — może; nieprzypisany nie.
    assert (
        client_orders._can_manage_order_finance(
            _FakeUser(Role.delivery_lead), dl_assigned=True
        )
        is True
    )
    assert (
        client_orders._can_manage_order_finance(
            _FakeUser(Role.delivery_lead), dl_assigned=False
        )
        is False
    )


async def test_only_assigned_delivery_lead_can_rewrite_order_rate_unit(
    app_client: AsyncClient,
) -> None:
    """Jednostka jest snapshotem zamówienia, ale nadal wymaga przypisania DL.

    Zmiana ``rate_unit`` i ``billing_hours_per_month`` przelicza wyłącznie
    stawki jednego zamówienia. Nie zmienia Contract ani innych zamówień, więc
    przypisany Delivery Lead korzysta z tego samego uprawnienia co przy zapisie
    kwot; nieprzypisany DL pozostaje odcięty.
    """
    import pytest as _pytest
    from fastapi import HTTPException

    from app.api import client_orders
    from app.models.user import UserRole as Role

    class _FakeUser:
        def __init__(self, role: Role) -> None:
            self._roles = {role}

        def has_role(self, role: Role) -> bool:
            return role in self._roles

    dl = _FakeUser(Role.delivery_lead)
    # Kwoty — wolno.
    client_orders._assert_order_finance_write_allowed(
        dl, {"rate_client", "rate_candidate"}, can_finance=True
    )
    # Jednostka i liczba godzin są częścią snapshotu tego zamówienia — wolno.
    client_orders._assert_order_finance_write_allowed(
        dl,
        {"rate_client", "rate_unit", "billing_hours_per_month"},
        can_finance=True,
    )

    # Ten sam DL bez jawnego przypisania do klienta — nie.
    with _pytest.raises(HTTPException) as exc_info:
        client_orders._assert_order_finance_write_allowed(
            dl,
            {"rate_client", "rate_unit", "billing_hours_per_month"},
            can_finance=False,
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["fields"] == [
        "billing_hours_per_month",
        "rate_client",
        "rate_unit",
    ]

    # Admin — pełen zestaw, niezależnie od flagi.
    client_orders._assert_order_finance_write_allowed(
        _FakeUser(Role.admin),
        {"rate_client", "rate_unit", "billing_hours_per_month"},
        can_finance=False,
    )


async def test_client_order_reads_require_explicit_dl_assignment(
    app_client: AsyncClient,
) -> None:
    client_id, order_id, _contract_id = await _seed_client_order()

    paths = (
        f"/api/clients/{client_id}/orders",
        f"/api/clients/{client_id}/orders/{order_id}",
        f"/api/clients/{client_id}/orders/{order_id}/file",
    )
    unassigned = await _headers_for(app_client, "delivery_lead")
    for path in paths:
        denied = await app_client.get(path, headers=unassigned)
        assert denied.status_code == 403, (
            f"delivery_lead without explicit client assignment read {path}: "
            f"{denied.status_code} {denied.text}"
        )

    assigned = await _headers_for(
        app_client,
        "delivery_lead",
        assigned_client_id=client_id,
    )
    allowed_list = await app_client.get(paths[0], headers=assigned)
    assert allowed_list.status_code == 200, allowed_list.text
    allowed_detail = await app_client.get(paths[1], headers=assigned)
    assert allowed_detail.status_code == 200, allowed_detail.text
    missing_file = await app_client.get(paths[2], headers=assigned)
    assert missing_file.status_code == 404, missing_file.text

    # A legacy TAC-client relationship must not reopen the Delivery section.
    tac = await _headers_for(app_client, "tac", assigned_client_id=client_id)
    for path in paths:
        denied = await app_client.get(path, headers=tac)
        assert denied.status_code == 403, denied.text


# ── F-13: list_contracts filters ignored for non-finance (no oracle) ─────────


async def _seed_contract_for_client() -> tuple[int, int]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Flt",
            lastname=f"C-{uuid.uuid4().hex[:6]}",
            email=f"fltc-{uuid.uuid4().hex[:8]}@example.com",
        )
        client = Client(name=f"FltClient-{uuid.uuid4().hex[:6]}")
        db.add_all([cand, client])
        await db.commit()
        await db.refresh(cand)
        await db.refresh(client)
        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=_TODAY - timedelta(days=10),
            end_date=_TODAY + timedelta(days=90),
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("150.000"),
            margin=Decimal("50.000"),
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        return client.id, contract.id


async def test_list_contracts_rate_filter_ignored_for_non_finance(
    app_client: AsyncClient,
) -> None:
    """A rate filter must be ignored for TCM, which can read but not see rates.

    Otherwise TCM can binary-search the hidden ``rate_client`` by watching which
    rows survive ``rate_client_min`` — the filter becomes an oracle.
    """
    client_id, contract_id = await _seed_contract_for_client()
    tcm = await _headers_for(app_client, "talent_community_manager")

    # rate_client_min far above the real rate (150): a finance caller would get
    # zero rows, TCM must still see the contract because the filter is dropped.
    resp = await app_client.get(
        f"/api/contracts?client_id={client_id}&rate_client_min=999999",
        headers=tcm,
    )
    assert resp.status_code == 200, resp.text
    ids = {c["id"] for c in resp.json()["items"]}
    assert contract_id in ids, (
        "rate_client_min must be ignored for non-finance — the contract is gone, "
        "which leaks the hidden rate as an oracle"
    )
    # And the amounts are redacted in the payload.
    row = next(c for c in resp.json()["items"] if c["id"] == contract_id)
    assert row["rate_client"] is None
    assert row["rate_candidate"] is None
    assert row["margin"] is None


async def test_list_contracts_rate_filter_applies_for_finance(
    app_client: AsyncClient,
) -> None:
    """For admin (VIEW_FINANCE) the rate filter is honoured."""
    client_id, contract_id = await _seed_contract_for_client()
    admin = await _headers_for(app_client, "admin")

    # Above the real rate → excluded.
    excluded = await app_client.get(
        f"/api/contracts?client_id={client_id}&rate_client_min=999999",
        headers=admin,
    )
    assert excluded.status_code == 200, excluded.text
    assert contract_id not in {c["id"] for c in excluded.json()["items"]}

    # No rate filter → present, with rates visible.
    present = await app_client.get(
        f"/api/contracts?client_id={client_id}", headers=admin
    )
    assert present.status_code == 200, present.text
    row = next((c for c in present.json()["items"] if c["id"] == contract_id), None)
    assert row is not None
    assert row["rate_client"] is not None
