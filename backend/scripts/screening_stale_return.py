"""Karty bez śladu wracają do „Nowych” — ręczny przebieg (23.11.2026).

Na produkcji robi to pętla ``screening_stale`` co 15 minut. Na stagingu pętla
jest zatrzymana (wspólna kopia produkcji), więc tu: domyślnie podgląd bez
zapisu, ``--apply`` wykonuje przebieg z dzwonkami. ``--job`` zawęża do
rekrutacji, ``--as-of`` liczy dni tak, jakby był inny moment (sprawdzenie
ścieżki bez czekania dwóch dni). ``--warn`` liczy poranne ostrzeżenie „Jutro
wrócą do „Nowych”” (z ``--apply`` wysyła je).

    python -m scripts.screening_stale_return --job 758737
    python -m scripts.screening_stale_return --job 758737 --as-of 2026-11-27T08:00+01:00 --apply
    python -m scripts.screening_stale_return --warn --as-of 2026-11-26T09:00+01:00 --apply
"""

import argparse
import asyncio
import json
from collections import Counter
from datetime import datetime, timezone

from app.core.database import AsyncSessionLocal, engine
from app.services import screening_stale


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--job", type=int, action="append", dest="jobs")
    parser.add_argument("--as-of", dest="as_of")
    parser.add_argument("--limit", type=int, default=screening_stale.MAX_PER_RUN)
    parser.add_argument("--warn", action="store_true")
    args = parser.parse_args()
    now = (
        datetime.fromisoformat(args.as_of).astimezone(timezone.utc)
        if args.as_of
        else datetime.now(timezone.utc)
    )
    async with AsyncSessionLocal() as db:
        if args.warn:
            day, by_holder = await screening_stale.soon_cards(
                db, now=now, job_ids=args.jobs
            )
            summary = {
                "as_of": now.isoformat(),
                "returns_on": day.isoformat(),
                "holders": len(by_holder),
                "cards": sum(len(cards) for cards in by_holder.values()),
            }
            if args.apply:
                summary["sent"] = await screening_stale.send_soon_bells(
                    db, now=now, job_ids=args.jobs
                )
                await db.commit()
            else:
                await db.rollback()
            await engine.dispose()
            print(json.dumps(summary, ensure_ascii=False))
            return
        due = await screening_stale.due_cards(db, now=now, job_ids=args.jobs)
        summary = {
            "as_of": now.isoformat(),
            "due": len(due),
            "per_kind": dict(Counter(card.kind for card, _ in due)),
            "jobs": len({card.job_id for card, _ in due}),
            "holders": len({card.holder_id for card, _ in due if card.holder_id}),
        }
        if args.apply:
            result = await screening_stale.run_sweep(
                db, now=now, limit=args.limit, job_ids=args.jobs
            )
            await db.commit()
            summary["bells_sent"] = await screening_stale.send_bells(
                db, result, now=now
            )
            await db.commit()
            summary["applied"] = result.as_dict()
        else:
            summary["sample"] = [
                {
                    "job_id": card.job_id,
                    "candidate_id": card.candidate_id,
                    "kind": card.kind,
                    "last_trace": trace.isoformat(),
                    "returns_on": screening_stale.return_day(trace).isoformat(),
                }
                for card, trace in due[:10]
            ]
            await db.rollback()
    await engine.dispose()
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
