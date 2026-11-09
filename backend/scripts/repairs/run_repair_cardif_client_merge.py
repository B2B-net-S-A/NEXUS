"""Jednorazowa naprawa `repair-cardif-client-merge`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0435_cardif_client_merge` (2026-10-13), `0436_cardif_contract_fill` (2026-10-13).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_cardif_client_merge`.
"""
# Pełne scalenie „BNP Paribas Cardif” 52 → Cardif Assurances 38335 (13.10.2026) —
# jednorazowo: rekrutacje z procesami, kontakty, karta klienta i alerty DL
# przechodzą na klienta docelowego, podpisana umowa 1520/2026 dostaje właściwy
# kontrakt (#689), a rekord 52 zostaje oznaczony jako scalony. Logika
# w `scripts/repairs/cardif_client_merge_repair.py`, przypięta do id i nazwy;
# marker w `app_settings` + advisory lock; porażka nie zapisuje niczego.
# Log: wyłącznie liczby i kody.
import asyncio
import app.models  # noqa: F401 — komplet mapperów przed pierwszym zapytaniem
from app.core.database import AsyncSessionLocal
from scripts.repairs.cardif_client_merge_repair import (
    run_cardif_client_merge,
    run_cardif_contract_fill,
    summarize_for_log,
)

async def repair():
    async with AsyncSessionLocal() as db:
        try:
            summary = await run_cardif_client_merge(db)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — treść błędu może nieść dane osób
            await db.rollback()
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            print(
                f"cardif client merge failed ({type(exc).__name__}, "
                f"sqlstate={sqlstate}); nothing written, next start retries"
            )
            return
    print(f"cardif client merge: {summarize_for_log(summary)}")
    # Rekrutacja i numer umowy na kontrakcie #689 — osobny znacznik, bo bieg
    # z 13.10.2026 powiązał umowę, zanim powiązanie zaczęło je uzupełniać.
    async with AsyncSessionLocal() as db:
        try:
            filled = await run_cardif_contract_fill(db)
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            print(
                f"cardif contract fill failed ({type(exc).__name__}); "
                "nothing written, next start retries"
            )
            return
    state = "already applied" if filled is None else (filled["skipped"] or filled["filled"])
    print(f"cardif contract fill: {state}")

asyncio.run(repair())
