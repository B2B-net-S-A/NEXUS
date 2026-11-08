"""Jednorazowa naprawa `repair-billing-hours-168`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0345_billing_hours_168` (2026-09-22).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_billing_hours_168`.
"""
# Jeden miesiąc roboczy 168 h (0345, decyzja 22.09.2026) — jednorazowo:
# znacznik 176 h/mc przechodzi do `contracts.orders_in_md`, a godziny
# rozliczeniowe 160/176 kontraktów i zamówień → 168 (inna, jawnie wybrana
# liczba zostaje). Żadna stawka nie jest przepisywana. Safety-net dla
# migracji 0345 (alembic na prodzie bywa osierocony). Jedno źródło SQL-a
# w `app/services/billing_hours_unification.py`; marker + advisory lock,
# `lock_timeout` 15 s — po przekroczeniu nic nie zapisuje, następny start
# ponawia. Log: wyłącznie liczby (paragon w `app_settings`).
import asyncio
import json
from sqlalchemy import text
from app.core.database import engine
from app.services.billing_hours_unification import (
    BILLING_HOURS_MARKER,
    BILLING_HOURS_UNIFICATION_SQL,
    summarize_receipt_for_log,
)

async def repair():
    try:
        async with engine.begin() as conn:
            await conn.execute(text(BILLING_HOURS_UNIFICATION_SQL))
            receipt = await conn.scalar(
                text("SELECT value::text FROM app_settings WHERE key = :key"),
                {"key": BILLING_HOURS_MARKER},
            )
    except Exception as exc:  # noqa: BLE001 — treść błędu może nieść dane umów
        sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
        print(
            f"billing hours unification failed ({type(exc).__name__}, "
            f"sqlstate={sqlstate}); nothing written, next start retries"
        )
        return
    summary = summarize_receipt_for_log(json.loads(receipt) if receipt else None)
    print(f"billing hours unification: {summary}")

asyncio.run(repair())
