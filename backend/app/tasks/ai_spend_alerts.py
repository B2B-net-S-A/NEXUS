"""Ostrzeżenie o skoku zużycia AI — bez blokowania czegokolwiek.

Decyzja Artura (24.08, znalezisko #202): funkcje AI **nie dostają sufitów**.
Blokada chroni budżet, ale odmawia rekruterowi pracy w miesiącu ze zwiększonym
ruchem, a to gorszy tryb awarii niż rachunek. Zamiast tego: ostrzeżenie.

Dlaczego SKOK, a nie próg do wpisania
-------------------------------------
Próg, którego nikt nie ustawi, nigdy nie zadziała — a to dokładnie tryb awarii
ze znaleziska #204 (workflow raportujący sukces każdego ranka, nie robiąc nic).
Wszystkie 11 wierszy `ai_features` istnieje dziś z `monthly_limit = 0`
i nikt tej liczby nie wybrał przez rok; nie ma powodu zakładać, że wybierze
teraz. Dlatego alarm liczy się WZGLĘDEM POPRZEDNIEGO OKRESU i działa bez
żadnej konfiguracji.

Trzy decyzje, które trzymają ten alarm uczciwym:

* **Podłoga bezwzględna** (`AI_SPEND_ALERT_MIN_CALLS`, domyślnie 200). Funkcja,
  która urosła z 3 wywołań na 12, urosła czterokrotnie i nikogo to nie
  obchodzi. Bez podłogi kanał zapchałby się szumem, a alarm, którego się nie
  czyta, jest gorszy niż jego brak.
* **Brak historii NIE jest skokiem.** Pierwszy miesiąc życia funkcji ma zerową
  bazę, więc każde użycie byłoby „nieskończonym wzrostem". Wtedy porównujemy
  wyłącznie z podłogą.
* **Poziomy, nie pojedynczy strzał.** Stempel trzyma KROTNOŚĆ, przy której
  ostatnio ostrzegaliśmy (3×, potem 6×, 12×…). Jednorazowy alert milczałby,
  gdy zużycie rośnie dalej — a właśnie wtedy jest najciekawszy.

Kolejność zapisu i wysyłki
--------------------------
Stempel jest **commitowany PRZED** POST-em na webhook — ten sam porządek, co
w `slack_sla_alerts` i `contract_alerts`, i z tego samego powodu: POST nie jest
ani idempotentny, ani transakcyjny, więc „dokładnie raz" jest nieosiągalne.
Wybieramy **najwyżej raz**: zgubione ostrzeżenie zamiast zdublowanego. Jest to
akceptowalne, bo liczba zużycia NIE ZNIKA — `/api/settings/ai` pokazuje ją na
żywo, a kolejny przebieg zaalarmuje na następnym poziomie.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.ai_feature import AIFeatureConfig, AIFeatureKey
from app.services.ai_quota import get_total_usage_for_period

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = max(
    300, int(os.environ.get("AI_SPEND_ALERT_INTERVAL_SECONDS", "3600"))
)
MIN_CALLS = int(os.environ.get("AI_SPEND_ALERT_MIN_CALLS", "200"))
MULTIPLIER = float(os.environ.get("AI_SPEND_ALERT_MULTIPLIER", "3"))


def _period_start(when: Optional[date] = None) -> date:
    d = when or datetime.now(timezone.utc).date()
    return d.replace(day=1)


def _previous_period_start(period: date) -> date:
    return (period - timedelta(days=1)).replace(day=1)


def _level_for(used: int, baseline: int) -> int:
    """Krotność progu, którą właśnie przekroczono. 0 = nie ma o czym mówić.

    Bez historii (baseline == 0) próg to sama podłoga — inaczej pierwszy miesiąc
    życia funkcji byłby „nieskończonym wzrostem" i alarmowałby zawsze.
    """
    if used < MIN_CALLS:
        return 0
    if baseline <= 0:
        return 1
    ratio = used / (baseline * MULTIPLIER)
    if ratio < 1:
        return 0
    level = 1
    while ratio >= 2:
        ratio /= 2
        level += 1
    return level


async def _post_to_slack(webhook: str, text: str) -> bool:
    """`httpx` nie rzuca na 4xx/5xx, więc status trzeba sprawdzić samemu."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook, json={"text": text})
        if resp.status_code >= 400:
            logger.warning(
                "ai_spend_alerts: Slack odrzucił wiadomość (HTTP %s)", resp.status_code
            )
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("ai_spend_alerts: nie udało się wysłać na Slacka: %s", exc)
        return False


async def _scan_once(db: AsyncSession, webhook: str) -> int:
    period = _period_start()
    prev = _previous_period_start(period)
    sent = 0

    for feature in AIFeatureKey:
        used = await get_total_usage_for_period(db, feature, period)
        baseline = await get_total_usage_for_period(db, feature, prev)
        level = _level_for(used, baseline)
        if level == 0:
            continue

        config = await db.scalar(
            select(AIFeatureConfig).where(AIFeatureConfig.feature == feature)
        )
        if config is None:
            # Brak wiersza to „włączona, bez sufitu" (patrz `ai_quota`), ale nie
            # mamy gdzie zapisać stempla — a alarm bez dedupu poszedłby co
            # godzinę. Milczymy i mówimy o tym w logu.
            logger.warning(
                "ai_spend_alerts: brak wiersza ai_features dla %s — "
                "pomijam alarm, bo nie ma gdzie zapisać stempla",
                feature.value,
            )
            continue

        already = (
            config.spend_alert_period == period
            and (config.spend_alert_level or 0) >= level
        )
        if already:
            continue

        # STEMPEL PRZED WYSYŁKĄ. Odwrotna kolejność powtarzałaby alarm po każdym
        # restarcie (Coolify restartuje przy każdym pushu na main).
        config.spend_alert_period = period
        config.spend_alert_level = level
        await db.commit()

        if baseline > 0:
            body = (
                f":chart_with_upwards_trend: *Zużycie AI wzrosło* — `{feature.value}`\n"
                f"Ten miesiąc: *{used}* wywołań. Poprzedni: {baseline}. "
                f"To ponad {MULTIPLIER * (2 ** (level - 1)):.0f}× więcej.\n"
                f"_Nic nie jest blokowane — to tylko ostrzeżenie._"
            )
        else:
            body = (
                f":chart_with_upwards_trend: *Nowa funkcja AI w użyciu* — `{feature.value}`\n"
                f"Ten miesiąc: *{used}* wywołań, w poprzednim nie było żadnych.\n"
                f"_Nic nie jest blokowane — to tylko ostrzeżenie._"
            )
        if await _post_to_slack(webhook, body):
            sent += 1

    return sent


async def ai_spend_alerts_loop() -> None:
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook:
        logger.info("ai_spend_alerts: brak SLACK_WEBHOOK_URL — zadanie wyłączone")
        return

    logger.info(
        "ai_spend_alerts: start (co %ss, podłoga %s wywołań, mnożnik %s)",
        CHECK_INTERVAL_SECONDS,
        MIN_CALLS,
        MULTIPLIER,
    )
    while True:
        try:
            async with AsyncSessionLocal() as db:
                sent = await _scan_once(db, webhook)
            if sent:
                logger.info("ai_spend_alerts: wysłano %s ostrzeżeń", sent)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("ai_spend_alerts: przebieg padł: %s", exc)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
