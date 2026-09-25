"""Bramka zakresu klientów Delivery Leada na trasach ``/{client_id}/...``.

Od 25.09.2026 Delivery Lead widzi w modułach Delivery wyłącznie klientów
z przypisania (``access_scope.resolve_delivery_lead_client_ids``). Część tras
zamówień, umów ramowych i wykonawczych autoryzowała zapis samą rolą
(``DeliveryLeadOrAdmin``) — bez tej bramki DL mógłby założyć zamówienie
u klienta, którego nie widzi. Zależność czyta ``client_id`` z adresu, więc
jedna linijka na routerze obejmuje wszystkie jego trasy; trasa bez
``client_id`` w adresie przechodzi bez zmian.
"""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services.access_scope import (
    assert_delivery_lead_client_visible,
    resolve_delivery_lead_client_ids,
)


async def require_delivery_client_path_scope(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    raw = request.path_params.get("client_id")
    if raw is None:
        return
    try:
        client_id = int(raw)
    except (TypeError, ValueError):
        return
    assert_delivery_lead_client_visible(
        client_id, await resolve_delivery_lead_client_ids(current_user, db)
    )


DELIVERY_CLIENT_SCOPE_DEPENDENCIES = [Depends(require_delivery_client_path_scope)]
