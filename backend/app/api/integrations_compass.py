"""Eksport kontraktorów dla COMPASSA — pierwsza powierzchnia HTTP tej integracji.

UWAGA: ten moduł NIE MOŻE mieć ``from __future__ import annotations``.
PEP 563 + slowapi #579 zamieniają guard ``Annotated`` w wymagany parametr
QUERY, więc endpoint zaczyna zwracać 422 na poprawnym żądaniu.

KIERUNEK JEST ODWROTNY NIŻ W D5
-------------------------------
Dotąd NEXUS *ciągnął* z COMPASSA (dni robocze). Tu COMPASS ciąga z NEXUSA —
i to jest pierwsze wystawienie danych NEXUSA drugiej aplikacji.

PO CO
-----
COMPASS trzyma 689 kontraktorów, z czego **0 ma e-mail** i **0 ma
``profile_id``**; tożsamością jest samo imię i nazwisko. Wszystkie mają
``status='active'`` mimo 365 zarejestrowanych zejść od klientów, bo nikt tego
pola nigdy nie zmienia. NEXUS zna te osoby dokładnie: z e-mailem, klientem,
datami i realnym statusem umowy.

CZEGO TEN EKSPORT NIE ODDAJE — I DLACZEGO
------------------------------------------
**Żadnych kwot.** Ani stawki kontraktora, ani stawki klienta, ani marży.
Decyzja produktowa (04.09.2026) w tym samym duchu co D5, gdzie eksport dni
roboczych celowo nie niesie typu nieobecności: odbiorcą jest zespół TCM, który
prowadzi opiekę nad konsultantem, a nie rozlicza kontraktu. Poszerzenie
eksportu o kwoty otwiera je każdemu z dostępem do People Ops w COMPASSIE.

Skutek uboczny jest korzystny: skoro kwoty nie jadą, ten handler **nie woła**
``effective_rate_fields``, więc nie dotyczy go pułapka ``RATE_SCHEDULE_LOADS``
(brak trzech ``selectinload`` = ``MissingGreenlet`` w sesji async, czyli 500
bez nagłówków CORS).

DLACZEGO OSOBNY ENDPOINT, A NIE ``/api/contractors``
-----------------------------------------------------
Tamten ma własne scope'owanie ról (``_apply_contractor_scope``), redakcję
finansową per wiersz i paginację pod UI. Doklejenie do niego drugiego trybu
uwierzytelnienia zmieszałoby dwie różne polityki dostępu na jednej trasie.

Ścieżka ``/api/integrations/...`` jest wymuszona kontraktem testowym:
``test_key_cannot_reach_domain_data`` wymaga, żeby klucz z DOWOLNYM zestawem
scope'ów dostawał 401 na ``/api/candidates``, ``/api/jobs``, ``/api/clients``
i ``/api/users``. Eksport musi więc stać obok nich, nie pod nimi.
"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import ContractorsReadCaller
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.scheduling import business_today
from app.models.client_order import ClientOrderStatus
from app.models.contract import Contract, ContractStatus
from app.services.client_identity import client_display_name
from app.services.order_excel_export import is_current_order_period
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter()

# Te same kubełki co w rejestrze kontraktorów: umowy żywe i te w drodze.
# `ended`/`void` świadomie poza eksportem BIEŻĄCEGO stanu — historia zejść
# jedzie osobnym polem (`end_date`), a nie osobnym wierszem.
_EXPORT_STATUSES = (
    ContractStatus.draft,
    ContractStatus.ready_for_signature,
    ContractStatus.active,
    ContractStatus.ending,
)

_MAX_PAGE_SIZE = 500

# Zamówienie zakończone albo anulowane nie „obowiązuje dziś" niezależnie od dat.
# Lustro reguły z frontu (`isCurrentOrder`, `lib/client-order-list.ts`) — SZKIC
# celowo LICZY SIĘ jako pokrycie: to zaślepka zakładana hookiem zatrudnienia,
# więc osoba ze szkicem jest obsadzona, tylko zamówienie nie jest uzupełnione.
_DEAD_ORDER_STATUSES = (ClientOrderStatus.completed, ClientOrderStatus.cancelled)


def _lacks_current_order(contract: Contract, today) -> bool:
    """Czy kontraktor jest „bez projektu" — czyli na ławce.

    To NIE jest to samo co ``b2b_generated_contracts.contract_status =
    'suspended'``. Tamten sygnał jest deklaracją człowieka i jest precyzyjny,
    ale ślepy na kontraktorów, których umowy nie generowano w NEXUSIE. Ta
    reguła jest wyprowadzana z zamówień i obejmuje wszystkich, którzy mają
    kontrakt — dlatego jest sygnałem podstawowym, a `suspended` potwierdzającym.
    """
    for order in contract.client_orders or ():
        if order.status in _DEAD_ORDER_STATUSES:
            continue
        if is_current_order_period(order.start_date, order.end_date, today):
            return False
    return True


def _service_rate_limit() -> str:
    """Callable, nie stała — limit czytany przy każdym żądaniu, bez deployu."""
    return settings.SERVICE_ACCOUNT_RATE_LIMIT


@router.get("/contractors")
@limiter.limit(_service_rate_limit)
async def export_contractors(
    request: Request,
    _caller: ContractorsReadCaller,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=_MAX_PAGE_SIZE),
    updated_since: date | None = Query(
        None,
        description="Tylko umowy zmienione od tej daty (przyrostowo).",
    ),
):
    """Kontraktorzy: tożsamość + zaangażowanie. Bez kwot.

    Stronicowanie jest OBOWIĄZKOWE po stronie konsumenta — odpowiedź niesie
    ``total`` i ``has_more``, bo lista przycięta limitem bez licznika czyta się
    jak komplet.
    """
    query = (
        select(Contract)
        .options(
            selectinload(Contract.candidate),
            selectinload(Contract.client),
            selectinload(Contract.job),
            # Bez tego `_lacks_current_order` sięgnąłby po relację leniwie,
            # a w sesji async lazy-load to nie wolniejszy odczyt, tylko
            # `MissingGreenlet` — czyli 500 bez nagłówków CORS.
            selectinload(Contract.client_orders),
        )
        .where(Contract.status.in_(_EXPORT_STATUSES))
        # Ten sam filtr co w rejestrze kontraktorów. Umowa odpięta po usunięciu
        # kandydata (migracja 0225) nie ma tożsamości do wyeksportowania, a
        # COMPASS łączy wiersze właśnie po osobie.
        .where(Contract.candidate_id.is_not(None))
    )
    if updated_since is not None:
        query = query.where(Contract.updated_at >= updated_since)

    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar() or 0

    # `Contract.id` jako ostatni klucz sortowania jest OBOWIĄZKOWY: bez
    # unikalnego rozstrzygnięcia remisu stronicowanie gubi i dubluje wiersze
    # (ta sama pułapka co w `/api/contractors`).
    query = query.order_by(Contract.updated_at.desc(), Contract.id.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    contracts = (await db.execute(query)).scalars().all()

    today = business_today()
    items = []
    for c in contracts:
        cand = c.candidate
        items.append(
            {
                "nexus_contract_id": c.id,
                "candidate": {
                    "id": cand.id if cand else c.candidate_id,
                    "name": cand.name if cand else None,
                    "lastname": cand.lastname if cand else None,
                    # E-mail jest tu POWODEM istnienia eksportu: to jedyny
                    # klucz, po którym COMPASS może połączyć wiersz bez
                    # zgadywania po nazwisku. Bywa pusty — wtedy wiersz idzie
                    # u odbiorcy do kolejki ręcznej, nie do automatu.
                    "email": cand.email if cand else None,
                },
                "client_id": c.client_id,
                "client_name": client_display_name(c.client) if c.client else None,
                "job_title": c.job.title if c.job else None,
                "status": c.status.value if c.status else None,
                "start_date": c.start_date,
                "end_date": c.end_date,
                # „Bez projektu" — odpowiednik `contractor_bench` w COMPASSIE,
                # dziś utrzymywanego tam ręcznie z auto-seedem z zejść.
                "lacks_current_order": _lacks_current_order(c, today),
                "updated_at": c.updated_at,
            }
        )

    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": (page * page_size) < total,
    }
