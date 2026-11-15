#!/usr/bin/env python3
"""Jeden bieg bota radaru przepisów na żądanie: próba rutyny przed włączeniem flagi.

Zakłada bieg i wywołuje webhook rutyny (``GROK_BOT_LAW_COLLECT_WEBHOOK_URL``
i ``_KEY`` albo ``GROK_BOT_LAW_ANALYZE_…``) także przy wyłączonym
``LAW_RADAR_ENABLED``, bo właśnie próba ma pokazać, czy rutyna sama odeśle
raport. Raport Zbieracza uruchamia bramkę i Analityka jak na produkcji.
Stan biegu widać w ``law_radar_runs`` (ekran „Przepisy” po włączeniu flagi).

``--kind analyze`` wysyła Analitykowi pozycje po bramce, które jeszcze nie
były analizowane; bez takich pozycji nic nie startuje. ``--since`` nadpisuje
datę, od której Zbieracz szuka zmian (domyślnie: start ostatniego przyjętego
biegu albo dziś − 3 dni).

Uruchomienie (z ``backend/``)::

    python -m scripts.law_radar_run --kind collect
    python -m scripts.law_radar_run --kind collect --since 2026-11-01
    python -m scripts.law_radar_run --kind analyze

Wynik to same liczby i identyfikatory (logi są publiczne).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, datetime, timezone
from typing import Optional, Sequence

from app.core.database import AsyncSessionLocal, engine
from app.services.law_radar import collect, flow, runs


def _since(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--since w postaci RRRR-MM-DD.") from exc


async def run(kind: str, since: Optional[date] = None) -> dict[str, object]:
    try:
        async with AsyncSessionLocal() as db:
            now = datetime.now(timezone.utc)
            running = await flow.open_run(db, kind)
            if running is not None:
                return {
                    "started": False,
                    "reason": "bieg tego bota już czeka na raport",
                    "run_id": running.id,
                }
            if kind == collect.KIND:
                request = (
                    collect.build_request(since)
                    if since is not None
                    else await flow.collect_request(db, now=now)
                )
                started = await runs.start_run(db, kind, request, now=now)
            else:
                started = await flow.start_analyze(db, now=now)
            if started is None:
                return {
                    "started": False,
                    "reason": "brak pozycji po bramce do analizy"
                    if kind != collect.KIND
                    else "brak adresu albo klucza webhooka",
                }
            return {
                "started": True,
                "run_id": started.id,
                "status": started.status,
                "error": started.error,
                "items": len((started.request or {}).get("items", [])),
            }
    finally:
        await engine.dispose()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Próbny bieg bota radaru przepisów")
    parser.add_argument("--kind", choices=runs.KINDS, default=collect.KIND)
    parser.add_argument("--since", type=_since, default=None)
    args = parser.parse_args(argv)
    if args.since is not None and args.kind != collect.KIND:
        parser.error("--since tylko z --kind collect.")
    if not runs.configured(args.kind):
        print(
            f"Brak adresu albo klucza webhooka dla rodzaju {args.kind}.",
            file=sys.stderr,
        )
        return 2
    result = asyncio.run(run(args.kind, args.since))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") in ("started", "received") else 1


if __name__ == "__main__":
    sys.exit(main())
