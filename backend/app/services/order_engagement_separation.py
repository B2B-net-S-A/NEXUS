"""Zamówienia MD/kosztowe i okresowe to DWA niezależne byty na jednym kontrakcie.

Kontrakt (``Contract``) opisuje parę *osoba × klient*, a nie pojedyncze
zamówienie. U klientów wielo-konsultantowych ta sama osoba bywa więc opisana
dwa razy: linią grupy MD/kosztowej (``ClientOrder.order_group_id IS NOT NULL``)
oraz samodzielnym zamówieniem okresowym. Zgłoszenie z sierpnia 2026: zakończenie
tego drugiego kasowało budżet MD tej samej osoby, bo obie ścieżki kończenia
prowadziły przez wypowiedzenie CAŁEGO kontraktu.

Ten moduł trzyma w jednym miejscu obie reguły rozdzielenia:

* :func:`open_group_line_ids` / :func:`has_open_group_line` — czy osoba jest już
  obsadzona linią grupy. Na tym stoi bramka tworzenia zamówień okresowych;
* :func:`assert_no_open_group_line` — 409 po polsku dla ścieżek RĘCZNYCH
  (formularz „Dodaj przedłużenie", „Nowy kontraktor"). Ścieżki AUTOMATYCZNE
  (hook zatrudnienia, szkic „Dodaj kolejny projekt") pytają predykatem i po
  cichu odpuszczają: zatrudnienie nie może się wywrócić dlatego, że ktoś jest
  już na zamówieniu MD.

Świadomie NIE ma tu reguły odwrotnej („nie dodawaj linii MD, gdy jest okresowe"):
ticket żąda zabezpieczenia dokładnie jednego kierunku, a linia grupy powstaje
zawsze świadomą decyzją operatora, nigdy z automatu.
"""

from __future__ import annotations

from typing import Optional, Sequence

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.order_type import OrderType
from app.services.order_types import effective_group_order_type


#: Zamówienie/linia, która JESZCZE OBOWIĄZUJE. ``cancelled``/``completed`` są
#: historią i nie blokują niczego — inaczej jedno stare zamówienie zamykałoby
#: drogę do założenia nowego na zawsze.
OPEN_ORDER_STATUSES: tuple[ClientOrderStatus, ...] = (
    ClientOrderStatus.draft,
    ClientOrderStatus.active,
    ClientOrderStatus.paused,
)


async def open_group_line_ids(
    db: AsyncSession,
    contract_id: Optional[int],
    *,
    md_only: bool = False,
) -> list[int]:
    """Otwarte linie grupowe tego kontraktu, rosnąco po ``id``.

    ``md_only`` zawęża do zamówień rozliczanych w MD. Typ liczy
    ``effective_group_order_type``, a nie surowa kolumna: rekordy sprzed
    wdrożenia jawnych typów mają ``order_type IS NULL`` i ich znaczenie wynika
    z ``is_cost_based``.
    """

    if contract_id is None:
        return []
    result = await db.execute(
        select(ClientOrder.id, ClientOrderGroup)
        .join(ClientOrderGroup, ClientOrderGroup.id == ClientOrder.order_group_id)
        .where(
            ClientOrder.contract_id == contract_id,
            ClientOrder.status.in_(OPEN_ORDER_STATUSES),
        )
        .order_by(ClientOrder.id.asc())
    )
    return [
        line_id
        for line_id, group in result.all()
        if not md_only or effective_group_order_type(group) == OrderType.md
    ]


async def has_open_group_line(db: AsyncSession, contract_id: Optional[int]) -> bool:
    """Czy osoba jest już obsadzona żywą linią zamówienia MD albo kosztowego."""

    return bool(await open_group_line_ids(db, contract_id))


def _conflict(line_ids: Sequence[int]) -> HTTPException:
    return HTTPException(
        status_code=http_status.HTTP_409_CONFLICT,
        detail={
            "code": "consultant_already_on_group_order",
            "message": (
                "Ten konsultant jest już obsadzony na zamówieniu rozliczanym "
                "w MD (albo kosztowym) u tego klienta. Zamówienie okresowe "
                "byłoby drugim, równoległym zapisem tej samej współpracy — "
                "edytuj linię w zamówieniu grupowym zamiast zakładać nowe."
            ),
            "order_ids": list(line_ids),
        },
    )


async def assert_no_open_md_group_line(
    db: AsyncSession, contract_id: Optional[int]
) -> None:
    """Odmów RĘCZNEGO założenia zamówienia okresowego obok żywej linii MD.

    Duplikat nie jest tylko nadmiarowym wierszem: obie pozycje wiszą na tym
    samym kontrakcie, więc wypowiedzenie kontraktu z karty okresowej domykało
    także linię MD — zgłoszony objaw „skasowało zamówienie MD".

    Bramka jest WĄSKA — dotyczy wyłącznie zamówień rozliczanych w MD, dokładnie
    tak, jak mówi ticket („dla osoby, która ma już aktywne zamówienie MD").
    Współistnienie zamówienia KOSZTOWEGO i okresowego u tej samej osoby jest
    wspieranym scenariuszem (dwa różne modele rozliczenia u jednego klienta)
    i nikt nie prosił o jego odebranie — po rozdzieleniu akcji „Zakończ"
    przestało być groźne.
    """

    line_ids = await open_group_line_ids(db, contract_id, md_only=True)
    if line_ids:
        raise _conflict(line_ids)


#: Tytuł-zaślepka, którym hook zatrudnienia znaczy szkic „do uzupełnienia przez
#: Delivery" u klientów wielo-konsultantowych/kosztowych. Bramka aktywacji go
#: odrzuca, więc taki wiersz nigdy nie jest zamówieniem — jest zaproszeniem do
#: wpisania numeru.
AUTO_DRAFT_TITLE_PLACEHOLDER = "(bez numeru)"


async def absorb_auto_draft_shells(
    db: AsyncSession, contract_id: Optional[int]
) -> list[int]:
    """Usuń puste szkice-zaślepki, gdy osoba trafia na linię grupy.

    Kolejność zdarzeń, która robiła duplikaty: hook zatrudnienia zakłada szkic
    „(bez numeru)", a dopiero potem Delivery obsadza tę samą osobę na
    zamówieniu MD. Od tej chwili kontrakt niesie DWA zapisy tej samej
    współpracy — a wypowiedzenie z karty okresowej domyka oba.

    Kasujemy WYŁĄCZNIE wiersz, który na pewno niczego nie niesie: szkic bez
    pliku PO, bez budżetu MD i bez śladu uzupełniania, z tytułem-zaślepką.
    Każdy inny (uzupełniony numer, wgrany PDF, historia) zostaje — usunięcie
    szkicu kasuje też jego plik, a bywa on jedyną kopią dokumentu.

    Zwraca id usuniętych wierszy (do wpisu w audycie wołającego).
    """

    if contract_id is None:
        return []
    result = await db.execute(
        select(ClientOrder).where(
            ClientOrder.contract_id == contract_id,
            ClientOrder.order_group_id.is_(None),
            ClientOrder.status == ClientOrderStatus.draft,
            ClientOrder.title == AUTO_DRAFT_TITLE_PLACEHOLDER,
            ClientOrder.file_path.is_(None),
            ClientOrder.md_total.is_(None),
            ClientOrder.filled_at.is_(None),
        )
    )
    removed: list[int] = []
    for order in result.scalars().all():
        removed.append(order.id)
        await db.delete(order)
    return removed
