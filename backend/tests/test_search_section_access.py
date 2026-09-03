"""Section and client-scope contract for mixed-entity search buckets."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api import search
from app.models.user import User, UserRole
from app.services.section_permissions import ProductSection


class _EmptyResult:
    def scalars(self) -> _EmptyResult:
        return self

    def all(self) -> list[object]:
        return []


def _user(*, role: UserRole, access: dict[str, str]) -> User:
    user = User(
        id=987654,
        email="search-section@example.com",
        name="Search Section",
        role=role,
        roles=[role.value],
        is_active=True,
    )
    user.effective_section_access = {
        section.value: access.get(section.value, "none") for section in ProductSection
    }
    return user


@pytest.mark.asyncio
async def test_global_search_skips_every_denied_bucket_without_querying_db() -> None:
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=AssertionError("unexpected SQL"))
    )
    user = _user(role=UserRole.recruiter, access={})

    response = await search.global_search(user, db, "needle")

    assert response == {
        "query": "needle",
        "candidates": [],
        "jobs": [],
        "clients": [],
        "contacts": [],
    }
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_global_search_applies_canonical_scope_to_clients_and_contacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = SimpleNamespace(execute=AsyncMock(return_value=_EmptyResult()))
    user = _user(
        role=UserRole.user,
        access={"pipeline": "read", "delivery": "read"},
    )
    resolve_scope = AsyncMock(return_value=frozenset({17}))
    monkeypatch.setattr(search, "resolve_client_visible_client_ids", resolve_scope)

    response = await search.global_search(user, db, "needle")

    assert response["candidates"] == []
    assert response["jobs"] == []
    assert response["clients"] == []
    assert response["contacts"] == []
    resolve_scope.assert_awaited_once_with(db, user)
    rendered = [
        " ".join(str(statement.compile(compile_kwargs={"literal_binds": True})).split())
        for statement in (call.args[0] for call in db.execute.await_args_list)
    ]
    assert any("clients.id IN (17)" in sql for sql in rendered)
    assert any("contacts.client_id IN (17)" in sql for sql in rendered)


@pytest.mark.asyncio
async def test_global_search_uses_exact_section_for_candidates_and_contacts() -> None:
    db = SimpleNamespace(execute=AsyncMock(return_value=_EmptyResult()))
    pipeline_only = _user(role=UserRole.recruiter, access={"pipeline": "read"})

    response = await search.global_search(pipeline_only, db, "needle")

    assert response["candidates"] == []
    assert response["clients"] == []
    assert response["contacts"] == []
    assert response["jobs"] == []
    # The sole query belongs to the allowed Pipeline jobs bucket.
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_unified_search_requires_sourcing_for_candidate_bucket() -> None:
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=AssertionError("unexpected SQL"))
    )
    pipeline_only = _user(role=UserRole.recruiter, access={"pipeline": "read"})

    response = await search.unified_search(
        pipeline_only,
        db,
        "needle",
        entity="candidates",
    )

    assert response == {"query": "needle", "results": {}}
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_unified_search_omits_pipeline_and_delivery_buckets_when_denied() -> None:
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=AssertionError("unexpected SQL"))
    )
    user = _user(role=UserRole.recruiter, access={})

    response = await search.unified_search(user, db, "needle")

    assert response == {"query": "needle", "results": {}}
    db.execute.assert_not_awaited()
