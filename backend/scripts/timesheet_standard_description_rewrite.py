"""„Praca standardowa” → „Realizacja usług zgodnie z umową” w szkicach (28.10.2026).

Tylko szkice raportu godzin jednego miesiąca (domyślnie bieżącego w kalendarzu
firmy), osoby na B2B i zleceniu (``services/hr/time_description_rewrite.py``).
Domyślnie podgląd (bez zapisu). ``--apply`` wykonuje zapis.
Wynik: JSON z liczbą szkiców i wpisów per forma.
"""

import argparse
import asyncio
import json
from dataclasses import asdict

from app.core.database import AsyncSessionLocal, engine
from app.core.scheduling import business_today
from app.services.hr import time_description_rewrite as rewrite


async def main() -> None:
    today = business_today()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=today.year)
    parser.add_argument("--month", type=int, default=today.month)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    async with AsyncSessionLocal() as db:
        if args.apply:
            done = await rewrite.apply(db, year=args.year, month=args.month)
            await db.commit()
        else:
            done = await rewrite.plan(db, year=args.year, month=args.month)
            await db.rollback()
    await engine.dispose()
    print(
        json.dumps(
            {
                "period": f"{args.year}-{args.month:02d}",
                "applied": args.apply,
                "per_form": [asdict(item) for item in done],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
