"""Uwierzytelnienie wtyczki LinkedIn (nagłówek ``X-Extension-Key``).

Osobna zależność, a nie gałąź w ``get_authenticated_user``: JWT działa na
każdej trasie, a klucz wtyczki ma działać WYŁĄCZNIE na ``/api/extension/*``.
Żadna inna trasa nie czyta tego nagłówka, więc zakres wynika z budowy, nie
z listy wyjątków do pilnowania. Za kluczem stoi prawdziwe konto — te same
granice co ``get_current_user`` (onboarding, praktykant, uprawnienia z bazy)
i ta sama lista ról co ``RecruiterPlus``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    ROLE_DENIED_DETAIL,
    ensure_not_trainee,
    ensure_onboarding_complete,
)
from app.core.config import settings
from app.core.database import get_db
from app.models.linkedin_extension import LinkedinExtensionConnection
from app.models.user import User, UserRole
from app.services.effective_access import resolve_effective_access
from app.services.linkedin_extension_auth import (
    EXTENSION_KEY_HEADER,
    ExtensionKeyError,
    authenticate_extension_key,
    stamp_last_used,
)
from app.services.order_change_audit import stamp_actor
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)

logger = logging.getLogger(__name__)

#: Kod odpowiedzi 401 — wtyczka pokazuje wtedy ekran „Połącz z NEXUSEM”.
EXTENSION_KEY_INVALID = "extension_key_invalid"

#: Role, które pracują z kandydatami — ten sam zbiór co ``RecruiterPlus``.
EXTENSION_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.talent_community_manager,
    UserRole.recruiter,
    UserRole.finance,
)


@dataclass
class ExtensionPrincipal:
    user: User
    connection: LinkedinExtensionConnection


async def get_extension_principal(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ExtensionPrincipal:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=EXTENSION_KEY_INVALID,
    )
    if not settings.LINKEDIN_EXTENSION_ENABLED:
        raise unauthorized
    raw = request.headers.get(EXTENSION_KEY_HEADER)
    if not raw:
        raise unauthorized
    try:
        connection = await authenticate_extension_key(db, raw)
    except ExtensionKeyError as exc:
        logger.info("linkedin_extension.key_rejected reason=%s", exc.reason)
        raise unauthorized from exc

    user = connection.user
    stamp_actor(db.info, user.id)
    ensure_onboarding_complete(user)
    ensure_not_trainee(user)
    await resolve_effective_access(db, [user])
    if not user.has_role(UserRole.admin) and not user.has_any_role(*EXTENSION_ROLES):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ROLE_DENIED_DETAIL)
    stamp_last_used(connection)
    request.state.extension_key_id = connection.key_id
    return ExtensionPrincipal(user=user, connection=connection)


def _require_sourcing(principal: ExtensionPrincipal, required: SectionAccess) -> ExtensionPrincipal:
    """Sufit sekcji Sourcing — ten sam, który stoi przed ``/api/candidates``.
    Zależność ``require_section_access`` czyta JWT, więc tu liczymy go sami."""
    if section_access_for_user(principal.user, ProductSection.sourcing) < required:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Twoje konto nie ma dostępu do kandydatów w NEXUSIE"
                + (" do zapisu." if required is SectionAccess.write else ".")
                + " Poproś administratora o dostęp."
            ),
        )
    return principal


async def get_extension_reader(
    principal: ExtensionPrincipal = Depends(get_extension_principal),
) -> ExtensionPrincipal:
    return _require_sourcing(principal, SectionAccess.read)


async def get_extension_writer(
    principal: ExtensionPrincipal = Depends(get_extension_principal),
) -> ExtensionPrincipal:
    return _require_sourcing(principal, SectionAccess.write)


ExtensionAuth = Annotated[ExtensionPrincipal, Depends(get_extension_principal)]
ExtensionReader = Annotated[ExtensionPrincipal, Depends(get_extension_reader)]
ExtensionWriter = Annotated[ExtensionPrincipal, Depends(get_extension_writer)]
