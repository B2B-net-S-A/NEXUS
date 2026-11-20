"""„Klient zamówił okres po zakończeniu” — konflikt do decyzji i blokada linii.

Decyzja Artura z 19.11.2026 (wariant „Konflikt do decyzji + blokada”) po
sprawdzeniu produkcji: na 82 kontraktach „Kończący się” i „Zakończony” dwa
miały żywe zamówienie po końcu projektu.

* Szkic z maila na okres po wypowiedzeniu. Bramka
  ``order_mail_signature.termination_allows`` celowo go nie aktywowała (mail
  nie cofa decyzji człowieka), ale nikt nie dostał o nim sygnału.
* Aktywna linia MD dopięta do umowy zlecenie po jej końcu. Zamówienie
  świadomie nie wskrzesza umowy nie-B2B z datą końca
  (``contract_lifecycle.sync_contract_to_live_order``), więc osoby nie było
  w aktywnych kontraktach ani w MRR.

Jedna reguła zasila kartę na stronie kontraktu, kubełek listy i dzwonek DL-a:

* kontrakt „Kończący się” albo „Zakończony”;
* koniec projektu = ``end_date``, a gdy jej brak — ``terminated_at``;
* zamówienie inne niż anulowane i zakończone, którego koniec jest pusty albo
  późniejszy od końca projektu.

Zakończone zamówienie po końcu projektu to rozliczona historia, nie decyzja,
więc karty nie daje.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional, Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.core.scheduling import business_today
from app.models.contract import Contract, ContractStatus, ContractType
from app.services.order_mail_signature import termination_allows

__all__ = [
    "CONFLICT_CONTRACT_STATUSES",
    "OrderAfterEnd",
    "attach_order_after_end",
    "ended_agreement_block",
    "open_order_after_end",
    "order_after_end_contracts",
    "order_after_end_message",
    "orders_after_end",
    "project_end",
]

CONFLICT_CONTRACT_STATUSES: tuple[ContractStatus, ...] = (
    ContractStatus.ending,
    ContractStatus.ended,
)
# Zamówienia, które już niczego nie wymagają: anulowane i rozliczone.
_SETTLED_ORDER_STATUSES: tuple[ClientOrderStatus, ...] = (
    ClientOrderStatus.cancelled,
    ClientOrderStatus.completed,
)

_AGREEMENT_LABELS = {
    ContractType.uzlecenie.value: "Umowa zlecenie",
    ContractType.uop.value: "Umowa o pracę",
}


def _value(raw: object) -> str:
    return str(getattr(raw, "value", raw))


def project_end(contract: Contract) -> Optional[date]:
    """Koniec projektu: data końca umowy, a bez niej data z okna zakończenia."""
    return contract.end_date or contract.terminated_at


def _project_end_column():
    return func.coalesce(Contract.end_date, Contract.terminated_at)


def _conflict_where() -> tuple:
    """Warunek konfliktu na złączeniu ``Contract`` ⋈ ``ClientOrder``."""
    end = _project_end_column()
    return (
        Contract.status.in_(CONFLICT_CONTRACT_STATUSES),
        end.is_not(None),
        ClientOrder.status.not_in(_SETTLED_ORDER_STATUSES),
        or_(ClientOrder.end_date.is_(None), ClientOrder.end_date > end),
    )


def order_after_end_contracts():
    """Podzapytanie: kontrakty z co najmniej jednym zamówieniem po końcu projektu."""
    return (
        select(Contract.id)
        .join(ClientOrder, ClientOrder.contract_id == Contract.id)
        .where(*_conflict_where())
    )


@dataclass(frozen=True)
class OrderAfterEnd:
    """Jedno zamówienie, które klient złożył na okres po końcu współpracy."""

    contract_id: int
    order_id: int
    client_id: int
    order_group_id: Optional[int]
    # Numer zamówienia: przy linii zamówienia zbiorczego numer grupy, bo tytuł
    # linii niesie nazwisko osoby.
    order_number: Optional[str]
    status: str
    start_date: Optional[date]
    end_date: Optional[date]
    # Szkic, którego wypowiedzenie nie pozwala aktywować
    # (``termination_allows``): automat poczty zostawił go do decyzji.
    held_by_termination: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "order_id": self.order_id,
            "client_id": self.client_id,
            "order_group_id": self.order_group_id,
            "order_number": self.order_number,
            "status": self.status,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "held_by_termination": self.held_by_termination,
        }


def _sort_key(item: OrderAfterEnd) -> tuple:
    return (item.start_date or date.max, item.order_id)


async def _load(db: AsyncSession, *conditions: Any) -> list[OrderAfterEnd]:
    rows = (
        await db.execute(
            select(Contract, ClientOrder, ClientOrderGroup.order_number)
            .join(ClientOrder, ClientOrder.contract_id == Contract.id)
            .outerjoin(
                ClientOrderGroup, ClientOrderGroup.id == ClientOrder.order_group_id
            )
            .where(*_conflict_where(), *conditions)
        )
    ).all()
    found = []
    for contract, order, group_number in rows:
        status = _value(order.status)
        held = status == ClientOrderStatus.draft.value and not termination_allows(
            contract, order_start=order.start_date, order_end=order.end_date
        )
        found.append(
            OrderAfterEnd(
                contract_id=contract.id,
                order_id=order.id,
                client_id=order.client_id,
                order_group_id=order.order_group_id,
                order_number=(group_number or order.title or None),
                status=status,
                start_date=order.start_date,
                end_date=order.end_date,
                held_by_termination=held,
            )
        )
    return sorted(found, key=_sort_key)


async def orders_after_end(db: AsyncSession, contract_id: int) -> list[OrderAfterEnd]:
    """Zamówienia po końcu projektu jednego kontraktu (karta „Co się dzieje”)."""
    return await _load(db, Contract.id == contract_id)


async def open_order_after_end(db: AsyncSession) -> list[OrderAfterEnd]:
    """Wszystkie otwarte konflikty — dla dzwonka Delivery Leada."""
    return await _load(db)


async def attach_order_after_end(db: AsyncSession, items: Sequence[Any]) -> None:
    """Wpisz w wiersze listy pierwsze zamówienie po końcu projektu.

    Wiersz zgrupowany po osobie sprawdza też pozostałe umowy tej osoby
    (``group_members``): konflikt na zakończonej umowie nie może zniknąć
    tylko dlatego, że wiersz prowadzi umowa żywsza.
    """
    owners: dict[int, Any] = {}
    for item in items:
        item_id = getattr(item, "id", None)
        if item_id is not None:
            owners.setdefault(item_id, item)
        for member in getattr(item, "group_members", None) or []:
            member_id = getattr(member, "id", None)
            if member_id is not None:
                owners.setdefault(member_id, item)
    if not owners:
        return
    conflicts = await _load(db, Contract.id.in_(list(owners)))
    by_item: dict[int, list[OrderAfterEnd]] = {}
    for conflict in conflicts:
        item = owners[conflict.contract_id]
        by_item.setdefault(id(item), []).append(conflict)
    for item in {id(item): item for item in owners.values()}.values():
        found = by_item.get(id(item))
        if not found:
            continue
        first = found[0]
        item.order_after_end = {
            "contract_id": first.contract_id,
            "order_id": first.order_id,
            "status": first.status,
            "start_date": first.start_date.isoformat() if first.start_date else None,
            "end_date": first.end_date.isoformat() if first.end_date else None,
            "count": len(found),
        }


def _pl_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def order_after_end_message(contract: Contract, conflict: OrderAfterEnd) -> str:
    """Treść dzwonka Delivery Leada: co klient zamówił i jaka decyzja czeka."""
    number = f" {conflict.order_number}" if conflict.order_number else ""
    is_draft = conflict.status == ClientOrderStatus.draft.value
    if conflict.order_group_id is not None:
        what = f"linia zamówienia zbiorczego{number}"
    elif is_draft:
        what = f"szkic zamówienia{number}"
    else:
        what = f"zamówienie{number}"
    if conflict.start_date and conflict.end_date:
        period = f"{_pl_date(conflict.start_date)}–{_pl_date(conflict.end_date)}"
    elif conflict.start_date:
        period = f"od {_pl_date(conflict.start_date)} bez daty końca"
    else:
        period = "bez dat"
    end = project_end(contract)
    ended = _value(contract.status) == ContractStatus.ended.value
    if end is None:
        when = "Współpraca jest zakończona"
    elif ended:
        when = f"Współpraca zakończyła się {_pl_date(end)}"
    else:
        when = f"Współpraca kończy się {_pl_date(end)}"
    parts = [f"{when}, a {what} obejmuje {period}."]
    if conflict.held_by_termination:
        parts.append(
            "NEXUS nie aktywuje go sam, bo zakończenie współpracy to decyzja człowieka."
        )
    label = _AGREEMENT_LABELS.get(_value(contract.contract_type))
    exits = ["cofnij zakończenie", "przypisz zamówienie innej osobie"]
    if is_draft and conflict.order_group_id is None:
        exits.append("anuluj szkic")
    if label is not None:
        exits[0] = "przedłuż umowę aneksem"
    parts.append(
        "Zdecyduj na karcie kontraktu: " + ", ".join(exits[:-1]) + f" albo {exits[-1]}."
    )
    return " ".join(parts)


def ended_agreement_block(
    contract: Contract,
    *,
    line_start: Optional[date],
    today: Optional[date] = None,
) -> Optional[str]:
    """Powód odmowy żywej linii zamówienia zbiorczego na zakończonej umowie nie-B2B.

    Umowa zlecenie i umowa o pracę mają datę końca w treści umowy, a zamówienie
    jej nie zeruje — linia dopięta po końcu pracowałaby na umowie, której nie
    ma (osoby nie ma w aktywnych kontraktach ani w MRR). Odmowa dotyczy umowy
    „Zakończonej” i umowy, której data końca wypada przed startem linii. Umowa
    B2B wraca sama (powrót po przerwie), więc jej to nie dotyczy. Data końca
    z przyszłości daje „kończy się”, bo umowa jeszcze trwa.
    """
    label = _AGREEMENT_LABELS.get(_value(contract.contract_type))
    if label is None:
        return None
    ended = _value(contract.status) == ContractStatus.ended.value
    before_line = (
        contract.end_date is not None
        and line_start is not None
        and contract.end_date < line_start
    )
    if not (ended or before_line):
        return None
    end = project_end(contract)
    remedy = "przedłuż ją aneksem albo załóż nowy kontrakt"
    if end is None:
        return f"{label} jest zakończona — {remedy}"
    verb = "kończy się" if end >= (today or business_today()) else "zakończyła się"
    return f"{label} {verb} {_pl_date(end)} — {remedy}"
