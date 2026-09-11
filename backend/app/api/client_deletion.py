"""Ręczne usunięcie klienta z profilu (dowolny status).

Dwie trasy:

* ``POST /api/clients/{id}/deletion-check`` — kliknięcie „Usuń klienta".
  Zwraca ocenę (blokady, historia, tryb usunięcia) i niczego nie usuwa.
  Zablokowana próba JEST już próbą usunięcia, więc trafia do Historii zdarzeń.
* ``DELETE /api/clients/{id}?confirmation=0`` — wykonanie po wpisaniu „0".
  Ocena jest liczona od nowa pod blokadą wiersza klienta — między podglądem
  a potwierdzeniem mogło przybyć zamówienie.

Bramka to imienne uprawnienie ``users.can_delete_clients`` — nie rola.
Administrator bez tej flagi dostaje 403 tak samo jak każdy inny, a próba
wywołania trasy bez uprawnienia też ląduje w Historii zdarzeń.

Router nie niesie bramki zapisu sekcji Delivery (``DELIVERY_SECTION_
DEPENDENCIES``): ta wymagałaby „zapisu", a uprawnienie do usuwania nadaje
administrator imiennie, niezależnie od roli. Wymagany jest odczyt Delivery —
kto nie widzi klientów, nie ma czego usuwać.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarded_user
from app.api.section_access import require_section_access_any_read
from app.core.database import get_db
from app.models.client import Client
from app.models.critical_event import CriticalEvent
from app.models.user import User
from app.schemas.client_deletion import (
    ClientDeletionCheckResponse,
    ClientDeletionResult,
)
from app.services.client_deletion import (
    CONFIRMATION_PHRASE,
    ClientDeletionAssessment,
    assess_client_deletion,
    execute_client_deletion,
    lock_client,
)
from app.services.client_identity import client_display_name, is_client_visible
from app.services.critical_events import record_blocked, record_executed
from app.services.section_permissions import ProductSection

router = APIRouter(
    dependencies=[Depends(require_section_access_any_read(ProductSection.delivery))]
)

EVENT_TYPE = "client.delete"


async def require_client_deletion_permission(
    request: Request,
    client_id: int,
    current_user: User = Depends(require_onboarded_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Imienne uprawnienie do usuwania klientów. Odmowa trafia do dziennika."""

    impersonating = getattr(request.state, "impersonator_id", None) is not None
    if current_user.can_delete_clients and not impersonating:
        return current_user

    reason = (
        "Usuwanie klientów jest niedostępne w trybie podglądu jako inny użytkownik."
        if impersonating
        else "Brak uprawnienia do usuwania klientów."
    )
    client = await db.scalar(select(Client).where(Client.id == client_id))
    if client is not None and not await _recently_refused(
        db, actor_id=current_user.id, client_id=client.id
    ):
        await record_blocked(
            actor=current_user,
            event_type=EVENT_TYPE,
            entity_type="client",
            entity_id=client.id,
            entity_label=client_display_name(client),
            client_id=client.id,
            client_name=client_display_name(client),
            reason_code="impersonation" if impersonating else "no_permission",
            reason=reason,
        )
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=reason)


# Jedna odmowa „brak uprawnienia" na osobę i klienta w tym oknie. Trasa jest
# dostępna dla każdego z odczytem Delivery, więc bez tego skrypt wołający ją
# w pętli zapchałby Historię zdarzeń wpisami bez nowej informacji.
_REFUSAL_DEDUP_WINDOW = timedelta(minutes=10)


async def _recently_refused(db: AsyncSession, *, actor_id: int, client_id: int) -> bool:
    since = datetime.now(timezone.utc) - _REFUSAL_DEDUP_WINDOW
    existing = await db.scalar(
        select(CriticalEvent.id)
        .where(
            CriticalEvent.event_type == EVENT_TYPE,
            CriticalEvent.client_id == client_id,
            CriticalEvent.actor_user_id == actor_id,
            CriticalEvent.outcome == "blocked",
            CriticalEvent.reason_code.in_(("no_permission", "impersonation")),
            CriticalEvent.occurred_at >= since,
        )
        .limit(1)
    )
    return existing is not None


