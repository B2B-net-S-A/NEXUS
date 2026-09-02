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
    assert access.can_view_legal_documents
    assert access.can_view_materials
    assert access.can_edit_materials is (role is UserRole.admin)
    assert access.can_manage_client is (role is UserRole.admin)
    db.scalars.assert_not_awaited()
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_delivery_lead_and_tac_use_only_their_explicit_assignment_tables() -> (
    None
):
    dl_db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([10, 20])))
    tac_db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([30, 40])))

    assert await resolve_client_team_client_ids(
        dl_db,
        _user(UserRole.delivery_lead),
    ) == frozenset({10, 20})
    dl_sql = str(dl_db.scalars.await_args.args[0])
    assert "delivery_lead_client_assignments" in dl_sql
    assert "client_tac_assignments" not in dl_sql

    assert await resolve_client_team_client_ids(
        tac_db,
        _user(UserRole.tac),
    ) == frozenset({30, 40})
    tac_sql = str(tac_db.scalars.await_args.args[0])
    assert "client_tac_assignments" in tac_sql
    assert "delivery_lead_client_assignments" not in tac_sql


@pytest.mark.asyncio
async def test_valid_dl_tac_hybrid_uses_only_dl_assignments() -> None:
    db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([10, 20])))
    hybrid = _user(
        UserRole.delivery_lead,
        roles=[UserRole.delivery_lead.value, UserRole.tac.value],
    )

    assert await resolve_client_team_client_ids(db, hybrid) == frozenset({10, 20})
    assert db.scalars.await_count == 1
    rendered = str(db.scalars.await_args.args[0])
    assert "delivery_lead_client_assignments" in rendered
    assert "client_tac_assignments" not in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.delivery_lead, UserRole.tac])
async def test_unassigned_client_team_role_is_deny_all(role: UserRole) -> None:
    db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([])))

    access = await resolve_client_access(db, _user(role), client_id=77)

    assert not access.is_client_team
    assert not access.can_view_contacts
    assert not access.can_view_knowledge
    assert not access.can_view_materials
    assert not access.can_edit_materials
    assert not access.can_view_legal_documents
    assert not access.can_edit_legal_documents
    assert not access.can_view_financials


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.delivery_lead, UserRole.tac])
async def test_assigned_client_team_role_can_read_client_surfaces(
    role: UserRole,
) -> None:
    db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([77])))

    access = await resolve_client_access(db, _user(role), client_id=77)

    assert access.is_client_team
    assert access.can_view_contacts
    assert access.can_view_knowledge
    assert access.can_view_materials
    assert access.can_view_legal_documents
    assert access.can_edit_materials is (role is UserRole.delivery_lead)
    assert access.can_edit_legal_documents is (role is UserRole.delivery_lead)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.recruiter, UserRole.sourcer])
async def test_unassigned_recruitment_operator_cannot_read_client_materials(
    role: UserRole,
) -> None:
    db = SimpleNamespace(execute=AsyncMock(return_value=_Scalar(False)))

    access = await resolve_client_access(db, _user(role), client_id=77)

    assert not access.is_job_assigned
    assert not access.can_view_materials


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.recruiter, UserRole.sourcer])
async def test_job_assigned_recruitment_operator_can_read_client_materials(
    role: UserRole,
) -> None:
    db = SimpleNamespace(execute=AsyncMock(return_value=_Scalar(True)))

    access = await resolve_client_access(db, _user(role), client_id=77)

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
    assert not access.can_edit_legal_documents
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
async def test_tcm_dl_hybrid_cannot_borrow_global_tcm_delivery_scope() -> None:
    db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([10])))
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

    db.scalars.reset_mock()
    db.scalars.return_value = _Rows([10])
    denied = await resolve_client_access(db, hybrid, client_id=77)
    assert not denied.is_client_team
    assert not denied.is_organization_reader
    assert not denied.can_view_contacts


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
    assert_client = AsyncMock()
    resolve_access = AsyncMock(
        return_value=SimpleNamespace(can_view_legal_documents=False)
    )
    monkeypatch.setattr(client_orders, "_assert_client", assert_client)
    monkeypatch.setattr(client_orders, "resolve_client_access", resolve_access)

    with pytest.raises(HTTPException) as exc:
        await client_orders._require_client_order_read(
            db=object(),  # type: ignore[arg-type]
            user=_user(UserRole.tac),
            client_id=77,
        )
    assert exc.value.status_code == 403
    assert str(exc.value.detail).startswith("client_access_denied")

    resolve_access.return_value = SimpleNamespace(can_view_legal_documents=True)
    await client_orders._require_client_order_read(
        db=object(),  # type: ignore[arg-type]
        user=_user(UserRole.tac),
        client_id=77,
    )

    assert assert_client.await_count == 2
    assert resolve_access.await_count == 2


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
async def test_hybrid_visible_scope_stays_inside_dl_assignments() -> None:
    db = SimpleNamespace(scalars=AsyncMock(return_value=_Rows([10])))
    hybrid = _user(
        UserRole.delivery_lead,
        roles=[UserRole.delivery_lead.value, UserRole.recruiter.value],
    )

    assert await resolve_client_visible_client_ids(db, hybrid) == frozenset({10})
    assert db.scalars.await_count == 1


@pytest.mark.asyncio
async def test_material_and_required_document_writes_use_central_edit_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    denied = SimpleNamespace(
        can_edit_materials=False,
        can_edit_legal_documents=False,
    )
    allowed = SimpleNamespace(
        can_edit_materials=True,
        can_edit_legal_documents=True,
    )
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

    with pytest.raises(HTTPException) as legal_exc:
        await client_materials._require_material_write(
            object(),  # type: ignore[arg-type]
            _user(UserRole.tac),
            77,
            legal=True,
        )
    assert legal_exc.value.status_code == 403

    with pytest.raises(HTTPException) as docs_exc:
        await required_documents._require_required_docs_access(
            object(),  # type: ignore[arg-type]
            _user(UserRole.tac),
            77,
            write=True,
        )
    assert docs_exc.value.status_code == 403

    material_resolver.return_value = allowed
    docs_resolver.return_value = allowed
    await client_materials._require_material_write(
        object(),  # type: ignore[arg-type]
        _user(UserRole.delivery_lead),
        77,
    )
    await client_materials._require_material_write(
        object(),  # type: ignore[arg-type]
        _user(UserRole.tac),
        77,
        legal=True,
    )
    await required_documents._require_required_docs_access(
        object(),  # type: ignore[arg-type]
        _user(UserRole.tac),
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
