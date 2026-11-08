"""Jednorazowa naprawa `repair-md-periodic-orders`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0262_separate_md_periodic` (2026-09-01).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_md_periodic_orders`.
"""
# Rozdzielenie zamówień MD i okresowych — jednorazowa naprawa danych
# (safety-net dla migracji 0262, gdy alembic na prodzie stoi na starszej
# rewizji). Blok SQL jest ten sam co w migracji — jedno źródło w
# `app/services/order_separation_repair.py` — i jest idempotentny: advisory
# lock serializuje równoległe deploye, a marker w `app_settings` sprawia, że
# drugie wywołanie kończy się natychmiast.
import asyncio
from sqlalchemy import text
from app.core.database import engine
from app.services.order_separation_repair import (
    SEPARATE_MD_PERIODIC_MARKER,
    SEPARATE_MD_PERIODIC_SQL,
)

async def repair():
    async with engine.begin() as conn:
        await conn.execute(text(SEPARATE_MD_PERIODIC_SQL))
        receipt = await conn.scalar(
            text("SELECT value::text FROM app_settings WHERE key = :key"),
            {"key": SEPARATE_MD_PERIODIC_MARKER},
        )
    print(f"md/periodic separation: {receipt}")

asyncio.run(repair())
