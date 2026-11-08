"""Jednorazowa naprawa `repair-kpi-catalog-unification`, do 08.11.2026 krok w `entrypoint.sh`.

Znacznik w `app_settings` na produkcji: `0346_kpi_catalog_unification` (2026-09-22).
Drugi przebieg sam kończy się na znaczniku. Uruchomienie: `python -m scripts.repairs.run_repair_kpi_catalog_unification`.
"""
# Jeden katalog KPI (0346, 22.09.2026) — stare id panelu „Moje KPI" na
# kanoniczne id katalogu, martwe id z 0034 i wiersze równe domyślnym z
# `kpi_role_defaults` usunięte (katalog = jedyne źródło liczb). Safety-net dla
# migracji 0346: ten sam blok SQL z `app/services/kpi_target_normalization.py`,
# marker w `app_settings` + advisory lock → drugi start kończy się natychmiast.
import asyncio
from sqlalchemy import text
from app.core.database import engine
from app.services.kpi_target_normalization import (
    KPI_TARGET_NORMALIZATION_MARKER,
    KPI_TARGET_NORMALIZATION_SQL,
)

async def repair():
    async with engine.begin() as conn:
        await conn.execute(text(KPI_TARGET_NORMALIZATION_SQL))
        done = await conn.scalar(
            text("SELECT 1 FROM app_settings WHERE key = :key"),
            {"key": KPI_TARGET_NORMALIZATION_MARKER},
        )
    print(f"kpi catalog unification: {'done' if done else 'not applied'}")

asyncio.run(repair())
