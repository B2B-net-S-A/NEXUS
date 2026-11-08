"""Jednorazowa naprawa `repair-m365-private-event-candidate`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `m365_private_event_candidate_unlink_2026_09_26` (2026-09-27).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_m365_private_event_candidate`.
"""
# Prywatne spotkania z Outlooka oczyszczone przed rundą 7 (R8-V3-3) —
# jednorazowo: zdjęcie `candidate_id`, który pochodził z uczestników. Profil
# kandydata pokazywał „Spotkanie prywatne”, czyli z kim było. Logika
# w `scripts/repairs/m365_private_event_link_repair.py`; marker w `app_settings`
# + advisory lock; porażka nie zapisuje niczego. Log: wyłącznie liczby.
import asyncio
import app.models  # noqa: F401 — komplet mapperów przed pierwszym zapytaniem
from app.core.database import AsyncSessionLocal
from scripts.repairs.m365_private_event_link_repair import (
    run_private_event_unlink,
    summarize_for_log,
)

async def repair():
    async with AsyncSessionLocal() as db:
        try:
            summary = await run_private_event_unlink(db)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — treść błędu może nieść dane wydarzeń
            await db.rollback()
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            print(
                f"private event unlink failed ({type(exc).__name__}, "
                f"sqlstate={sqlstate}); nothing written, next start retries"
            )
            return
    print(f"private event unlink: {summarize_for_log(summary)}")

asyncio.run(repair())
