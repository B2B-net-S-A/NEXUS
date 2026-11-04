"""Odmowa z nazwą brakującego uprawnienia (jedno z dziewięciu z ekranu).

Moduł bez zależności od ``app.api`` — importują go zarówno bramki tras
(``api/permission_access``), jak i helpery w środku handlerów
(``api/financial_access``, ``services/client_access``).
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.models.user import User
from app.services import permission_catalog as catalog
from app.services.action_permissions import ProductAction, has_permission

PERMISSION_DENIED_CODE = "permission_denied"


def permission_denied(*permissions: ProductAction | str) -> HTTPException:
    """403 z nazwą brakującego uprawnienia (kilka = wystarczy jedno z nich)."""

    keys = [ProductAction(permission).value for permission in permissions]
    labels = [catalog.label(key) for key in keys]
    listed = " albo ".join(f"„{label}”" for label in labels)
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": PERMISSION_DENIED_CODE,
            "permission": keys[0],
            "label": labels[0],
            "permissions": keys,
            "message": (
                f"Brakuje Ci uprawnienia {listed}. Poproś administratora o dostęp."
            ),
        },
    )


def ensure_permission(user: User, permission: ProductAction | str) -> None:
    """Sprawdzenie w środku handlera (gdy uprawnienie zależy od treści żądania)."""

    if not has_permission(user, permission):
        raise permission_denied(permission)


def ensure_any_permission(user: User, *permissions: ProductAction | str) -> None:
    if not any(has_permission(user, permission) for permission in permissions):
        raise permission_denied(*permissions)
