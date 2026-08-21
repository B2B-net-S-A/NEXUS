"""Miesięczny sufit z Ustawienia → AI musi realnie blokować.

Powód istnienia tego pliku: na produkcji wszystkie 11 wierszy `ai_features`
istnieje i każdy ma `monthly_limit = 0`, czyli „bez sufitu" — więc gałąź
blokująca w `check_and_increment` nie odpala się dziś dla ŻADNEJ funkcji AI.
Zamknięcie tej luki to decyzja admina (wpisanie liczby), a nie zmiana kodu.
Dopóki tak jest, jedyne, co chroni tę ścieżkę przed cichą regresją, to test:
gdyby refaktor zepsuł porównanie zużycia z limitem, wpisana w panelu liczba
przestałaby cokolwiek znaczyć i NIC by tego nie zgłosiło — rachunek od
dostawcy przychodzi raz w miesiącu, a `/api/health` i tak zwraca 200.

Zapisy idą w jednej transakcji zakończonej rollbackiem: `check_and_increment`
świadomie nie commituje, więc ani podniesiony limit, ani naliczone zużycie nie
wychodzą poza ten test.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import select

from app.models.ai_feature import AIFeatureKey, AIMasterToggle
from app.services.ai_quota import (
    AIQuotaExceeded,
    _current_period_start,
    check_and_increment,
    get_feature_config,
    get_total_usage_for_period,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="wymaga PostgreSQL (upsert ON CONFLICT + realne wiersze ai_features)",
)


async def test_zero_means_no_ceiling_and_a_positive_limit_blocks():
    from app.core.database import AsyncSessionLocal

    # Funkcja o najmniejszym ruchu — test i tak nic nie commituje, ale wybór
    # kubełka masowego (`cv_backfill`) mieszałby się z danymi biegów.
    feature = AIFeatureKey.order_parser

    async with AsyncSessionLocal() as db:
        try:
            master = await db.scalar(
                select(AIMasterToggle).where(AIMasterToggle.id == 1)
            )
            if master is not None and not master.enabled:
                master.enabled = True  # rollback i tak to cofnie

            config = await get_feature_config(db, feature)
            assert config is not None, (
                "wiersz ai_features dla order_parser nie istnieje — "
                "baza testowa nie jest zmigrowana"
            )
            config.enabled = True
            config.monthly_limit = 0
            await db.flush()

            # 0 = bez sufitu: wywołanie przechodzi niezależnie od zużycia.
            state = await check_and_increment(db, feature, user_id=None)
            assert state.limit == 0
            assert state.remaining > 0

            period = _current_period_start()
            used = await get_total_usage_for_period(db, feature, period)
            assert used >= 1

            # Admin wpisuje liczbę <= dotychczasowego zużycia → od tej chwili
            # kolejne wywołanie MUSI zostać odrzucone (API tłumaczy to na 503).
            config.monthly_limit = used
            await db.flush()

            with pytest.raises(AIQuotaExceeded) as excinfo:
                await check_and_increment(db, feature, user_id=None)

            assert excinfo.value.limit == used
            assert excinfo.value.used == used
            assert excinfo.value.feature is feature

            # Licznik nie mógł urosnąć na odrzuconym wywołaniu — inaczej sufit
            # przesuwałby się sam wraz z próbami odbijanymi od niego.
            assert await get_total_usage_for_period(db, feature, period) == used
        finally:
            await db.rollback()
