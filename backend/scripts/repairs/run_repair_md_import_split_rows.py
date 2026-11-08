"""Jednorazowa naprawa `repair-md-import-split-rows`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `md_import_split_rows_repair_2026_09_24` (2026-09-24).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_md_import_split_rows`.
"""
# Ticket 1.1 (24.09.2026): dwa wiersze jednej osoby z dwoma numerami zamówień
# (BIK) zsumowane na jednym zamówieniu — 19 MD przechodzi na zamówienie
# wskazane w wierszu, pierwsze wraca do salda 0 i zakończenia z końcem miesiąca
# ostatniego zejścia. Przypięte do ID i stanu z 24.09 (inna wartość =
# pominięcie z kodem). Logika w `scripts/repairs/md_import_split_rows_repair.py`;
# marker w `app_settings` + advisory lock. Log: wyłącznie liczby, ID i kody.
import asyncio
import app.models  # noqa: F401 — komplet mapperów przed pierwszym zapytaniem
from app.core.database import AsyncSessionLocal
from scripts.repairs.md_import_split_rows_repair import (
    run_md_import_split_rows_repair,
    summarize_for_log,
)

async def repair():
    async with AsyncSessionLocal() as db:
        try:
            summary = await run_md_import_split_rows_repair(db)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — treść błędu może nieść dane zamówień
            await db.rollback()
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            print(
                f"md import split-rows repair failed ({type(exc).__name__}, "
                f"sqlstate={sqlstate}); nothing written, next start retries"
            )
            return
    print(f"md import split-rows repair: {summarize_for_log(summary)}")

asyncio.run(repair())
