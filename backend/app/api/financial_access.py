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
    delivery_lead_client_ids: frozenset[int] | None,
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

    * ``client_id`` musi leżeć w granicy portfela wyznaczonej przez
      ``resolve_delivery_lead_client_ids``. Trasy i tak odrzucają klienta spoza
      niej, ale finanse nie mogą wisieć na tym, że wcześniejsza linijka nie
      rzuciła wyjątku,
    * ``None`` jako granica znaczy „ten odbiorca NIE jest rządzony personą DL"
      (admin, head_of_recruitment, rola nie-DL) i finansów stąd nie dostaje.
      Dzięki temu multi-rola ``head_of_recruitment + delivery_lead`` nie dostaje
      kwot u WSZYSTKICH klientów — jej nadzór jest nieoskopowany, a repo
      konsekwentnie trzyma HoR poza finansami
      (patrz ``/settings/clients-overview``),
    * ``tac`` zostaje przy redakcji: jest w zespole klienta i widzi
      konsultantów, ale obsady nie prowadzi, więc stawki go nie dotyczą.

    Konsumenci: profil klienta (``api/clients.py``) i portal DL
    (``api/my_clients.py``). Reguła mieszka tutaj, bo rozjazd dwóch kopii
    kończy się ekranem, który sam sobie przeczy: te same kwoty tego samego
    klienta widoczne w jednej zakładce i puste w drugiej.
    """

    if has_financial_access(user):
        return True
    if delivery_lead_client_ids is None:
        return False
    # Test roli jest redundantny wobec kontraktu
    # ``resolve_delivery_lead_client_ids`` (niepusta granica = persona DL) —
    # i ma taki zostać. Gdyby ta funkcja zaczęła kiedyś zwracać zbiór dla innej
    # persony, sam warunek na granicy po cichu rozdałby jej kwoty.
    return (
        user.has_role(UserRole.delivery_lead) and client_id in delivery_lead_client_ids
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
