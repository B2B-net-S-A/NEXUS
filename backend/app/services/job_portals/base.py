"""Wspólny interfejs adapterów portali ogłoszeniowych (0360, 0381).

Adapter zna WYŁĄCZNIE protokół portalu. Co publikujemy (treść z
zatwierdzonego opisu publicznego, link aplikacyjny, ustawienia ogłoszenia),
kiedy (kolejka) i kto może (bramki) — rozstrzyga ``service`` i router.

Konfiguracja wzorem ``TraffitConfig.from_env``: jawna klasa z env-ów, bez
sekretów w odpowiedziach API (``state`` mówi tylko, czy jest komplet).
JustJoin.IT i RocketJobs dodatkowo wymagają połączonego konta firmy —
to sprawdza asynchronicznie ``job_portals.resolve_state``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, Optional

from app.core.config import settings
from app.models.job_posting import Portal

ConfigState = Literal["disabled", "misconfigured", "not_connected", "ready"]

# Portale obsługiwane przez Employer Public API (1EP) jednego dostawcy.
JJIT_FAMILY: tuple[Portal, ...] = (Portal.justjoinit, Portal.rocketjobs)


class PortalError(Exception):
    """Odmowa portalu z komunikatem po polsku (trafia do ``last_error``)."""

    retryable: ClassVar[bool] = True

    def __init__(
        self,
        message: str,
        *,
        retryable: Optional[bool] = None,
        status: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        # Status HTTP odpowiedzi portalu (gdy błąd przyszedł z API).
        self.status = status
        if retryable is not None:
            self.retryable = retryable  # type: ignore[misc]


class PortalNotConfigured(PortalError):
    """Portal wyłączony flagą albo bez konfiguracji — ponawianie nic nie da."""

    retryable = False


class PortalNotImplemented(PortalError):
    """Integracja czeka na dokumentację API portalu."""

    retryable = False


class PortalReconnectRequired(PortalError):
    """Token konta portalu wygasł albo został cofnięty — trzeba połączyć ponownie.

    Worker nie zużywa na nim prób: wiersz czeka, aż admin połączy konto.
    """

    retryable = False


class PortalGone(PortalError):
    """Ogłoszenia nie ma na portalu (404 — usunięte poza API)."""

    retryable = False


@dataclass(frozen=True)
class PortalConfig:
    portal: Portal
    enabled: bool
    # Nazwy brakujących ustawień (bez wartości) — `misconfigured`, gdy niepuste.
    missing: tuple[str, ...] = ()
    needs_connection: bool = False

    @property
    def state(self) -> ConfigState:
        """Stan z samych env-ów; połączenie konta dokłada ``resolve_state``."""
        if not self.enabled:
            return "disabled"
        if self.missing:
            return "misconfigured"
        return "ready"

    @classmethod
    def from_settings(cls, portal: Portal) -> "PortalConfig":
        if portal == Portal.pracuj_pl:
            return cls(
                portal=portal,
                enabled=bool(settings.PORTAL_PRACUJ_ENABLED),
                missing=_blank(
                    PORTAL_PRACUJ_API_URL=settings.PORTAL_PRACUJ_API_URL,
                    PORTAL_PRACUJ_API_KEY=settings.PORTAL_PRACUJ_API_KEY,
                ),
            )
        if portal in JJIT_FAMILY:
            flag = (
                settings.PORTAL_JJIT_ENABLED
                if portal == Portal.justjoinit
                else settings.PORTAL_ROCKETJOBS_ENABLED
            )
            return cls(
                portal=portal,
                enabled=bool(flag),
                missing=_blank(
                    PORTAL_JJIT_API_URL=settings.PORTAL_JJIT_API_URL,
                    JJIT_OAUTH_CLIENT_ID=settings.JJIT_OAUTH_CLIENT_ID,
                    JJIT_OAUTH_CLIENT_SECRET=settings.JJIT_OAUTH_CLIENT_SECRET,
                    JJIT_OAUTH_REDIRECT_URI=settings.JJIT_OAUTH_REDIRECT_URI,
                ),
                needs_connection=True,
            )
        return cls(portal=portal, enabled=False)


def _blank(**values: Any) -> tuple[str, ...]:
    return tuple(name for name, value in values.items() if not str(value or "").strip())


@dataclass(frozen=True)
class PostingContent:
    """Treść ogłoszenia — biała lista z opisu publicznego + link aplikacyjny.

    ``options`` (ustawienia ogłoszenia wpisane przez DL) i ``external_ref``
    (nasz identyfikator publikacji wysyłany jako ``externalId``) dokłada
    worker tuż przed wywołaniem adaptera.
    """

    title: str
    job: dict[str, Any]
    apply_url: str
    options: dict[str, Any] = field(default_factory=dict)
    external_ref: Optional[str] = None


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
                f"Portal {self.label} jest włączony, ale brakuje konfiguracji "
                f"({', '.join(self.config.missing)})."
            )

    def validate_options(self, content: PostingContent) -> list[str]:
        """Braki w ustawieniach ogłoszenia (po polsku) — sprawdzane przed kolejką."""
        return []

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
