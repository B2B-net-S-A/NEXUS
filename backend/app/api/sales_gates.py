"""Bramki tras Sprzedaży: „Sprzedaż: podgląd” na odczyt, „Sprzedaż: edycja” na zapis.

Sprzedaż nie ma osobnej sekcji produktu (jak „Ludzie”) — decyduje uprawnienie
z ekranu Osoby i role (decyzja Artura 26.10.2026, bez roli „Handlowiec”).
Zmianę opiekuna i rzeczy nieodwracalne robi opiekun albo admin
(``ensure_owner_or_admin``), jak w Atlasie robił to opiekun albo manager.
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status

from app.api.permission_access import SalesEditUser, SalesViewUser
from app.models.user import User, UserRole

__all__ = ["SalesEditUser", "SalesViewUser", "ensure_owner_or_admin", "is_admin"]

OWNER_ONLY_DETAIL = "Opiekuna zmienia obecny opiekun albo administrator."


def is_admin(user: User) -> bool:
    roles = {str(role) for role in (user.roles or [])} | {user.role.value}
    return UserRole.admin.value in roles


def ensure_owner_or_admin(user: User, owner_user_id: Optional[int]) -> None:
    if owner_user_id is None or owner_user_id == user.id or is_admin(user):
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, detail=OWNER_ONLY_DETAIL)
