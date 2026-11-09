"""Otwarte wnioski o terminy na kartach zamkniętych i po rozmowie sprzed reguły
z 04.11.2026.

Od tej daty taki ruch karty anuluje wniosek w ``transition_process``. Ten skrypt
domyka wiersze założone wcześniej (9 na kopii z 03.11.2026). Domyślnie podgląd
(bez zapisu), ``--apply`` anuluje to, co pokazał podgląd, pod blokadą wierszy.
Wynik: JSON z samymi identyfikatorami.
"""

import argparse
import asyncio
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, engine
from app.models.client_interview_slot_request import (
    OPEN_SLOT_STATUSES,
    ClientInterviewSlotRequest,
)
from app.models.recruitment_pipeline import CandidateStage
from app.services import interview_slots
from app.services.recruitment_process_commands import SLOT_REQUEST_ENDING_STAGES


async def closed_card_open_requests(
    db: AsyncSession, *, for_update: bool = False
) -> list[ClientInterviewSlotRequest]:
    latest = (
        select(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.stage,
        )
        .distinct(CandidateStage.candidate_id, CandidateStage.job_id)
        .order_by(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.moved_at.desc(),
            CandidateStage.id.desc(),
        )
        .subquery()
    )
    stmt = (
        select(ClientInterviewSlotRequest)
        .join(
            latest,
            (latest.c.candidate_id == ClientInterviewSlotRequest.candidate_id)
            & (latest.c.job_id == ClientInterviewSlotRequest.job_id),
        )
        .where(
            ClientInterviewSlotRequest.status.in_(OPEN_SLOT_STATUSES),
            latest.c.stage.in_(tuple(SLOT_REQUEST_ENDING_STAGES)),
        )
        .order_by(ClientInterviewSlotRequest.id)
    )
    if for_update:
        stmt = stmt.with_for_update(of=ClientInterviewSlotRequest)
    return list((await db.scalars(stmt)).all())


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    async with AsyncSessionLocal() as db:
        requests = await closed_card_open_requests(db, for_update=args.apply)
        request_ids = [req.id for req in requests]
        if args.apply:
            for req in requests:
                interview_slots.cancel(req)
            await db.commit()
        else:
            await db.rollback()
    await engine.dispose()
    print(
        json.dumps(
            {
                "planned": len(request_ids),
                "cancelled": len(request_ids) if args.apply else 0,
                "request_ids": request_ids,
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
