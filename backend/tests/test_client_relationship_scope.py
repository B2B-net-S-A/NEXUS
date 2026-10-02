"""Focused fail-closed contracts for client relationship access."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api import (
    client_directory,
    client_materials,
    client_orders,
    clients,
    required_documents,
)
from app.api.contract_access import (
    apply_contract_legal_client_scope,
    assert_contract_legal_client_access,
    require_contract_legal_access,
)
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.user import User, UserRole
from app.schemas.client import ClientResponse, ClientSafeResponse
from app.services.client_access import (
    resolve_client_access,
    resolve_client_team_client_ids,
    resolve_client_visible_client_ids,
)
from app.services.access_scope import resolve_delivery_lead_finance_client_ids


class _Rows:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class _Scalar:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


def _user(role: UserRole, *, roles: list[str] | None = None) -> User:
    return User(
        id=100,
        email=f"{role.value}@example.com",
        name=role.value,
        role=role,
        roles=roles or [role.value],
        is_active=True,
        profile_completed=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.admin, UserRole.head_of_recruitment])
async def test_admin_and_head_keep_unrestricted_client_oversight(
    role: UserRole,
) -> None:
    db = SimpleNamespace(scalars=AsyncMock(), execute=AsyncMock())

    assert await resolve_client_team_client_ids(db, _user(role)) is None
    access = await resolve_client_access(db, _user(role), client_id=77)

    assert access.is_admin_like
    assert access.is_client_team
    # Dokumenty Delivery wymagają podglądu kwot (ma go admin, HoR nie);
    # generator umów B2B zostaje przy grafie organizacyjnym.
    assert access.can_view_legal_documents is (role is UserRole.admin)
    assert access.generator_can_view_legal
    assert access.can_view_materials
    assert access.can_edit_materials is (role is UserRole.admin)
    assert access.can_manage_client is (role is UserRole.admin)
    db.scalars.assert_not_awaited()
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_delivery_lead_uses_assignments_in_delivery_and_all_clients_for_org() -> (
    None
):
    """Od 25.09.2026 DL w modułach Delivery widzi tylko przypisanych klientów.

    ``purpose="org"`` (rekrutacje, generator B2B, zespół klienta) zostaje przy
    wszystkich klientach.
    """

    dl_db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([10, 20])))
    org_db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([10, 20, 30])))

    assert await resolve_client_team_client_ids(
        dl_db,
        _user(UserRole.delivery_lead),
    ) == frozenset({10, 20})
    dl_sql = str(dl_db.scalars.await_args.args[0])
    assert "delivery_lead_client_assignments" in dl_sql
    assert "client_tac_assignments" not in dl_sql

    assert await resolve_client_team_client_ids(
        org_db,
        _user(UserRole.delivery_lead),
        purpose="org",
    ) == frozenset({10, 20, 30})
    org_sql = str(org_db.scalars.await_args.args[0])
    assert "FROM clients" in org_sql
    assert "delivery_lead_client_assignments" not in org_sql
    assert "client_tac_assignments" not in org_sql


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose", ["delivery", "org"])
async def test_recruiter_is_in_no_client_team_whatever_the_legacy_assignments(
    purpose: str,
) -> None:
    """Do 0411 rola TAC dostawała tu klientów z ``ClientTacAssignment``.

    Roli nie ma, a rekruter nie należy do zespołu klienta: resolver nie pyta
    bazy wcale, więc wiersze przypisań nie mogą już dać dostępu.
    """

    db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([30, 40])))

    assert (
        await resolve_client_team_client_ids(
            db,
            _user(UserRole.recruiter),
            purpose=purpose,  # type: ignore[arg-type]
        )
        == frozenset()
    )
    db.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_dl_recruiter_hybrid_uses_only_dl_assignments() -> None:
    db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([10, 20])))
    hybrid = _user(
        UserRole.delivery_lead,
        roles=[UserRole.delivery_lead.value, UserRole.recruiter.value],
    )

    assert await resolve_client_team_client_ids(db, hybrid) == frozenset({10, 20})
    assert db.scalars.await_count == 1
    rendered = str(db.scalars.await_args.args[0])
    # Od 25.09.2026 zakres Delivery DL-a = jego przypisania (nie cała baza);
    # historyczne przypisania opiekuna (TAC) nie są dokładane.
    assert "delivery_lead_client_assignments" in rendered
    assert "client_tac_assignments" not in rendered


@pytest.mark.asyncio
async def test_assigned_delivery_lead_can_read_client_surfaces() -> None:
    db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([77])))

    access = await resolve_client_access(
        db, _user(UserRole.delivery_lead), client_id=77
    )

    assert access.is_client_team
    assert access.can_view_contacts
    assert access.can_view_knowledge
    assert access.can_view_materials
    assert access.can_view_legal_documents
    assert access.generator_can_view_legal
    assert access.can_edit_materials
    assert access.can_edit_legal_documents
    assert access.generator_can_edit_legal


@pytest.mark.asyncio
async def test_unassigned_recruiter_cannot_read_any_client_surface() -> None:
    db = SimpleNamespace(
        scalars=AsyncMock(return_value=_Rows([77])),
        execute=AsyncMock(return_value=_Scalar(False)),
    )

    access = await resolve_client_access(db, _user(UserRole.recruiter), client_id=77)

    assert not access.is_client_team
    assert not access.is_job_assigned
    assert not access.can_view_contacts
    assert not access.can_view_knowledge
    assert not access.can_view_materials
    assert not access.can_edit_materials
    assert not access.can_view_legal_documents
    assert not access.can_edit_legal_documents
    assert not access.generator_can_view_legal
    assert not access.can_view_financials
    # Zespół klienta nie jest czytany z bazy — zostaje samo pytanie o rekrutację.
    db.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_job_assigned_recruiter_can_read_client_materials() -> None:
    db = SimpleNamespace(execute=AsyncMock(return_value=_Scalar(True)))

    access = await resolve_client_access(db, _user(UserRole.recruiter), client_id=77)

    assert access.is_job_assigned
    assert access.can_view_materials
    assert not access.can_edit_materials
    assert not access.can_view_legal_documents


@pytest.mark.asyncio
async def test_finance_has_organization_wide_client_read_without_edit() -> None:
    db = SimpleNamespace(scalars=AsyncMock(), execute=AsyncMock())

    access = await resolve_client_access(db, _user(UserRole.finance), client_id=77)

    assert access.is_organization_reader
    assert access.can_view_contacts
    assert access.can_view_knowledge
    assert access.can_view_materials
    assert access.can_view_legal_documents
    assert access.can_view_financials
    assert not access.can_edit_contacts
    assert not access.can_edit_knowledge
    assert not access.can_edit_materials
    # Decyzja Artura 02.10.2026: Finanse prowadzą kontrakty i zamówienia,
    # więc zapisują też umowy ramowe i wykonawcze. Klientów nie edytują.
    assert access.can_edit_legal_documents
    assert access.missing_edit_permission == "clients_edit"
    assert not access.can_manage_client
    assert access.can_view_contact_private_notes(
        SimpleNamespace(key_relationship_owner_id=999)
    )
    assert access.can_view_contact_private_notes(
        SimpleNamespace(key_relationship_owner_id=None)
    )
    db.scalars.assert_not_awaited()
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_tcm_has_safe_organization_wide_client_read() -> None:
    db = SimpleNamespace(scalars=AsyncMock(), execute=AsyncMock())

    access = await resolve_client_access(
        db,
        _user(UserRole.talent_community_manager),
        client_id=77,
    )

    assert access.is_organization_reader
    assert access.can_view_contacts
    assert access.can_view_knowledge
    assert access.can_view_materials
    assert not access.can_view_legal_documents
    assert not access.can_view_financials
    assert not access.can_edit_contacts
    assert not access.can_edit_knowledge
    assert not access.can_edit_materials
    assert not access.can_edit_legal_documents
    assert not access.can_manage_client
    db.scalars.assert_not_awaited()
    db.execute.assert_not_awaited()

    private_contact = SimpleNamespace(
        key_relationship_owner_id=100,
    )
    assert not access.can_view_contact_private_notes(private_contact)

    assert (
        await resolve_client_visible_client_ids(
            db,
            _user(UserRole.talent_community_manager),
        )
        is None
    )


@pytest.mark.asyncio
async def test_tcm_hor_hybrid_does_not_compose_into_legal_delivery_access() -> None:
    db = SimpleNamespace(scalars=AsyncMock(), execute=AsyncMock())
    hybrid = _user(
        UserRole.talent_community_manager,
        roles=[
            UserRole.talent_community_manager.value,
            UserRole.head_of_recruitment.value,
        ],
    )

    access = await resolve_client_access(db, hybrid, client_id=77)

    assert access.can_view_materials
    assert not access.can_view_legal_documents
    assert not access.can_edit_materials
    assert not access.can_view_contact_private_notes(
        SimpleNamespace(key_relationship_owner_id=hybrid.id)
    )
    db.scalars.assert_not_awaited()
    db.execute.assert_not_awaited()


def test_tcm_hor_hybrid_keeps_safe_client_and_directory_projection() -> None:
    hybrid = _user(
        UserRole.talent_community_manager,
        roles=[
            UserRole.talent_community_manager.value,
            UserRole.head_of_recruitment.value,
        ],
    )

    assert clients._client_schema_for(hybrid) is ClientSafeResponse
    assert not client_directory._can_view_directory_legal(hybrid)
    assert clients._client_schema_for(_user(UserRole.delivery_lead)) is ClientResponse
    assert client_directory._can_view_directory_legal(_user(UserRole.delivery_lead))


@pytest.mark.asyncio
async def test_tcm_dl_hybrid_uses_global_delivery_lead_client_scope() -> None:
    db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([10, 77])))
    hybrid = _user(
        UserRole.talent_community_manager,
        roles=[
            UserRole.talent_community_manager.value,
            UserRole.delivery_lead.value,
        ],
    )

    allowed = await resolve_client_access(db, hybrid, client_id=10)
    assert allowed.is_client_team
    assert not allowed.is_organization_reader

    other_client = await resolve_client_access(db, hybrid, client_id=77)
    assert other_client.is_client_team
    assert not other_client.is_organization_reader
    assert other_client.can_view_contacts


@pytest.mark.asyncio
async def test_viewer_cannot_open_mixed_client_surface() -> None:
    db = SimpleNamespace(scalars=AsyncMock(), execute=AsyncMock())

    access = await resolve_client_access(db, _user(UserRole.user), client_id=77)

    assert not access.can_view_contacts
    assert not access.can_view_materials
    assert not access.can_view_legal_documents
    assert not access.can_view_financials
    db.scalars.assert_not_awaited()
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_client_order_read_helper_uses_central_fail_closed_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.client_access import deny
    from app.services.permission_denial import permission_denied

    def decision(allowed: bool, *, missing: str | None = None) -> SimpleNamespace:
        # Lustro ``ClientAccess.legal_denial``: brak uprawnienia → nazwana
        # odmowa, uprawnienie poza zakresem klienta → dotychczasowy komunikat.
        return SimpleNamespace(
            can_view_legal_documents=allowed,
            legal_denial=lambda detail, write=False: (
                permission_denied(missing) if missing else deny(detail)
            ),
        )

    assert_client = AsyncMock()
    resolve_access = AsyncMock(return_value=decision(False))
    monkeypatch.setattr(client_orders, "_assert_client", assert_client)
    monkeypatch.setattr(client_orders, "resolve_client_access", resolve_access)

    with pytest.raises(HTTPException) as exc:
        await client_orders._require_client_order_read(
            db=object(),  # type: ignore[arg-type]
            user=_user(UserRole.recruiter),
            client_id=77,
        )
    assert exc.value.status_code == 403
    assert str(exc.value.detail).startswith("client_access_denied")

    # Dokument zamówienia niesie stawki: brak „Stawki i kwoty: podgląd”
    # kończy się odmową, która nazywa to uprawnienie.
    resolve_access.return_value = decision(False, missing="amounts_view")
    with pytest.raises(HTTPException) as exc:
        await client_orders._require_client_order_read(
            db=object(),  # type: ignore[arg-type]
            user=_user(UserRole.recruiter),
            client_id=77,
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "permission_denied"
    assert exc.value.detail["permission"] == "amounts_view"

    resolve_access.return_value = decision(True)
    await client_orders._require_client_order_read(
        db=object(),  # type: ignore[arg-type]
        user=_user(UserRole.recruiter),
        client_id=77,
    )

    assert assert_client.await_count == 3
    assert resolve_access.await_count == 3


@pytest.mark.asyncio
async def test_recruitment_operator_global_client_scope_uses_only_assigned_jobs() -> (
    None
):
    db = SimpleNamespace(
        scalars=AsyncMock(side_effect=[_Rows([10]), _Rows([20])]),
    )

    visible = await resolve_client_visible_client_ids(
        db,
        _user(UserRole.recruiter),
    )

    assert visible == frozenset({10, 20})
    assert db.scalars.await_count == 2
    rendered = "\n".join(str(call.args[0]) for call in db.scalars.await_args_list)
    assert "jobs.recruiter_id" in rendered
    assert "job_collaborators.user_id" in rendered


@pytest.mark.asyncio
async def test_hybrid_visible_scope_uses_dl_assignments_from_dl_role() -> None:
    """DL+rekruter: zakres Delivery z przypisań DL (25.09.2026), bez Jobów."""

    db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([10, 77])))
    hybrid = _user(
        UserRole.delivery_lead,
        roles=[UserRole.delivery_lead.value, UserRole.recruiter.value],
    )

    assert await resolve_client_visible_client_ids(db, hybrid) == frozenset({10, 77})
    assert db.scalars.await_count == 1
    rendered = str(db.scalars.await_args.args[0])
    assert "delivery_lead_client_assignments" in rendered
    assert "jobs.recruiter_id" not in rendered


@pytest.mark.asyncio
async def test_hybrid_visible_scope_uses_all_clients_for_org_purpose() -> None:
    db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([10, 77, 99])))
    hybrid = _user(
        UserRole.delivery_lead,
        roles=[UserRole.delivery_lead.value, UserRole.recruiter.value],
    )

    assert await resolve_client_visible_client_ids(
        db, hybrid, purpose="org"
    ) == frozenset({10, 77, 99})
    assert db.scalars.await_count == 1
    assert "FROM clients" in str(db.scalars.await_args.args[0])


@pytest.mark.asyncio
async def test_dl_client_scope_all_restores_every_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wyłącznik ``DL_CLIENT_SCOPE=all`` przywraca stan z #1365."""

    from app.core.config import settings

    monkeypatch.setattr(settings, "DL_CLIENT_SCOPE", "all")
    db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([10, 20, 30])))

    assert await resolve_client_team_client_ids(
        db, _user(UserRole.delivery_lead)
    ) == frozenset({10, 20, 30})
    assert "FROM clients" in str(db.scalars.await_args.args[0])


