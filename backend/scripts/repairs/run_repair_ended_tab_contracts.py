"""Jednorazowa naprawa `repair-ended-tab-contracts`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0274_ended_tab_contract_repair` (2026-09-03).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_ended_tab_contracts`.
"""
# Reguła zakładki „Zakończeni" (09.2026) — jednorazowa korekta wskazanego
# kontraktu + audyt klasy (safety-net dla migracji 0274, gdy alembic na prodzie
# stoi na starszej rewizji). Jedno źródło SQL-a w
# `app/services/contract_ended_tab_repair.py`; blok jest idempotentny.
import asyncio
from sqlalchemy import text
from app.core.database import engine
from app.services.contract_ended_tab_repair import (
    ENDED_TAB_REPAIR_MARKER,
    ENDED_TAB_REPAIR_SQL,
)

async def repair():
    async with engine.begin() as conn:
        await conn.execute(text(ENDED_TAB_REPAIR_SQL))
        receipt = await conn.scalar(
            text("SELECT value::text FROM app_settings WHERE key = :key"),
            {"key": ENDED_TAB_REPAIR_MARKER},
        )
    print(f"ended-tab contract repair: {receipt}")

asyncio.run(repair())
