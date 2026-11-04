"""Zamówienie MD kończy się wyczerpaniem limitów MD, nie datą.

Linie MD już dziś kończą się same, gdy ich budżet zejdzie do zera
(``client_order_lines.sync_md_line_status``) — ale grupa zostawała ``active``
bez ani jednej aktywnej osoby. Do 24.09.2026 dotyczyło to tylko klientów
z polityką ``closes_on_md_exhaustion`` (BIK); od ticketu 4500030067 KAŻDE
zamówienie MD z pulą per osoba idzie za liniami:

* pozostaje **aktywna**, dopóki choć jedna przypisana osoba ma niewykorzystany
  limit MD (albo limitu jeszcze nie ma — osoby bez budżetu nie „wyczerpały"
  niczego);
* przechodzi na **zakończone** (``completed``, „Zakończone"), gdy WSZYSTKIE
  osoby wyczerpią swój limit — ostatnia osoba kończy całe zamówienie. Osoba
  z zakończoną współpracą, pozostawiona na zamówieniu jako historia, jest
  przy tej ocenie POMIJANA (rozstrzygnięcie otwartego pytania z ticketu
  09.2026): jej niewykorzystany limit nie trzyma zamówienia otwartego.

Zużycie przychodzi z istniejącego importu Finansów: to on przelicza
``md_remaining`` (``recompute_remaining``), a ta funkcja jest wołana stamtąd,
więc nie powstaje drugie śledzenie zużycia. Dobowy skaner i odczyt zakładki
dociągają stany, których żadne przeliczenie linii nie dotknęło (np. zdjęcie
z zamówienia ostatniej osoby z niewykorzystanym limitem).

Świadomie ``completed``, a nie ``exhausted``: ticket mówi o statusie
„Zakończone", a ``exhausted`` opisuje w tym module wyłącznie pulę WSPÓLNĄ
(kosztową albo wspólną pulę MD) i ma własne alerty. Zakończenie automatyczne
jest rozpoznawalne po ``closure_reason`` bez autora; tylko takie cofamy
automatycznie, gdy korekta zużycia albo budżetu przywróci komuś MD —
zakończenia ręcznego (autor, własny powód) nigdy.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_offboarding import (
    OFFBOARDING_STATUS_PENDING,
    ClientOrderOffboardingCase,
)
from app.models.client_order_group import (
    GROUP_STATUS_ACTIVE,
    GROUP_STATUS_COMPLETED,
    ClientOrderGroup,
)
from app.services.client_order_lines import record_event
from app.services.multi_consultant_orders import (
    EVENT_ORDER_CLOSED,
    EVENT_ORDER_REOPENED,
)
from app.services.shared_md_orders import uses_shared_md_pool

MD_EXHAUSTED_CLOSURE_REASON = "Wszyscy konsultanci wyczerpali limit MD"

_ZERO = Decimal("0")


def _remaining(line: ClientOrder) -> Decimal:
    return Decimal(str(line.md_remaining if line.md_remaining is not None else 0))


def closed_by_md_exhaustion(group: ClientOrderGroup) -> bool:
    """Czy zamówienie zakończyło się SAMO, po wyczerpaniu limitów MD."""
    return (
        group.status == GROUP_STATUS_COMPLETED
        and group.closure_reason == MD_EXHAUSTED_CLOSURE_REASON
        and group.closed_by_user_id is None
    )


async def sync_md_group_exhaustion(
    db: AsyncSession,
    group_id: int,
    *,
    client_id: Optional[int] = None,
    today: Optional[date] = None,
) -> bool:
    """Dopasuj status zamówienia do limitów MD jego osób. Zwraca, czy się zmienił.

    ``client_id`` zostaje w sygnaturze dla wołających (dawniej odcinał klientów
    spoza polityki BIK). Zmienia wyłącznie obiekty w sesji; transakcją
    zarządza wołający.
    """
    group = await db.get(ClientOrderGroup, group_id)
    if group is None:
        return False
    if group.is_cost_based or uses_shared_md_pool(group):
        return False  # pula wspólna ma własny stan ``exhausted``
    if group.status != GROUP_STATUS_ACTIVE and not closed_by_md_exhaustion(group):
        return False

    lines = [
        line
        for line in (
            await db.execute(
                select(ClientOrder).where(ClientOrder.order_group_id == group.id)
            )
        ).scalars()
        if line.status != ClientOrderStatus.cancelled
    ]
    if group.status == GROUP_STATUS_ACTIVE:
        # Osoba z ZAKOŃCZONĄ współpracą (linia ``completed`` z niewykorzystanym
        # limitem — zapis historyczny albo zakończenie kontraktu) nie trzyma
        # zamówienia otwartego: jej MD i tak nikt już nie wykorzysta. Decydują
        # osoby na obsadzie. Zamówienie kończy się jednak dopiero wtedy, gdy
        # ktoś NAPRAWDĘ wyczerpał limit — same odejścia to nie „wyczerpanie MD".
        on_staff = [
            line for line in lines if line.status != ClientOrderStatus.completed
        ]
        exhausted_any = any(
            line.md_total is not None and _remaining(line) <= _ZERO for line in lines
        )
        if not exhausted_any or any(
            line.md_total is None or _remaining(line) > _ZERO for line in on_staff
        ):
            return False
        # Nierozstrzygnięta decyzja o pozostałej puli MD (offboarding) trzyma
        # zamówienie otwarte: po zamknięciu „przywróć" i „przenieś" nie
        # miałyby już dokąd wrócić — zostałoby tylko „usuń".
        # Sprawa z pulą 0 MD nie czeka na decyzję — zamyka się tu sama
        # (ticket 4500030067: import po zejściu wyzerował pulę, a otwarta
        # sprawa trzymała zamówienie w „Aktywnych”).
        from app.services.md_pool_used_up import resolve_used_up_offboarding_cases

        # ``autoflush=False``: zapytania niżej muszą widzieć zmiany z sesji.
        await db.flush()
        await resolve_used_up_offboarding_cases(db, group_id=group.id)
        pending_case = await db.scalar(
            select(ClientOrderOffboardingCase.id)
            .where(
                ClientOrderOffboardingCase.order_group_id == group.id,
                ClientOrderOffboardingCase.status == OFFBOARDING_STATUS_PENDING,
            )
            .limit(1)
        )
        if pending_case is not None:
            return False
        # Audyt 24.09.2026 (H9): dzień przeliczenia, nie koniec miesiąca
        # ostatniego zejścia. Data cofnięta do 31.08 (raport sierpnia wgrany
        # 10.09) zamykała wrzesień — ``group_settles_in_month`` odrzucał import
        # za bieżący miesiąc, choć konsultanci na tym zamówieniu pracowali.
        closure_day = today or business_today()
        group.status = GROUP_STATUS_COMPLETED
        group.closure_date = closure_day
        group.closure_reason = MD_EXHAUSTED_CLOSURE_REASON
        group.closed_at = datetime.now(timezone.utc)
        group.closed_by_user_id = None
        record_event(
            db,
            group_id=group.id,
            event_type=EVENT_ORDER_CLOSED,
            description=(
                f"Zamówienie {group.order_number} zakończone automatycznie "
                f"z dniem {closure_day.isoformat()} — pula MD wykorzystana "
                "w całości"
            ),
            payload={
                "closure_date": closure_day.isoformat(),
                "automatic": True,
                "reason": "md_exhausted",
                "lines": len(lines),
            },
        )
        return True

    # Zakończone automatycznie: wraca, gdy korekta przywróciła komuś MD, a linia
    # tej osoby znów pracuje (``sync_md_line_status`` wskrzesza ją wcześniej).
    revived = [
        line
        for line in lines
        if line.status == ClientOrderStatus.active and _remaining(line) > _ZERO
    ]
    if not revived:
        # Sprawa offboardingu otwarta ponownie po korekcie (runda 6 audytu,
        # MD-2) trzyma zamówienie otwarte tak samo jak przed zamknięciem —
        # inaczej „przywróć” i „przenieś” nie miałyby dokąd wrócić.
        await db.flush()
        reopened_case = await db.scalar(
            select(ClientOrderOffboardingCase.id)
            .where(
                ClientOrderOffboardingCase.order_group_id == group.id,
                ClientOrderOffboardingCase.status == OFFBOARDING_STATUS_PENDING,
            )
            .limit(1)
        )
        if reopened_case is None:
            return False
    previous_closure = group.closure_date
    group.status = GROUP_STATUS_ACTIVE
    group.closure_date = None
    group.closure_reason = None
    group.closed_at = None
    group.closed_by_user_id = None
    record_event(
        db,
        group_id=group.id,
        event_type=EVENT_ORDER_REOPENED,
        description=(
            f"Przywrócono zamówienie {group.order_number} — po korekcie "
            "zużycia lub budżetu konsultant ma znów niewykorzystany limit MD"
        ),
        payload={
            "previous_closure_date": (
                previous_closure.isoformat() if previous_closure else None
            ),
            "automatic": True,
            "reason": "md_available",
            "lines_reopened": len(revived),
        },
    )
    return True


async def reconcile_md_exhausted_groups(
    db: AsyncSession,
    *,
    client_id: Optional[int] = None,
    today: Optional[date] = None,
) -> int:
    """Dociągnij statusy wszystkich zamówień MD. Zwraca liczbę zmian.

    Siatka bezpieczeństwa dla przejść, których nie wywołało przeliczenie linii
    (skaner dobowy, odczyt zakładki). Idempotentna; tylko ``flush``.
    """
    stmt_filter = (
        [ClientOrderGroup.client_id == client_id] if client_id is not None else []
    )
    groups = (
        await db.execute(
            select(ClientOrderGroup.id, ClientOrderGroup.client_id).where(
                *stmt_filter,
                ClientOrderGroup.is_cost_based.is_(False),
                or_(
                    ClientOrderGroup.status == GROUP_STATUS_ACTIVE,
                    ClientOrderGroup.closure_reason == MD_EXHAUSTED_CLOSURE_REASON,
                ),
            )
        )
    ).all()
    changed = 0
    for group_id, group_client_id in groups:
        if await sync_md_group_exhaustion(
            db, group_id, client_id=group_client_id, today=today
        ):
            changed += 1
    if changed:
        await db.flush()
    return changed
