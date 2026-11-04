#!/usr/bin/env python3
"""Czy ranking na stagingu liczy to samo co na produkcji. Tylko odczyt.

Wnioski ze stagingu idą do decyzji Artura. 02.11.2026 raport o wysłanych
i pomiar #2882 policzono bez trzech flag z produkcji (wyniki różniły się do
22 pkt), a Qdrant był o 10 dni starszy od bazy. Nikt tego nie widział, bo
staging działa wtedy zupełnie normalnie.

Dwa sprawdzenia:

- stempel ``ranker_version`` procesu wobec ostatniego automatycznego przeglądu
  z kopii. Te przeglądy liczyła produkcja, bo pętla na stagingu stoi;
- ile osób ma w Qdrancie wektor z innej treści niż dziś w bazie. Dla pełnej
  oceny to ``stale``, czyli osoba wypada z rankingu.

Kod wyjścia 0 = zgodnie, 1 = rozjazd, 2 = nie staging. Wołane z
``scripts/staging/refresh_code.sh``, ręcznie w kontenerze backendu stagingu::

    docker exec nexus-staging-backend-1 python -m scripts.staging_ranking_parity
"""

from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine
from app.models.candidate_search_run import CandidateSearchRun
from app.services import candidate_search_store as store
from app.services.auto_full_review import current_review_versions
from scripts.reembed_collections import DEFAULT_MAX_BATCH_CHARS, _reembed_candidates

# Kilka osób różni się zawsze: edycje na stagingu i wiersze bez tekstu. Nowa
# kopia bazy bez wyrównania Qdranta to tysiące.
MAX_STALE = 50
SYNC_COMMAND = (
    "docker exec nexus-staging-backend-1 python -m scripts.reembed_collections "
    "--target candidates --resume --commit"
)


def parity_warnings(
    current: str, copy_stamp: str | None, stale: int, *, max_stale: int = MAX_STALE
) -> list[str]:
    """Teksty ostrzeżeń; pusta lista = staging punktuje jak produkcja."""
    warnings = []
    if copy_stamp is None:
        warnings.append("Kopia nie ma automatycznego przeglądu ze stemplem rankingu.")
    elif current != copy_stamp:
        warnings.append(
            f"ranker_version {current} różni się od ostatniego przeglądu z kopii "
            f"{copy_stamp}. Sprawdź flagi z _SCORING_CACHE_INPUTS w "
            "docker-compose.staging.yml albo zmianę kontraktu w kodzie."
        )
    if stale > max_stale:
        warnings.append(
            f"{stale} osób ma w Qdrancie wektor z innej treści niż w bazie. "
            f"Wyrównanie: {SYNC_COMMAND}"
        )
    return warnings


async def _latest_review_stamp() -> str | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CandidateSearchRun.version_trace["ranker_version"].astext)
            .where(
                store.auto_origin_clause(),
                CandidateSearchRun.state.in_(("complete", "partial")),
                CandidateSearchRun.version_trace["ranker_version"].astext.is_not(None),
            )
            .order_by(CandidateSearchRun.completed_at.desc().nulls_last())
            .limit(1)
        )


async def _stale_people() -> int:
    processed, current, blank = await _reembed_candidates(
        commit=False,
        batch=128,
        limit=None,
        log_every=10**9,
        max_batch_chars=DEFAULT_MAX_BATCH_CHARS,
        resume=True,
        estimate=True,
    )
    return processed - current - blank


async def main() -> int:
    if os.environ.get("NEXUS_ENV") != "staging":
        print("To sprawdzenie działa tylko na stagingu.", file=sys.stderr)
        return 2
    try:
        current = current_review_versions()["ranker_version"]
        copy_stamp = await _latest_review_stamp()
        stale = await _stale_people()
    finally:
        await engine.dispose()
    warnings = parity_warnings(current, copy_stamp, stale)
    print(f"ranker_version={current} kopia={copy_stamp} stale={stale}")
    for warning in warnings:
        print(f"UWAGA: {warning}", file=sys.stderr)
    return 1 if warnings else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
