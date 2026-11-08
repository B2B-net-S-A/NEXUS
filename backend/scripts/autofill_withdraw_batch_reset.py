"""Wycofanie nietkniętych kart od systemu, które nie należą do porcji dnia
(decyzja Artura 08.11.2026): starszych niż 7 dni albo poniżej 65%, w rekrutacjach
w pracy. Uruchamiane raz, przed włączeniem ``REVIEW_BATCH_ENABLED``.

Domyślnie podgląd (bez zapisu). ``--apply`` wykonuje to, co pokazał podgląd —
każda para sprawdzana drugi raz pod blokadą (``services/autofill_withdraw.py``).
Wynik: JSON z liczbą i parami ``[candidate_id, job_id]`` per rekrutacja.
"""

import argparse
import asyncio
import json
from collections import Counter
from datetime import datetime, timezone

from app.core.database import AsyncSessionLocal, engine
from app.services import autofill_withdraw


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    async with AsyncSessionLocal() as db:
        pairs = await autofill_withdraw.plan_batch_reset(
            db, now=datetime.now(timezone.utc)
        )
        if args.apply:
            done = await autofill_withdraw.apply(
                db,
                pairs,
                reason=autofill_withdraw.BATCH_RESET_REASON,
                check_batch_reset=True,
            )
            await db.commit()
        else:
            done = []
            await db.rollback()
    await engine.dispose()
    print(
        json.dumps(
            {
                "planned": len(pairs),
                "withdrawn": len(done) if args.apply else None,
                "per_job": dict(Counter(job_id for _, job_id in pairs)),
                "pairs": pairs,
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
