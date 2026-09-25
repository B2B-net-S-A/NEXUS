"""Multiposting rekrutacji na portale ogłoszeniowe (0360, 0381) — rejestr adapterów.

Obsługiwane: JustJoin.IT i RocketJobs (jedno Employer Public API dostawcy,
jedno połączone konto firmy) oraz Pracuj.pl (czeka na dokumentację API).
Wszystko za flagami (domyślnie OFF): sekcja „Portale” w oknie zlecenia
i na ekranie nowej rekrutacji pokazuje się dopiero, gdy którykolwiek portal
jest gotowy, a worker kończy się przed pętlą. Pozostałe wartości enuma
``portal`` (LinkedIn, NFJ, Bulldogjob) zostały z symulacji i nie mają adaptera.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_posting import Portal
from app.services.job_portals.base import (
    PortalAdapter,
    PortalConfig,
    PortalError,
    PortalNotConfigured,
    PortalNotImplemented,
    PortalResult,
    PostingContent,
)
from app.services.job_portals.jjit import JjitAdapter, RocketJobsAdapter
from app.services.job_portals.pracuj import PracujAdapter

ADAPTERS: dict[Portal, type[PortalAdapter]] = {
    Portal.rocketjobs: RocketJobsAdapter,
    Portal.justjoinit: JjitAdapter,
    Portal.pracuj_pl: PracujAdapter,
}

__all__ = [
    "ADAPTERS",
    "PortalAdapter",
    "PortalConfig",
    "PortalError",
    "PortalNotConfigured",
    "PortalNotImplemented",
    "PortalResult",
    "PostingContent",
    "adapter_for",
    "portal_configs",
    "any_enabled",
    "resolve_state",
    "health_state",
]


def adapter_for(portal: Portal) -> PortalAdapter:
    try:
        return ADAPTERS[portal]()
    except KeyError:
        raise PortalNotConfigured("Ten portal nie ma integracji w NEXUSIE.") from None


def portal_configs() -> list[PortalConfig]:
    return [PortalConfig.from_settings(portal) for portal in ADAPTERS]


def any_enabled() -> bool:
    return any(config.enabled for config in portal_configs())


async def resolve_state(db: AsyncSession, config: PortalConfig) -> str:
    """Stan z env-ów + połączenie konta (JustJoin.IT / RocketJobs)."""
    state = config.state
    if state != "ready" or not config.needs_connection:
        return state
    from app.services.job_portals import jjit_connection

    return "ready" if await jjit_connection.is_connected(db) else "not_connected"


def health_state(failed_recently: int, *, reconnect_required: bool = False) -> str:
    """``checks.job_portals`` — informacyjne, nigdy nie zmienia ``status``.

    ``unconfigured`` = wszystkie portale wyłączone (stan dzisiejszy),
    ``misconfigured`` = włączony bez konfiguracji, ``degraded`` = konto
    portalu do ponownego połączenia albo nieudane publikacje w ostatniej
    dobie, inaczej ``healthy``.
    """

    configs = portal_configs()
    if not any(c.enabled for c in configs):
        return "unconfigured"
    if any(c.state == "misconfigured" for c in configs):
        return "misconfigured"
    if reconnect_required or failed_recently:
        return "degraded"
    return "healthy"
