"""Central capability guard for legal-document surfaces of the contracts module
(Moduł 5 audit, PR-01).

P0.11 containment (audit ``docs/contracts-engagement-onboarding-billing-
offboarding-module-audit-and-claude-implementation-plan-2026-07-16.md``): the
B2B contract generator and the contract-template render endpoints used bare
``CurrentUser``. That let the read-only viewer/client persona ``user`` — and the
delivery ``recruiter``/``sourcer`` personas — do things they must not:

- ``POST /b2b-contract-generator/generate`` with a passed ``contract_id`` loaded
  **any** Contract (only checking it was type ``b2b``) and then mutated
  ``start_date``, ``rate_candidate``, ``currency`` and **replaced** the whole
  candidate rate schedule → horizontal privilege escalation + rate tampering.
- ``GET .../contracts/{id}/detail`` and ``.../docx`` exposed candidate rate and
  the full legal DOCX (partner PII, terms) of any contract.
- ``GET .../generated`` and ``.../generated/{id}/docx`` exposed partner/client
  PII and let anyone re-render a legal document.
- ``POST /render`` and ``GET /next-number`` allocated a legal contract number to
  any logged-in user.
- ``contract_templates`` ``GET .../render`` rendered any template + Contract.

**Fix:** legal surfaces use the same authoritative decision as
``client_access.can_view_legal_documents``.

Od migracji 0410 są tu dwie ścieżki:

* **Delivery** (umowy ramowe, aneksy, szablony umów, podpisy kontraktów):
  dokumenty mogą nieść stawki, więc odczyt wymaga uprawnienia „Stawki i kwoty:
  podgląd”, a zapis dodatkowo „Kontrakty i zamówienia: tworzenie i edycja”.
  Konto z rolą Delivery Leada działa u klientów z przypisania, pozostali
  posiadacze — u wszystkich.
* **Generator umów B2B** (``purpose="org"``): graf organizacyjny sprzed 0410
  (``ClientAccess.generator_can_*``) — Admin/Head of Recruitment i Finanse
  czytają całą organizację, Delivery Lead każdego klienta, a konsekwentne
  zapisy wymagają u niego jawnego przypisania; TAC zostaje przy swoim grafie.
  Dostęp do generatora się nie zmienił.

Owner/admin checks that already gate mutating ``generated`` rows
(PATCH/DELETE) stay in place as a second layer; this guard only ensures the
caller is legal-team at all.

Global catalogs (role names, templates, numbering helpers) require a non-empty
client graph for DL/TAC. Entity routes additionally resolve the exact client
before reading, rendering, mutating, or downloading a document. Rows without
an authoritative ``client_id`` are visible only to Admin/HoR.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.contract import Contract
from app.models.user import User, UserRole
from app.services.action_permissions import (
    ActionAccess,
    ProductAction,
    action_access_for_user,
)
from app.services.access_scope import is_delivery_lead_governed
from app.services.client_access import (
    ADMIN_LIKE_ROLES,
    ClientScopePurpose,
    deny,
    resolve_client_access,
    resolve_client_team_client_ids,
)
from app.services.permission_denial import ensure_permission

# Legal-team personas trusted with contract legal documents. Mirrors
# ``client_access.can_view_legal_documents`` (admin_like ∪ client_team).
CONTRACT_LEGAL_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.tac,
)

CONTRACT_LEGAL_READ_ROLES: tuple[UserRole, ...] = (
    *CONTRACT_LEGAL_ROLES,
    UserRole.finance,
)


def user_is_contract_legal_team(user: User) -> bool:
    """Role-only preflight; entity authorization still requires DB scope."""
    return user.has_any_role(*CONTRACT_LEGAL_ROLES)


async def _require_legal_client_graph(current_user: User, db: AsyncSession) -> None:
    """Konto rządzone portfelem DL bez żadnego klienta nie wchodzi do narzędzi."""

    if not is_delivery_lead_governed(current_user):
        return
    if not await resolve_client_team_client_ids(db, current_user):
        raise deny("dostęp prawny wymaga jawnego przypisania klienta")


async def require_contract_legal_access(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Gate global legal tools that can mutate; an empty client graph fails closed."""

    ensure_permission(current_user, ProductAction.contracts_orders_edit)
    ensure_permission(current_user, ProductAction.amounts_view)
    await _require_legal_client_graph(current_user, db)
    return current_user


