"""Polityka zapisu zamówień i kontraktów — „kto” i „czy wolno” (PR 2B, migracja 0443).

Te same zapisy (zakończenie, przedłużenie i anulowanie zamówienia MD,
zakończenie i edycja zamówienia okresowego, PDF zamówienia, data końca
i status kontraktu) robią dwaj autorzy: osoba z ekranu (``User``) i konto
serwisowe z API integracyjnego v1. Ciało zapisu jest jedno — funkcje
``apply_*`` obok tras w ``client_order_groups``, ``client_orders``
i ``contracts`` — a pytania o uprawnienia i autora idą przez ``WritePolicy``:

* ``UserWritePolicy`` woła DOKŁADNIE te bramki, które handler ekranu wołał
  przed wydzieleniem ciała, z tymi samymi argumentami; pomocników modułu trasy
  szuka przez atrybut modułu (podmiana w testach działa jak dotąd). Zachowanie
  ekranu się nie zmienia: kody, komunikaty, zakres Delivery Leada.
* ``IntegrationWritePolicy`` decyduje ze scope'ów klucza: działa w całej
  firmie (konto serwisowe nie ma portfela Delivery Leada), kwoty wyłącznie
  z ``amounts:write``, odmowa w kształcie ``insufficient_scope``.

Konto serwisowe NIGDY nie udaje ``User``: bramki czytające użytkownika
(``has_permission`` i pochodne) dla obiektu bez zapisanych uprawnień wracają
do domyślnych uprawnień roli — podstawiony obiekt przechodziłby tam, gdzie
powinien odpaść. Autor zapisu konta to ``IntegrationActor`` (bez ról).

Moduł importuje moduły tras leniwie (w ciele metod): trasy importują politykę
na poziomie modułu, a ``client_orders`` już sięga po ``contracts`` — import
na górze domykałby cykl. Ta sama konwencja co ``b2b_documents.effects``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable, Optional, Protocol

from fastapi import HTTPException, status

from app.models.service_account import ServiceScope
from app.services.action_permissions import ProductAction, has_permission
from app.services.integration_actor import IntegrationActor, actor_for

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.api.client_orders import _OrderAmounts
    from app.models.contract import Contract
    from app.models.user import User
    from app.schemas.contract import ContractUpdate
    from app.services.service_account_auth import ServicePrincipal


class WritePolicy(Protocol):
    """Pytania zapisu, które ciało ``apply_*`` zadaje autorowi."""

    @property
    def actor_id(self) -> Optional[int]:
        """``users.id`` autora — ``None`` dla konta serwisowego."""

    @property
    def actor(self) -> Any:
        """Autor dla kodu czytającego ``.id`` (np. ``_build_line``)."""

    def event_actor(self) -> dict[str, str]:
        """Dopisek do ładunku zdarzenia zamówienia: kto, gdy nie ma ``user_id``."""

    def can_edit_orders(self) -> bool:
        """Edycja zamówienia poza kwotami (``assert_amounts_only``)."""

    def can_edit_contracts(self) -> bool:
        """Edycja kontraktu poza kwotami (``assert_amounts_only``)."""

    async def require_order_lifecycle(
        self, client_id: int, *, for_write: bool = False
    ) -> None:
        """Klient istnieje (i nie jest scalony przy ``for_write``) + zakres."""

    async def assert_order_amounts_writable(
        self, client_id: int, supplied_fields: Iterable[str]
    ) -> None:
        """Kwoty zamówienia okresowego (``_ORDER_FINANCE_WRITE_FIELDS``)."""

    async def assert_line_amounts_writable(
        self, client_id: int, supplied_fields: set[str]
    ) -> None:
        """Kwoty grupy i linii MD/kosztowej (``_GROUP_FINANCE_FIELDS``)."""

    async def require_order_file(self, client_id: int) -> None:
        """Podmiana PDF-a zamówienia."""

    async def assert_contract_visible(self, contract: Contract) -> None:
        """Kontrakt w zakresie autora (portfel Delivery Leada)."""

    async def assert_contract_status_writable(self, contract: Contract) -> None:
        """Zmiana statusu kontraktu (trasa ``/status``) — zakres autora."""

    async def assert_contract_amounts_writable(
        self, supplied_fields: Iterable[str], *, client_id: Optional[int]
    ) -> None:
        """Kwoty kontraktu (``_CONTRACT_FINANCE_WRITE_FIELDS``)."""

    def assert_contract_status_change_allowed(
        self, contract: Contract, data: ContractUpdate
    ) -> None:
        """Zmiana statusu bocznymi drogami (data końca, dane zakończenia)."""


class UserWritePolicy:
    """Osoba z ekranu — delegacja do bramek ekranu bez żadnej zmiany."""

    def __init__(self, user: User, db: AsyncSession) -> None:
        self.user = user
        self.db = db
        self._order_amounts: dict[int, _OrderAmounts] = {}

    @property
    def actor_id(self) -> Optional[int]:
        return self.user.id

    @property
    def actor(self) -> Any:
        return self.user

    def event_actor(self) -> dict[str, str]:
        # Autor osoby jest w `created_by_user_id` — ładunek zostaje taki jak był.
        return {}

    def can_edit_orders(self) -> bool:
        return has_permission(self.user, ProductAction.contracts_orders_edit)

    def can_edit_contracts(self) -> bool:
        return has_permission(self.user, ProductAction.contracts_orders_edit)

    async def require_order_lifecycle(
        self, client_id: int, *, for_write: bool = False
    ) -> None:
        from app.api import client_order_groups as routes

        await routes._require_order_lifecycle(
            self.db, self.user, client_id, for_write=for_write
        )

    async def order_amounts(self, client_id: int) -> _OrderAmounts:
        """Kwoty zamówień klienta dla osoby — raz na żądanie, jak w handlerze
        sprzed wydzielenia (ta sama wartość wraca do redakcji odpowiedzi)."""
        from app.api import client_orders as routes

        cached = self._order_amounts.get(client_id)
        if cached is None:
            cached = await routes._order_amounts(self.db, self.user, client_id)
            self._order_amounts[client_id] = cached
        return cached

    async def assert_order_amounts_writable(
        self, client_id: int, supplied_fields: Iterable[str]
    ) -> None:
        from app.api import client_orders as routes

        amounts = await self.order_amounts(client_id)
        routes._assert_order_finance_write_allowed(
            self.user, supplied_fields, can_finance=amounts.can_write
        )

    async def assert_line_amounts_writable(
        self, client_id: int, supplied_fields: set[str]
    ) -> None:
        from app.api import client_order_groups as routes

        await routes._assert_line_finance_write_allowed(
            self.db, self.user, client_id, supplied_fields
        )

    async def require_order_file(self, client_id: int) -> None:
        from app.api import client_orders as routes

        await routes._require_order_file_read(self.db, self.user, client_id)

    async def assert_contract_visible(self, contract: Contract) -> None:
        from app.api import contracts as routes

        await routes._ensure_delivery_lead_contract_visible(
            contract, self.user, self.db
        )

    async def assert_contract_status_writable(self, contract: Contract) -> None:
        # Ekran: uprawnienie „Status kontraktu” sprawdza zależność trasy
        # (`ContractStatusUser`); w ciele zostaje portfel Delivery Leada.
        await self.assert_contract_visible(contract)

    async def assert_contract_amounts_writable(
        self, supplied_fields: Iterable[str], *, client_id: Optional[int]
    ) -> None:
        from app.api import contracts as routes

        await routes._assert_contract_finance_write_allowed(
            self.user, supplied_fields, client_id=client_id, db=self.db
        )

    def assert_contract_status_change_allowed(
        self, contract: Contract, data: ContractUpdate
    ) -> None:
        from app.api import contracts as routes

        routes._assert_contract_status_change_allowed(self.user, contract, data)


def _insufficient_scope(
    scope: ServiceScope, message: str, *, fields: Optional[list[str]] = None
) -> HTTPException:
    detail: dict[str, object] = {
        "error": "insufficient_scope",
        "message": message,
        "required": [scope.value],
        "missing": [scope.value],
    }
    if fields:
        detail["fields"] = fields
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class IntegrationWritePolicy:
    """Konto serwisowe API v1 — decyzje wyłącznie ze scope'ów klucza.

    Zakres: cała firma (konto nie ma portfela Delivery Leada, jak „Kontrakty
    i zamówienia” u osoby bez roli DL). Kwoty — tylko ``amounts:write``
    (lustro „Stawki i kwoty: zmiana”); prowadzenie zamówień samo kwot nie
    otwiera. Każda metoda sprawdza swój scope, nawet gdy trasa zrobiła to
    zależnością — polityka nie zakłada, skąd ją wywołano.
    """

    def __init__(self, principal: ServicePrincipal, db: AsyncSession) -> None:
        self.principal = principal
        self.db = db
        self._actor = actor_for(principal)

    @property
    def actor_id(self) -> Optional[int]:
        return None

    @property
    def actor(self) -> IntegrationActor:
        return self._actor

    def event_actor(self) -> dict[str, str]:
        return {"actor": self.principal.display_label}

    def _has(self, scope: ServiceScope) -> bool:
        return scope.value in self.principal.scopes

    def _require(self, scope: ServiceScope, message: str) -> None:
        if not self._has(scope):
            raise _insufficient_scope(scope, message)

    def can_edit_orders(self) -> bool:
        return self._has(ServiceScope.orders_write)

    def can_edit_contracts(self) -> bool:
        return self._has(ServiceScope.contracts_write)

    async def require_order_lifecycle(
        self, client_id: int, *, for_write: bool = False
    ) -> None:
        from app.api import client_order_groups as routes

        self._require(ServiceScope.orders_write, "Zapis zamówień wymaga orders:write.")
        await routes._assert_client(self.db, client_id, for_write=for_write)

    def _require_amounts(self, forbidden: list[str]) -> None:
        if forbidden and not self._has(ServiceScope.amounts_write):
            raise _insufficient_scope(
                ServiceScope.amounts_write,
                "Zmiana stawek i kwot wymaga scope'u amounts:write.",
                fields=forbidden,
            )

    async def assert_order_amounts_writable(
        self, client_id: int, supplied_fields: Iterable[str]
    ) -> None:
        from app.api import client_orders as routes

        self._require_amounts(
            sorted(set(supplied_fields) & routes._ORDER_FINANCE_WRITE_FIELDS)
        )

    async def assert_line_amounts_writable(
        self, client_id: int, supplied_fields: set[str]
    ) -> None:
        from app.api import client_order_groups as routes

        self._require_amounts(sorted(supplied_fields & routes._GROUP_FINANCE_FIELDS))

    async def require_order_file(self, client_id: int) -> None:
        self._require(
            ServiceScope.orders_write, "PDF zamówienia wymaga scope'u orders:write."
        )

    async def assert_contract_visible(self, contract: Contract) -> None:
        self._require(
            ServiceScope.contracts_write, "Zapis kontraktu wymaga contracts:write."
        )

    async def assert_contract_status_writable(self, contract: Contract) -> None:
        # Osobny scope jak uprawnienie „Status kontraktu” — bez ``contracts:write``
        # (przegląd PR 2B: klucz z samym statusem dostawał 403).
        self._require(
            ServiceScope.contracts_status,
            "Zmiana statusu kontraktu wymaga scope'u contracts:status.",
        )

    async def assert_contract_amounts_writable(
        self, supplied_fields: Iterable[str], *, client_id: Optional[int]
    ) -> None:
        from app.api import contracts as routes

        self._require_amounts(
            sorted(set(supplied_fields) & routes._CONTRACT_FINANCE_WRITE_FIELDS)
        )

    def assert_contract_status_change_allowed(
        self, contract: Contract, data: ContractUpdate
    ) -> None:
        # Lustro uprawnienia „Zakończenie współpracy, zmiana statusu kontraktu”:
        # data końca, która kończy albo przywraca współpracę, wymaga osobnego
        # scope'u ``contracts:status`` — ``contracts:write`` przesuwa termin
        # w przyszłości (ta sama reguła co ekran, ``contract_update_changes_status``).
        from app.api import contracts as contract_routes

        if contract_routes.contract_update_changes_status(contract, data):
            self._require(
                ServiceScope.contracts_status,
                "Data końca, która kończy albo przywraca współpracę, wymaga "
                "scope'u contracts:status.",
            )
