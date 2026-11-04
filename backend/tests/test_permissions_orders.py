"""Zamówienia za uprawnieniami z ekranu „Osoby i role” (02.10.2026).

Trzy reguły, które łatwo cofnąć:

* trasę otwiera UPRAWNIENIE, nie rola — także nadane osobie spoza domyślnych
  ról i wyłączone roli, która ma je domyślnie;
* kwoty i plik zamówienia wymagają podglądu kwot TEGO klienta: konto z rolą
  Delivery Leada ma go u klientów z przypisania, pozostali — u wszystkich;
* odmowa mówi, czego brakuje: nazwę uprawnienia albo zdanie o portfelu.

Pierwsza część (helpery) nie potrzebuje bazy. Scenariusze HTTP idą przez
in-process ``app_client``; baza testowa jest wspólna i nieczyszczona, więc
każdy test zakłada własnego klienta, osoby i konta.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.api import client_order_groups, client_orders
from app.api import order_mail_queue as queue
from app.core.scheduling import business_today
from app.models.user import User, UserRole
from app.services import permission_catalog
from app.services.access_scope import DL_CLIENT_OUT_OF_SCOPE_DETAIL
from tests._permission_grants import grant_permissions, role_permission
from tests.test_order_mail_apply_and_queue import seeded  # noqa: F401

CLIENT = 77
OTHER_CLIENT = 78

AMOUNTS_VIEW_LABEL = permission_catalog.label("amounts_view")
_PDF = b"%PDF-1.4\n% minimalny plik\n"


# ── Helpery: konta spoza bazy ───────────────────────────────────────────────


def _account(role: UserRole, *granted: str, without: tuple[str, ...] = ()) -> User:
    """Konto z rolą: jej domyślne uprawnienia plus ``granted``, minus ``without``.

    Oba zrzuty żądania (uprawnienia i wynikające z nich sekcje) ustawione
    razem — tak jak robi to uwierzytelnienie HTTP.
    """

    held = set(permission_catalog.default_permissions_for_role(role.value))
    held = (held | set(granted)) - set(without)
    effective = permission_catalog.close(held)
    user = User(id=1, email=f"{role.value}@example.com", role=role, roles=[role.value])
    user.effective_action_access = {key: "manage" for key in effective}
    user.effective_section_access = permission_catalog.derive_sections(effective)
    return user


def _order_editor_without_amounts() -> User:
    """Prowadzi zamówienia, nie widzi kwot (np. TCM z nadanym uprawnieniem)."""

    return _account(UserRole.talent_community_manager, "contracts_orders_edit")


async def _delivery_lead_boundary(user: User, _db: object) -> frozenset[int] | None:
    """Lustro resolvera przypisań: zbiór dla konta z rolą DL, inaczej ``None``."""

    return frozenset({CLIENT}) if user.has_role(UserRole.delivery_lead) else None


@pytest.mark.parametrize(
    ("account", "boundary", "can_read", "can_write"),
    [
        pytest.param(lambda: _account(UserRole.admin), None, True, True, id="admin"),
        pytest.param(
            lambda: _account(UserRole.finance), None, True, True, id="finance"
        ),
        pytest.param(
            lambda: _account(UserRole.delivery_lead),
            frozenset({CLIENT}),
            True,
            True,
            id="delivery-lead-assigned",
        ),
        pytest.param(
            lambda: _account(UserRole.delivery_lead),
            frozenset({OTHER_CLIENT}),
            False,
            False,
            id="delivery-lead-visible-but-unassigned",
        ),
        pytest.param(
            # Brak granicy u konta z rolą DL to błąd wołającego — odmowa.
            lambda: _account(UserRole.delivery_lead),
            None,
            False,
            False,
            id="delivery-lead-boundary-missing",
        ),
        pytest.param(
            lambda: _account(
                UserRole.delivery_lead, without=("contracts_orders_edit",)
            ),
            frozenset({CLIENT}),
            True,
            False,
            id="delivery-lead-with-order-editing-switched-off",
        ),
        pytest.param(
            lambda: _account(UserRole.talent_community_manager),
            None,
            False,
            False,
            id="delivery-view-only",
        ),
        pytest.param(
            _order_editor_without_amounts,
            None,
            False,
            False,
            id="order-editor-without-amounts-view",
        ),
        pytest.param(
            lambda: _account(
                UserRole.talent_community_manager,
                "contracts_orders_edit",
                "amounts_view",
            ),
            None,
            True,
            True,
            id="order-editor-with-amounts-view",
        ),
        pytest.param(
            lambda: _account(UserRole.recruiter, "amounts_view"),
            None,
            True,
            False,
            id="amounts-view-without-order-editing",
        ),
        pytest.param(
            lambda: _account(UserRole.recruiter, "amounts_edit"),
            None,
            True,
            True,
            id="amounts-edit-only",
        ),
        pytest.param(
            lambda: _account(UserRole.head_of_recruitment),
            frozenset({CLIENT}),
            False,
            False,
            id="no-delivery-permission",
        ),
    ],
)
def test_order_amounts_follow_permissions_and_assignment(
    account, boundary, can_read, can_write
) -> None:
    amounts = client_orders._order_amounts_within(account(), CLIENT, boundary)

    assert (amounts.can_read, amounts.can_write) == (can_read, can_write)


def test_amount_refusal_says_what_is_missing() -> None:
    """Stały kod i pola dla frontu + nazwa uprawnienia albo zdanie o portfelu."""

    # Prowadzi zamówienia, nie widzi kwot → brakuje podglądu kwot.
    detail = client_orders.amount_fields_forbidden(
        _order_editor_without_amounts(), ["rate_client"]
    ).detail
    assert detail["code"] == "finance_fields_forbidden"
    assert detail["fields"] == ["rate_client"]
    assert detail["permission"] == "amounts_view"
    assert detail["label"] == AMOUNTS_VIEW_LABEL
    assert AMOUNTS_VIEW_LABEL in detail["message"]

    # Komplet uprawnień, a mimo to odmowa → klient spoza przypisania. To nie
    # jest brak uprawnienia, więc odmowa go nie nazywa.
    detail = client_orders.amount_fields_forbidden(
        _account(UserRole.delivery_lead), ["rate_client"]
    ).detail
    assert detail == {
        "code": "finance_fields_forbidden",
        "fields": ["rate_client"],
        "message": DL_CLIENT_OUT_OF_SCOPE_DETAIL,
    }

    # Ani zamówień, ani zmiany kwot → brakuje zmiany kwot.
    detail = client_orders.amount_fields_forbidden(
        _account(UserRole.talent_community_manager), ["rate_client"]
    ).detail
    assert detail["code"] == "finance_fields_forbidden"
    assert detail["permission"] == "amounts_edit"


def test_order_amount_write_guard_follows_the_client_decision() -> None:
    guard = client_orders._assert_order_finance_write_allowed
    lead = _account(UserRole.delivery_lead)

    # Zapis bez pól kwot nie pyta o kwoty — także u konta bez podglądu kwot.
    guard(_order_editor_without_amounts(), {"title", "notes", "end_date"})
    # Decyzję o kliencie podaje wołający (``_OrderAmounts.can_write``).
    guard(lead, {"rate_client", "rate_unit"}, can_finance=True)
    with pytest.raises(HTTPException) as exc:
        guard(lead, {"rate_client", "rate_unit"}, can_finance=False)
    assert exc.value.status_code == 403
    assert exc.value.detail["fields"] == ["rate_client", "rate_unit"]
    # Zmiana kwot bez portfela Delivery Leada nie zależy od flagi: handler,
    # który zapomni ją policzyć, zamyka się dla reszty, nie otwiera.
    guard(_account(UserRole.finance), {"rate_client"})
    guard(_account(UserRole.recruiter, "amounts_edit"), {"rate_client"})
    with pytest.raises(HTTPException) as exc:
        guard(_order_editor_without_amounts(), {"rate_client"})
    assert exc.value.detail["permission"] == "amounts_view"


async def test_order_file_requires_amounts_of_this_client(monkeypatch) -> None:
    """Plik PO: podgląd kwot w zakresie klienta ORAZ kwoty tego klienta."""

    async def passes(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(client_orders, "_require_client_order_read", passes)
    lead = _account(UserRole.delivery_lead)

    await client_orders._require_order_file_read(
        None,
        lead,
        CLIENT,
        amounts=client_orders._order_amounts_within(lead, CLIENT, frozenset({CLIENT})),
    )
    with pytest.raises(HTTPException) as exc:
        await client_orders._require_order_file_read(
            None,
            lead,
            CLIENT,
            amounts=client_orders._order_amounts_within(
                lead, CLIENT, frozenset({OTHER_CLIENT})
            ),
        )
    assert exc.value.status_code == 403
    assert "przypisania do klienta" in exc.value.detail


async def test_group_file_and_line_rates_follow_the_same_rule(monkeypatch) -> None:
    monkeypatch.setattr(
        client_order_groups,
        "resolve_delivery_lead_finance_client_ids",
        _delivery_lead_boundary,
    )
    lead = _account(UserRole.delivery_lead)
    editor = _order_editor_without_amounts()

    # Plik PDF zamówienia MD/kosztowego.
    await client_order_groups._require_file_amounts(None, lead, CLIENT)
    await client_order_groups._require_file_amounts(
        None, _account(UserRole.finance), OTHER_CLIENT
    )
    with pytest.raises(HTTPException) as exc:
        await client_order_groups._require_file_amounts(None, lead, OTHER_CLIENT)
    assert exc.value.status_code == 403
    assert "przypisania do klienta" in exc.value.detail
    with pytest.raises(HTTPException) as exc:
        await client_order_groups._require_file_amounts(None, editor, CLIENT)
    assert exc.value.detail["code"] == "permission_denied"
    assert exc.value.detail["permission"] == "amounts_view"

    # Stawki linii i budżety grupy.
    guard = client_order_groups._assert_line_finance_write_allowed
    await guard(None, lead, CLIENT, {"rate_cost", "rate_revenue"})
    await guard(None, editor, CLIENT, {"end_date", "input_value"})
    with pytest.raises(HTTPException) as exc:
        await guard(None, lead, OTHER_CLIENT, {"rate_cost", "end_date"})
    assert exc.value.detail == {
        "code": "finance_fields_forbidden",
        "fields": ["rate_cost"],
        "message": DL_CLIENT_OUT_OF_SCOPE_DETAIL,
    }
    with pytest.raises(HTTPException) as exc:
        await guard(None, editor, CLIENT, {"rate_cost", "budget_amount"})
    assert exc.value.detail["fields"] == ["budget_amount", "rate_cost"]
    assert exc.value.detail["permission"] == "amounts_view"


async def test_amount_budget_of_a_line_is_an_amount(monkeypatch) -> None:
    """Budżet linii w trybie „kwota” to złotówki: serwer liczy z niego
    ``md_total = kwota / stawka`` i oddaje MD każdemu, kto widzi linię. Konto
    bez prawa do kwot nie może go zmienić — inaczej odczytałoby stawkę
    przychodową z odpowiedzi (przegląd pakietu zamówień, 02.10.2026)."""

    monkeypatch.setattr(
        client_order_groups,
        "resolve_delivery_lead_finance_client_ids",
        _delivery_lead_boundary,
    )
    guard = client_order_groups._assert_amount_budget_write_allowed
    editor = _order_editor_without_amounts()
    lead = _account(UserRole.delivery_lead)
    md_line = SimpleNamespace(md_input_mode="md", md_input_value=Decimal("10"))
    amount_line = SimpleNamespace(
        md_input_mode="amount", md_input_value=Decimal("10000.000")
    )
    to_amount = {"input_mode": "amount", "input_value": Decimal("10000")}

    with pytest.raises(HTTPException) as exc:
        await guard(None, editor, CLIENT, md_line, to_amount)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "finance_fields_forbidden"
    assert exc.value.detail["fields"] == ["input_mode", "input_value"]
    assert exc.value.detail["permission"] == "amounts_view"
    # Sama nowa kwota na linii, która już jest w trybie „kwota”.
    with pytest.raises(HTTPException) as exc:
        await guard(None, editor, CLIENT, amount_line, {"input_value": Decimal("1")})
    assert exc.value.detail["fields"] == ["input_value"]

    # Budżet w MD jest operacyjny; formularz odsyłający niezmieniony komplet
    # pól linii „kwotowej” też przechodzi (liczy się zmiana); zapis bez pól
    # budżetu w ogóle o kwoty nie pyta.
    await guard(
        None, editor, CLIENT, md_line, {"input_mode": "md", "input_value": Decimal("12")}
    )
    await guard(None, editor, CLIENT, amount_line, to_amount)
    await guard(None, editor, CLIENT, amount_line, {"end_date": None})
    # Z kwoty na MD: nowa wartość to dni, nie złotówki.
    await guard(
        None,
        editor,
        CLIENT,
        amount_line,
        {"input_mode": "md", "input_value": Decimal("20")},
    )

    # Prawo do kwot klienta otwiera zapis; rola Delivery Leada — w przypisaniu.
    await guard(None, lead, CLIENT, md_line, to_amount)
    await guard(None, _account(UserRole.finance), OTHER_CLIENT, md_line, to_amount)
    with pytest.raises(HTTPException) as exc:
        await guard(None, lead, OTHER_CLIENT, md_line, to_amount)
    assert exc.value.detail["message"] == DL_CLIENT_OUT_OF_SCOPE_DETAIL


async def test_order_lifecycle_asks_only_for_the_client_scope(monkeypatch) -> None:
    """Zakończenie, przywrócenie, usunięcie: uprawnienie na trasie, tu zakres."""

    async def client_exists(*_args, **_kwargs):
        return SimpleNamespace(id=CLIENT)

    async def no_scope_question(*_args, **_kwargs):
        raise AssertionError("zakres klienta dotyczy tylko konta z rolą DL")

    monkeypatch.setattr(client_order_groups, "_assert_client", client_exists)
    monkeypatch.setattr(client_order_groups, "resolve_client_access", no_scope_question)
    # Bez podglądu kwot i bez roli Delivery Leada: każdy klient.
    await client_order_groups._require_order_lifecycle(
        None, _order_editor_without_amounts(), CLIENT
    )

    # Konto z rolą Delivery Leada: klient musi leżeć w jego zakresie Delivery.
    lead = _account(UserRole.delivery_lead)

    async def in_scope(*_args, **_kwargs):
        return SimpleNamespace(is_client_team=True)

    async def out_of_scope(*_args, **_kwargs):
        return SimpleNamespace(is_client_team=False)

    monkeypatch.setattr(client_order_groups, "resolve_client_access", in_scope)
    await client_order_groups._require_order_lifecycle(None, lead, CLIENT)
    monkeypatch.setattr(client_order_groups, "resolve_client_access", out_of_scope)
    with pytest.raises(HTTPException) as exc:
        await client_order_groups._require_order_lifecycle(None, lead, CLIENT)
    assert exc.value.status_code == 403


async def test_mail_queue_scope_and_write_rights(monkeypatch) -> None:
    monkeypatch.setattr(
        queue, "resolve_delivery_lead_client_ids", _delivery_lead_boundary
    )
    monkeypatch.setattr(
        queue, "resolve_delivery_lead_finance_client_ids", _delivery_lead_boundary
    )
    lead = _account(UserRole.delivery_lead)
    finance = _account(UserRole.finance)
    viewer = _account(UserRole.recruiter, "delivery_view")
    editor = _order_editor_without_amounts()

    # Zakres kolejki: portfel konta z rolą DL, cała organizacja dla każdego
    # innego posiadacza podglądu, nic dla konta bez podglądu.
    assert await queue._visible_client_ids(None, lead) == {CLIENT}
    assert await queue._visible_client_ids(None, finance) is None
    assert await queue._visible_client_ids(None, viewer) is None
    assert (
        await queue._visible_client_ids(None, _account(UserRole.head_of_recruitment))
        == set()
    )

    # Bezpieczna projekcja = brak podglądu kwot, nie rola.
    assert queue._reads_safe_projection(viewer) is True
    assert queue._reads_safe_projection(editor) is True
    assert queue._reads_safe_projection(lead) is False
    assert queue._reads_safe_projection(
        _account(UserRole.recruiter, "amounts_view")
    ) is (False)

    # „Zastosuj” / „Odrzuć”: prawo do kwot zamówień klienta z dokumentu.
    await queue._require_apply_rights(None, SimpleNamespace(client_id=CLIENT), lead)
    await queue._require_apply_rights(
        None, SimpleNamespace(client_id=OTHER_CLIENT), finance
    )
    with pytest.raises(HTTPException) as exc:
        await queue._require_apply_rights(
            None, SimpleNamespace(client_id=OTHER_CLIENT), lead
        )
    assert exc.value.status_code == 403
    assert exc.value.detail == DL_CLIENT_OUT_OF_SCOPE_DETAIL
    with pytest.raises(HTTPException) as exc:
        await queue._require_apply_rights(
            None, SimpleNamespace(client_id=CLIENT), editor
        )
    assert exc.value.detail["permission"] == "amounts_view"

    # Sama zmiana kwot nie wystarcza: dokument z maila zakłada zamówienie,
    # kontrakt i kandydata. Flagi „Zastosuj”/„Odrzuć” mówią to samo co trasa.
    amounts_only = _account(UserRole.recruiter, "amounts_edit")
    boundary = queue._FinanceBoundary(None)
    assert queue._can_write_orders(amounts_only, CLIENT, boundary) is False
    assert queue._can_write_orders(finance, CLIENT, boundary) is True
    assert queue._can_write_orders(editor, CLIENT, boundary) is False

    # Dokument bez rozpoznanego klienta nie leży w niczyim portfelu: odrzuca
    # go konto, które prowadzi zamówienia u wszystkich klientów.
    orphan = SimpleNamespace(client_id=None)
    await queue._require_apply_rights(None, orphan, finance)
    await queue._require_apply_rights(None, orphan, _account(UserRole.admin))
    with pytest.raises(HTTPException):
        await queue._require_apply_rights(None, orphan, lead)


@pytest.mark.parametrize(
    "endpoint",
    [
        queue.refresh_queue_plan,
        queue.apply_queue_item,
        queue.queue_order_target,
        queue.mark_queue_item_resolved_in_order,
        queue.dismiss_queue_item,
    ],
)
async def test_mail_queue_writes_need_order_editing_not_just_amounts(endpoint) -> None:
    """Trasy zapisu kolejki wymagają prowadzenia zamówień; „Stawki i kwoty:
    zmiana” bez niego dostaje odmowę z nazwą brakującego uprawnienia."""

    from typing import get_type_hints

    gate = get_type_hints(endpoint, include_extras=True)["user"].__metadata__[0]
    with pytest.raises(HTTPException) as exc:
        await gate.dependency(
            current_user=_account(UserRole.recruiter, "amounts_edit")
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "permission_denied"
    assert exc.value.detail["permission"] == "contracts_orders_edit"
    finance = _account(UserRole.finance)
    assert await gate.dependency(current_user=finance) is finance


# ── Scenariusze HTTP (wymagają bazy) ────────────────────────────────────────


async def _login_as(
    app_client: AsyncClient,
    role: UserRole,
    *,
    assigned_client_id: int | None = None,
) -> tuple[int, dict[str, str]]:
    """Załóż konto z rolą, zaloguj je i oddaj (id, nagłówki)."""

    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.team_structure import DeliveryLeadClientAssignment

    suffix = uuid.uuid4().hex[:8]
    email = f"perm-orders-{role.value}-{suffix}@example.com"
    password = f"T3st_{suffix}!PassX"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Perm orders {role.value}",
            role=role,
            roles=[role.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.flush()
        if assigned_client_id is not None:
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=user.id, client_id=assigned_client_id
                )
            )
        await db.commit()
        user_id = user.id
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return user_id, {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _order_form(contract_id: int, **extra: str) -> dict[str, str]:
    """Formularz „Dodaj przedłużenie”: szkic bez dat; kwoty tylko z ``extra``."""

    return {
        "contract_id": str(contract_id),
        "title": f"PERM-{uuid.uuid4().hex[:8]}",
        "order_status": "draft",
        **extra,
    }


async def test_finance_creates_orders_with_amounts_and_runs_their_lifecycle(
    app_client: AsyncClient, monkeypatch
) -> None:
    """Finanse prowadzą zamówienia jak Delivery Lead (decyzja 02.10.2026)."""
    from tests.test_order_lifecycle_and_cost import (
        _create_group,
        _enable_multi,
        _md_line,
        _seed_client_with_contracts,
    )

    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_multi(monkeypatch, client_id)
    _, finance = await _login_as(app_client, UserRole.finance)

    created = await app_client.post(
        f"/api/clients/{client_id}/orders",
        data=_order_form(contracts[0], rate_client="17000"),
        headers=finance,
    )
    assert created.status_code == 201, created.text
    assert Decimal(created.json()["rate_client"]) == Decimal(17000)

    # Zamówienie MD z obsadą: stawki linii zapisane i widoczne.
    group = await _create_group(
        app_client, finance, client_id, [_md_line(contracts[1])]
    )
    assert group["lines"][0]["rate_revenue"] is not None
    base = f"/api/clients/{client_id}/order-groups/{group['id']}"

    closed = await app_client.post(
        f"{base}/close",
        json={"closure_date": business_today().isoformat()},
        headers=finance,
    )
    assert closed.status_code == 200, closed.text
    reopened = await app_client.post(f"{base}/reopen", headers=finance)
    assert reopened.status_code == 200, reopened.text
    extended = await app_client.post(
        f"{base}/extend",
        json={
            "order_number": f"ext-{uuid.uuid4().hex[:6]}",
            "start_date": business_today().isoformat(),
            "lines": [],
        },
        headers=finance,
    )
    assert extended.status_code == 201, extended.text


async def test_finance_applies_an_order_from_the_mail_queue(
    seeded,  # noqa: F811
    app_client: AsyncClient,
) -> None:
    from app.models.order_mail import OUTCOME_APPLIED

    _, finance = await _login_as(app_client, UserRole.finance)
    doc_url = f"/api/order-mail/queue/{seeded['doc_id']}"

    detail = await app_client.get(doc_url, headers=finance)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["can_apply"] is True and body["can_dismiss"] is True
    assert body["has_file"] is True
    assert body["extraction"]["rate_client"] == "950.00"

    applied = await app_client.post(f"{doc_url}/apply", headers=finance)
    assert applied.status_code == 200, applied.text
    result = applied.json()
    assert result["ok"] is True
    assert result["document"]["outcome"] == OUTCOME_APPLIED
    assert result["document"]["applied_order_id"]


async def test_finance_removes_an_empty_draft_card(app_client: AsyncClient) -> None:
    from tests.test_order_line_takeover import _seed_draft_card

    seed = await _seed_draft_card()
    _, finance = await _login_as(app_client, UserRole.finance)

    resp = await app_client.post(
        f"/api/clients/{seed['client_id']}/contractors/{seed['contract_id']}"
        "/dismiss-draft",
        headers=finance,
    )

    assert resp.status_code == 204, resp.text


async def test_order_editor_needs_amounts_view_for_amounts_and_files(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, tmp_path
) -> None:
    """Uprawnienie nadane osobie spoza domyślnych ról (TCM).

    Samo prowadzenie zamówień pozwala założyć i zakończyć zamówienie, ale
    kwota albo plik kończą się odmową z nazwą „Stawki i kwoty: podgląd”.
    Po nadaniu podglądu kwot te same żądania przechodzą.
    """
    from app.services import storage_service
    from tests.test_order_lifecycle_and_cost import (
        _create_group,
        _enable_multi,
        _md_line,
        _seed_client_with_contracts,
    )

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(
        storage_service, "CLIENT_ORDER_POS_DIR", tmp_path / "client_orders"
    )
    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_multi(monkeypatch, client_id)
    user_id, headers = await _login_as(app_client, UserRole.talent_community_manager)
    orders_url = f"/api/clients/{client_id}/orders"

    # Rola sama z siebie zamówień nie prowadzi.
    refused = await app_client.post(
        orders_url, data=_order_form(contracts[0]), headers=headers
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"]["code"] == "permission_denied"
    assert refused.json()["detail"]["permission"] == "contracts_orders_edit"

    await grant_permissions(user_id, "contracts_orders_edit")

    created = await app_client.post(
        orders_url, data=_order_form(contracts[0]), headers=headers
    )
    assert created.status_code == 201, created.text
    order = created.json()
    assert order["rate_client"] is None, "kwoty wyciekły kontu bez podglądu kwot"
    assert order["has_file"] is False
    file_url = f"{orders_url}/{order['id']}/file"

    with_amount = await app_client.post(
        orders_url, data=_order_form(contracts[0], rate_client="17000"), headers=headers
    )
    assert with_amount.status_code == 403, with_amount.text
    denial = with_amount.json()["detail"]
    assert denial["code"] == "finance_fields_forbidden"
    assert denial["fields"] == ["rate_client"]
    assert denial["permission"] == "amounts_view"
    assert AMOUNTS_VIEW_LABEL in denial["message"]

    upload = await app_client.put(
        file_url,
        files={"file": ("zamowienie.pdf", _PDF, "application/pdf")},
        headers=headers,
    )
    assert upload.status_code == 403, upload.text
    assert upload.json()["detail"]["code"] == "permission_denied"
    assert upload.json()["detail"]["permission"] == "amounts_view"

    # Zamówienie MD: obsada niesie stawki → odmowa; zakończenie ich nie
    # dotyka, więc wystarcza prowadzenie zamówień.
    groups_url = f"/api/clients/{client_id}/order-groups"
    staffed = await app_client.post(
        groups_url,
        json={
            "order_number": f"445-{uuid.uuid4().hex[:6]}",
            "start_date": business_today().isoformat(),
            "lines": [_md_line(contracts[1])],
        },
        headers=headers,
    )
    assert staffed.status_code == 403, staffed.text
    assert staffed.json()["detail"]["code"] == "finance_fields_forbidden"
    assert staffed.json()["detail"]["permission"] == "amounts_view"

    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[1])]
    )
    closed = await app_client.post(
        f"{groups_url}/{group['id']}/close",
        json={"closure_date": business_today().isoformat()},
        headers=headers,
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "completed"
    assert closed.json()["lines"][0]["rate_revenue"] is None

    # Ta sama osoba z podglądem kwot: kwota i plik przechodzą.
    await grant_permissions(user_id, "amounts_view")

    with_amount = await app_client.post(
        orders_url, data=_order_form(contracts[0], rate_client="17000"), headers=headers
    )
    assert with_amount.status_code == 201, with_amount.text
    assert Decimal(with_amount.json()["rate_client"]) == Decimal(17000)

    upload = await app_client.put(
        file_url,
        files={"file": ("zamowienie.pdf", _PDF, "application/pdf")},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    assert upload.json()["has_file"] is True


async def test_delivery_lead_writes_amounts_only_at_assigned_clients(
    app_client: AsyncClient, monkeypatch
) -> None:
    """Klient widoczny, ale spoza przypisania: zamówienie tak, kwoty nie."""
    from app.core.config import settings
    from tests.test_order_lifecycle_and_cost import _seed_client_with_contracts

    # Klienta spoza przypisania Delivery Lead widzi tylko przy wyłączniku
    # ``DL_CLIENT_SCOPE=all`` (domyślnie odcina go bramka routera).
    monkeypatch.setattr(settings, "DL_CLIENT_SCOPE", "all")
    own, own_contracts, _ = await _seed_client_with_contracts(1)
    other, other_contracts, _ = await _seed_client_with_contracts(1)
    _, headers = await _login_as(
        app_client, UserRole.delivery_lead, assigned_client_id=own
    )

    accepted = await app_client.post(
        f"/api/clients/{own}/orders",
        data=_order_form(own_contracts[0], rate_client="17000"),
        headers=headers,
    )
    assert accepted.status_code == 201, accepted.text
    assert Decimal(accepted.json()["rate_client"]) == Decimal(17000)

    refused = await app_client.post(
        f"/api/clients/{other}/orders",
        data=_order_form(other_contracts[0], rate_client="17000"),
        headers=headers,
    )
    assert refused.status_code == 403, refused.text
    denial = refused.json()["detail"]
    assert denial["code"] == "finance_fields_forbidden"
    assert denial["fields"] == ["rate_client"]
    # Uprawnień nie brakuje — brakuje przypisania, więc odmowa mówi o portfelu.
    assert denial["message"] == DL_CLIENT_OUT_OF_SCOPE_DETAIL
    assert "permission" not in denial

    operational = await app_client.post(
        f"/api/clients/{other}/orders",
        data=_order_form(other_contracts[0]),
        headers=headers,
    )
    assert operational.status_code == 201, operational.text
    assert operational.json()["rate_client"] is None

    upload = await app_client.put(
        f"/api/clients/{other}/orders/{operational.json()['id']}/file",
        files={"file": ("zamowienie.pdf", _PDF, "application/pdf")},
        headers=headers,
    )
    assert upload.status_code == 403, upload.text
    assert "przypisania do klienta" in upload.json()["detail"]


async def test_delivery_view_reads_orders_without_amounts_and_files(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
) -> None:
    """Sam podgląd nadany rekruterowi: lista tak, kwoty, eksport i plik nie."""
    from tests.test_order_lifecycle_and_cost import (
        _create_group,
        _enable_multi,
        _md_line,
        _seed_client_with_contracts,
    )

    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_multi(monkeypatch, client_id)
    orders_url = f"/api/clients/{client_id}/orders"
    groups_url = f"/api/clients/{client_id}/order-groups"
    created = await app_client.post(
        orders_url,
        data=_order_form(contracts[0], rate_client="17000"),
        headers=app_auth_headers,
    )
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[1])]
    )
    user_id, headers = await _login_as(app_client, UserRole.recruiter)

    assert (await app_client.get(orders_url, headers=headers)).status_code == 403

    await grant_permissions(user_id, "delivery_view")

    listing = await app_client.get(orders_url, headers=headers)
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body["can_manage_finance"] is False
    row = next(c for c in body["contractors"] if c["contract_id"] == contracts[0])
    assert row["rate_candidate"] is None
    assert row["latest_order_rate_client"] is None
    listed_order = next(o for o in row["orders"] if o["id"] == order_id)
    assert listed_order["rate_client"] is None

    groups = await app_client.get(groups_url, headers=headers)
    assert groups.status_code == 200, groups.text
    listed_group = next(g for g in groups.json()["groups"] if g["id"] == group["id"])
    assert listed_group["lines"][0]["rate_cost"] is None
    assert listed_group["lines"][0]["rate_revenue"] is None

    # Plik i eksport niosą stawki — odmowa nazywa „Stawki i kwoty: podgląd”.
    for path in (
        f"{orders_url}/{order_id}/file",
        f"{groups_url}/{group['id']}/file",
    ):
        denied = await app_client.get(path, headers=headers)
        assert denied.status_code == 403, (path, denied.text)
        assert denied.json()["detail"]["code"] == "permission_denied", path
        assert denied.json()["detail"]["permission"] == "amounts_view", path

    export = await app_client.post(
        f"{orders_url}/export", json={"order_ids": [order_id]}, headers=headers
    )
    assert export.status_code == 403, export.text
    assert export.json()["detail"]["code"] == "permission_denied"
    assert "amounts_view" in export.json()["detail"]["permissions"]

    # Podgląd niczego nie zapisuje.
    write = await app_client.post(
        orders_url, data=_order_form(contracts[0]), headers=headers
    )
    assert write.status_code == 403, write.text


async def test_switching_the_permission_off_for_the_role_stops_order_writes(
    app_client: AsyncClient,
) -> None:
    """Uprawnienie wyłączone roli, która ma je domyślnie (Delivery Lead)."""
    from tests.test_order_lifecycle_and_cost import _seed_client_with_contracts

    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _, headers = await _login_as(
        app_client, UserRole.delivery_lead, assigned_client_id=client_id
    )
    orders_url = f"/api/clients/{client_id}/orders"

    async with role_permission("delivery_lead", "contracts_orders_edit", granted=False):
        refused = await app_client.post(
            orders_url, data=_order_form(contracts[0]), headers=headers
        )
        assert refused.status_code == 403, refused.text
        assert refused.json()["detail"]["code"] == "permission_denied"
        assert refused.json()["detail"]["permission"] == "contracts_orders_edit"

        # Odczyt zostaje — razem z kwotami własnego klienta. Przycisk zapisu
        # kwot znika, bo bez prowadzenia zamówień nie ma czym ich zapisać.
        listing = await app_client.get(orders_url, headers=headers)
        assert listing.status_code == 200, listing.text
        assert listing.json()["can_manage_finance"] is False

    restored = await app_client.post(
        orders_url, data=_order_form(contracts[0]), headers=headers
    )
    assert restored.status_code == 201, restored.text
