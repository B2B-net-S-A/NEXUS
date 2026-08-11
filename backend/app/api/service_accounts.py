"""Ustawienia → API: zarządzanie kontami serwisowymi i kluczami (tylko admin).

Rozdział odpowiedzialności między dwoma zasobami wynika wprost z rotacji:

* ``/settings/service-accounts`` — tożsamość i uprawnienia. Zmiana scope'ów
  działa NATYCHMIAST na wszystkie klucze konta, bo uprawnienia są czytane
  z konta przy każdym requeście, a nie zapiekane w poświadczeniu (tym różni się
  ten mechanizm od ``oauth_clients``, gdzie wystawiony JWT niesie scope'y ze
  sobą i żyje własnym życiem przez godzinę po odebraniu uprawnień).
* ``/settings/service-accounts/{id}/keys`` — poświadczenia. Wiele naraz, żeby
  wymiana wyglądała tak: wydaj drugi → wdroż → rewokuj pierwszy.

Wszystko za ``AdminUser``. Świadomie NIE da się zarządzać kontami serwisowymi
kluczem API — inaczej klucz o wąskim scope'ie mógłby wydać sobie klucz szerszy
i cała konstrukcja najmniejszych uprawnień byłaby dekoracją.
"""

# UWAGA: bez `from __future__ import annotations` — PEP 563 zamienia adnotacje
# FastAPI w ForwardRef, a `@limiter.limit` (slowapi #579) rozwiązuje je już
# w SWOICH globalsach, więc `AdminUser` i modele Pydantic przestają być
# rozpoznawane i lądują jako wymagane parametry QUERY (422 na poprawnym body).
# Ten sam trap co w `candidate_activity_summary.py`.

import logging
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import AdminUser
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.service_account import (
    SCOPE_LABELS,
    ServiceAccount,
    ServiceAccountKey,
    ServiceScope,
)
from app.schemas.service_account import (
    ScopeInfo,
    ServiceAccountCreate,
    ServiceAccountKeyCreate,
    ServiceAccountKeyCreateResponse,
    ServiceAccountKeyOut,
    ServiceAccountKeyRevoke,
    ServiceAccountOut,
    ServiceAccountUpdate,
)
from app.services.service_account_auth import default_expires_at, generate_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings/service-accounts", tags=["service-accounts"])


async def _get_account(db: AsyncSession, account_id: int) -> ServiceAccount:
    result = await db.execute(
        select(ServiceAccount)
        .options(selectinload(ServiceAccount.keys))
        .where(ServiceAccount.id == account_id)
    )
    account = result.unique().scalar_one_or_none()
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Konto serwisowe nie istnieje",
        )
    return account


@router.get("/scopes", response_model=List[ScopeInfo])
async def list_scopes(_: AdminUser) -> List[ScopeInfo]:
    """Słownik uprawnień + etykiety PL dla pickera w Ustawieniach."""
    return [
        ScopeInfo(value=scope.value, label=SCOPE_LABELS.get(scope, scope.value))
        for scope in ServiceScope
    ]


