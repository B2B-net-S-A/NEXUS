"""Zamień naruszenie więzów bazy przy zapisie zamówienia na czytelną odmowę.

Powód istnienia: ``IntegrityError`` przy ``commit()`` to wyjątek NIEOBSŁUŻONY.
Leci ponad ``CORSMiddleware``, więc przeglądarka blokuje odpowiedź i użytkownik
widzi wyłącznie „Network Error" — bez statusu, bez treści, bez wskazówki, co
poprawić. Odpowiedź OBSŁUŻONA (4xx) niesie komplet nagłówków CORS, więc ten
sam błąd staje się komunikatem, na który da się zareagować.

``UnhandledErrorMiddleware`` w ``app/main.py`` jest siecią bezpieczeństwa dla
całej aplikacji (500 z CORS zamiast zerwanego połączenia). To jest warstwa
wyżej: dla ZNANYCH więzów modułu zamówień potrafimy powiedzieć po polsku,
które pole się nie zgadza, więc odmowa jest 409 z konkretem, a nie 500
z „spróbuj ponownie".

Reguła: helper NIE jest walidacją. Każdy warunek, który da się sprawdzić
wcześniej, ma zostać sprawdzony wcześniej (``_apply_md_order_quantity``,
``_refresh_md_rate_mirror`` i sąsiednie bramki robią właśnie to). Ten moduł
łapie to, co przecieknie mimo tamtych bramek — historyczne wiersze, wyścig
dwóch okien, nowy CHECK dołożony bez lustra w API.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# Import na poziomie modułu, nie w funkcji: ładuje listener ``after_flush``,
# który zbiera kontrakty ruszonych zamówień. Zarejestrowany dopiero przy
# pierwszym commicie przegapiłby flushe pierwszego żądania po starcie.
from app.services.contract_order_sync import (
    pending_order_contract_ids,
    sync_pending_order_contracts,
)
from app.services.order_change_audit import ACTOR_INFO_KEY
from app.services.order_gaps import refresh_order_gaps_safely

logger = logging.getLogger(__name__)


# Nazwa więzu → komunikat po polsku. Dopisując CHECK w migracji, dopisz tu
# zdanie, które powie operatorowi, co poprawić — inaczej dostanie komunikat
# ogólny i nie będzie wiedział, którego pola dotyczy.
_CONSTRAINT_MESSAGES: dict[str, str] = {
    "ck_client_orders_md_coherence": (
        "Budżet MD zamówienia jest niekompletny: liczba MD wymaga dodatniej "
        "stawki przychodowej. Uzupełnij stawkę albo wyczyść liczbę MD."
    ),
    "ck_client_orders_order_type": (
        "Nieznany typ zamówienia. Wybierz okresowe, kosztowe albo MD."
    ),
    "ck_client_orders_md_optional": (
        "Zakres opcjonalny MD może istnieć tylko obok zakresu podstawowego "
        "i nie może być ujemny."
    ),
    "ck_client_orders_project_part": (
        "Nieznana część umowy. Wybierz wartość ze słownika Centrum e-Zdrowia."
    ),
    "ux_client_executive_contracts_client_number": (
        "Umowa wykonawcza o tym numerze już istnieje u tego klienta"
    ),
    # FK z migracji 0312 (inline ``REFERENCES`` → nazwa domyślna Postgresa).
    "client_orders_executive_contract_id_fkey": (
        "Wskazana umowa wykonawcza nie istnieje albo należy do innego klienta"
    ),
    "client_order_groups_executive_contract_id_fkey": (
        "Wskazana umowa wykonawcza nie istnieje albo należy do innego klienta"
    ),
    "ck_client_orders_dates": (
        "Data zakończenia zamówienia jest wcześniejsza niż data rozpoczęcia."
    ),
    "ck_client_order_groups_dates": (
        "Data zakończenia zamówienia jest wcześniejsza niż data rozpoczęcia."
    ),
    "ck_client_order_groups_cost_coherence": (
        "Zamówienie kosztowe wymaga kwoty większej od zera."
    ),
    "ck_client_order_groups_md_budget_coherence": (
        "Zamówienie na MD wymaga wspólnego budżetu większego od zera."
    ),
    "ck_client_order_groups_explicit_type_coherence": (
        "Typ zamówienia nie zgadza się z jego sposobem rozliczenia."
    ),
    "ck_client_order_groups_status": (
        "Nieznany stan zamówienia — odśwież stronę i spróbuj ponownie."
    ),
    "ck_client_order_groups_cancel_coherence": (
        "Anulowane zamówienie musi pamiętać stan sprzed anulowania — odśwież "
        "stronę i spróbuj ponownie."
    ),
    "ck_client_order_group_events_type": (
        "Nieznany typ zdarzenia w historii zamówienia — zgłoś to jako błąd "
        "aplikacji, zmiana nie została zapisana."
    ),
    "ck_client_order_offboarding_restore_target": (
        "Przywrócenie konsultanta nie przyjmuje odbiorcy puli ani podstawy "
        "stawki — odśwież stronę i wybierz decyzję ponownie."
    ),
    "ck_client_order_offboarding_resolution": (
        "Nieznana decyzja o zakończeniu współpracy. Odśwież stronę i wybierz "
        "decyzję ponownie."
    ),
}

_FALLBACK_MESSAGE = (
    "Zapisu nie da się pogodzić z regułami spójności danych zamówienia. "
    "Sprawdź stawki, budżet i daty, a jeśli wszystko wygląda poprawnie — "
    "zgłoś to jako błąd aplikacji."
)


def _violated_constraint(error: IntegrityError) -> Optional[str]:
    """Nazwa naruszonego więzu, gdy sterownik ją podał."""

    original = getattr(error, "orig", None)
    # asyncpg wystawia szczegóły błędu strukturalnie; psycopg2 przez `diag`.
    name = getattr(original, "constraint_name", None)
    if not name:
        diag = getattr(original, "diag", None)
        name = getattr(diag, "constraint_name", None)
    return str(name) if name else None


def integrity_error_conflict(error: IntegrityError) -> HTTPException:
    """Zbuduj 409 z komunikatem po polsku dla naruszonego więzu."""

    constraint = _violated_constraint(error)
    message = _CONSTRAINT_MESSAGES.get(constraint or "", _FALLBACK_MESSAGE)
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "order_integrity_conflict",
            "constraint": constraint,
            "message": message,
        },
    )


async def commit_order_write(
    db: AsyncSession, *, actor_id: Optional[int] = None
) -> None:
    """``db.commit()``, ale naruszenie więzów kończy się 409, nie „Network Error".

    Rollback jest tu OBOWIĄZKOWY: po nieudanym flushu sesja zostaje w stanie
    ``PendingRollbackError`` i każde kolejne użycie tej samej sesji (choćby
    odczyt do zbudowania odpowiedzi) wywaliłoby się ponownie — tym razem już
    poza tym blokiem, czyli znowu jako 500 bez CORS.

    Przed commitem kontrakty, których zamówienia ten zapis ruszył, dostają
    okres zamówienia i stawkę przychodową, a zamówienia — stawkę kosztową
    z kontraktu (``contract_order_sync``), a otwarte braki tej osoby
    (``order_gaps``) dostają informację o uzupełnieniu. To jedyny punkt, przez który
    przechodzą wszystkie zapisy zamówień, więc nowy endpoint nie musi pamiętać
    o synchronizacji.
    """

    try:
        await db.flush()
        touched_contracts = pending_order_contract_ids(db)
        await sync_pending_order_contracts(db, actor_id=actor_id)
        # Brak kolejnego zamówienia (Finanse → Braki) zamyka się w chwili
        # zapisu następnego zamówienia, a nie o północy — Finanse widzą
        # uzupełnienie od razu. Savepoint: awaria nie cofa zamówienia.
        if touched_contracts:
            await refresh_order_gaps_safely(
                db,
                contract_ids=sorted(touched_contracts),
                actor_id=actor_id or db.info.get(ACTOR_INFO_KEY),
            )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        logger.warning(
            "Order write rejected by database constraint %s",
            _violated_constraint(exc) or "<nieznany>",
            exc_info=True,
        )
        raise integrity_error_conflict(exc) from exc
