#!/usr/bin/env python3
"""Lista do przeglądu dostępów: kto ma obszar, ile razy do niego wszedł.

Tylko odczyt (transakcja ``READ ONLY``). Skrypt zamiast trasy, bo aktywność osób
to dane pracownicze: bez nowego endpointu czyta je tylko ten, kto ma dostęp do
kontenera. Zasady i kontekst: ``docs/claude/uprawnienia/licznik-uzycia-obszarow.md``.

Użycie (w kontenerze backendu)::

    python -m scripts.access_usage_review --days 28
    python -m scripts.access_usage_review --days 28 --unused-only

CSV na stdout, podsumowanie okresu na stderr. Wyjście zawiera dane osobowe:
tylko terminal, nigdy repo ani logi Actions (są publiczne).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from pathlib import Path
from typing import TextIO

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.core.database import AsyncSessionLocal, engine  # noqa: E402
from app.services.access_usage import (  # noqa: E402
    AREA_LABELS,
    Review,
    load_review,
)

EXIT_NO_DATA = 3

_HEADER = (
    "user_id",
    "imie_i_nazwisko",
    "email",
    "role",
    "obszar",
    "ma_dostep",
    "wejscia",
    "dni_z_wejsciem",
    "ostatnio",
)
_ACCESS_LABEL = {True: "tak", False: "nie", None: "bramka na trasie"}


def write_csv(review: Review, out: TextIO, *, unused_only: bool = False) -> int:
    writer = csv.writer(out)
    writer.writerow(_HEADER)
    written = 0
    for row in review.rows:
        if unused_only and not row.unused:
            continue
        writer.writerow(
            (
                row.user_id,
                row.full_name,
                row.email,
                "+".join(row.roles),
                AREA_LABELS[row.area],
                _ACCESS_LABEL[row.has_access],
                row.entries,
                row.active_days,
                row.last_day.isoformat() if row.last_day else "",
            )
        )
        written += 1
    return written


async def _run(days: int, unused_only: bool) -> int:
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SET TRANSACTION READ ONLY"))
            review = await load_review(db, days=days)
    finally:
        await engine.dispose()
    print(
        f"Okres {review.since} – {review.until}: dni z danymi "
        f"{review.collected_days} z {days}; licznik "
        f"{'włączony' if settings.ACCESS_USAGE_COUNTER_ENABLED else 'WYŁĄCZONY'}.",
        file=sys.stderr,
    )
    if review.collected_days == 0:
        print(
            "Brak danych, więc każde „0 wejść” byłoby fałszywe. Listy nie ma.",
            file=sys.stderr,
        )
        return EXIT_NO_DATA
    write_csv(review, sys.stdout, unused_only=unused_only)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=28, help="długość okresu w dniach")
    parser.add_argument(
        "--unused-only",
        action="store_true",
        help="tylko wiersze „ma dostęp, 0 wejść”",
    )
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days musi być dodatnie")
    return asyncio.run(_run(args.days, args.unused_only))


if __name__ == "__main__":
    raise SystemExit(main())
