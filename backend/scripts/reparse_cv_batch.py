"""Ponowny odczyt CV starej bazy pełnym promptem przez Message Batches API — CLI.

Decyzja Artura z 07.11.2026 (Haiku 5.5 + Batch API, wszyscy bez osi
technologii). Bieg płatny tylko z `run`; zgoda Artura przed pierwszym `run`
na produkcji. Osobny proces (nie pętla w webie), np. `docker exec`:

    # zakres i szacunek kosztu: zero AI, zero zapisów
    python -m scripts.reparse_cv_batch count

    # pierwsza paczka na próbę, potem całość (wznawialne: zakres sam maleje)
    python -m scripts.reparse_cv_batch run --limit 200
    python -m scripts.reparse_cv_batch run

    # proces przerwany w trakcie paczki — wyniki tej paczki (id z logu)
    python -m scripts.reparse_cv_batch collect --batch-id msgbatch_...

`--include-with-axis` dokłada osoby, które mają już oś z odczytu v7/v8, ale
nie mają pól v9. `--until-id` / `--after-id` dzielą bazę na zakresy.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.core.database import AsyncSessionLocal  # noqa: E402
from app.services import cv_reparse_batch as reparse  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("reparse_cv_batch")


def _client():
    import anthropic

    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, max_retries=3)


async def _prepare() -> None:
    # Filtr technologii bez śladu w CV nie działa bez mapy aliasów, a tę
    # ładuje dopiero lifespan aplikacji (`parser-cv-technologie-bez-sladu-w-cv.md`).
    from app.services.skill_taxonomy_loader import refresh_alias_map

    await refresh_alias_map()


async def _count(args: argparse.Namespace) -> None:
    async with AsyncSessionLocal() as db:
        n = await reparse.count_scope(db, include_with_axis=args.include_with_axis)
    logger.info(
        "zakres: %s osób, model %s, szacunek %.0f USD (Batch API)",
        f"{n:,}",
        reparse.bulk_model(),
        n * reparse.EST_USD_PER_CV,
    )


async def _collect(
    client, batch_id: str, model: str, stats: reparse.ReparseStats
) -> None:
    # Całość w wątku, przed zapisem: `results()` to leniwy strumień JSONL, a
    # zapis 2000 wierszy trwa dziesiątki minut — zerwany strumień zabijałby bieg.
    results = await asyncio.to_thread(
        lambda: list(client.messages.batches.results(batch_id))
    )
    async with AsyncSessionLocal() as db:
        await reparse.apply_batch_results(db, results, model=model, stats=stats)


async def _run(args: argparse.Namespace) -> None:
    await _prepare()
    client = _client()
    model = reparse.bulk_model()
    stats = reparse.ReparseStats()
    cursor = args.after_id
    while args.limit is None or stats.submitted < args.limit:
        size = (
            args.chunk
            if args.limit is None
            else min(args.chunk, args.limit - stats.submitted)
        )
        async with AsyncSessionLocal() as db:
            rows = await reparse.pick_chunk(
                db,
                after_id=cursor,
                until_id=args.until_id,
                size=size,
                include_with_axis=args.include_with_axis,
            )
        if not rows:
            break
        cursor = rows[-1][0]
        requests = reparse.build_requests(rows, model=model)
        batch = await asyncio.to_thread(
            client.messages.batches.create, requests=requests
        )
        stats.submitted += len(requests)
        stats.batch_ids.append(batch.id)
        logger.info(
            "paczka %s: %s CV (id %s–%s), wznowienie: collect --batch-id %s; dalej --after-id %s",
            batch.id,
            len(requests),
            rows[0][0],
            cursor,
            batch.id,
            cursor,
        )
        await reparse.wait_for_batch(client, batch.id, poll_s=args.poll)
        await _collect(client, batch.id, model, stats)
        logger.info("%s", json.dumps(stats.as_dict(), ensure_ascii=False))
    logger.info("=== KONIEC === %s", json.dumps(stats.as_dict(), ensure_ascii=False))


async def _collect_cmd(args: argparse.Namespace) -> None:
    await _prepare()
    client = _client()
    stats = reparse.ReparseStats(batch_ids=[args.batch_id])
    await reparse.wait_for_batch(client, args.batch_id, poll_s=args.poll)
    await _collect(client, args.batch_id, reparse.bulk_model(), stats)
    logger.info("=== KONIEC === %s", json.dumps(stats.as_dict(), ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("count", "run"):
        p = sub.add_parser(name)
        p.add_argument("--include-with-axis", action="store_true")
        if name == "run":
            p.add_argument("--limit", type=int, default=None)
            p.add_argument("--chunk", type=int, default=2000)
            p.add_argument("--after-id", type=int, default=0)
            p.add_argument("--until-id", type=int, default=None)
            p.add_argument("--poll", type=float, default=60.0)
    p = sub.add_parser("collect")
    p.add_argument("--batch-id", required=True)
    p.add_argument("--poll", type=float, default=60.0)
    args = parser.parse_args()
    handler = {"count": _count, "run": _run, "collect": _collect_cmd}[args.command]
    asyncio.run(handler(args))


if __name__ == "__main__":
    main()
