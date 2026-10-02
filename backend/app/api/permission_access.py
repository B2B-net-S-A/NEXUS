"""Bramki tras dla dziewięciu uprawnień z ekranu Ustawienia → Osoby i role.

Trasa pyta o UPRAWNIENIE, nie o rolę: ``require_permission(...)`` zamiast
``require_roles(...)``. Dzięki temu to, co administrator zaznacza na ekranie,
jest tym, co decyduje — a odmowa mówi po imieniu, czego brakuje.

Zakres klientów nie należy do tej bramki. Konto z rolą Delivery Leada działa
u swoich klientów (``access_scope``), pozostali posiadacze — u wszystkich;
handler dalej woła swój helper zakresu.
"""

from __future__ import annotations

from fastapi import Depends

from app.api.deps import require_onboarded_user
from app.models.user import User
from app.services.action_permissions import ProductAction, has_permission
from app.services.permission_denial import (
    PERMISSION_DENIED_CODE,
    ensure_any_permission,
    ensure_permission,
    permission_denied,
)

__all__ = [
    "PERMISSION_DENIED_CODE",
    "ensure_any_permission",
    "ensure_permission",
    "has_permission",
    "permission_denied",
    "require_any_permission",
    "require_permission",
]


def require_permission(permission: ProductAction):
    """Zależność trasy: konto musi mieć ``permission``."""

    async def _check(current_user: User = Depends(require_onboarded_user)) -> User:
        ensure_permission(current_user, permission)
        return current_user

    return _check


def require_any_permission(*permissions: ProductAction):
    """Zależność trasy: wystarczy jedno z ``permissions``."""

    if not permissions:
        raise ValueError("At least one permission is required")

    async def _check(current_user: User = Depends(require_onboarded_user)) -> User:
        ensure_any_permission(current_user, *permissions)
        return current_user

    return _check
