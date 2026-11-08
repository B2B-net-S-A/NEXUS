"""Jednorazowa naprawa `repair-contact-duplicates`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `contact_duplicates_merge_2026_09_25` (2026-10-14).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_contact_duplicates`.
"""
# Zdublowane kontakty klienta z Traffita (25.09.2026) — jednorazowo: trzy pary
# tej samej osoby u tego samego klienta. Zostaje kontakt o niższym id, drugi
# rekord Traffita dostaje alias (`traffit_contact_aliases`), żeby nocny import
# go nie odtworzył. Logika w `app/services/contact_duplicate_merge.py`,
# przypięta do id. Marker + advisory lock; porażka nie zapisuje niczego.
import asyncio
import app.models  # noqa: F401 — komplet mapperów przed pierwszym zapytaniem
from app.core.database import AsyncSessionLocal
from app.services.contact_duplicate_merge import (
    run_contact_duplicate_merge,
    summarize_for_log,
)

async def repair():
    async with AsyncSessionLocal() as db:
        try:
            summary = await run_contact_duplicate_merge(db)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — treść błędu może nieść dane osób
            await db.rollback()
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            print(
                f"contact duplicate merge failed ({type(exc).__name__}, "
                f"sqlstate={sqlstate}); nothing written, next start retries"
            )
            return
    print(f"contact duplicate merge: {summarize_for_log(summary)}")

asyncio.run(repair())
