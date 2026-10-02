"""Bramki tras dla dziewięciu uprawnień z ekranu Ustawienia → Osoby i role.

Trasa pyta o UPRAWNIENIE, nie o rolę: alias z tego modułu zamiast
``require_roles(...)``. Dzięki temu to, co administrator zaznacza na ekranie,
jest tym, co decyduje — a odmowa mówi po imieniu, czego brakuje.

Zakres klientów nie należy do bramki uprawnienia. Konto z rolą Delivery Leada
działa u swoich klientów (``access_scope``), pozostali posiadacze — u
wszystkich; handler dalej woła swój helper zakresu. Wyjątkiem jest
``ClientContractsEditUser``, które łączy uprawnienie z przypisaniem klienta
z adresu (konsekwentne zapisy: umowy wykonawcze, obsada zamówień).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    FinanceModuleUser,
    require_any_permission,
    require_onboarded_user,
    require_permission,
)
from app.core.database import get_db
from app.models.user import User
from app.services.access_scope import (
    DL_CLIENT_OUT_OF_SCOPE_DETAIL,
    resolve_delivery_lead_assigned_client_ids,
)
from app.services.action_permissions import ProductAction, has_permission
from app.services.permission_denial import (
    PERMISSION_DENIED_CODE,
    ensure_any_permission,
    ensure_permission,
    permission_denied,
)

__all__ = [
    "PERMISSION_DENIED_CODE",
    "AmountsEditUser",
    "AmountsViewUser",
    "ClientContractsEditUser",
    "ClientsEditUser",
    "ContractStatusUser",
    "ContractsOrdersEditUser",
    "ContractsOrdersOrAmountsEditUser",
    "DeliveryViewUser",
    "FinanceModuleUser",
    "RecruitmentManageUser",
    "ensure_any_permission",
    "ensure_permission",
    "has_permission",
    "permission_denied",
    "require_any_permission",
    "require_client_contracts_edit",
    "require_permission",
]

# Jeden obiekt zależności na uprawnienie — FastAPI liczy go raz na żądanie.
DeliveryViewUser = Annotated[
    User, Depends(require_permission(ProductAction.delivery_view))
]
ClientsEditUser = Annotated[
    User, Depends(require_permission(ProductAction.clients_edit))
]
ContractsOrdersEditUser = Annotated[
    User, Depends(require_permission(ProductAction.contracts_orders_edit))
]
ContractStatusUser = Annotated[
    User, Depends(require_permission(ProductAction.contract_status))
]
RecruitmentManageUser = Annotated[
    User, Depends(require_permission(ProductAction.recruitment_manage))
]
AmountsViewUser = Annotated[
    User, Depends(require_permission(ProductAction.amounts_view))
]
AmountsEditUser = Annotated[
    User, Depends(require_permission(ProductAction.amounts_edit))
]
# Trasa mieszana (PATCH kontraktu, zamówienia, linii): edycja rekordu ALBO sama
# zmiana kwot. Handler woła ``financial_access.assert_amounts_only``.
ContractsOrdersOrAmountsEditUser = Annotated[
    User,
    Depends(
        require_any_permission(
            ProductAction.contracts_orders_edit, ProductAction.amounts_edit
        )
    ),
]


async def require_client_contracts_edit(
    client_id: int,
    current_user: User = Depends(require_onboarded_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """„Kontrakty i zamówienia: tworzenie i edycja” u klienta z adresu.

    Konto z rolą Delivery Leada musi mieć tego klienta w przypisaniach
    (``resolve_delivery_lead_assigned_client_ids`` — razem ze scalonymi
    duplikatami); pozostałych posiadaczy przypisanie nie dotyczy. FastAPI
    bierze ``client_id`` z parametru ścieżki routera.
    """

    ensure_permission(current_user, ProductAction.contracts_orders_edit)
    assigned = await resolve_delivery_lead_assigned_client_ids(current_user, db)
    if assigned is not None and client_id not in assigned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DL_CLIENT_OUT_OF_SCOPE_DETAIL,
        )
    return current_user


require_client_contracts_edit.required_permissions = (
    ProductAction.contracts_orders_edit,
)

ClientContractsEditUser = Annotated[User, Depends(require_client_contracts_edit)]