async def require_contract_legal_read_access(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Read-only legal-document gate: dokumenty mogą nieść stawki."""

    ensure_permission(current_user, ProductAction.amounts_view)
    await _require_legal_client_graph(current_user, db)
    return current_user


# Bramka sekcji biegnie przed tymi zależnościami; po tych atrybutach nazywa
# w odmowie uprawnienie, którego konto nie ma (``section_access._named_denial``).
require_contract_legal_access.required_permission_groups = (
    (ProductAction.contracts_orders_edit,),
    (ProductAction.amounts_view,),
)
require_contract_legal_read_access.required_permissions = (ProductAction.amounts_view,)


async def assert_contract_legal_client_access(
    db: AsyncSession,
    user: User,
    client_id: int | None,
    *,
    write: bool = False,
    purpose: ClientScopePurpose = "delivery",
) -> None:
    """Authorize one legal entity against its authoritative client relation.

    ``purpose="org"`` is used by the B2B generator: a Delivery Lead reads every
    client there (decision 25.09.2026) and the decision follows the
    organizational graph (``generator_can_*``). Delivery legal surfaces follow
    the permissions from the settings screen and keep the assigned-client scope.
    """

    if client_id is None:
        if user.has_any_role(*ADMIN_LIKE_ROLES):
            return
        raise deny("dokument prawny bez klienta jest dostępny tylko Admin/HoR")

    access = await resolve_client_access(db, user, client_id, purpose=purpose)
    detail = (
        "edycja dokumentu wymaga jawnego przypisania klienta"
        if write
        else "brak dostępu do dokumentu tego klienta"
    )
    if purpose == "org":
        allowed = (
            access.generator_can_edit_legal
            if write
            else access.generator_can_view_legal
        )
        if not allowed:
            raise deny(detail)
        return

    allowed = (
        access.can_edit_legal_documents if write else access.can_view_legal_documents
    )
    if not allowed:
        raise access.legal_denial(detail, write=write)


async def assert_contract_legal_contract_access(
    db: AsyncSession,
    user: User,
    contract_id: int,
    *,
    write: bool = False,
) -> None:
    """Resolve a contract id to its client before authorizing legal content."""

    client_id = await db.scalar(
        select(Contract.client_id).where(Contract.id == contract_id)
    )
    if client_id is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    await assert_contract_legal_client_access(
        db,
        user,
        client_id,
        write=write,
    )


async def apply_contract_legal_client_scope(
    statement,
    client_column,
    db: AsyncSession,
    user: User,
    *,
    purpose: ClientScopePurpose = "delivery",
):
    """Scope legal list queries before sorting/limiting."""

    client_ids = await resolve_client_team_client_ids(db, user, purpose=purpose)
    if client_ids is None:
        return statement
    return statement.where(client_column.in_(sorted(client_ids) or [-1]))


# Organizacyjny odczyt Finansów daje wyłącznie alias GET poniżej — nigdy
# bramka zdolna do mutacji (``require_contract_legal_access``).
#
# GET-only counterpart.  Never use this alias on render/generate/mutation
# commands; entity writes still resolve ``can_edit_legal_documents``.
ContractLegalReadAccess = Annotated[
    User,
    Depends(require_contract_legal_read_access),
]


# Every operational role except Delivery Lead admitted unconditionally to the
# sourcing-side generator. Legacy viewer `user` usunięty 22.09.2026 (decyzja
# Artura; migracja 0210 nie zostawiła żadnego takiego konta), więc jest
# odrzucany jak każda rola bez jawnej decyzji. Wejście do rejestru NIE daje
# wglądu w stawki — te rozstrzyga ``_RateVisibility`` w generatorze. Explicit tuple
# rather than an implicit "everyone else" fallthrough — a bare `return
# current_user` default would silently hand full generator access to any
# *future* UserRole the moment it's added to the enum, with no callsite
# forcing a conscious decision (matches the discipline behind
# ``capabilities.ts``'s `ALL_ROLES` on the frontend). A role added to
# ``UserRole`` and left off this tuple fails closed here until someone
# deliberately widens it.
#
# Public (no leading underscore) because ``b2b_contract_generator``'s
# ``_generator_unscoped`` imports and reuses it directly, rather than keeping
# its own copy — auto-review on #1216 flagged two independently-maintained
# role tuples as a sync hazard: a role added to one but not the other would
# pass this entry gate and then hit a permanently empty list inside the
# generator. One tuple, two call sites, no drift possible.
B2B_GENERATOR_UNCONDITIONAL_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.talent_community_manager,
    UserRole.tac,
    UserRole.finance,
    UserRole.recruiter,
    UserRole.sourcer,
)

B2B_GENERATOR_ACTION = ProductAction.b2b_contract_generator


def assert_b2b_generator_action_access(user: User, required: ActionAccess) -> None:
    """Enforce the configurable action ceiling inside the Sourcing section."""

    granted = action_access_for_user(user, B2B_GENERATOR_ACTION)
    if granted < required:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "action_access_denied",
                "action": B2B_GENERATOR_ACTION.value,
                "required": required.name,
                "granted": granted.name,
            },
        )


async def require_b2b_generator_access(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Gate for the B2B contract generator specifically.

    The coarse Sourcing section remains the outer ceiling. Inside it, the
    database-backed action policy controls whether the sidebar and this gate
    expose the generator at all.

    Delivery Lead receives the concrete graph of all current clients; an empty
    graph is still denied and clientless entities stay fail-closed. The
    configurable action policy independently selects view, generation or
    management. Rate-bearing generation and management additionally require
    ownership assignment in ``b2b_contract_generator``.
    """

    assert_b2b_generator_action_access(current_user, ActionAccess.view)
    if current_user.has_any_role(*B2B_GENERATOR_UNCONDITIONAL_ROLES):
        return current_user
    if current_user.has_role(UserRole.delivery_lead):
        client_ids = await resolve_client_team_client_ids(
            db, current_user, purpose="org"
        )
        if client_ids:
            return current_user
        raise deny("Generator wymaga co najmniej jednego klienta w organizacji")
    raise deny(
        "Generator umów B2B: nieznana rola bez jawnej decyzji dostępu "
        "(require_b2b_generator_access)"
    )


# Entry gate for the B2B generator surfaces. Every role in
# ``B2B_GENERATOR_UNCONDITIONAL_ROLES`` passes unconditionally; Delivery Lead
# still needs a non-empty client graph; anything else (a future role not yet
# triaged here) fails closed. Client-level scoping of individual entities/lists
# is intentionally disabled for the unconditional roles inside
# ``b2b_contract_generator`` (full-access tool, see ``_generator_unscoped``)
# — otherwise roles with no client-assignment graph at all
# (recruiter/sourcer/finance) would pass this gate and then hit a
# permanently empty list.
B2BGeneratorAccess = Annotated[User, Depends(require_b2b_generator_access)]