@pytest.mark.asyncio
async def test_unassigned_delivery_lead_is_denied_delivery_but_not_org_surfaces() -> (
    None
):
    empty_db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([])))
    denied = await resolve_client_access(
        empty_db, _user(UserRole.delivery_lead), client_id=77
    )
    assert not denied.is_client_team
    assert not denied.can_view_contacts
    assert not denied.can_view_knowledge
    assert not denied.can_view_legal_documents
    assert not denied.can_edit_contacts

    # ``org``: zespół klienta liczy się z całej bazy, przypisania (puste)
    # nadal bramkują zapisy prawne.
    org_db = SimpleNamespace(
        scalars=AsyncMock(side_effect=[_Rows([77]), _Rows([])]),
    )
    org_access = await resolve_client_access(
        org_db, _user(UserRole.delivery_lead), client_id=77, purpose="org"
    )
    assert org_access.is_client_team
    assert org_access.can_view_knowledge
    assert org_access.can_view_legal_documents
    assert not org_access.is_delivery_lead_assigned
    assert not org_access.can_edit_legal_documents


@pytest.mark.asyncio
async def test_delivery_lead_finance_scope_still_uses_assignments() -> None:
    db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([10])))
    delivery_lead = _user(UserRole.delivery_lead)

    finance_client_ids = await resolve_delivery_lead_finance_client_ids(
        delivery_lead,
        db,
    )

    assert finance_client_ids == frozenset({10})
    rendered = str(db.scalars.await_args.args[0])
    assert "delivery_lead_client_assignments" in rendered
    # Od rundy 6 (DL-04) zapytanie czyta ``clients`` wyłącznie po to, żeby
    # przypisanie na scalonym duplikacie objęło klienta kanonicznego (i
    # odwrotnie) — każdy warunek wychodzi od przypisań DL, nie z całej firmy.
    assert "merged_into_client_id" in rendered
    where = rendered.split("WHERE", 1)[1]
    assert where.count("delivery_lead_client_assignments") >= 1


