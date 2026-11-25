"""Orzecznictwo dla asystenta prawnego: ``GET /api/legal/cases/search`` (część C).

Bramka: sekcja Delivery i uprawnienie „Klienci, kontrakty i zamówienia:
podgląd” (``DeliveryViewUser``) — asystent pracuje przy kontraktach B2B,
a orzeczenia to dane publiczne bez kwot i bez danych osób z NEXUSA. Sesja
scalająca wyrównuje bramkę z routerem ``/api/legal`` fundamentu (część A),
jeśli ten wybierze inną. Reguła:
``docs/claude/asystent-prawny/orzecznictwo-i-interpretacje.md``.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.permission_access import DeliveryViewUser
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.services.legal_case_law import links, schema, search

router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)

CourtValue = Literal[schema.COURT_TYPES]  # type: ignore[valid-type]


@router.get("/cases/search")
async def search_cases(
    _user: DeliveryViewUser,
    q: str = Query(..., min_length=2, max_length=300),
    courts: Optional[list[CourtValue]] = Query(None),
    since: Optional[date] = Query(None),
    limit: int = Query(5, ge=1, le=search.MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    outcome = await search.search_case_law_outcome(
        db, q, courts=courts, since=since, limit=limit
    )
    return {
        "items": [
            {
                "kind": passage.kind,
                "ref": passage.ref,
                "label": passage.label,
                "text": passage.text,
                "url": passage.url,
            }
            for passage in outcome.passages
        ],
        "retrieval": outcome.retrieval,
        # Źródła bez API: sam link do wyszukiwarki (reguła, ``links.py``).
        "links": [
            {"source": link.source, "label": link.label, "url": link.url, "note": link.note}
            for link in links.search_links(search.normalize_courts(courts))
        ],
    }
