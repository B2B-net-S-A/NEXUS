"""Jednorazowa naprawa `repair-contract-duplicate`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0308_contract_duplicate_merge` (2026-09-13).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_contract_duplicate`.
"""
# Duplikat kontraktu ze zgłoszenia (09.2026) — jednorazowo: dane, zamówienia,
# dokumenty i historia duplikatu przechodzą na kontrakt zachowany (bez
# nadpisywania uzupełnionych pól), duplikat jest usuwany trwale, a scalenie
# zapisane w dzienniku kontraktu i w Historii zdarzeń. Pary przypięte po ID
# (bez nazwisk w repo); niezgodna para zostaje nietknięta z kodem powodu.
# Logika w `app/services/contract_duplicate_merge_repair.py`; marker
# w `app_settings` + advisory lock. Porażka nie zapisuje niczego (rollback) —
# następny start spróbuje ponownie. Log: wyłącznie liczby, ID i kody powodów.
import asyncio
import sys
import app.models  # noqa: F401 — komplet mapperów przed pierwszym zapytaniem
from app.core.database import AsyncSessionLocal
from app.services.contract_duplicate_merge_repair import (
    run_contract_duplicate_merge_repair,
    summarize_for_log,
)

async def repair():
    async with AsyncSessionLocal() as db:
        try:
            summary = await run_contract_duplicate_merge_repair(db)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — treść błędu może nieść dane umów
            await db.rollback()
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            print(
                f"contract duplicate merge failed ({type(exc).__name__}, "
                f"sqlstate={sqlstate}); nothing written, next start retries"
            )
            sys.exit(1)
    print(f"contract duplicate merge: {summarize_for_log(summary)}")

asyncio.run(repair())