async def _load_deletable_client(db: AsyncSession, client_id: int) -> Client:
    client = await db.scalar(select(Client).where(Client.id == client_id))
    if client is None or not is_client_visible(client):
        # Usunięty, scalony albo techniczny (ukryty) klient nie ma profilu,
        # z którego można by go usunąć.
        raise HTTPException(status_code=404, detail="Klient nie istnieje")
    return client


def _blocked_details(assessment: ClientDeletionAssessment) -> dict:
    """Szczegóły zablokowanej próby BEZ pozycji blokad.

    Pozycje (``items``) niosą imiona i nazwiska kontraktorów — okno pokazuje
    je na żywo, ale dziennik przeżywa usunięcie osoby (art. 17 RODO), więc
    zapisujemy wyłącznie rodzaj i liczbę blokad.
    """

    return {
        "blockers": [
            {"code": blocker.code, "label": blocker.label, "count": blocker.count}
            for blocker in assessment.blockers
        ],
        "client_status": assessment.status,
    }


async def _record_blocked_in_session(
    db: AsyncSession, actor: User, assessment: ClientDeletionAssessment
) -> None:
    """Zapisz zablokowaną próbę w sesji żądania.

    Żądanie kończy się normalną odpowiedzią (200 / 409 jako ``JSONResponse``),
    więc sesja jest zatwierdzana — osobna sesja nie jest tu potrzebna.
    """

    await record_executed(
        db,
        actor=actor,
        event_type=EVENT_TYPE,
        entity_type="client",
        entity_id=assessment.client_id,
        entity_label=assessment.client_name,
        client_id=assessment.client_id,
        client_name=assessment.client_name,
        outcome="blocked",
        reason_code="+".join(blocker.code for blocker in assessment.blockers),
        reason=assessment.blocked_reason(),
        details=_blocked_details(assessment),
    )


@router.post(
    "/{client_id}/deletion-check",
    response_model=ClientDeletionCheckResponse,
)
async def check_client_deletion(
    client_id: int,
    current_user: User = Depends(require_client_deletion_permission),
    db: AsyncSession = Depends(get_db),
):
    client = await _load_deletable_client(db, client_id)
    assessment = await assess_client_deletion(db, client)
    if assessment.mode == "blocked":
        await _record_blocked_in_session(db, current_user, assessment)
    return ClientDeletionCheckResponse(**assessment.as_dict())


@router.delete("/{client_id}", response_model=ClientDeletionResult)
async def delete_client(
    client_id: int,
    confirmation: str = Query(
        "",
        description='Potwierdzenie usunięcia — wymagane dokładnie "0".',
    ),
    current_user: User = Depends(require_client_deletion_permission),
    db: AsyncSession = Depends(get_db),
):
    if confirmation.strip() != CONFIRMATION_PHRASE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail='Aby usunąć klienta, wpisz "0" w oknie potwierdzenia.',
        )
    await _load_deletable_client(db, client_id)
    client = await lock_client(db, client_id)
    if client is None or not is_client_visible(client):
        raise HTTPException(status_code=404, detail="Klient nie istnieje")

    assessment = await execute_client_deletion(db, client, actor=current_user)
    if assessment.mode == "blocked":
        await _record_blocked_in_session(db, current_user, assessment)
        # JSONResponse, nie HTTPException: wyjątek wycofałby sesję żądania,
        # a razem z nią wpis o zablokowanej próbie.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": assessment.blocked_reason(),
                "check": ClientDeletionCheckResponse(
                    **assessment.as_dict()
                ).model_dump(),
            },
        )

    result = "purged" if assessment.mode == "purge" else "archived"
    await record_executed(
        db,
        actor=current_user,
        event_type=EVENT_TYPE,
        entity_type="client",
        entity_id=assessment.client_id,
        entity_label=assessment.client_name,
        client_id=assessment.client_id,
        client_name=assessment.client_name,
        reason_code=result,
        reason=(
            "Klient pusty — usunięty trwale."
            if result == "purged"
            else "Klient usunięty z list; dane historyczne zachowane w systemie. "
            + (assessment.history_sentence() or "")
        ).strip(),
        details={
            "result": result,
            "client_status": assessment.status,
            "history": [item.as_dict() for item in assessment.history],
        },
    )
    return ClientDeletionResult(
        client_id=assessment.client_id,
        client_name=assessment.client_name,
        result=result,
        history=[item.as_dict() for item in assessment.history],
        history_sentence=assessment.history_sentence(),
    )
