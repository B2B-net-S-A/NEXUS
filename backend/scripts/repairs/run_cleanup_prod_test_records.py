"""Jednorazowa naprawa `cleanup-prod-test-records`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `prod_test_records_cleanup_2026_10_20` (2026-10-20).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_cleanup_prod_test_records`.
"""
# Rekordy testowe z ręcznego audytu UI 26–27.09.2026 (decyzja Artura
# 20.10.2026) — jednorazowo: szkice zamówień i kontrakty klienta testowego
# → void, spotkania z Outlooka podpięte do osoby testowej po adresie
# pracownika wracają bez niej, cztery osoby testowe usuwane ścieżką przycisku
# „Usuń”. Logika w `scripts/repairs/prod_test_records_cleanup.py`, przypięta do
# id i odcisków; paragon w `app_settings` + advisory lock; porażka nie
# zapisuje niczego. Log: wyłącznie liczby.
import asyncio
import app.models  # noqa: F401 — komplet mapperów przed pierwszym zapytaniem
from app.core.database import AsyncSessionLocal
from app.services.candidate_hard_delete import finish_after_commit
from scripts.repairs.prod_test_records_cleanup import (
    run_prod_test_records_cleanup,
    summarize_for_log,
)

async def repair():
    async with AsyncSessionLocal() as db:
        try:
            result = await run_prod_test_records_cleanup(db)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — treść błędu może nieść dane osób
            await db.rollback()
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            print(
                f"prod test records cleanup failed ({type(exc).__name__}, "
                f"sqlstate={sqlstate}); nothing written, next start retries"
            )
            return
        summary, outcomes = result if result is not None else (None, [])
        for outcome in outcomes:
            try:
                await finish_after_commit(db, outcome, actor_id=None)
            except Exception as exc:  # noqa: BLE001 — wektor ma trwały retry w outboxie
                print(f"prod test records cleanup: after-commit step {type(exc).__name__}")
    print(f"prod test records cleanup: {summarize_for_log(summary)}")

asyncio.run(repair())
