"""Dane firm z umów — do potwierdzenia (E5a, 0755, decyzja Artura 22.11.2026).

``GET  /api/contract-partner-reads`` — odczyty w stanie (``open`` domyślnie,
       ``failed``, ``applied``, ``dismissed``) z licznikami i stanem teczek.
``POST /api/contract-partner-reads/{id}/apply`` — „Zastosuj” (poprawki
       człowieka w ``values``; ``overwrite`` zmienia wpisane już pola firmy).
``POST /api/contract-partner-reads/{id}/dismiss`` — „Odrzuć”.
``POST /api/contract-partner-reads/{id}/verify`` — „Sprawdź w rejestrze”
       (CEIDG albo KRS po NIP-ie lub KRS z odczytu i poprawek).

Bramki jak praca na kontraktach: sekcja Delivery i „Kontrakty i zamówienia:
tworzenie i edycja” na każdej trasie (lista to kolejka do pracy z danymi
osobowymi kontraktorów), konto z rolą Delivery Leada — tylko u swoich
klientów. Logika: ``app.services.contract_partner_reads``.
"""

from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.permission_access import ContractsOrdersEditUser
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.user import User
from app.services.access_scope import resolve_delivery_lead_client_ids
from app.services.contract_partner_reads import reader, service

router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)

DbIdPath = Annotated[int, Path(ge=1, le=2_147_483_647)]
_VALUE_MAX = 600


class _Values(BaseModel):
    # Poprawki człowieka: pole odczytu → wartość (pusta = „brak w umowie”).
    values: dict[str, Optional[str]] = Field(default_factory=dict)

    @field_validator("values")
    @classmethod
    def _known_short(cls, v: dict[str, Optional[str]]) -> dict[str, Optional[str]]:
        unknown = sorted(set(v) - set(reader.FIELDS))
        if unknown:
            raise ValueError(f"Nieznane pola: {', '.join(unknown)}.")
        if any(value is not None and len(value) > _VALUE_MAX for value in v.values()):
            raise ValueError(f"Wartość pola może mieć najwyżej {_VALUE_MAX} znaków.")
        return v


class ApplyBody(_Values):
    overwrite: bool = False


class VerifyBody(_Values):
    pass


def _refusal(exc: service.PartnerReadError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("")
async def list_partner_reads(
    current_user: ContractsOrdersEditUser,
    state: Literal["open", "failed", "applied", "dismissed"] = "open",
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100_000),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Dane firm z umów w jednym stanie, od najnowszego odczytu."""

    client_ids = await resolve_delivery_lead_client_ids(current_user, db)
    items, total = await service.list_reads(
        db, state=state, client_ids=client_ids, limit=limit, offset=offset
    )
    return {
        "state": state,
        "items": items,
        "total": total,
        "counts": await service.counts(db, client_ids),
    }


async def _decide(
    db: AsyncSession, user: User, read_id: int, action: str, body: Any = None
) -> dict[str, Any]:
    client_ids = await resolve_delivery_lead_client_ids(user, db)
    try:
        if action == "apply":
            await service.apply_read(
                db,
                read_id,
                user=user,
                overwrite=body.overwrite,
                corrections=body.values,
                client_ids=client_ids,
            )
        elif action == "dismiss":
            await service.dismiss_read(db, read_id, user=user, client_ids=client_ids)
        else:
            await service.verify_read(
                db, read_id, client_ids=client_ids, corrections=body.values
            )
    except service.PartnerReadError as exc:
        await db.rollback()
        raise _refusal(exc) from exc
    await db.commit()
    return await service.read_view(db, read_id)


@router.post("/{read_id}/apply")
async def apply_partner_read(
    read_id: DbIdPath,
    body: ApplyBody,
    current_user: ContractsOrdersEditUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """„Zastosuj” — potwierdzone dane firmy; puste pola profilu kandydata."""

    return await _decide(db, current_user, read_id, "apply", body)


@router.post("/{read_id}/dismiss")
async def dismiss_partner_read(
    read_id: DbIdPath,
    current_user: ContractsOrdersEditUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """„Odrzuć” — odczyt nie trafia ani do profilu, ani do nowej umowy."""

    return await _decide(db, current_user, read_id, "dismiss")


@router.post("/{read_id}/verify")
async def verify_partner_read(
    read_id: DbIdPath,
    body: VerifyBody,
    current_user: ContractsOrdersEditUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """„Sprawdź w rejestrze” — CEIDG albo KRS; wynik zostaje przy odczycie.

    Zawsze 200 z wynikiem rejestru: niedostępny rejestr to ``unverified``
    z powodem, bo sprawdzenie jest informacją dla człowieka, nie bramką."""

    return await _decide(db, current_user, read_id, "verify", body)
