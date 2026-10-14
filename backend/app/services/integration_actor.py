"""Konto serwisowe jako autor zapisu (API integracyjne v1, 0442).

Do 14.10.2026 zapis wykonany kluczem ``X-API-Key`` nie zostawiał autora:
dziennik zmian zamówień brał go za „system”, a ``Activity`` i Historia zdarzeń
miały puste pole osoby. Automatyzacje mają zapisywać rozliczenia, więc każdy
ich zapis musi mówić, KTÓRA integracja go zrobiła.

Jeden stempel sesji (``stamp_integration``) przy uwierzytelnieniu klucza
obsługuje trzy ujścia bez dotykania miejsc zapisu:

* ``order_change_events`` — ``source='integration'`` + id konta
  (``order_change_audit.stamp_service_account``),
* ``activities`` — ``details["via"] = "integration:<slug>"`` (listener
  ``before_flush`` z ``jarvis.via_tag``, ten sam co dla Jarvisa),
* Historia zdarzeń i odhaczenia Finansów — ``IntegrationActor`` przekazywany
  jawnie tam, gdzie kod oczekuje osoby (czyta tylko ``id/name/email``).

Konto serwisowe świadomie NIE udaje ``User`` (``models/service_account.py``):
``IntegrationActor`` nie ma ról ani uprawnień, więc nie przejdzie przez żadną
bramkę, nawet gdyby ktoś przekazał go tam przez pomyłkę.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Import rejestruje listener ``before_flush`` dopisujący ``details["via"]``.
from app.services.jarvis.via_tag import VIA_INFO_KEY
from app.services.order_change_audit import stamp_service_account
from app.services.service_account_auth import ServicePrincipal

PRINCIPAL_INFO_KEY = "integrations.principal"
VIA_PREFIX = "integration:"


@dataclass(frozen=True)
class IntegrationActor:
    """Autor zapisu dla kodu, który oczekuje osoby (``.id/.name/.email``)."""

    name: str
    service_account_id: Optional[int] = None
    id: None = None
    email: None = None


def stamp_integration(session_info: dict, principal: ServicePrincipal) -> None:
    """Oznacz sesję żądania jako działanie konta serwisowego."""

    stamp_service_account(session_info, principal.account_id)
    session_info[VIA_INFO_KEY] = f"{VIA_PREFIX}{principal.slug}"
    session_info[PRINCIPAL_INFO_KEY] = principal


def actor_for(principal: ServicePrincipal) -> IntegrationActor:
    return IntegrationActor(
        name=principal.display_label, service_account_id=principal.account_id
    )
