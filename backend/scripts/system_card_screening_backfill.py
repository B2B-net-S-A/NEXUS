"""Osoba na kartach „System”, które już stoją w „Screeningu” (28.10.2026).

Domyślnie podgląd (bez zapisu). ``--apply`` wykonuje to, co pokazał podgląd —
każdy proces sprawdzany drugi raz pod blokadą
(``services/system_card_screening_backfill.py``).
Wynik: JSON z liczbą i liczbą kart per osoba i per rekrutacja.
"""

import argparse
import asyncio
import json
from collections import Counter

from app.core.database import AsyncSessionLocal, engine
from app.services import system_card_screening_backfill as backfill


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    async with AsyncSessionLocal() as db:
        takes = await backfill.plan(db)
        if args.apply:
            done = await backfill.apply(db, takes)
            await db.commit()
        else:
            done = []
            await db.rollback()
    await engine.dispose()
    print(
        json.dumps(
            {
                "planned": len(takes),
                "taken": len(done) if args.apply else None,
                "per_user": dict(Counter(t.user_id for t in takes)),
                "per_job": dict(Counter(t.job_id for t in takes)),
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
