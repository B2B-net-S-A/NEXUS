"""Historia zmian szansy — zapis zdarzeń do ``sales_opportunity_events``.

Jak „Historia zmian” deala w Atlasie (``src/services/audit_log.py``): kto,
kiedy, które pole, stara i nowa wartość. Wywołujący robi zdjęcie pól przed
zmianą (``snapshot``), a po niej ``record_changes`` dopisuje po wierszu na
każde pole, które się naprawdę zmieniło. Zapis idzie w tej samej transakcji
co zmiana — commit robi wywołujący. Import z Atlasa tego modułu nie woła.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import SalesOpportunity, SalesOpportunityEvent
from app.services.sales_schema import OpportunityEventKind

#: Pola, których zmiany widać w historii (etap i status zmienia tylko ``/move``).
TRACKED_FIELDS: tuple[str, ...] = (
    "title",
    "stage_id",
    "status",
    "lost_reason",
    "value",
    "mrr_value",
    "margin_pct",
    "owner_user_id",
    "expected_close_date",
)


def as_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        # 45000 i 45000.00 to ta sama kwota — bez zer po przecinku.
        return format(value.normalize(), "f")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def snapshot(opportunity: SalesOpportunity) -> dict[str, Optional[str]]:
    return {field: as_text(getattr(opportunity, field)) for field in TRACKED_FIELDS}


def record(
    db: AsyncSession,
    *,
    opportunity_id: int,
    user_id: Optional[int],
    kind: OpportunityEventKind,
    field: Optional[str] = None,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
) -> None:
    db.add(
        SalesOpportunityEvent(
            opportunity_id=opportunity_id,
            user_id=user_id,
            kind=kind.value,
            field=field,
            old_value=old_value,
            new_value=new_value,
        )
    )


def record_created(
    db: AsyncSession, opportunity: SalesOpportunity, *, user_id: Optional[int]
) -> None:
    """Założenie szansy = wejście na jej pierwszy etap (KPI liczy z tego wiersza)."""

    record(
        db,
        opportunity_id=opportunity.id,
        user_id=user_id,
        kind=OpportunityEventKind.created,
        field="stage_id",
        new_value=str(opportunity.stage_id),
    )


def record_changes(
    db: AsyncSession,
    opportunity: SalesOpportunity,
    before: dict[str, Optional[str]],
    *,
    user_id: Optional[int],
) -> int:
    """Dopisz po zdarzeniu na każde zmienione pole; zwraca ich liczbę."""

    after = snapshot(opportunity)
    changed = [field for field in TRACKED_FIELDS if before[field] != after[field]]
    for field in changed:
        record(
            db,
            opportunity_id=opportunity.id,
            user_id=user_id,
            kind=OpportunityEventKind.updated,
            field=field,
            old_value=before[field],
            new_value=after[field],
        )
    return len(changed)
