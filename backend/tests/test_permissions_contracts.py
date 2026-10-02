"""Kontrakty za uprawnieniami z ekranu Osoby i role — trasy na bazie (02.10.2026).

Każdy scenariusz idzie przez prawdziwą trasę: bramka uprawnienia, reguły
w handlerze (kwoty, zmiana statusu, szkic i pliki) i zakres klientów Delivery
Leada. Reguły policzone bez bazy: ``test_permissions_contracts_rules.py``.

Pilnowane decyzje (``docs/permissions-nine-switches-contract.md`` §6):

* Finanse prowadzą kontrakty (tworzenie, edycja, aktywacja, unieważnienie),
  ale statusu nie zmieniają i współpracy nie kończą,
* TCM kończy współpracę także zbiorczo,
* rola, której administrator nadał uprawnienie, może z niego skorzystać —
  a rola, której je odebrał, traci samo to uprawnienie, nic więcej.

Baza testowa jest wspólna i nieczyszczona: każdy test zakłada własne konta,
klientów i kontrakty, a wiersz roli zmieniony w teście wraca po bloku
(``role_permission``). Osoby i firmy są zmyślone.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import hash_password
from app.models.contract import (
    Contract,
    ContractStatus,
    ContractTerminationReason,
    ContractType,
    RateUnit,
)
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services import permission_catalog
from app.services.access_scope import DL_CLIENT_OUT_OF_SCOPE_DETAIL
from tests._contract_parties import pick_parties
from tests._permission_grants import grant_permissions, role_permission

pytestmark = pytest.mark.asyncio


async def _account(
    app_client: AsyncClient,
    role: str,
    *,
    assigned_client_ids: tuple[int, ...] = (),
) -> tuple[dict[str, str], int]:
    """Konto o jednej roli (z przypisaniami DL) i jego nagłówki."""

    unique = uuid.uuid4().hex[:8]
    email = f"perm-contracts-{role}-{unique}@example.com"
    password = f"T3st_{unique}!Perm"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Uprawnienia {role}",
            role=UserRole(role),
            roles=[role],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.flush()
        for client_id in assigned_client_ids:
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=user.id, client_id=client_id
                )
            )
        await db.commit()
        user_id = user.id
    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, user_id


async def _contract(
    *, status: ContractStatus = ContractStatus.active
) -> tuple[int, int]:
    """Kontrakt B2B z kwotami wprost w bazie; zwraca ``(kontrakt, klient)``."""

    candidate_id, client_id = await pick_parties()
    async with AsyncSessionLocal() as db:
        contract = Contract(
            candidate_id=candidate_id,
            client_id=client_id,
            contract_type=ContractType.b2b,
            status=status,
            start_date=business_today() - timedelta(days=30),
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("150.000"),
            rate_unit=RateUnit.hourly,
        )
        db.add(contract)
        await db.commit()
        return contract.id, client_id


async def _stored(contract_id: int) -> Contract:
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract is not None
        return contract


def _new_contract(candidate_id: int, client_id: int, **extra) -> dict:
    return {
        "candidate_id": candidate_id,
        "client_id": client_id,
        "start_date": (business_today() - timedelta(days=5)).isoformat(),
        **extra,
    }


def _assert_denied(response, permission: str) -> None:
    """403 z nazwą brakującego uprawnienia — tą samą, którą pokazuje ekran."""

    assert response.status_code == 403, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "permission_denied", detail
    assert detail["permission"] == permission, detail
    assert detail["label"] == permission_catalog.label(permission)
    assert detail["label"] in detail["message"]


def _assert_amounts_refused(response, *fields: str) -> None:
    """Odmowa zapisu kwot: stary kod i lista pól + nazwa brakującego uprawnienia."""

    assert response.status_code == 403, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "finance_fields_forbidden", detail
    assert detail["fields"] == sorted(fields)
    assert detail["permission"] == "amounts_edit"
    assert detail["label"] == permission_catalog.label("amounts_edit")
    assert detail["label"] in detail["message"]


# ── 1. Finanse prowadzą kontrakty ────────────────────────────────────────────


async def test_finance_creates_activates_and_voids_a_contract_with_amounts(
    app_client: AsyncClient,
) -> None:
    """Decyzja 02.10.2026: Finanse zakładają kontrakt razem z kwotami."""

    finance, _ = await _account(app_client, "finance")
    candidate_id, client_id = await pick_parties()

    created = await app_client.post(
        "/api/contracts",
        headers=finance,
        json=_new_contract(
            candidate_id,
            client_id,
            rate_candidate=100,
            rate_client=150,
            rate_unit="hourly",
        ),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "draft"
    assert body["rate_candidate"] == 100
    assert body["rate_client"] == 150
    contract_id = body["id"]

    activated = await app_client.post(
        f"/api/contracts/{contract_id}/activate", headers=finance, json={}
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "active"

    scope = await app_client.post(
        f"/api/contracts/{contract_id}/amendments",
        headers=finance,
        json={
            "amendment_type": "scope_change",
            "effective_date": business_today().isoformat(),
            "new_project_name": "Projekt po aneksie",
        },
    )
    assert scope.status_code == 201, scope.text

    voided = await app_client.post(
        f"/api/contracts/{contract_id}/void",
        headers=finance,
        json={"reason": "kontrakt założony omyłkowo"},
    )
    assert voided.status_code == 200, voided.text
    assert voided.json()["status"] == "void"

    stored = await _stored(contract_id)
    assert stored.status == ContractStatus.void
    assert stored.project_name == "Projekt po aneksie"


# ── 2. …ale statusu nie zmieniają i współpracy nie kończą ───────────────────


async def test_finance_edits_a_contract_but_cannot_change_its_status(
    app_client: AsyncClient,
) -> None:
    finance, _ = await _account(app_client, "finance")
    contract_id, _client_id = await _contract(status=ContractStatus.active)

    by_status_route = await app_client.patch(
        f"/api/contracts/{contract_id}/status",
        headers=finance,
        json={"status": "draft"},
    )
    _assert_denied(by_status_route, "contract_status")

    terminated = await app_client.post(
        f"/api/contracts/{contract_id}/terminate",
        headers=finance,
        json={"termination_reason": "project_ended"},
    )
    _assert_denied(terminated, "contract_status")

    bulk = await app_client.post(
        f"/api/contracts/bulk-mark-ended?ids={contract_id}",
        headers=finance,
        json={
            "termination_reason": "project_ended",
            "terminated_at": business_today().isoformat(),
        },
    )
    _assert_denied(bulk, "contract_status")

    # Formularz edycji odsyła `status` przy każdym zapisie — niezmieniony
    # status nie żąda uprawnienia, którego ta edycja nie dotyka.
    same_status = await app_client.patch(
        f"/api/contracts/{contract_id}",
        headers=finance,
        json={"status": "active", "project_name": "Projekt po edycji"},
    )
    assert same_status.status_code == 200, same_status.text
    assert same_status.json()["status"] == "active"
    assert same_status.json()["project_name"] == "Projekt po edycji"

    # Inny status w tym samym formularzu to już zmiana statusu…
    changed_status = await app_client.patch(
        f"/api/contracts/{contract_id}",
        headers=finance,
        json={"status": "draft", "project_name": "Nie powinno się zapisać"},
    )
    _assert_denied(changed_status, "contract_status")

    # …a dane zakończenia współpracy to zakończenie bocznymi drzwiami.
    termination_fields = await app_client.patch(
        f"/api/contracts/{contract_id}",
        headers=finance,
        json={"termination_reason": "project_ended"},
    )
    _assert_denied(termination_fields, "contract_status")

    # Data wsteczna kończyłaby umowę przy najbliższym biegu nocnym.
    backdated = await app_client.patch(
        f"/api/contracts/{contract_id}",
        headers=finance,
        json={"end_date": "2020-01-31"},
    )
    _assert_denied(backdated, "contract_status")

    stored = await _stored(contract_id)
    assert stored.status == ContractStatus.active
    assert stored.project_name == "Projekt po edycji"
    assert stored.termination_reason is None
    assert stored.terminated_at is None
    assert stored.end_date is None

    # „Zakończonego” kontraktu Finanse nie przywracają datą ani przedłużeniem.
    ended_id, _ = await _contract(status=ContractStatus.ended)
    for response in (
        await app_client.patch(
            f"/api/contracts/{ended_id}",
            headers=finance,
            json={"end_date": "2999-12-31"},
        ),
        await app_client.post(
            f"/api/contracts/{ended_id}/amendments",
            headers=finance,
            json={
                "amendment_type": "extension",
                "effective_date": business_today().isoformat(),
                "new_end_date": "2999-12-31",
            },
        ),
        await app_client.post(
            f"/api/contracts/bulk-extend?ids={ended_id}&months=3", headers=finance
        ),
    ):
        _assert_denied(response, "contract_status")
    assert (await _stored(ended_id)).status == ContractStatus.ended


# ── 3. Uprawnienie nadane osobie ponad rolę ──────────────────────────────────


async def test_tcm_with_granted_contract_editing_works_without_amounts(
    app_client: AsyncClient,
) -> None:
    """„Kontrakty i zamówienia: tworzenie i edycja” nie daje kwot ani plików."""

    tcm, tcm_id = await _account(app_client, "talent_community_manager")
    await grant_permissions(tcm_id, "contracts_orders_edit")
    candidate_id, client_id = await pick_parties()

    with_rate = await app_client.post(
        "/api/contracts",
        headers=tcm,
        json=_new_contract(candidate_id, client_id, rate_candidate=120),
    )
    _assert_amounts_refused(with_rate, "rate_candidate")

    created = await app_client.post(
        "/api/contracts", headers=tcm, json=_new_contract(candidate_id, client_id)
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "draft"
    assert body["rate_candidate"] is None
    contract_id = body["id"]

    edited = await app_client.patch(
        f"/api/contracts/{contract_id}",
        headers=tcm,
        json={"project_name": "Projekt bez kwot"},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["project_name"] == "Projekt bez kwot"

    rate_patch = await app_client.patch(
        f"/api/contracts/{contract_id}", headers=tcm, json={"rate_client": 200}
    )
    _assert_amounts_refused(rate_patch, "rate_client")

    rate_amendment = await app_client.post(
        f"/api/contracts/{contract_id}/amendments",
        headers=tcm,
        json={
            "amendment_type": "rate_change",
            "effective_date": business_today().isoformat(),
            "new_rate_candidate": 130,
        },
    )
    _assert_amounts_refused(rate_amendment, "new_rate_candidate", "rate_change")

    # Szkic i pliki mogą nieść stawki, a ich treści nie da się zredagować —
    # bez „Stawki i kwoty: podgląd” nie ma do nich dostępu także przy prawie
    # edycji kontraktu. Odczyt odmawia bramka trasy, zapis — handler.
    listing = await app_client.get(
        f"/api/contracts/{contract_id}/documents", headers=tcm
    )
    _assert_denied(listing, "amounts_view")
    draft_read = await app_client.get(
        f"/api/contracts/{contract_id}/draft", headers=tcm
    )
    _assert_denied(draft_read, "amounts_view")
    draft_write = await app_client.patch(
        f"/api/contracts/{contract_id}/draft",
        headers=tcm,
        json={"content_html": "<p>Treść umowy</p>"},
    )
    _assert_denied(draft_write, "amounts_view")
    upload = await app_client.post(
        f"/api/contracts/{contract_id}/documents",
        headers=tcm,
        files={"file": ("umowa.pdf", b"%PDF-1.4\n% test\n", "application/pdf")},
    )
    _assert_denied(upload, "amounts_view")

    stored = await _stored(contract_id)
    assert stored.rate_client is None
    assert stored.rate_candidate is None
    assert stored.draft_content_html is None


# ── 4. TCM: zakończenie zbiorcze tak, zakładanie kontraktu nie ──────────────


async def test_plain_tcm_ends_cooperation_in_bulk_but_does_not_create_contracts(
    app_client: AsyncClient,
) -> None:
    """Zbiorcze „Oznacz zakończone” to to samo uprawnienie co pojedyncze."""

    tcm, _ = await _account(app_client, "talent_community_manager")
    contract_id, _client_id = await _contract(status=ContractStatus.active)
    when = business_today() - timedelta(days=3)

    ended = await app_client.post(
        f"/api/contracts/bulk-mark-ended?ids={contract_id}",
        headers=tcm,
        json={
            "termination_reason": "project_ended",
            "terminated_at": when.isoformat(),
        },
    )
    assert ended.status_code == 200, ended.text
    assert ended.json() == {"requested": 1, "changed": 1}

    stored = await _stored(contract_id)
    assert stored.status == ContractStatus.ended
    assert stored.termination_reason == ContractTerminationReason.project_ended
    assert stored.terminated_at == when
    assert stored.end_date == when

    candidate_id, client_id = await pick_parties()
    refused = await app_client.post(
        "/api/contracts", headers=tcm, json=_new_contract(candidate_id, client_id)
    )
    _assert_denied(refused, "contracts_orders_edit")

    extended = await app_client.post(
        f"/api/contracts/bulk-extend?ids={contract_id}&months=3", headers=tcm
    )
    _assert_denied(extended, "contracts_orders_edit")


# ── 5. Delivery Lead: uprawnienie mówi CO, portfel mówi U KOGO ───────────────


async def test_delivery_lead_creates_contracts_only_in_the_portfolio_and_without_amounts(
    app_client: AsyncClient,
) -> None:
    candidate_id, own_client = await pick_parties()
    other_candidate, foreign_client = await pick_parties()
    dl, _ = await _account(
        app_client, "delivery_lead", assigned_client_ids=(own_client,)
    )

    with_amounts = await app_client.post(
        "/api/contracts",
        headers=dl,
        json=_new_contract(candidate_id, own_client, rate_client=150),
    )
    _assert_amounts_refused(with_amounts, "rate_client")

    created = await app_client.post(
        "/api/contracts", headers=dl, json=_new_contract(candidate_id, own_client)
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "draft"
    assert created.json()["client_id"] == own_client

    foreign = await app_client.post(
        "/api/contracts",
        headers=dl,
        json=_new_contract(other_candidate, foreign_client),
    )
    assert foreign.status_code == 403, foreign.text
    assert foreign.json()["detail"] == DL_CLIENT_OUT_OF_SCOPE_DETAIL


async def test_delivery_lead_with_granted_amounts_edit_changes_amounts_only_in_the_portfolio(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """„Stawki i kwoty: zmiana” nadane Delivery Leadowi działa u klientów
    z przypisania — nie poszerza się na resztę organizacji."""

    from app.core.config import settings

    own_contract, own_client = await _contract()
    foreign_contract, _foreign_client = await _contract()
    dl, dl_id = await _account(
        app_client, "delivery_lead", assigned_client_ids=(own_client,)
    )
    await grant_permissions(dl_id, "amounts_edit")

    own = await app_client.patch(
        f"/api/contracts/{own_contract}", headers=dl, json={"rate_client": 175}
    )
    assert own.status_code == 200, own.text
    assert own.json()["rate_client"] == 175

    # Przy `DL_CLIENT_SCOPE=all` Delivery Lead WIDZI kontrakty każdego klienta,
    # więc odmowa niżej pochodzi z bramki kwot, a nie z widoczności kontraktu.
    monkeypatch.setattr(settings, "DL_CLIENT_SCOPE", "all")
    foreign_edit = await app_client.patch(
        f"/api/contracts/{foreign_contract}",
        headers=dl,
        json={"project_name": "Widoczny, edytowalny"},
    )
    assert foreign_edit.status_code == 200, foreign_edit.text
    foreign_amount = await app_client.patch(
        f"/api/contracts/{foreign_contract}", headers=dl, json={"rate_client": 175}
    )
    assert foreign_amount.status_code == 403, foreign_amount.text
    assert foreign_amount.json()["detail"] == DL_CLIENT_OUT_OF_SCOPE_DETAIL

    assert (await _stored(own_contract)).rate_client == Decimal("175")
    assert (await _stored(foreign_contract)).rate_client == Decimal("150")


# ── 6. Uprawnienie odebrane roli ─────────────────────────────────────────────


async def test_delivery_lead_without_contract_status_still_edits_but_does_not_terminate(
    app_client: AsyncClient,
) -> None:
    contract_id, client_id = await _contract(status=ContractStatus.active)
    dl, _ = await _account(
        app_client, "delivery_lead", assigned_client_ids=(client_id,)
    )

    async with role_permission("delivery_lead", "contract_status", granted=False):
        terminated = await app_client.post(
            f"/api/contracts/{contract_id}/terminate",
            headers=dl,
            json={"termination_reason": "project_ended"},
        )
        _assert_denied(terminated, "contract_status")

        by_status_route = await app_client.patch(
            f"/api/contracts/{contract_id}/status",
            headers=dl,
            json={"status": "draft"},
        )
        _assert_denied(by_status_route, "contract_status")

        changed_status = await app_client.patch(
            f"/api/contracts/{contract_id}", headers=dl, json={"status": "draft"}
        )
        _assert_denied(changed_status, "contract_status")

        edited = await app_client.patch(
            f"/api/contracts/{contract_id}",
            headers=dl,
            json={"status": "active", "project_name": "Edycja bez zmiany statusu"},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["project_name"] == "Edycja bez zmiany statusu"

        stored = await _stored(contract_id)
        assert stored.status == ContractStatus.active
        assert stored.terminated_at is None

    # Po przywróceniu wartości roli to samo konto kończy współpracę jak dotąd
    # (uprawnienia są czytane z bazy przy każdym żądaniu).
    restored = await app_client.post(
        f"/api/contracts/{contract_id}/terminate",
        headers=dl,
        json={"termination_reason": "project_ended"},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["termination_reason"] == "project_ended"
    assert (await _stored(contract_id)).terminated_at == business_today()
