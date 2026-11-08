"""Jednorazowa naprawa `repair-pfron-resync`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0306_pfron_revenue_resync` (2026-09-11).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_pfron_resync`.
"""
# PFRON 507–509 (0306) — krok przychodu kontraktu zaraz po rozdzieleniu: surowy
# SQL wyżej nie wyzwala synchronizacji kontrakt ↔ zamówienia, więc przywrócony
# okres nie ma kroku przychodu, a czerwiec–sierpień czytałby stawkę nowego
# okresu do najbliższego zapisu zamówienia. `scripts/repairs/pfron_revenue_resync.py`
# woła tę samą synchronizację co zwykły zapis zamówienia (tylko przy włączonej
# 0304); własny marker + advisory lock, jednorazowy. Log: tylko liczby.
import asyncio
import sys
import app.models  # noqa: F401 — komplet mapperów przed pierwszym zapytaniem
from app.core.database import AsyncSessionLocal
from scripts.repairs.pfron_revenue_resync import (
    run_pfron_revenue_resync,
    summarize_for_log,
)

async def resync():
    async with AsyncSessionLocal() as db:
        try:
            summary = await run_pfron_revenue_resync(db)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — treść błędu może nieść dane umów
            await db.rollback()
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            print(
                f"pfron revenue resync failed ({type(exc).__name__}, "
                f"sqlstate={sqlstate}); nothing written, next start retries"
            )
            sys.exit(1)
    print(f"pfron revenue resync: {summarize_for_log(summary)}")

asyncio.run(resync())
