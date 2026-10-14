"""API integracyjne v1 (``/api/integrations/v1``) — automatyzacje procesów firmy.

Każdy moduł ma własny ``router`` z ``route_class=IntegrationRoute`` (koperta
błędu v1); ``main.py`` montuje je pod wspólnym prefiksem ``PREFIX``.
Uwierzytelnienie wyłącznie kluczem ``X-API-Key`` (konto serwisowe ze
scope'ami) — opis i zasady: ``docs/api/integracje-v1.md``.
"""

from app.api.integrations_v1 import (
    clients,
    contract_writes,
    contracts,
    finance,
    invoices,
    md,
    meta,
    order_writes,
    orders,
)
from app.api.integrations_v1.common import PREFIX

ROUTERS = (
    meta.router,
    clients.router,
    contracts.router,
    contract_writes.router,
    orders.router,
    order_writes.router,
    md.router,
    finance.router,
    invoices.router,
)

__all__ = ["PREFIX", "ROUTERS"]
