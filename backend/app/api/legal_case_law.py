"""Orzecznictwo dla asystenta prawnego: ``GET /api/legal/cases/search`` (część C).

Bramka jak reszta ``/api/legal`` (fundament, część A): sekcja Sourcing
i Generator umów B2B (``B2BGeneratorAccess``) — asystent stoi w tle
Generatora i kontraktów, a każdy, kto pracuje na kontrakcie, ma Generator.
Orzeczenia to dane publiczne bez kwot i bez danych osób z NEXUSA. Reguła:
``docs/claude/asystent-prawny/orzecznictwo-i-interpretacje.md``.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contract_access import B2BGeneratorAccess
from app.api.section_access import SOURCING_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.services.legal_case_law import links, schema, search

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)

CourtValue = Literal[schema.COURT_TYPES]  # type: ignore[valid-type]


@router.get("/cases/search")
async def search_cases(
    _user: B2BGeneratorAccess,
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
            {
                "source": link.source,
                "label": link.label,
                "url": link.url,
                "note": link.note,
            }
            for link in links.search_links(search.normalize_courts(courts))
        ],
    }
