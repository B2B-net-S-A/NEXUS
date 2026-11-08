"""Jednorazowa naprawa `repair-job-creator-delivery-lead`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `job_creator_delivery_lead_2026_10` (2026-10-08).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_job_creator_delivery_lead`.
"""
# Delivery Lead rekrutacji (08.10.2026) — jednorazowo: otwarte rekrutacje
# założone przez Delivery Leada, którym automat wpisał głównego DL-a klienta,
# wracają do twórcy (od tej daty `create_job_core` robi to sam). Warunek SQL,
# nie lista ID; logika w `scripts/repairs/job_creator_delivery_lead_repair.py`,
# marker w `app_settings` + advisory lock. Log: same liczby i ID.
import asyncio
import app.models  # noqa: F401 — komplet mapperów przed pierwszym zapytaniem
from app.core.database import AsyncSessionLocal
from scripts.repairs.job_creator_delivery_lead_repair import (
    run_job_creator_delivery_lead_repair,
)

async def repair():
    async with AsyncSessionLocal() as db:
        try:
            summary = await run_job_creator_delivery_lead_repair(db)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    print(f"job creator delivery lead repair: {summary or 'already done'}")

asyncio.run(repair())
