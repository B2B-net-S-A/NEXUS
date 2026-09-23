"""Wspólny interfejs adapterów portali ogłoszeniowych (0360).

Adapter zna WYŁĄCZNIE protokół portalu. Co publikujemy (treść z
zatwierdzonego opisu publicznego, link aplikacyjny), kiedy (kolejka) i kto
może (bramki) — rozstrzyga ``service`` i router. Dzięki temu dołożenie
prawdziwej integracji po otrzymaniu dokumentacji API to zmiana jednego pliku.

Konfiguracja wzorem ``TraffitConfig.from_env``: jawna klasa z env-ów,
bez sekretów w odpowiedziach API (``state`` mówi tylko, czy jest komplet).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, Optional

from app.core.config import settings
from app.models.job_posting import Portal

ConfigState = Literal["disabled", "misconfigured", "ready"]


class PortalError(Exception):
    """Odmowa portalu z komunikatem po polsku (trafia do ``last_error``)."""

    retryable: ClassVar[bool] = True

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class PortalNotConfigured(PortalError):
    """Portal wyłączony flagą albo bez adresu/klucza — ponawianie nic nie da."""

    retryable = False


class PortalNotImplemented(PortalError):
    """Integracja czeka na dokumentację API portalu."""

    retryable = False


@dataclass(frozen=True)
class PortalConfig:
    portal: Portal
    enabled: bool
    api_url: str
    api_key: str

    @property
    def state(self) -> ConfigState:
        if not self.enabled:
            return "disabled"
        if not (self.api_url.strip() and self.api_key.strip()):
            return "misconfigured"
        return "ready"

    @classmethod
    def from_settings(cls, portal: Portal) -> "PortalConfig":
        prefix = {
            Portal.pracuj_pl: "PORTAL_PRACUJ",
            Portal.justjoinit: "PORTAL_JJIT",
        }[portal]
        return cls(
            portal=portal,
            enabled=bool(getattr(settings, f"{prefix}_ENABLED", False)),
            api_url=str(getattr(settings, f"{prefix}_API_URL", "") or ""),
            api_key=str(getattr(settings, f"{prefix}_API_KEY", "") or ""),
        )


@dataclass(frozen=True)
class PostingContent:
    """Treść ogłoszenia — biała lista z opisu publicznego + link aplikacyjny."""

    title: str
    job: dict[str, Any]
    apply_url: str


@dataclass
class PortalResult:
    external_id: Optional[str] = None
    url: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)


class PortalAdapter(ABC):
    portal: ClassVar[Portal]
    label: ClassVar[str]

    def __init__(self, config: Optional[PortalConfig] = None) -> None:
        self.config = config or PortalConfig.from_settings(self.portal)

    def ensure_ready(self) -> None:
        state = self.config.state
        if state == "disabled":
            raise PortalNotConfigured(f"Portal {self.label} nie jest włączony.")
        if state == "misconfigured":
            raise PortalNotConfigured(
                f"Portal {self.label} jest włączony, ale brakuje adresu API albo klucza."
            )

    @abstractmethod
    async def publish(self, content: PostingContent) -> PortalResult: ...

    @abstractmethod
    async def update(
        self, external_id: str, content: PostingContent
    ) -> PortalResult: ...

    @abstractmethod
    async def unpublish(self, external_id: str) -> None: ...

    @abstractmethod
    async def status(self, external_id: str) -> dict[str, Any]: ...


class PendingDocumentationAdapter(PortalAdapter):
    """Adapter bez dokumentacji API: każda operacja mówi to wprost.

    Nie udaje publikacji (dawne ``SIM-…`` z losowymi wyświetleniami
    kłamało w raportach) — wiersz kończy jako ``failed`` z jasnym powodem.
    """

    def _pending(self) -> PortalNotImplemented:
        self.ensure_ready()
        return PortalNotImplemented(
            f"Integracja z {self.label} czeka na dokumentację API portalu — "
            "ogłoszenie nie zostało wysłane."
        )

    async def publish(self, content: PostingContent) -> PortalResult:
        raise self._pending()

    async def update(self, external_id: str, content: PostingContent) -> PortalResult:
        raise self._pending()

    async def unpublish(self, external_id: str) -> None:
        raise self._pending()

    async def status(self, external_id: str) -> dict[str, Any]:
        raise self._pending()
