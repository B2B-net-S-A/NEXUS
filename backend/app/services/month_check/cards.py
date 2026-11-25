"""Karta DL z kontroli miesiąca: sprawa danych bez kwot (0784).

Delivery Lead dostaje tylko to, co sam naprawia: faktura konsultanta albo
klienta za miesiąc, w którym osoba nie ma w NEXUSIE trwającego kontraktu
(``no_contract``) albo pozycji zamówienia (``no_order``). Kwot, numerów faktur
i pozostałych rozbieżności karta nie niesie (decyzja Artura 25.11.2026) —
to sprawy Finansów w „Przebiegu miesiąca”.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.month_check_case import MonthCheckCase
from app.services.month_check import rules, service


@dataclass(frozen=True)
class DataCard:
    case_id: int
    kind: str
    client_id: int
    person: str
    month: str
    data_issue: str

    @property
    def entity_key(self) -> str:
        return f"month_check:{self.case_id}"

    @property
    def period_label(self) -> str:
        return f"{self.month[5:7]}.{self.month[:4]}"


async def open_data_cases(db: AsyncSession) -> list[DataCard]:
    rows = list(
        (
            await db.scalars(
                select(MonthCheckCase)
                .where(
                    MonthCheckCase.state.in_(service.OPEN_STATES),
                    MonthCheckCase.data_issue.is_not(None),
                    MonthCheckCase.client_id.is_not(None),
                )
                .order_by(MonthCheckCase.id)
            )
        ).all()
    )
    person, _ = await service.names(db, rows)
    return [
        DataCard(
            case_id=r.id,
            kind=r.kind,
            client_id=int(r.client_id),
            person=person.get(r.candidate_id, "osoba"),
            month=r.period_month,
            data_issue=str(r.data_issue),
        )
        for r in rows
    ]


def describe(card: DataCard, client_name: str) -> tuple[str, str]:
    who = (
        "Konsultant wystawił fakturę"
        if card.kind == rules.COST_WITHOUT_SALE
        else "Klient dostał fakturę"
    )
    if card.data_issue == rules.NO_CONTRACT:
        title = f"{client_name} — {card.person}: faktura bez kontraktu"
        message = (
            f"🧾 {who} za {card.period_label} za pracę {card.person}, a w NEXUSIE "
            "ta osoba nie ma w tym miesiącu trwającego kontraktu. Sprawdź datę "
            "końca kontraktu albo uzupełnij kontrakt."
        )
    else:
        title = f"{client_name} — {card.person}: faktura bez zamówienia"
        message = (
            f"🧾 {who} za {card.period_label} za pracę {card.person}, a w NEXUSIE "
            "ta osoba nie ma w tym miesiącu pozycji zamówienia. Dopisz pozycję "
            "albo sprawdź okres zamówienia."
        )
    return title, message
