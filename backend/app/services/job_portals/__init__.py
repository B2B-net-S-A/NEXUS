"""Multiposting rekrutacji na portale ogłoszeniowe (0358) — rejestr adapterów.

Obsługiwane: Pracuj.pl i JustJoinIT. Oba czekają na dokumentację API, więc
dziś to szkielet za flagami (domyślnie OFF): sekcja „Portale” w oknie
zlecenia pokazuje się dopiero, gdy którykolwiek portal jest włączony, a worker
kończy się przed pętlą. Pozostałe wartości enuma ``portal`` (LinkedIn, NFJ,
Bulldogjob) zostały z symulacji i nie mają adaptera.
"""

from __future__ import annotations

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
from app.services.job_portals.jjit import JjitAdapter
from app.services.job_portals.pracuj import PracujAdapter

ADAPTERS: dict[Portal, type[PortalAdapter]] = {
    Portal.pracuj_pl: PracujAdapter,
    Portal.justjoinit: JjitAdapter,
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


def health_state(failed_recently: int) -> str:
    """``checks.job_portals`` — informacyjne, nigdy nie zmienia ``status``.

    ``unconfigured`` = wszystkie portale wyłączone (stan dzisiejszy),
    ``misconfigured`` = włączony bez adresu/klucza, ``degraded`` = nieudane
    publikacje w ostatniej dobie, inaczej ``healthy``.
    """

    configs = portal_configs()
    if not any(c.enabled for c in configs):
        return "unconfigured"
    if any(c.state == "misconfigured" for c in configs):
        return "misconfigured"
    if failed_recently:
        return "degraded"
    return "healthy"
