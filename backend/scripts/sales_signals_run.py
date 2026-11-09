#!/usr/bin/env python3
"""Jeden bieg bota researchu na żądanie: próba kanału przed włączeniem flagi.

Zakłada bieg i wywołuje webhook bota (``GROK_BOT_WEBHOOK_URL`` i ``_KEY`` muszą być
ustawione) także przy wyłączonym ``SALES_SIGNALS_ENABLED``, bo właśnie próba ma
pokazać, czy rutyna bota sama odeśle raport. Ekrany pokażą wynik dopiero po
włączeniu flagi; stan biegu widać w ``sales_signal_runs``.

Uruchomienie (z ``backend/``)::

    python -m scripts.sales_signals_run --kind signals --company-ids 12,34,56
    python -m scripts.sales_signals_run --kind briefing --company-ids 12

Wynik to same liczby i identyfikatory (logi są publiczne).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from typing import Optional, Sequence

from app.core.database import AsyncSessionLocal, engine
from app.services import sales_schema
from app.services.sales import signal_targets, signals

MAX_TRIAL_FIRMS = 20


def _ids(value: str) -> list[int]:
    ids = [int(part) for part in value.split(",") if part.strip()]
    if not ids or len(ids) > MAX_TRIAL_FIRMS:
        raise argparse.ArgumentTypeError(
            f"Od 1 do {MAX_TRIAL_FIRMS} identyfikatorów firm."
        )
    return ids


async def run(kind: str, company_ids: list[int]) -> dict[str, object]:
    try:
        async with AsyncSessionLocal() as db:
            now = datetime.now(timezone.utc)
            modes = (
                await signal_targets.modes_for(db, company_ids, now=now)
                if kind == "briefing"
                else None
            )
            started = await signals.start_run(
                db, kind, company_ids, now=now, modes=modes
            )
            if started is None:
                return {"started": False, "reason": "brak firm albo adresu bota"}
            return {
                "started": True,
                "run_id": started.id,
                "status": started.status,
                "error": started.error,
                "firms": len(started.company_ids),
            }
    finally:
        await engine.dispose()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Próbny bieg bota researchu")
    parser.add_argument(
        "--kind", choices=sales_schema.SIGNAL_RUN_KINDS, default="signals"
    )
    parser.add_argument("--company-ids", type=_ids, required=True)
    args = parser.parse_args(argv)
    if not signals.configured():
        print("Brak GROK_BOT_WEBHOOK_URL albo GROK_BOT_WEBHOOK_KEY.", file=sys.stderr)
        return 2
    result = asyncio.run(run(args.kind, args.company_ids))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") == "started" else 1


if __name__ == "__main__":
    sys.exit(main())
