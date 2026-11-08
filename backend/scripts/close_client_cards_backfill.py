"""Jednorazowo: pary u klienta w rekrutacjach zamkniętych od 12.10 (B5, 08.11.2026).

Domyślnie podgląd z liczbami, zapis tylko z ``--apply``. Dotyczy powodów
``competitor`` i ``budget`` (``--reasons`` zmienia listę). Karty w „Umowie” i etapy
wewnętrzne zostają. Data wiersza = zamknięcie rekrutacji, żeby lejek nie urósł o
„odrzucenia z dziś”. Bez dzwonków i bez maili do kandydatów.

    python -m scripts.close_client_cards_backfill
    python -m scripts.close_client_cards_backfill --apply

Reguła: ``docs/claude/rekrutacja-tablica/zamkniecie-rekrutacji-osoby-w-toku.md``.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.job import Job, JobCloseReason, JobStatus
from app.models.recruitment_pipeline import CandidateStage
from app.services.job_close_client_cards import (
    CLIENT_SIDE_COLUMNS,
    client_side_cards,
    end_card,
)
from app.services.rejection_reason_labels import (
    CLIENT_CHOSE_OTHER,
    REQUEST_CLOSED,
    rejection_reason_label,
)

SINCE = date(2026, 10, 12)
DEFAULT_REASONS = ("competitor", "budget")
BACKFILL_KEYS: dict[JobCloseReason, str] = {
    JobCloseReason.competitor: CLIENT_CHOSE_OTHER,
    JobCloseReason.budget: REQUEST_CLOSED,
}
SOURCE = "close_client_cards_backfill"


def moved_at_for(closed_at: datetime, last_moved_at: Optional[datetime]) -> datetime:
    """Data końca pary: zamknięcie rekrutacji, ale nigdy przed ostatnim ruchem karty."""
    if last_moved_at is not None and last_moved_at >= closed_at:
        return last_moved_at + timedelta(seconds=1)
    return closed_at


def parse_reasons(raw: Iterable[str]) -> list[JobCloseReason]:
    reasons = [JobCloseReason(item.strip()) for item in raw if item.strip()]
    if not reasons:
        raise SystemExit("Podaj co najmniej jeden powód zamknięcia.")
    missing = [r.value for r in reasons if r not in BACKFILL_KEYS]
    if missing:
        raise SystemExit(f"Te powody nie mają klucza końca pary: {', '.join(missing)}")
    return reasons


async def _closed_jobs(db, reasons: list[JobCloseReason], since: date) -> list[Job]:
    start = datetime(since.year, since.month, since.day, tzinfo=timezone.utc)
    return list(
        (
            await db.scalars(
                select(Job)
                .where(
                    Job.status == JobStatus.closed,
                    Job.close_reason.in_(reasons),
                    Job.closed_at >= start,
                )
                .order_by(Job.closed_at, Job.id)
            )
        ).all()
    )


async def run(*, apply: bool, reasons: list[JobCloseReason], since: date) -> int:
    per_reason: Counter[tuple[str, str]] = Counter()
    job_ids: dict[str, set[int]] = {}
    ended = skipped = 0
    async with AsyncSessionLocal() as db:
        jobs = await _closed_jobs(db, reasons, since)
        for job in jobs:
            job_id = job.id
            reason = JobCloseReason(
                getattr(job.close_reason, "value", job.close_reason)
            )
            cards = await client_side_cards(db, job)
            if not cards:
                continue
            job_ids.setdefault(reason.value, set()).add(job_id)
            for column in cards.values():
                per_reason[(reason.value, column)] += 1
            if not apply:
                continue
            closed_at = job.closed_at
            key = BACKFILL_KEYS[reason]
            for candidate_id in sorted(cards):
                last = await db.scalar(
                    select(func.max(CandidateStage.moved_at)).where(
                        CandidateStage.job_id == job_id,
                        CandidateStage.candidate_id == candidate_id,
                    )
                )
                stage = await end_card(
                    db,
                    job,
                    candidate_id,
                    reason_key=key,
                    actor_id=None,
                    note=f"Porządek po zamknięciu: {rejection_reason_label(key)}",
                    source=SOURCE,
                    moved_at=moved_at_for(closed_at, last),
                )
                await db.commit()
                if stage is None:
                    skipped += 1
                else:
                    ended += 1
    print(
        f"Rekrutacje zamknięte od {since.isoformat()}, powody: {[r.value for r in reasons]}"
    )
    for reason in reasons:
        rows = {c: per_reason[(reason.value, c)] for c in CLIENT_SIDE_COLUMNS}
        print(
            f"  {reason.value}: {len(job_ids.get(reason.value, ()))} rekrutacji, "
            + ", ".join(f"{c} {n}" for c, n in rows.items())
        )
    total = sum(per_reason.values())
    print(f"Razem par do zakończenia: {total}")
    print(
        f"ZAPISANO: zakończone {ended}, pominięte {skipped}"
        if apply
        else "PODGLĄD: nic nie zapisano (dodaj --apply)."
    )
    return ended if apply else total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Zapisz zmiany.")
    parser.add_argument("--since", default=SINCE.isoformat(), help="RRRR-MM-DD")
    parser.add_argument(
        "--reasons",
        default=",".join(DEFAULT_REASONS),
        help="Powody zamknięcia, po przecinku (competitor,budget).",
    )
    args = parser.parse_args()
    asyncio.run(
        run(
            apply=args.apply,
            reasons=parse_reasons(args.reasons.split(",")),
            since=date.fromisoformat(args.since),
        )
    )


if __name__ == "__main__":
    main()
