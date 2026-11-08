"""Jednorazowa naprawa `repair-contract-start-dates`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0334_contract_start_date_correction` (2026-09-21).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_contract_start_dates`.
"""
# Daty rozpoczęcia umów (zgłoszenie 21.09.2026) — jednorazowo: poprawne daty
# z arkusza działu, przypięte do trójki ID i stanu bazy z 21.09 (świeższa
# zmiana człowieka wygrywa). Dane bez nazwisk w
# `app/data/contract_start_date_corrections.py`, logika w
# `scripts/repairs/contract_start_date_repair.py`; marker w `app_settings` +
# advisory lock. Porażka nie zapisuje niczego — następny start ponawia.
# Log: wyłącznie liczby.
import asyncio
import app.models  # noqa: F401 — komplet mapperów przed pierwszym zapytaniem
from app.core.database import AsyncSessionLocal
from scripts.repairs.contract_start_date_repair import (
    run_contract_start_date_repair,
    summarize_for_log,
)

async def repair():
    async with AsyncSessionLocal() as db:
        try:
            summary = await run_contract_start_date_repair(db)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — treść błędu może nieść dane umów
            await db.rollback()
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            print(
                f"contract start-date repair failed ({type(exc).__name__}, "
                f"sqlstate={sqlstate}); nothing written, next start retries"
            )
            return
    print(f"contract start-date repair: {summarize_for_log(summary)}")

asyncio.run(repair())
