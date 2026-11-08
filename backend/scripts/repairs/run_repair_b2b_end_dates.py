"""Jednorazowa naprawa `repair-b2b-end-dates`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0307_b2b_indefinite_end_date` (2026-09-11).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_b2b_end_dates`.
"""
# Umowy B2B bezterminowe (09.2026) — jednorazowo: najpierw zakończenia osób ze
# zgłoszenia (po trójkach ID, bez nazwisk w repo), potem każda umowa B2B
# „Aktywny"/„Kończący się" z datą końca, której nikt ręcznie nie zakończył,
# staje się bezterminowa. Logika ORM w `scripts/repairs/b2b_end_date_repair.py`;
# marker w `app_settings` + advisory lock → drugi start kończy się od razu.
# Porażka nie zapisuje niczego (rollback) — następny start spróbuje ponownie.
# Log: wyłącznie liczby.
import asyncio
import sys
import app.models  # noqa: F401 — komplet mapperów przed pierwszym zapytaniem
from app.core.database import AsyncSessionLocal
from scripts.repairs.b2b_end_date_repair import (
    run_b2b_end_date_repair,
    summarize_for_log,
)

async def repair():
    async with AsyncSessionLocal() as db:
        try:
            summary = await run_b2b_end_date_repair(db)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — treść błędu może nieść dane umów
            await db.rollback()
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            print(
                f"b2b end-date repair failed ({type(exc).__name__}, "
                f"sqlstate={sqlstate}); nothing written, next start retries"
            )
            sys.exit(1)
    print(f"b2b end-date repair: {summarize_for_log(summary)}")

asyncio.run(repair())