@pytest.mark.asyncio
async def test_material_and_required_document_writes_use_central_edit_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Decyzje z prawdziwego resolvera (moduły wołają też jego nazwaną odmowę):
    # konto bez uprawnień, konto z uprawnieniami poza portfelem i admin.
    denied = await resolve_client_access(
        SimpleNamespace(execute=AsyncMock(return_value=_Scalar(False))),
        _user(UserRole.recruiter),
        client_id=77,
    )
    out_of_portfolio = await resolve_client_access(
        SimpleNamespace(scalars=AsyncMock(return_value=_Rows([10]))),
        _user(UserRole.delivery_lead),
        client_id=77,
    )
    allowed = await resolve_client_access(
        SimpleNamespace(scalars=AsyncMock(), execute=AsyncMock()),
        _user(UserRole.admin),
        client_id=77,
    )
    assert not denied.can_edit_materials and not denied.can_edit_legal_documents
    assert not out_of_portfolio.can_edit_materials
    assert not out_of_portfolio.can_edit_legal_documents
    assert allowed.can_edit_materials and allowed.can_edit_legal_documents

    material_resolver = AsyncMock(return_value=denied)
    docs_resolver = AsyncMock(return_value=denied)
    monkeypatch.setattr(
        client_materials,
        "resolve_client_access",
        material_resolver,
    )
    monkeypatch.setattr(
        required_documents,
        "resolve_client_access",
        docs_resolver,
    )

    with pytest.raises(HTTPException) as material_exc:
        await client_materials._require_material_write(
            object(),  # type: ignore[arg-type]
            _user(UserRole.delivery_lead),
            77,
        )
    assert material_exc.value.status_code == 403
    # Brak uprawnienia — odmowa nazywa je, zamiast mówić o roli.
    assert material_exc.value.detail["code"] == "permission_denied"
    assert material_exc.value.detail["permission"] == "clients_edit"

    with pytest.raises(HTTPException) as legal_exc:
        await client_materials._require_material_write(
            object(),  # type: ignore[arg-type]
            _user(UserRole.recruiter),
            77,
            legal=True,
        )
    assert legal_exc.value.status_code == 403
    assert legal_exc.value.detail["permission"] == "contracts_orders_edit"

    with pytest.raises(HTTPException) as docs_exc:
        await required_documents._require_required_docs_access(
            object(),  # type: ignore[arg-type]
            _user(UserRole.recruiter),
            77,
            write=True,
        )
    assert docs_exc.value.status_code == 403
    assert docs_exc.value.detail["permission"] == "clients_edit"

    # Uprawnienie jest, klient leży poza portfelem — dotychczasowy komunikat
    # (bez nazwy uprawnienia, bo to nie jego brakuje).
    material_resolver.return_value = out_of_portfolio
    docs_resolver.return_value = out_of_portfolio
    with pytest.raises(HTTPException) as scope_exc:
        await client_materials._require_material_write(
            object(),  # type: ignore[arg-type]
            _user(UserRole.delivery_lead),
            77,
        )
    assert scope_exc.value.status_code == 403
    assert str(scope_exc.value.detail).startswith("client_access_denied")
    with pytest.raises(HTTPException) as legal_scope_exc:
        await client_materials._require_material_write(
            object(),  # type: ignore[arg-type]
            _user(UserRole.delivery_lead),
            77,
            legal=True,
        )
    assert legal_scope_exc.value.status_code == 403
    assert str(legal_scope_exc.value.detail).startswith("client_access_denied")
    with pytest.raises(HTTPException) as docs_scope_exc:
        await required_documents._require_required_docs_access(
            object(),  # type: ignore[arg-type]
            _user(UserRole.delivery_lead),
            77,
            write=True,
        )
    assert docs_scope_exc.value.status_code == 403
    assert str(docs_scope_exc.value.detail).startswith("client_access_denied")

    material_resolver.return_value = allowed
    docs_resolver.return_value = allowed
    await client_materials._require_material_write(
        object(),  # type: ignore[arg-type]
        _user(UserRole.delivery_lead),
        77,
    )
    await client_materials._require_material_write(
        object(),  # type: ignore[arg-type]
        _user(UserRole.recruiter),
        77,
        legal=True,
    )
    await required_documents._require_required_docs_access(
        object(),  # type: ignore[arg-type]
        _user(UserRole.recruiter),
        77,
        write=True,
    )


