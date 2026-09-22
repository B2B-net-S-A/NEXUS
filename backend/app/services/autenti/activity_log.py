"""Aktywności Autenti z kluczem zewnętrznym per ZDARZENIE (INT-09).

`activities` ma częściowy UNIQUE `(external_source, external_id)`. Do 09.2026
każde zdarzenie procesu (wysłanie, przypomnienie, podpis, odrzucenie,
wycofanie, wygaśnięcie) zapisywało `external_id = process_id`, więc DRUGIE
zdarzenie tego samego procesu wywracało commit webhooka (IntegrityError) —
podpis nigdy nie docierał do NEXUSA. Klucz to teraz `"{process_id}:{akcja}"`
(przypomnienia dostają jeszcze znacznik czasu, bo może ich być kilka), a zapis
pomija zdarzenie już zapisane — powtórka tego samego webhooka jest no-opem.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity

AUTENTI_SOURCE = "autenti"


def autenti_event_key(process_id: Any, action: str) -> Optional[str]:
    if process_id is None or str(process_id).strip() == "":
        return None
    return f"{process_id}:{action}"[:100]


def autenti_remind_key(process_id: Any, at: Optional[datetime] = None) -> Optional[str]:
    base = autenti_event_key(process_id, "signature_remind_sent")
    if base is None:
        return None
    stamp = (at or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S")
    return f"{base}:{stamp}"[:100]


async def add_autenti_activity(
    db: AsyncSession,
    *,
    process_id: Any,
    action: str,
    entity_type: str,
    entity_id: Optional[int],
    user_id: Optional[int],
    details: Optional[dict] = None,
    external_id: Optional[str] = None,
) -> Optional[Activity]:
    """Dodaje aktywność, chyba że to samo zdarzenie jest już zapisane.

    `entity_id` None (np. podpis bez kontraktu) = brak wpisu: kolumna jest
    NOT NULL, a wpis bez obiektu i tak nie miałby gdzie się pokazać.
    """
    if entity_id is None:
        return None
    key = external_id or autenti_event_key(process_id, action)
    if key is not None:
        exists = await db.scalar(
            select(Activity.id)
            .where(
                Activity.external_source == AUTENTI_SOURCE,
                Activity.external_id == key,
            )
            .limit(1)
        )
        if exists is not None:
            return None
    activity = Activity(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        user_id=user_id,
        external_source=AUTENTI_SOURCE,
        external_id=key,
        details=details if details is not None else {},
    )
    db.add(activity)
    return activity
