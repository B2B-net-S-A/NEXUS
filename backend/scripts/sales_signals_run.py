#!/usr/bin/env python3
"""Jeden bieg bota researchu na żądanie: próba kanału przed włączeniem flagi.

Zakłada bieg i wywołuje webhook bota (``GROK_BOT_WEBHOOK_URL`` i ``_KEY`` muszą być
ustawione) także przy wyłączonym ``SALES_SIGNALS_ENABLED``, bo właśnie próba ma
pokazać, czy rutyna bota sama odeśle raport. Ekrany pokażą wynik dopiero po
włączeniu flagi; stan biegu widać w ``sales_signal_runs``.

Rodzaj to dowolny wpis rejestru zadań bota (``services/sales/bot_tasks``).
Rodzaje inne niż ``signals`` i ``briefing`` startują dopiero przy włączonym
``SALES_BOT_TASKS_ENABLED``; ``--request`` to pola zlecenia sprawdzane modelem rodzaju.

Uruchomienie (z ``backend/``)::

    python -m scripts.sales_signals_run --kind signals --company-ids 12,34,56
    python -m scripts.sales_signals_run --kind briefing --company-ids 12
    python -m scripts.sales_signals_run --kind briefing --mode call_hook --company-ids 12
    python -m scripts.sales_signals_run --kind <rodzaj> --request '{"pole": 1}'

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
from app.services.sales import bot_tasks, signal_targets, signals

MAX_TRIAL_FIRMS = 20


def _ids(value: str) -> list[int]:
    ids = [int(part) for part in value.split(",") if part.strip()]
    if not ids or len(ids) > MAX_TRIAL_FIRMS:
        raise argparse.ArgumentTypeError(
            f"Od 1 do {MAX_TRIAL_FIRMS} identyfikatorów firm."
        )
    return ids


def _request(value: str) -> dict[str, object]:
    try:
        data = json.loads(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--request musi być obiektem JSON.") from exc
    if not isinstance(data, dict):
        raise argparse.ArgumentTypeError("--request musi być obiektem JSON.")
    return data


#: Tryby punktów z 0684 do próby przed włączeniem ``SALES_BOT_TASKS_ENABLED``.
TRIAL_MODES = ("call_hook", "meeting_prep")


async def run(
    kind: str,
    company_ids: list[int],
    request: Optional[dict[str, object]] = None,
    mode: Optional[str] = None,
) -> dict[str, object]:
    try:
        async with AsyncSessionLocal() as db:
            now = datetime.now(timezone.utc)
            modes = (
                await signal_targets.modes_for(db, company_ids, now=now)
                if kind == "briefing"
                else None
            )
            if modes is not None and mode is not None:
                # Teczka mówi botowi, z kim to pierwsze spotkanie (jak pętla o 16:00).
                if mode == "meeting_prep" and request is None:
                    request = {
                        "first_meeting": sorted(
                            cid for cid, m in modes.items() if m == "first_call"
                        )
                    }
                modes = {cid: mode for cid in modes}
            started = await signals.start_run(
                db, kind, company_ids, now=now, modes=modes, request=request
            )
            if started is None:
                return {
                    "started": False,
                    "reason": "brak firm albo adresu bota"
                    if bot_tasks.allowed_to_start(kind)
                    else "rodzaj czeka na SALES_BOT_TASKS_ENABLED",
                }
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
    parser.add_argument("--kind", choices=sorted(bot_tasks.REGISTRY), default="signals")
    parser.add_argument("--company-ids", type=_ids, default=[])
    parser.add_argument("--request", type=_request, default=None)
    parser.add_argument("--mode", choices=TRIAL_MODES, default=None)
    args = parser.parse_args(argv)
    if args.mode and args.kind != "briefing":
        parser.error("--mode tylko z --kind briefing.")
    task = bot_tasks.REGISTRY[args.kind]
    if task.needs_firms and not args.company_ids:
        parser.error(f"Rodzaj {args.kind} wymaga --company-ids.")
    try:
        task.validate_request(args.request)
    except ValueError as exc:
        # Sam rodzaj błędu: treść zlecenia nie idzie do logu.
        parser.error(f"Niepoprawne --request ({type(exc).__name__}).")
    if not signals.configured():
        print("Brak GROK_BOT_WEBHOOK_URL albo GROK_BOT_WEBHOOK_KEY.", file=sys.stderr)
        return 2
    result = asyncio.run(run(args.kind, args.company_ids, args.request, args.mode))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") == "started" else 1


if __name__ == "__main__":
    sys.exit(main())