@pytest.mark.asyncio
async def test_contract_legal_global_gate_requires_nonempty_relationship() -> None:
    assigned_db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([77])))
    unassigned_db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([])))
    dl = _user(UserRole.delivery_lead)

    assert (
        await require_contract_legal_access(
            current_user=dl,
            db=assigned_db,
        )
        is dl
    )
    with pytest.raises(HTTPException) as exc:
        await require_contract_legal_access(
            current_user=dl,
            db=unassigned_db,
        )
    assert exc.value.status_code == 403

    admin = _user(UserRole.admin)
    no_query_db = SimpleNamespace(scalars=AsyncMock())
    assert (
        await require_contract_legal_access(
            current_user=admin,
            db=no_query_db,
        )
        is admin
    )
    no_query_db.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_contract_legal_entity_scope_filters_lists_and_denies_null_client() -> (
    None
):
    dl = _user(UserRole.delivery_lead)
    db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([10, 20])))
    scoped = await apply_contract_legal_client_scope(
        select(B2BGeneratedContract),
        B2BGeneratedContract.client_id,
        db,
        dl,
    )
    rendered = str(scoped.compile(compile_kwargs={"literal_binds": True}))
    assert "b2b_generated_contracts.client_id IN (10, 20)" in rendered

    empty_db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([])))
    empty = await apply_contract_legal_client_scope(
        select(B2BGeneratedContract),
        B2BGeneratedContract.client_id,
        empty_db,
        dl,
    )
    empty_rendered = str(empty.compile(compile_kwargs={"literal_binds": True}))
    assert "b2b_generated_contracts.client_id IN (-1)" in empty_rendered

    with pytest.raises(HTTPException) as exc:
        await assert_contract_legal_client_access(
            object(),  # type: ignore[arg-type]
            dl,
            None,
        )
    assert exc.value.status_code == 403
    await assert_contract_legal_client_access(
        object(),  # type: ignore[arg-type]
        _user(UserRole.head_of_recruitment),
        None,
    )