@router.get("", response_model=List[ServiceAccountOut])
async def list_accounts(
    _: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> List[ServiceAccount]:
    """Wszystkie konta serwisowe wraz z metadanymi kluczy (bez sekretów)."""
    result = await db.execute(
        select(ServiceAccount)
        .options(selectinload(ServiceAccount.keys))
        .order_by(ServiceAccount.created_at.desc())
    )
    return list(result.unique().scalars().all())


@router.post("", response_model=ServiceAccountOut, status_code=status.HTTP_201_CREATED)
async def create_account(
    payload: ServiceAccountCreate,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> ServiceAccount:
    """Załóż konto serwisowe. Klucz wydaje się osobno (POST .../keys)."""
    account = ServiceAccount(
        slug=payload.slug,
        name=payload.name,
        description=payload.description,
        scopes=[scope.value for scope in payload.scopes],
        is_active=True,
        created_by=admin.id,
    )
    db.add(account)
    try:
        await db.commit()
    except IntegrityError as exc:
        # UNIQUE na slugu. Łapiemy zamiast sprawdzać wcześniej SELECT-em, bo
        # sprawdzenie i zapis to dwa kroki, a między nimi mieści się drugi request.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Konto serwisowe o slugu '{payload.slug}' już istnieje",
        ) from exc
    await db.refresh(account)
    logger.info(
        "service_account.created",
        extra={"slug": account.slug, "by_user_id": admin.id},
    )
    return await _get_account(db, account.id)


@router.patch("/{account_id}", response_model=ServiceAccountOut)
async def update_account(
    account_id: int,
    payload: ServiceAccountUpdate,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> ServiceAccount:
    """Zmień nazwę, opis, uprawnienia lub zgaś konto.

    PATCH jest CZĘŚCIOWY — rozróżniamy „pominięte" od „ustawione na None" po
    ``model_fields_set``. Bez tego zgaszenie konta (``is_active=False``)
    wyczyściłoby przy okazji opis i scope'y, bo wszystkie pola są ``Optional``.
    """
    account = await _get_account(db, account_id)
    fields = payload.model_fields_set

    if "name" in fields and payload.name is not None:
        account.name = payload.name
    if "description" in fields:
        account.description = payload.description
    if "scopes" in fields and payload.scopes is not None:
        account.scopes = [scope.value for scope in payload.scopes]
    if "is_active" in fields and payload.is_active is not None:
        account.is_active = payload.is_active

    await db.commit()
    logger.info(
        "service_account.updated",
        extra={
            "slug": account.slug,
            "by_user_id": admin.id,
            "changed": sorted(fields),
        },
    )
    return await _get_account(db, account_id)


@router.delete(
    "/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_account(
    account_id: int,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Skasuj konto razem z kluczami (FK ON DELETE CASCADE).

    Kasowanie jest natychmiastowe i pełne, bo uprawnienia są czytane z konta przy
    każdym requeście — nie zostaje żadne poświadczenie, które mogłoby dożyć
    swojego terminu. Dla zachowania historii audytu preferowane jest jednak
    ``is_active=false`` (PATCH), które gasi konto, nie usuwając śladu.
    """
    account = await _get_account(db, account_id)
    slug = account.slug
    await db.delete(account)
    await db.commit()
    logger.info("service_account.deleted", extra={"slug": slug, "by_user_id": admin.id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{account_id}/keys",
    response_model=ServiceAccountKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("10/minute")
async def create_key(
    request: Request,
    account_id: int,
    payload: ServiceAccountKeyCreate,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> ServiceAccountKeyCreateResponse:
    """Wydaj nowy klucz. Sekret jest w odpowiedzi RAZ i nigdy więcej.

    ``request`` jest w sygnaturze, bo wymaga go slowapi — dekorator wyciąga
    z niego IP do kubełka limitu.
    """
    account = await _get_account(db, account_id)

    wire_key, key_id, secret_sha256 = generate_api_key()
    key = ServiceAccountKey(
        key_id=key_id,
        service_account_id=account.id,
        secret_sha256=secret_sha256,
        label=payload.label,
        created_by=admin.id,
        expires_at=default_expires_at(payload.expires_in_days),
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)

    # Log niesie key_id (jawne) i NIGDY sekretu — to jest właśnie powód, dla
    # którego identyfikator jest oddzielony od sekretu w formacie klucza.
    logger.info(
        "service_account.key_issued",
        extra={
            "slug": account.slug,
            "key_id": key_id,
            "by_user_id": admin.id,
            "expires_at": key.expires_at.isoformat(),
        },
    )
    return ServiceAccountKeyCreateResponse(
        key=ServiceAccountKeyOut.model_validate(key),
        api_key=wire_key,
    )


@router.post("/{account_id}/keys/{key_id}/revoke", response_model=ServiceAccountKeyOut)
async def revoke_key(
    account_id: int,
    key_id: str,
    payload: ServiceAccountKeyRevoke,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> ServiceAccountKey:
    """Unieważnij klucz natychmiast, zachowując wiersz.

    Rewokacja zostawia ślad (kto, kiedy, dlaczego) zamiast kasować wiersz —
    inaczej po incydencie nie da się odtworzyć, który klucz był aktywny i kiedy
    przestał. Skutek jest natychmiastowy, bo ważność jest sprawdzana przy każdym
    requeście; nie ma tu odpowiednika „wystawionego tokenu", który przeżywa
    odebranie dostępu.
    """
    result = await db.execute(
        select(ServiceAccountKey).where(
            ServiceAccountKey.key_id == key_id,
            ServiceAccountKey.service_account_id == account_id,
        )
    )
    key = result.unique().scalar_one_or_none()
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Klucz nie istnieje"
        )

    if key.revoked_at is None:
        key.revoked_at = datetime.now(timezone.utc)
        key.revoked_by = admin.id
        key.revoke_reason = payload.reason
        await db.commit()
        await db.refresh(key)
        logger.info(
            "service_account.key_revoked",
            extra={"key_id": key_id, "by_user_id": admin.id},
        )
    return key


@router.get("/config", response_model=dict)
async def key_policy(_: AdminUser) -> dict:
    """Obowiązująca polityka ważności kluczy — UI pokazuje ją przy formularzu."""
    return {
        "enabled": settings.SERVICE_ACCOUNTS_ENABLED,
        "default_ttl_days": settings.SERVICE_ACCOUNT_KEY_DEFAULT_TTL_DAYS,
        "max_ttl_days": settings.SERVICE_ACCOUNT_KEY_MAX_TTL_DAYS,
        "header": "X-API-Key",
    }
