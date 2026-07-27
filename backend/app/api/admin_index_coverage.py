"""GET /api/admin/index-coverage — ilu kandydatów jest realnie wyszukiwalnych.

Audyt gotowości (2026-07-27) postawił wymaganie: każdy aktywny kandydat i każda
otwarta oferta ma stan ``indexed`` albo jawnie ``excluded``, zero cichych
pominięć. Nie dało się tego sprawdzić — jedyny sposób na policzenie luki był
ręczny: zapytanie do produkcyjnej bazy plus osobne zapytanie do Qdranta i
odjęcie liczb od siebie. Zmierzone tak 2026-07-27: **46 945 z 55 217**
kandydatów, czyli **8 272 osoby istnieją w bazie i nie istnieją w matchingu**.

Rekord bez wektora nie jest „gorzej dopasowany" — on po prostu nie bierze
udziału. Rekomendacje, hybrid search i skan Marketplace czytają identyfikatory
z Qdranta, więc kandydat spoza kolekcji nie pojawi się w żadnym z nich, a
rekruter nie ma jak zauważyć, że kogoś brakuje: lista kandydatów pokazuje go
normalnie.

Endpoint jest read-only i celowo NIE naprawia niczego — liczy. Backfill
(``scripts/reembed_collections.py``) i worker kolejki to osobne decyzje, bo
obie kosztują wywołania Voyage'a.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_snapshot import _snapshot_auth
from app.core.database import get_db
from app.models.candidate import Candidate, CandidateStatus
from app.models.index_outbox import IndexOutboxEvent
from app.models.job import Job

logger = logging.getLogger(__name__)
router = APIRouter()

_QDRANT_TIMEOUT_SECONDS = 5.0


async def _collection_points(collection: str) -> int | None:
    """Liczba punktów w kolekcji Qdrant; ``None`` gdy niedostępna.

    ``None`` znaczy „nie wiem", i tak jest raportowane. Zwrócenie 0 przy
    padniętym Qdrancie pokazałoby 100% luki i wywołało panikę zamiast diagnozy.
    """
    try:
        from app.services.embedding_service import _get_qdrant_client

        client = _get_qdrant_client()
        if client is None:
            return None
        info = await asyncio.wait_for(
            asyncio.to_thread(client.get_collection, collection),
            timeout=_QDRANT_TIMEOUT_SECONDS,
        )
        return int(getattr(info, "points_count", 0) or 0)
    except Exception as exc:  # noqa: BLE001 — diagnostics must not 500
        logger.warning("index-coverage: collection %s unreadable: %s", collection, exc)
        return None


def _gap(total: int, indexed: int | None) -> dict[str, Any]:
    if indexed is None:
        return {"total": total, "indexed": None, "missing": None, "coverage_pct": None}
    missing = max(0, total - indexed)
    pct = round(100.0 * indexed / total, 1) if total else 100.0
    return {
        "total": total,
        "indexed": indexed,
        "missing": missing,
        "coverage_pct": pct,
    }


@router.get("/index-coverage")
async def index_coverage(
    auth_mode: str = Depends(_snapshot_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Pokrycie indeksu semantycznego + zaległości kolejki reindeksu."""
    # Dwie liczby, bo odpowiadają na różne pytania i mylenie ich daje bzdury.
    # Kolekcja Qdranta trzyma punkty również dla kandydatów zablokowanych po
    # zaindeksowaniu (nic ich stamtąd nie usuwa), więc porównanie
    # `points / active` potrafiło dać pokrycie powyżej 100% i wyglądać jak błąd
    # pomiaru. Mianownikiem jest całość, a `active` zostaje jako kontekst
    # „ilu z nich ma się realnie wyszukiwać".
    candidates_total = (await db.scalar(select(func.count(Candidate.id)))) or 0
    candidates_active = (
        await db.scalar(
            select(func.count(Candidate.id)).where(
                Candidate.status != CandidateStatus.blacklisted
            )
        )
    ) or 0
    jobs_total = (await db.scalar(select(func.count(Job.id)))) or 0

    # Nazwy kolekcji z konfiguracji, nie zahardkodowane — inaczej raport
    # pokazywałby 0 na środowisku z własnym prefiksem i wyglądałby jak awaria.
    from app.services.embedding_service import (
        candidates_collection_name,
        jobs_collection_name,
    )

    candidate_points, job_points = await asyncio.gather(
        _collection_points(candidates_collection_name()),
        _collection_points(jobs_collection_name()),
    )

    # Zaległości kolejki. `pending` rośnie, gdy intencje są zapisywane, ale
    # worker jest wyłączony — to stan oczekiwany po wdrożeniu, nie awaria.
    # `dead` to przeciwieństwo: wiersze, które worker próbował i odpuścił.
    outbox_rows = await db.execute(
        select(IndexOutboxEvent.status, func.count(IndexOutboxEvent.id)).group_by(
            IndexOutboxEvent.status
        )
    )
    outbox = {status: count for status, count in outbox_rows}

    return {
        "auth_mode": auth_mode,
        "candidates": {
            **_gap(candidates_total, candidate_points),
            "active": candidates_active,
        },
        "jobs": _gap(jobs_total, job_points),
        "outbox": {
            "pending": outbox.get("pending", 0),
            "failed": outbox.get("failed", 0),
            "dead": outbox.get("dead", 0),
            "done": outbox.get("done", 0),
        },
    }
