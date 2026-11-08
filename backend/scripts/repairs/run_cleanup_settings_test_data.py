"""Jednorazowa naprawa `cleanup-settings-test-data`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `settings_test_data_cleanup_2026_10_20` (2026-10-20).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_cleanup_settings_test_data`.
"""
# Ślady testów w Ustawieniach (inwentarz docs/settings-test-data-inventory.md,
# zgoda Artura 20.10.2026) — jednorazowo: klient QA-E2E znika z list Ustawień
# (reguła CV, karta klienta, przypisanie DL, portfele; klient i rekrutacje
# zostają), szablon procesu i wzór umowy ze smoke testów są usuwane, konto
# serwisowe `claude-traffit-ops` wyłączone z odwołaniem kluczy. Logika
# w `scripts/repairs/settings_test_data_cleanup.py`, przypięta do id i odcisków;
# paragon w `app_settings` + advisory lock. Log: wyłącznie liczby.
import asyncio
import app.models  # noqa: F401 — komplet mapperów przed pierwszym zapytaniem
from app.core.database import AsyncSessionLocal
from scripts.repairs.settings_test_data_cleanup import (
    run_settings_test_data_cleanup,
    summarize_for_log,
)

async def repair():
    async with AsyncSessionLocal() as db:
        try:
            summary = await run_settings_test_data_cleanup(db)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — log bez treści wierszy
            await db.rollback()
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            print(
                f"settings test data cleanup failed ({type(exc).__name__}, "
                f"sqlstate={sqlstate}); nothing written, next start retries"
            )
            return
    print(f"settings test data cleanup: {summarize_for_log(summary)}")

asyncio.run(repair())
