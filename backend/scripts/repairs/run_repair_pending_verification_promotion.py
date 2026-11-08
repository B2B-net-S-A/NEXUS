"""Jednorazowa naprawa `repair-pending-verification-promotion`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `pending_verification_promotion_2026_09_17` (2026-09-17).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_pending_verification_promotion`.
"""
# Weryfikacje „Pending" (17.09.2026) — jednorazowo: bramka akceptacji stawki
# ponad budżet została USUNIĘTA, więc karty zapisane wcześniej jako `pending`
# zostają zaliczone tak, jak zrobiłaby to ręczna akceptacja (status `active`
# + zaliczenie pierwszego weryfikatora). Logika ORM w
# `scripts/repairs/pending_verification_promotion.py`; marker w `app_settings`
# + advisory lock → drugi start kończy się natychmiast. Na produkcji wykonane
# 17.09.2026; blok ZOSTAJE, bo świeża instalacja i odtworzenie bazy z kopii
# sprzed tej daty nadal go potrzebują. Log: same liczby.
import asyncio
import app.models  # noqa: F401 — komplet mapperów przed pierwszym zapytaniem
from app.core.database import AsyncSessionLocal
from scripts.repairs.pending_verification_promotion import (
    run_pending_verification_promotion,
)

async def promote():
    async with AsyncSessionLocal() as db:
        try:
            summary = await run_pending_verification_promotion(db)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    print(f"pending verification promotion: {summary or 'nothing to do'}")

asyncio.run(promote())
