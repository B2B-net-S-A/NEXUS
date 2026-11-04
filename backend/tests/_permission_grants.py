"""Uprawnienia z ekranu w testach HTTP.

Nadanie osobie (jak okno „Edytuj użytkownika”) i tymczasowe przełączenie
uprawnienia roli. Uprawnienia są czytane z bazy przy każdym żądaniu, więc
zmiana działa od następnego wywołania tym samym tokenem.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.core.database import AsyncSessionLocal
from app.models.section_permission import RoleActionPermission, UserActionOverride
from app.models.user import UserRole
from app.services.action_permissions import ProductAction


async def grant_permissions(user_id: int, *permissions: ProductAction | str) -> None:
    """Nadaj osobie uprawnienia ponad to, co daje jej rola."""

    async with AsyncSessionLocal() as db:
        for permission in permissions:
            await db.merge(
                UserActionOverride(
                    user_id=user_id,
                    action=ProductAction(permission).value,
                    access="manage",
                )
            )
        await db.commit()


@asynccontextmanager
async def role_permission(
    role: UserRole | str, permission: ProductAction | str, *, granted: bool
) -> AsyncIterator[None]:
    """Przełącz uprawnienie ROLI na czas bloku.

    Baza testowa jest wspólna dla całego przebiegu, więc poprzednia wartość
    wraca także wtedy, gdy test padnie.
    """

    role_value = UserRole(role).value
    action = ProductAction(permission).value
    async with AsyncSessionLocal() as db:
        row = await db.get(RoleActionPermission, (role_value, action))
        before = row.access if row is not None else None
        access = "manage" if granted else "none"
        if row is None:
            db.add(RoleActionPermission(role=role_value, action=action, access=access))
        else:
            row.access = access
        await db.commit()
    try:
        yield
    finally:
        async with AsyncSessionLocal() as db:
            row = await db.get(RoleActionPermission, (role_value, action))
            if row is not None:
                if before is None:
                    await db.delete(row)
                else:
                    row.access = before
            await db.commit()
