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

Trwały outbox rezerwuje alert przed wysłaniem. Powiadomienia NEXUS i stempel
powstają w jednej transakcji; Slack jest opcjonalną kopią z ponowieniem po
błędzie. Dostarczenie na Slack jest co najmniej raz (restart po POST może
powtórzyć wiadomość). Brak webhooka nie wyłącza powiadomień administratorów.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import select, func, and_, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.ai_feature import AIFeatureKey, FEATURE_LABELS
from app.models.ai_metering import AIOperation, AIProviderCall, AISpendAlert
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


async def queue_alert(
    db: AsyncSession, key: str, message: str, *, recipient_id: int | None = None
) -> None:
    await db.execute(
        insert(AISpendAlert)
        .values(key=key, message=message, recipient_id=recipient_id)
        .on_conflict_do_nothing(index_elements=[AISpendAlert.key])
    )


def _daily_level(used: float, baseline: float, floor: float) -> int:
    threshold = max(floor, baseline * MULTIPLIER)
    if used < threshold:
        return 0
    level = 1
    while used >= threshold * 2:
        threshold *= 2
        level += 1
    return level


async def _queue_daily_alerts(db: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # Compare a completed rolling day to the preceding seven days. Historical
    # monthly token counters never enter this calculation.
    day = now - timedelta(days=1)
    week = day - timedelta(days=7)
    total_tokens = (
        func.coalesce(AIProviderCall.input_tokens, 0)
        + func.coalesce(AIProviderCall.output_tokens, 0)
        + func.coalesce(AIProviderCall.cache_read_tokens, 0)
        + func.coalesce(AIProviderCall.cache_creation_tokens, 0)
    )
    rows = await db.execute(
        select(
            AIOperation.feature,
            func.sum(total_tokens).filter(AIProviderCall.created_at >= day),
            func.sum(total_tokens).filter(AIProviderCall.created_at < day),
            func.sum(AIProviderCall.estimated_cost_usd).filter(
                AIProviderCall.created_at >= day
            ),
            func.sum(AIProviderCall.estimated_cost_usd).filter(
                AIProviderCall.created_at < day
            ),
        )
        .join(AIProviderCall, AIProviderCall.operation_id == AIOperation.id)
        .where(AIProviderCall.created_at >= week)
        .group_by(AIOperation.feature)
    )
    for feature, tokens, prior_tokens, cost, prior_cost in rows:
        for metric, used, baseline, floor in (
            ("tokeny", float(tokens or 0), float(prior_tokens or 0) / 7, 1_000_000),
            ("USD (szacunek)", float(cost or 0), float(prior_cost or 0) / 7, 10),
        ):
            level = _daily_level(used, baseline, floor)
            if level:
                await queue_alert(
                    db,
                    f"daily:{today.date()}:{feature}:{metric}:{level}",
                    f"AI {feature}: ostatnie 24 h — {used:,.2f} {metric}; "
                    f"średnia wcześniejszych 7 dni — {baseline:,.2f}. "
                    "Sprawdź zużycie w Ustawienia → AI. Funkcja pozostaje dostępna.",
                )


def pending_alert_predicate(webhook: bool):
    """Deliverable backlog only; revoked test recipients stay dormant.

    Keep the original row for audit and never pretend an undelivered alert
    was delivered. It becomes eligible again if its recipient regains access.
    Apply before LIMIT so orphaned control alerts cannot starve real alerts.
    """
    from app.models.user import User

    current_admin = (
        select(User.id)
        .where(
            User.id == AISpendAlert.recipient_id,
            User.is_active.is_(True),
            User.roles.contains(["admin"]),
        )
        .exists()
    )
    return and_(
        or_(AISpendAlert.recipient_id.is_(None), current_admin),
        or_(
            AISpendAlert.in_app_at.is_(None),
            and_(
                AISpendAlert.slack_sent_at.is_(None),
                AISpendAlert.recipient_id.is_(None),
            )
            if webhook
            else False,
        ),
    )


async def deliver_alerts(
    db: AsyncSession, webhook: str, *, alert_id: int | None = None
) -> int:
    from app.models.notification import Notification, NotificationType
    from app.models.user import User

    sent = 0
    pending = list(
        (
            await db.scalars(
                select(AISpendAlert)
                .where(pending_alert_predicate(bool(webhook)))
                .where(AISpendAlert.id == alert_id if alert_id is not None else True)
                .order_by(AISpendAlert.id)
                .limit(25)
            )
        ).all()
    )
    # Limit visibility to the same administrators who can inspect AI settings.
    recipients = list(
        (
            await db.scalars(
                select(User.id).where(
                    User.is_active.is_(True), User.roles.contains(["admin"])
                )
            )
        ).all()
    )
    for alert in pending:
        targets = (
            [alert.recipient_id]
            if alert.recipient_id in recipients
            else ([] if alert.recipient_id is not None else recipients)
        )
        if alert.in_app_at is None and targets:
            for user_id in targets:
                db.add(
                    Notification(
                        user_id=user_id,
                        title="Ostrzeżenie o zużyciu AI",
                        message=alert.message,
                        link="/settings/ai",
                        notification_type=NotificationType.ai_spend_alert,
                        related_entity_type="ai_spend_alert",
                        related_entity_id=alert.id,
                    )
                )
            alert.in_app_at = datetime.now(timezone.utc)
            await db.commit()
            sent += 1
        # No transaction/row lock is held during the remote POST. The scanner
        # owns a committed cross-worker lease; failed deliveries retry next run.
        if webhook and alert.recipient_id is None and alert.slack_sent_at is None:
            alert.attempts += 1
            await db.commit()
            if await _post_to_slack(webhook, alert.message):
                alert.slack_sent_at = datetime.now(timezone.utc)
                await db.commit()
    return sent


async def _scan_once(db: AsyncSession, webhook: str) -> int:
    from app.services.ai_generation_lease import GenerationBusy, generation_lease

    try:
        async with generation_lease("ai-spend-alerts"):
            period = _period_start()
            prev = _previous_period_start(period)
            for feature in AIFeatureKey:
                used = await get_total_usage_for_period(db, feature, period)
                baseline = await get_total_usage_for_period(db, feature, prev)
                level = _level_for(used, baseline)
                if level:
                    await queue_alert(
                        db,
                        f"monthly:{period}:{feature.value}:{level}",
                        f"{FEATURE_LABELS[feature]}: {used} operacji w tym miesiącu, "
                        f"{baseline} w poprzednim. Sprawdź zużycie w Ustawienia → AI. "
                        "Funkcja pozostaje dostępna.",
                    )
            await _queue_daily_alerts(db)
            await db.commit()
            return await deliver_alerts(db, webhook)
    except GenerationBusy:
        return 0


async def ai_spend_alerts_loop() -> None:
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    logger.info("ai_spend_alerts: in-app enabled; Slack configured=%s", bool(webhook))
    while True:
        try:
            async with AsyncSessionLocal() as db:
                sent = await _scan_once(db, webhook)
            if sent:
                logger.info("ai_spend_alerts: delivered %s alerts", sent)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ai_spend_alerts: scan failed; pending alerts will retry")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
