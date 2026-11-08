"""Tygodniowy raport dwóch strumieni wysłanych CV (porcja dnia, P4).

    python -m scripts.review_batch_streams_report
    python -m scripts.review_batch_streams_report --weeks 8

Tylko odczyt. Ten sam rachunek pokazuje HoR w „Ranking kandydatów → Wagi →
Zobacz zespół dziś”.
"""

import argparse
import asyncio
from datetime import datetime, timezone

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.services import review_batch_streams


async def _run(weeks: int) -> str:
    async with AsyncSessionLocal() as db:
        report = await review_batch_streams.weekly_streams(
            db, now=datetime.now(timezone.utc), weeks=weeks
        )
    return review_batch_streams.format_report(report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weeks", type=int, default=4)
    args = parser.parse_args()
    print(asyncio.run(_run(args.weeks)))


if __name__ == "__main__":
    main()
