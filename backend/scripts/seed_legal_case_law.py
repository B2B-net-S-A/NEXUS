#!/usr/bin/env python3
"""Wstępne zasilenie orzecznictwa asystenta prawnego z SAOS (część C).

Tematy i zapytania: ``app/services/legal_case_law/ingest.py`` (``TOPICS``).
Każde zapytanie: jedno wyszukiwanie SAOS i najwyżej ``--per-query`` pobrań
treści, najwyżej jedno zapytanie na sekundę. Ponowne uruchomienie dopisuje
nowe orzeczenia, odświeża zmienione i sumuje tematy. Na koniec liczy wektory
w Qdrancie (``nexus_legal_cases``), o ile działają Voyage i Qdrant.

Uruchomienie (z ``backend/``)::

    python -m scripts.seed_legal_case_law
    python -m scripts.seed_legal_case_law --topic penalty_reduction --per-query 5
    python -m scripts.seed_legal_case_law --no-vectors

Wynik to same liczby (logi są publiczne).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Optional, Sequence

from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal, engine
from app.models.legal_case_law import LegalCase
from app.services.legal_case_law import index, ingest, saos


async def run(
    topics: Sequence[str], per_query: int, vectors: bool
) -> dict[str, object]:
    chosen = [t for t in ingest.TOPICS if not topics or t.key in topics]
    reports = []
    try:
        async with saos.new_client() as client, AsyncSessionLocal() as db:
            for topic in chosen:
                report = await ingest.ingest_topic(db, client, topic, per_query=per_query)
                reports.append(report.__dict__)
            embedded = 0
            if vectors:
                embedded = await index.index_pending(db)
                await db.commit()
            total = await db.scalar(
                select(func.count()).select_from(LegalCase).where(LegalCase.source == "saos")
            )
            return {
                "topics": reports,
                "saos_requests": client.requests,
                "saos_errors": client.errors,
                "embedded": embedded,
                "stored_saos_total": int(total or 0),
            }
    finally:
        await engine.dispose()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument(
        "--topic",
        action="append",
        choices=[t.key for t in ingest.TOPICS],
        help="tylko ten temat (można powtórzyć)",
    )
    parser.add_argument("--per-query", type=int, default=8)
    parser.add_argument("--no-vectors", action="store_true")
    args = parser.parse_args(argv)
    result = asyncio.run(
        run(args.topic or [], max(1, min(args.per_query, 50)), not args.no_vectors)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
