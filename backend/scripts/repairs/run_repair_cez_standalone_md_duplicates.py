"""Jednorazowa naprawa `repair-cez-standalone-md-duplicates`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0325_cez_standalone_md_duplicates` (2026-09-17).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_cez_standalone_md_duplicates`.
"""
# Centrum e-Zdrowia (09.2026) — jednorazowo: dwie osoby miały obok linii
# zamówienia grupowego CeZ/242/2025 stare, samodzielne zamówienie na tym samym
# kontrakcie (karta bez zużycia MD nad właściwą kartą). Anulowanie jak
# `DELETE /orders/{id}` (rekord zostaje, status „anulowane"), tylko gdy kontrakt
# jest żywy i ma żywą linię w aktywnej grupie; inaczej pominięcie z kodem.
# Logika w `scripts/repairs/cez_standalone_md_duplicate_repair.py`; marker
# w `app_settings` + advisory lock. Log: wyłącznie liczby, ID i kody powodów.
import asyncio
import sys
import app.models  # noqa: F401 — komplet mapperów przed pierwszym zapytaniem
from app.core.database import AsyncSessionLocal
from scripts.repairs.cez_standalone_md_duplicate_repair import (
    run_cez_standalone_md_duplicate_repair,
    summarize_for_log,
)

async def repair():
    async with AsyncSessionLocal() as db:
        try:
            summary = await run_cez_standalone_md_duplicate_repair(db)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — treść błędu może nieść dane zamówień
            await db.rollback()
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            print(
                f"cez standalone md duplicate repair failed ({type(exc).__name__}, "
                f"sqlstate={sqlstate}); nothing written, next start retries"
            )
            sys.exit(1)
    print(f"cez standalone md duplicate repair: {summarize_for_log(summary)}")

asyncio.run(repair())
