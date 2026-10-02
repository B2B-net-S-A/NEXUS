"""Shared guards and redaction for legacy financial API surfaces."""

from __future__ import annotations

from typing import Annotated, Any, Protocol

from fastapi import Depends, HTTPException, status

from app.analytics.capabilities import (
    AnalyticsCapability,
    require_capability,
    user_has_capability,
)
from app.models.user import User
from app.services import permission_catalog as catalog
from app.services.access_scope import (
    DL_CLIENT_OUT_OF_SCOPE_DETAIL,
    is_delivery_lead_governed,
)
from app.services.action_permissions import ProductAction, has_permission
from app.services.candidate_audit import CLIENT_RATE_CHANGED
from app.services.permission_denial import permission_denied


class _RoleAwareUser(Protocol):
    def get_all_roles(self) -> list[Any]: ...


# Activity actions whose ``details`` carry raw candidate pricing (rate) amounts.
# Mirrors the candidate timeline's ``_HIDDEN_TIMELINE_ACTIONS``: these audit rows
# are finance-only, so non-finance readers never see them in an activity feed.
# The audit payload keys (``old_client_rate`` / ``new_client_rate``) are NOT
# covered by ``_is_financial_key``, so the whole row is dropped rather than
# key-redacted — matching how the timeline omits the action entirely.
_RATE_AUDIT_ACTIONS = frozenset({CLIENT_RATE_CHANGED})


def has_financial_access(user: _RoleAwareUser) -> bool:
    """Return whether the effective policy grants financial read access."""

    return user_has_capability(user, AnalyticsCapability.VIEW_FINANCE)


def can_read_client_finance(
    user: User,
    *,
    client_id: int,
    delivery_lead_finance_client_ids: frozenset[int] | None,
) -> bool:
    """Czy odbiorca widzi kwoty JEDNEGO klienta: stawki, marżę, przychód, MRR.

    Dwie drogi:

    * ``VIEW_FINANCE`` (uprawnienie „Moduł Finanse”) — kwoty każdego klienta,
    * uprawnienie „Stawki i kwoty: podgląd” — u klientów z zakresu konta.
      Konto z rolą Delivery Leada widzi kwoty **wyłącznie u klientów
      z przypisania**, pozostali posiadacze — u wszystkich.

    **Capability ZOSTAJE nienadana globalnie.** ``VIEW_FINANCE`` steruje 40+
    powierzchniami (eksport kontraktów, ``/settings/clients-overview``,
    dashboardy zarządcze); podgląd kwot klienta jest od niej węższy.

    ``delivery_lead_finance_client_ids`` to wynik
    ``resolve_delivery_lead_finance_client_ids``: konkretny zbiór dla konta
    rządzonego portfelem DL, ``None`` dla pozostałych. Zbiór wiąże także
    konta wielorolowe — uprawnienie DL nie rozszerza się przez równoległą
    rolę HoR/TCM na całą organizację. ``None`` u konta rządzonego portfelem
    DL oznacza błąd wołającego i kończy się odmową.

    Konsumenci: profil klienta (``api/clients.py``), portal DL
    (``api/my_clients.py``), kontrakty, zamówienia i roster kontraktorów.
    Reguła mieszka tutaj, bo rozjazd lokalnych kopii kończy się ekranami,
    które pokazują inne uprawnienia do tych samych kwot tego samego klienta.
    """

    if has_financial_access(user):
        return True
    if not has_permission(user, ProductAction.amounts_view):
        return False
    if delivery_lead_finance_client_ids is None:
        return not is_delivery_lead_governed(user)
    return client_id in delivery_lead_finance_client_ids


def require_financial_access(user: _RoleAwareUser) -> None:
    """Fail closed before a legacy endpoint can query or serialize rates."""

    if not has_financial_access(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Financial contract data requires view_finance capability",
        )


FinanceReadUser = Annotated[
    User,
    Depends(require_capability(AnalyticsCapability.VIEW_FINANCE)),
]
FinanceManageUser = Annotated[
    User,
    Depends(require_capability(AnalyticsCapability.MANAGE_FINANCE)),
]
FinanceApproveUser = Annotated[
    User,
    Depends(require_capability(AnalyticsCapability.APPROVE_FINANCE)),
]


# ── Zapis kwot kontraktów i zamówień ────────────────────────────────────────
#
# Kwoty kontraktu zmienia uprawnienie „Stawki i kwoty: zmiana” (domyślnie
# Finanse; decyzja Artura 22.09.2026). Kwoty zamówienia i linii MD zmienia
# dodatkowo osoba, która prowadzi zamówienia i widzi kwoty klienta — tak jak
# od początku przypisany Delivery Lead. Trasy mieszane (kontrakt, zamówienie,
# linia MD) wpuszczają osobę z samą zmianą kwot wyłącznie po to, żeby zmieniła
# KWOTY — reszta pól wymaga prawa edycji rekordu.


