"""NEXUS nie ma limitów AI — wpisana liczba nie blokuje, a zużycie nadal się liczy.

Decyzja Artura z 17.09.2026: zero kwot, zero przełączników per funkcja, zero
globalnego wyłącznika. Ochroną budżetu jest wyłącznie alarm zużycia. Do tej daty
ten plik pilnował odwrotności (dodatni `monthly_limit` MUSIAŁ blokować), a
wyczerpana kwota `cv_parser` przełączała odczyt CV na regex bez żadnego sygnału.

Test pilnuje obu połówek naraz: stare kolumny `ai_features.enabled` /
`monthly_limit` nie mogą wrócić jako bramka, a wiersz `AIOperation` nadal musi
powstać, bo na nim stoją liczniki w Ustawieniach → AI i alarm wydatków.
Zapisy idą w jednej transakcji zakończonej rollbackiem.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import select

from app.models.ai_feature import AIFeatureKey, AIMasterToggle
from app.services.ai_quota import (
    _current_period_start,
    check_and_increment,
    get_feature_config,
    get_total_usage_for_period,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="wymaga PostgreSQL (realne wiersze ai_features)",
)


async def test_old_toggles_and_limits_never_block_but_usage_is_metered():
    from app.core.database import AsyncSessionLocal

    feature = AIFeatureKey.order_parser

    async with AsyncSessionLocal() as db:
        try:
            config = await get_feature_config(db, feature)
            assert config is not None, (
                "wiersz ai_features dla order_parser nie istnieje — "
                "baza testowa nie jest zmigrowana"
            )
            period = _current_period_start()
            before = await get_total_usage_for_period(db, feature, period)

            master = await db.scalar(
                select(AIMasterToggle).where(AIMasterToggle.id == 1)
            )
            if master is None:
                master = AIMasterToggle(id=1, enabled=False)
                db.add(master)
            master.enabled = False
            config.enabled = False
            config.monthly_limit = 1
            await db.flush()

            for _ in range(3):
                await check_and_increment(
                    db, feature, user_id=None, commit_with_caller=True
                )

            assert await get_total_usage_for_period(db, feature, period) == before + 3
        finally:
            await db.rollback()
