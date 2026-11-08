"""Jednorazowa naprawa `repair-ezdrowie-merge`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `ezdrowie_client_merge_2026_09` (2026-09-26), `ezdrowie_client_merge_2026_09_processes` (2026-09-26).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_ezdrowie_merge`.
"""
# Dokończenie scalenia E-Zdrowie 37721 → eZdrowie 115 (25.09.2026) —
# jednorazowo: rekrutacje i kontrakty (z zamówieniami i umowami B2B), które
# nocny import przypinał do ukrytego duplikatu. Import już podąża za
# `merged_into_client_id`. Logika w `scripts/repairs/ezdrowie_client_merge_repair.py`,
# przypięta do id; marker + advisory lock; porażka nie zapisuje niczego.
import asyncio
import app.models  # noqa: F401 — komplet mapperów przed pierwszym zapytaniem
from app.core.database import AsyncSessionLocal
from scripts.repairs.ezdrowie_client_merge_repair import (
    run_ezdrowie_client_merge,
    run_ezdrowie_process_client_sync,
    summarize_for_log,
)

async def repair():
    async with AsyncSessionLocal() as db:
        try:
            summary = await run_ezdrowie_client_merge(db)
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            print(
                f"ezdrowie client merge failed ({type(exc).__name__}, "
                f"sqlstate={sqlstate}); nothing written, next start retries"
            )
            return
    print(f"ezdrowie client merge: {summarize_for_log(summary)}")
    # Procesy rekrutacji (kopia jobs.client_id) — osobny znacznik, bo pierwszy
    # bieg z 26.09.2026 przeniósł rekrutacje bez nich.
    async with AsyncSessionLocal() as db:
        try:
            synced = await run_ezdrowie_process_client_sync(db)
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            print(
                f"ezdrowie process sync failed ({type(exc).__name__}); "
                "nothing written, next start retries"
            )
            return
    moved = "already applied" if synced is None else synced["processes_moved"]
    print(f"ezdrowie process sync: {moved}")

asyncio.run(repair())
