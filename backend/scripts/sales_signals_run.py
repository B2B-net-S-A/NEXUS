#!/usr/bin/env python3
"""Jeden bieg bota researchu na żądanie: próba kanału przed włączeniem flagi.

Zakłada bieg i wywołuje webhook bota (``GROK_BOT_WEBHOOK_URL`` i ``_KEY`` muszą być
ustawione) także przy wyłączonym ``SALES_SIGNALS_ENABLED``, bo właśnie próba ma
pokazać, czy rutyna bota sama odeśle raport. Ekrany pokażą wynik dopiero po
włączeniu flagi; stan biegu widać w ``sales_signal_runs``.

Rodzaj to dowolny wpis rejestru zadań bota (``services/sales/bot_tasks``).
Zadania wymagają właściwej flagi kanału. ``--request`` to pola zlecenia
sprawdzane modelem rodzaju. Dla Cognism ``--pilot`` wysyła następną partię
firm z tagiem pilota, najwyżej pięć w jednym biegu. Powtórz po przyjęciu raportu.

Uruchomienie (z ``backend/``)::

    python -m scripts.sales_signals_run --kind signals --company-ids 12,34,56
    python -m scripts.sales_signals_run --kind briefing --company-ids 12
    python -m scripts.sales_signals_run --kind briefing --mode call_hook --company-ids 12
    python -m scripts.sales_signals_run --kind people --pilot
    python -m scripts.sales_signals_run --kind people --company-ids 12,34
    python -m scripts.sales_signals_run --kind <rodzaj> --request '{"pole": 1}'

Wynik to same liczby i identyfikatory (logi są publiczne).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

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
    request: Optional[dict[str, Any]] = None,
    *,
    pilot: bool = False,
    mode: Optional[str] = None,
) -> dict[str, object]:
    try:
        async with AsyncSessionLocal() as db:
            now = datetime.now(timezone.utc)
            if kind == "people" and (request or {}).get("source") == "cognism":
                await signal_targets.lock_people_starts(db)
                now = datetime.now(timezone.utc)
                if await signal_targets.cognism_run_active(db, now=now):
                    return {"started": False, "reason": "bieg Cognism już trwa"}
                candidates = (
                    await signal_targets.pilot_company_ids(db) if pilot else company_ids
                )
                company_ids = await signal_targets.cognism_company_ids(
                    db, now=now, explicit_ids=candidates
                )
                employers = (request or {}).get("employers")
                if employers:
                    company_ids = [cid for cid in company_ids if cid in candidates]
                if not company_ids:
                    return {
                        "started": False,
                        "reason": "brak kwalifikujących się firm do wysłania",
                    }
                if employers:
                    selected = [
                        firm for firm in employers if firm["company_ref"] in company_ids
                    ]
                    request = {"source": "cognism"}
                    if selected:
                        request["employers"] = selected
            modes = (
                await signal_targets.modes_for(db, company_ids, now=now)
                if kind == "briefing"
                else None
            )
            if modes is not None and mode is not None:
                # Teczka mówi botowi, z kim to pierwsze spotkanie (jak pętla o 16:00).
                if mode == "meeting_prep" and not request:
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
    parser.add_argument(
        "--pilot", action="store_true", help="Następna partia firm pilota Cognism"
    )
    parser.add_argument("--mode", choices=TRIAL_MODES, default=None)
    args = parser.parse_args(argv)
    if args.mode and args.kind != "briefing":
        parser.error("--mode tylko z --kind briefing.")
    if args.kind == "people" and args.request is None:
        args.request = signal_targets.COGNISM_REQUEST
    cognism = args.kind == "people" and (args.request or {}).get("source") == "cognism"
    if args.pilot and (not cognism or args.company_ids):
        parser.error("--pilot jest dla people (Cognism) bez --company-ids.")
    if cognism and len(args.company_ids) > signal_targets.COGNISM_BATCH_SIZE:
        parser.error(
            f"Cognism przyjmuje najwyżej {signal_targets.COGNISM_BATCH_SIZE} firm na bieg."
        )
    task = bot_tasks.REGISTRY[args.kind]
    if task.needs_firms and not (args.company_ids or args.pilot):
        parser.error(f"Rodzaj {args.kind} wymaga --company-ids.")
    try:
        args.request = task.validate_request(args.request)
    except ValueError as exc:
        # Sam rodzaj błędu: treść zlecenia nie idzie do logu.
        parser.error(f"Niepoprawne --request ({type(exc).__name__}).")
    if cognism:
        employer_refs = {
            firm["company_ref"] for firm in args.request.get("employers", [])
        }
        if employer_refs and not employer_refs.issubset(args.company_ids):
            parser.error(
                "Potwierdzone firmy Cognism muszą być na liście --company-ids."
            )
        if not signals.people_enabled() or not signals.people_configured():
            print(
                "Kanał Cognism jest wyłączony albo brakuje konfiguracji webhooka.",
                file=sys.stderr,
            )
            return 2
    elif not signals.configured():
        print("Brak GROK_BOT_WEBHOOK_URL albo GROK_BOT_WEBHOOK_KEY.", file=sys.stderr)
        return 2
    result = asyncio.run(
        run(args.kind, args.company_ids, args.request, pilot=args.pilot, mode=args.mode)
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") in ("started", "received") else 1


if __name__ == "__main__":
    sys.exit(main())
