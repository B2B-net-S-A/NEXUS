"""Shared guards and redaction for legacy financial API surfaces."""

from __future__ import annotations

from typing import Annotated, Any, Protocol

from fastapi import Depends, HTTPException, status

from app.analytics.capabilities import (
    AnalyticsCapability,
    require_capability,
    user_has_capability,
)
from app.models.user import User, UserRole
from app.services.candidate_audit import CLIENT_RATE_CHANGED


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

    Role z ``VIEW_FINANCE`` — zawsze. Delivery Lead — **wyłącznie u klienta ze
    swojego portfela**, mimo że tej capability nie ma. To delivery odpowiada za
    obsadę i marżę swoich klientów, a bez tego wyjątku rola, dla której te
    ekrany powstały, widziała w kolumnach finansowych same „—".

    **Capability ZOSTAJE nienadana globalnie.** ``VIEW_FINANCE`` steruje 40+
    powierzchniami (eksport kontraktów, ``/settings/clients-overview``,
    dashboardy zarządcze), więc dopisanie jej roli ``delivery_lead``
    w ``ROLE_CAPABILITIES`` otworzyłoby je wszystkie naraz. Ten sam kompromis
    co ``_can_see_finance`` w module zamówień: wąska powierzchnia zamiast
    szerokiej capability.

    Zakres jest wąski i trzeba go pilnować:

    * ``client_id`` musi leżeć w finansowej granicy portfela wyznaczonej przez
      ``resolve_delivery_lead_finance_client_ids``. Jest ona niezależna od
      organizacyjnego dostępu operacyjnego DL do wszystkich klientów,
    * ``None`` jako granica znaczy „ten odbiorca NIE jest rządzony personą DL"
      (admin, Finance albo rola nie-DL) i finansów stąd nie dostaje. Każda
      multi-rola zawierająca ``delivery_lead`` dostaje z resolvera konkretny
      zbiór klientów, więc uprawnienie DL nie rozszerza się przez równoległą
      rolę HoR/TCM na całą organizację,
    * ``tac`` zostaje przy redakcji: jest w zespole klienta i widzi
      konsultantów, ale obsady nie prowadzi, więc stawki go nie dotyczą.

    Konsumenci: profil klienta (``api/clients.py``), portal DL
    (``api/my_clients.py``), kontrakty i roster kontraktorów. Reguła mieszka
    tutaj, bo rozjazd lokalnych kopii kończy się ekranami, które pokazują inne
    uprawnienia do tych samych kwot tego samego klienta.
    """

    if has_financial_access(user):
        return True
    if delivery_lead_finance_client_ids is None:
        return False
    # Test roli jest redundantny wobec kontraktu
    # ``resolve_delivery_lead_finance_client_ids`` (konkretny zbiór = persona DL) —
    # i ma taki zostać. Gdyby ta funkcja zaczęła kiedyś zwracać zbiór dla innej
    # persony, sam warunek na granicy po cichu rozdałby jej kwoty.
    return (
        user.has_role(UserRole.delivery_lead)
        and client_id in delivery_lead_finance_client_ids
    )


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


# ── Zapis kwot kontraktów i zamówień (decyzja Artura 22.09.2026) ────────────
#
# Finanse zmieniają kwoty kontraktów i zamówień przez ``MANAGE_FINANCE``
# (rola ``finance`` z zapisem w sekcji Finanse). Do 22.09 te pola zapisywał
# wyłącznie admin (plus przypisany DL na zamówieniach), mimo że capability
# istniała. Trasy mieszane (kontrakt, zamówienie, linia MD) wpuszczają osobę
# z samym ``MANAGE_FINANCE`` wyłącznie po to, żeby zmieniła KWOTY — reszta
# pól zostaje przy rolach operacyjnych danej trasy.


def can_manage_finance_amounts(user: User) -> bool:
    """Zapis kwot kontraktu i zamówienia: admin albo ``MANAGE_FINANCE``."""

    return user.has_role(UserRole.admin) or user_has_capability(
        user, AnalyticsCapability.MANAGE_FINANCE
    )


def require_roles_or_finance_manager(*roles: UserRole):
    """Bramka trasy mieszanej: role operacyjne trasy albo ``MANAGE_FINANCE``.

    Samo ``MANAGE_FINANCE`` daje wyłącznie zapis kwot — handler MUSI wołać
    ``assert_finance_manager_touches_only_amounts``.
    """

    from app.api.deps import ROLE_DENIED_DETAIL, require_onboarded_user

    async def _check(current_user: User = Depends(require_onboarded_user)) -> User:
        if (
            current_user.has_role(UserRole.admin)
            or current_user.has_any_role(*roles)
            or user_has_capability(current_user, AnalyticsCapability.MANAGE_FINANCE)
        ):
            return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=ROLE_DENIED_DETAIL
        )

    return _check


def assert_finance_manager_touches_only_amounts(
    user: User,
    supplied_fields,
    amount_fields,
    *,
    operational_roles: tuple[UserRole, ...],
) -> None:
    """Osoba wpuszczona wyłącznie przez ``MANAGE_FINANCE`` zmienia tylko kwoty."""

    if user.has_role(UserRole.admin) or user.has_any_role(*operational_roles):
        return
    extra = sorted(set(supplied_fields) - set(amount_fields))
    if extra:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "finance_amounts_only",
                "message": "Finanse zmieniają tutaj wyłącznie kwoty.",
                "fields": extra,
            },
        )


ExecutiveUser = Annotated[
    User,
    Depends(require_capability(AnalyticsCapability.VIEW_EXECUTIVE)),
]


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
