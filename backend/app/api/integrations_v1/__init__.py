"""API integracyjne v1 (``/api/integrations/v1``) — automatyzacje procesów firmy.

Każdy moduł ma własny ``router`` z ``route_class=IntegrationRoute`` (koperta
błędu v1); ``main.py`` montuje je pod wspólnym prefiksem ``PREFIX``.
Uwierzytelnienie wyłącznie kluczem ``X-API-Key`` (konto serwisowe ze
scope'ami) — opis i zasady: ``docs/api/integracje-v1.md``.
"""

from app.api.integrations_v1 import (
    academy,
    applications,
    calendar,
    candidate_writes,
    candidates,
    clients,
    contract_writes,
    contracts,
    cv,
    events,
    finance,
    insights,
    invoices,
    md,
    meta,
    order_writes,
    orders,
    recruitment_create,
    recruitment_writes,
    recruitments,
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
    recruitments.router,
    recruitment_writes.router,
    candidates.router,
    candidate_writes.router,
    recruitment_create.router,
    cv.router,
    calendar.router,
    applications.router,
    insights.router,
    academy.router,
    events.router,
)

__all__ = ["PREFIX", "ROUTERS"]