def can_manage_finance_amounts(
    user: User,
    *,
    client_id: int | None = None,
    delivery_lead_finance_client_ids: frozenset[int] | None = None,
) -> bool:
    """Zmiana kwot kontraktu i zamówienia: „Stawki i kwoty: zmiana”.

    Konto rządzone portfelem Delivery Leada zmienia kwoty wyłącznie u klientów
    z przypisania, więc wołający podaje klienta i granicę
    (``resolve_delivery_lead_finance_client_ids``); bez nich takie konto
    dostaje odmowę. Pozostałych posiadaczy granica nie dotyczy.
    """

    if not has_permission(user, ProductAction.amounts_edit):
        return False
    if not is_delivery_lead_governed(user):
        return True
    return (
        client_id is not None
        and delivery_lead_finance_client_ids is not None
        and client_id in delivery_lead_finance_client_ids
    )


def can_write_order_amounts(
    user: User,
    *,
    client_id: int,
    delivery_lead_finance_client_ids: frozenset[int] | None,
) -> bool:
    """Kwoty zamówienia i linii MD.

    „Stawki i kwoty: zmiana” albo — jak dotąd przypisany Delivery Lead —
    prowadzenie zamówień razem z podglądem kwot tego klienta.
    """

    if can_manage_finance_amounts(
        user,
        client_id=client_id,
        delivery_lead_finance_client_ids=delivery_lead_finance_client_ids,
    ):
        return True
    return has_permission(
        user, ProductAction.contracts_orders_edit
    ) and can_read_client_finance(
        user,
        client_id=client_id,
        delivery_lead_finance_client_ids=delivery_lead_finance_client_ids,
    )


def order_amounts_denied(user: User) -> HTTPException:
    """Odmowa zapisu kwot zamówienia, która nazywa to, czego brakuje.

    Kto prowadzi zamówienia, ale nie widzi kwot, potrzebuje podglądu kwot;
    kto ma komplet uprawnień, a mimo to trafił tutaj, jest poza swoim
    portfelem; pozostałym brakuje zmiany kwot.
    """

    edits_orders = has_permission(user, ProductAction.contracts_orders_edit)
    if edits_orders and not has_permission(user, ProductAction.amounts_view):
        return permission_denied(ProductAction.amounts_view)
    if edits_orders or has_permission(user, ProductAction.amounts_edit):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DL_CLIENT_OUT_OF_SCOPE_DETAIL,
        )
    return permission_denied(ProductAction.amounts_edit)


def assert_amounts_only(
    supplied_fields,
    amount_fields,
    *,
    can_edit_record: bool,
) -> None:
    """Osoba bez prawa edycji rekordu (ma samą zmianę kwot) zmienia tylko kwoty."""

    if can_edit_record:
        return
    extra = sorted(set(supplied_fields) - set(amount_fields))
    if extra:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "finance_amounts_only",
                "message": (
                    f"Uprawnienie „{catalog.label('amounts_edit')}” pozwala tu "
                    "zmienić wyłącznie kwoty. Do pozostałych pól potrzebujesz "
                    f"„{catalog.label('contracts_orders_edit')}”."
                ),
                "fields": extra,
            },
        )


def _is_financial_key(key: str) -> bool:
    normalized = key.lower()
    return (
        normalized == "rate"
        or normalized == "amount"
        or "rate_candidate" in normalized
        or "rate_client" in normalized
        or normalized.startswith(("rate_", "client_rate", "expected_rate"))
        or normalized.startswith(("salary", "budget"))
        or "rate_schedule" in normalized
        or "margin" in normalized
        or normalized
        in {
            "billing_hours_per_month",
            "currency",
            "framework_rate",
            "target_rate_min",
            "target_rate_max",
            "total_value",
            "pnl",
            "p&l",
            "profit",
            "revenue",
            "cost",
        }
    )


def redact_financial_fields(value: Any) -> Any:
    """Recursively remove known financial keys from flexible audit payloads."""

    if isinstance(value, dict):
        return {
            key: redact_financial_fields(item)
            for key, item in value.items()
            if not _is_financial_key(str(key))
        }
    if isinstance(value, list):
        return [redact_financial_fields(item) for item in value]
    return value


def redact_feed_activity(action: str, details: Any, *, finance_ok: bool) -> Any | None:
    """Return safe ``details`` for one activity-feed row, or ``None`` to drop it.

    Activity feeds (``/api/activities/feed``, ``/api/dashboard/recent-activity``,
    ``/api/contracts/{id}/activities``) serialize raw ``Activity.details``, which
    can carry rate amounts. This applies the same finance protection the candidate
    timeline already uses:

    - finance roles (``has_financial_access``) see everything unchanged;
    - for non-finance readers, rate-change audit rows are omitted entirely
      (mirrors ``_HIDDEN_TIMELINE_ACTIONS``), because their payload keys are not
      redactable field-by-field;
    - any residual finance keys on other rows (e.g. a contract ``updated`` event
      carrying ``rate_candidate`` / ``margin``) are stripped via
      :func:`redact_financial_fields`.
    """

    if finance_ok:
        return details
    if action in _RATE_AUDIT_ACTIONS:
        return None
    return redact_financial_fields(details or {})
