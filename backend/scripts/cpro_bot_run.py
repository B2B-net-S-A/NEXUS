#!/usr/bin/env python3
"""Próba bota Cpro przed włączeniem flagi: kolejka, braki i jeden bieg.

Bez ``--start`` skrypt tylko pokazuje kolejkę Cpro tak, jak widzi ją bot:
karta, rekrutacja (numer requestu), braki albo „gotowa”, skąd dane. Nic nie
wysyła — tak sprawdzisz kolejkę na produkcji przed włączeniem.

``--start --stage-ids <id>`` zleca bieg na wskazane karty także przy
wyłączonym ``CPRO_BOT_ENABLED``. Domyślnie to PRÓBA: bot wypełnia ofertę
i zostawia ją jako szkic (DRAFT) w Cpro, nic nie idzie do Nordei. ``--submit``
wysyła naprawdę (Submit Offer) i przesuwa kartę na „Wysłane do Cpro”.

Uruchomienie (z ``backend/``)::

    python -m scripts.cpro_bot_run
    python -m scripts.cpro_bot_run --start --stage-ids 123456
    python -m scripts.cpro_bot_run --start --stage-ids 123456 --submit

Wynik to identyfikatory, liczby i braki, bez nazwisk i stawek (logi są publiczne).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from typing import Optional, Sequence

from app.core.database import AsyncSessionLocal, engine
from app.core.scheduling import business_date
from app.services.cpro_bot import flow, runs
from app.services.cpro_bot import items as bot_items


def _ids(value: str) -> list[int]:
    try:
        return [int(part) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--stage-ids: liczby po przecinku.") from exc


async def show() -> dict[str, object]:
    try:
        async with AsyncSessionLocal() as db:
            now = datetime.now(timezone.utc)
            queue = await bot_items.load_items(db, now=now, today=business_date(now))
            states = await runs.item_states(db, [i.stage_id for i in queue], now=now)
            return {
                "items": [
                    {
                        "stage_id": item.stage_id,
                        "job_id": item.job_id,
                        "request": (item.payload or {}).get("request_number"),
                        "ready": item.payload is not None,
                        "blockers": list(item.blockers),
                        "data_from": list(item.data_from),
                        "bot_state": states[item.stage_id].state
                        if item.stage_id in states
                        else None,
                    }
                    for item in queue
                ],
            }
    finally:
        await engine.dispose()


async def start(stage_ids: list[int], submit: bool) -> dict[str, object]:
    try:
        async with AsyncSessionLocal() as db:
            now = datetime.now(timezone.utc)
            try:
                run = await flow.start_chosen(
                    db, stage_ids, now=now, today=business_date(now), submit=submit
                )
            except flow.NotReady as exc:
                return {"started": False, "reason": exc.detail}
            return {
                "started": True,
                "run_id": run.id,
                "status": run.status,
                "submit": run.submit,
                "error": run.error,
                "items": len(run.stage_ids or []),
            }
    finally:
        await engine.dispose()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Próba bota Cpro")
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--stage-ids", type=_ids, default=[])
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args(argv)
    if not args.start:
        print(json.dumps(asyncio.run(show()), ensure_ascii=False, indent=1))
        return 0
    if not args.stage_ids:
        parser.error("--start wymaga --stage-ids.")
    if not runs.configured():
        print("Brak GROK_BOT_CPRO_WEBHOOK_URL albo _KEY.", file=sys.stderr)
        return 2
    result = asyncio.run(start(args.stage_ids, args.submit))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") in ("started", "received") else 1


if __name__ == "__main__":
    sys.exit(main())
