"""Jednorazowa naprawa `repair-alior-reversed-order`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0397_alior_reversed_period_order` (2026-09-28).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_alior_reversed_order`.
"""
# Zamówienie z odwróconym okresem (Alior, zgłoszenie 28.09.2026) — jednorazowo:
# drugie zamówienie tej samej osoby o tym samym numerze, 01.01.2027 → 31.12.2026,
# założone oknem przedłużenia. Ta sama droga co usunięcie z zakładki
# „Zamówienia”; logika w `scripts/repairs/alior_reversed_order_repair.py`,
# przypięta do ID, numeru i dat. Plik PDF kasowany po commicie. Log: ID.
import asyncio
import app.models  # noqa: F401 — komplet mapperów przed pierwszym zapytaniem
from app.core.database import AsyncSessionLocal
from app.services import storage_service
from scripts.repairs.alior_reversed_order_repair import (
    run_alior_reversed_order_repair,
    summarize_for_log,
)
from app.services.order_write_errors import commit_order_write

async def repair():
    async with AsyncSessionLocal() as db:
        try:
            summary, po_paths = await run_alior_reversed_order_repair(db)
            await commit_order_write(db)
        except Exception as exc:  # noqa: BLE001 — treść błędu może nieść dane zamówień
            await db.rollback()
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            print(
                f"alior reversed order repair failed ({type(exc).__name__}, "
                f"sqlstate={sqlstate}); nothing written, next start retries"
            )
            return
    for path in po_paths:
        try:
            storage_service.delete_client_order_po(path)
        except Exception as exc:  # noqa: BLE001 — plik to sprzątanie, nie korekta
            print(f"alior reversed order repair: PDF cleanup failed ({type(exc).__name__})")
    print(f"alior reversed order repair: {summarize_for_log(summary)}")

asyncio.run(repair())
