"""Fast inventory of SQL rows, index points and durable indexing backlog.

Aggregate point counts do not establish candidate coverage or marker drift.
Missing/stale/orphan identities require the complete read-only reconciliation
in scripts.audit_candidate_index. Until then coverage measurements stay null.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_snapshot import _snapshot_auth
from app.core.database import get_db
from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_search_run import CandidateSearchRun
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


async def _candidate_search_storage(db: AsyncSession) -> dict[str, Any]:
    """Rozmiar pełnego przeglądu bazy — tanio, bez skanowania tabeli wyników.

    Każdy przegląd dopisuje wiersz na każdego kandydata, więc to jest pomiar,
    po którym widać, czy retencja (7 dni + najnowszy przegląd na autora
    i rekrutację) trzyma rozmiar w ryzach. `pg_class.reltuples` to ESTYMATA
    z ostatniego ANALYZE/VACUUM; -1 znaczy „nigdy nie liczone" i jest
    raportowane jako `None`, nie jako zero.
    """
    storage = (
        await db.execute(
            text(
                "SELECT pg_total_relation_size(to_regclass('candidate_search_results'))"
                " AS bytes,"
                " pg_size_pretty(pg_total_relation_size("
                "to_regclass('candidate_search_results'))) AS pretty,"
                " (SELECT reltuples FROM pg_class"
                "  WHERE oid = to_regclass('candidate_search_results'))"
                " AS estimated_rows"
            )
        )
    ).one()
    runs = await db.execute(
        select(CandidateSearchRun.state, func.count(CandidateSearchRun.id)).group_by(
            CandidateSearchRun.state
        )
    )
    total, estimated = storage.bytes, storage.estimated_rows
    # Nocne przeglądy automatyczne (21.09.2026): ile ich leży i ile zajmują.
    # Bajty to SZACUNEK proporcjonalny (udział wierszy w migawkach populacji
    # × rozmiar tabeli) — dokładny pomiar wymagałby skanu tabeli wyników.
    from app.services.candidate_search_store import auto_origin_clause

    auto = (
        await db.execute(
            select(
                func.count(CandidateSearchRun.id).filter(auto_origin_clause()),
                func.coalesce(
                    func.sum(CandidateSearchRun.population_size).filter(
                        auto_origin_clause()
                    ),
                    0,
                ),
                func.coalesce(func.sum(CandidateSearchRun.population_size), 0),
            )
        )
    ).one()
    auto_runs, auto_rows, all_rows = int(auto[0]), int(auto[1]), int(auto[2])
    return {
        "auto_runs": auto_runs,
        "auto_runs_rows": auto_rows,
        "auto_runs_estimated_bytes": (
            int(total * auto_rows / all_rows)
            if total is not None and all_rows > 0
            else None
        ),
        "results_total_bytes": int(total) if total is not None else None,
        "results_total_pretty": storage.pretty,
        "results_estimated_rows": (
            int(estimated) if estimated is not None and estimated >= 0 else None
        ),
        "runs_by_state": {state: count for state, count in runs},
    }


def _gap(total: int, indexed: int | None) -> dict[str, Any]:
    # A point may be orphaned, stale or missing while aggregate counts agree.
    # Exact coverage comes from the ID/content audit, not count subtraction.
    return {
        "total": total,
        "index_points": indexed,
        "indexed": None,
        "missing": None,
        "coverage_pct": None,
        "measurement": "index_unavailable"
        if indexed is None
        else "id_reconciliation_required",
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
    # Ile ofert MA ostemplowaną kolumnę. Endpoint zestawiał dotąd wiersze
    # Postgresa z `points_count` Qdranta i liczby wypełnionych kolumn NIE ZNAŁ,
    # więc na pytanie „jak duży jest dryf znacznika na produkcji" nie dało się
    # odpowiedzieć inaczej niż wejściem do bazy. Odczyt na KLASIE (wybór
    # wierszy), nie predykat na instancji — patrz `test_job_embedding_id_marker`.
    jobs_stamped = (
        await db.scalar(select(func.count(Job.id)).where(Job.embedding_id.is_not(None)))
    ) or 0

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
    candidate_search = await _candidate_search_storage(db)

    return {
        "auth_mode": auth_mode,
        "candidates": {
            **_gap(candidates_total, candidate_points),
            "active": candidates_active,
        },
        "jobs": {
            **_gap(jobs_total, job_points),
            # Marker count is known; point-minus-marker count is not drift.
            "stamped": jobs_stamped,
            "stamp_drift": None,
        },
        "outbox": {
            "pending": outbox.get("pending", 0),
            "failed": outbox.get("failed", 0),
            "dead": outbox.get("dead", 0),
            "done": outbox.get("done", 0),
        },
        "candidate_search": candidate_search,
    }
