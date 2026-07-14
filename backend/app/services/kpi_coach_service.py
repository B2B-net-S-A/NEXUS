"""KPI Coach — logika biznesowa dla dynamicznej analizy KPI.

Publiczne API:
- `run_scheduled_sweep(db, now)` — wywoływane z
  `app/tasks/kpi_coach_nudger.py` co 5 min. Sprawdza wszystkich aktywnych
  operacyjnych rekruterów, emituje praise/remind/eod_summary wedle reguł.
- `is_in_quiet_hours(now)` — helper, używany przez loop do early return.

Reguły:
- Quiet hours: pon–pt 09:00–17:30 Europe/Warsaw. Poza nim zero nudgów.
- `praise_hit`: state == "hit" + brak wcześniejszego wpisu dla
  (user, kpi, praise_hit, period_bucket) → emit. Jedno praise per
  (kpi, period). Jeśli rekruter przekroczy target i potem go "zgubi"
  (np. stage revert) — nie dostaje drugiego praise (dedup per bucket).
- `remind_behind`: state == "behind" + expected_ratio >= 0.35
  (≈11:00 dla dnia, ~wtorek rano dla tygodnia, ~11 dnia dla miesiąca) +
  <3 istniejących remindów w tym buckecie + minimum 120 min od ostatniego
  reminda → emit. Eskalacja wariantów 0/1/2 = delikatny/stanowczy/last call.
- `eod_summary`: 17:25 ≤ time ≤ 17:35, raz dziennie per user.

Dedup (hard): UniqueConstraint `uq_kpi_nudge_log_dedup` na
(user_id, kpi_id, nudge_type, period_bucket). IntegrityError = skip.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import ws as ws_manager
from app.core.config import settings
from app.models.kpi_nudge_log import KpiNudgeChannel, KpiNudgeLog, KpiNudgeType
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services.kpi_catalog import KpiPeriod
from app.services.kpi_engine import (
    KpiResult,
    WARSAW,
    evaluate_user_kpis,
    expected_progress_ratio,
    period_bucket_label,
)
from app.services.kpi_messages import render, select_reminder_variant

logger = logging.getLogger(__name__)


# ── Config values (hardcoded — not worth making everyone overridable) ──────

# Tylko te role dostają KPI Coach.
_OPERATIONAL_ROLES: frozenset[UserRole] = frozenset(
    {UserRole.tac, UserRole.recruiter, UserRole.sourcer}
)

# Od jakiej części okresu zaczynamy remindować (0.35 = ~11:00 przy daily).
_REMIND_MIN_RATIO = 0.35

# Maks. ile remindów na bucket.
_REMIND_CAP = 3

# Minimalny odstęp między remindami w tym samym buckecie (w sekundach).
_REMIND_MIN_INTERVAL_SEC = 120 * 60  # 2h

# EOD summary okno: 17:25–17:35.
_EOD_HOUR_START = time(17, 25)
_EOD_HOUR_END = time(17, 35)

# Syntetyczny kpi_id dla eod_summary (zachowuje dedup per dzień).
_EOD_KPI_ID = "__eod_summary__"


# ── Public helpers ─────────────────────────────────────────────────────────


def is_in_quiet_hours(now: datetime) -> bool:
    """True gdy mamy EMITOWAĆ nudge'e (mylące: "quiet hours" = cisza, tu
    odwrotnie — to okno głosu). Zachowuję nazwę zgodną z planem mimo
    tego — refaktor przy fazie 2."""
    now_w = _as_warsaw(now)
    # Sobota=5, niedziela=6.
    if now_w.weekday() >= 5:
        return False
    t = now_w.time()
    return time(9, 0) <= t <= time(17, 30)


def kpi_coach_nudge_mode() -> str:
    """Resolve the rollout mode with compatibility for the original flag."""

    mode = settings.KPI_COACH_V2_NUDGE_MODE
    if mode == "off" and settings.KPI_COACH_V2_NUDGES_ENABLED:
        return "live"
    return mode


# ── Core sweep ─────────────────────────────────────────────────────────────


async def run_scheduled_sweep(
    db: AsyncSession,
    now: Optional[datetime] = None,
    *,
    force: bool = False,
    target_user_id: Optional[int] = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Jeden cykl scheduler'a: ocena wszystkich operacyjnych rekruterów
    + emisja odpowiednich nudge'y.

    Args:
        db: async session
        now: punkt w czasie (default: teraz w Europe/Warsaw)
        force: bypass `is_in_quiet_hours` gate — używane przez admin
            endpoint `POST /api/kpis/admin/trigger-sweep` do smoke-testów
            po godzinach pracy (np. wieczorem, żeby zweryfikować end-to-end).
        target_user_id: zawęź sweep do tego konkretnego user_id (też admin-only).
            Gdy None — sweep leci po wszystkich uprawnionych userach.

    Zwraca counters: {"users", "praise", "remind", "eod", "skipped_dedup", "skipped_optout"}.
    """
    if now is None:
        now = datetime.now(WARSAW)
    now_w = _as_warsaw(now)

    counters = {
        "users": 0,
        "praise": 0,
        "remind": 0,
        "eod": 0,
        "skipped_dedup": 0,
        "skipped_optout": 0,
        "dry_run": 0,
    }

    if not force and not is_in_quiet_hours(now_w):
        logger.debug("kpi_coach sweep: outside quiet hours, skipping")
        return counters

    users = await _fetch_eligible_users(db)
    if target_user_id is not None:
        users = [u for u in users if u.id == target_user_id]
    counters["users"] = len(users)

    is_eod_window = _EOD_HOUR_START <= now_w.time() <= _EOD_HOUR_END

    for user in users:
        try:
            kpi_results = await evaluate_user_kpis(db, user=user, now=now_w)
        except Exception:
            logger.exception(
                "kpi_coach: evaluate_user_kpis failed for user_id=%s", user.id
            )
            continue

        for kpi_result in kpi_results:
            if kpi_result.target <= 0:
                # KPI nieaktywny dla roli — skip.
                continue

            if kpi_result.state == "hit":
                ok = await _try_emit(
                    db,
                    user=user,
                    kpi_result=kpi_result,
                    nudge_type=KpiNudgeType.praise_hit,
                    now=now_w,
                    dry_run=dry_run,
                )
                if ok is True:
                    counters["praise"] += 1
                    counters["dry_run"] += int(dry_run)
                elif ok is False:
                    counters["skipped_dedup"] += 1

            elif kpi_result.state == "behind":
                ratio = expected_progress_ratio(kpi_result.period, now_w)
                if ratio < _REMIND_MIN_RATIO:
                    continue
                # Reminder: eskalacja po liczbie istniejących reminderów
                # w tym buckecie + min-interval gate.
                bucket = period_bucket_label(kpi_result.period, now_w)
                existing = await _count_reminders(
                    db,
                    user_id=user.id,
                    kpi_id=kpi_result.kpi_id,
                    period_bucket=bucket,
                )
                if existing >= _REMIND_CAP:
                    continue
                last_remind_at = await _latest_remind_at(
                    db,
                    user_id=user.id,
                    kpi_id=kpi_result.kpi_id,
                    period_bucket=bucket,
                )
                if last_remind_at is not None:
                    since_last = (
                        _as_warsaw(now_w) - _as_warsaw(last_remind_at)
                    ).total_seconds()
                    if since_last < _REMIND_MIN_INTERVAL_SEC:
                        continue
                forced = select_reminder_variant(existing)
                ok = await _try_emit(
                    db,
                    user=user,
                    kpi_result=kpi_result,
                    nudge_type=KpiNudgeType.remind_behind,
                    now=now_w,
                    forced_variant=forced,
                    dry_run=dry_run,
                )
                if ok is True:
                    counters["remind"] += 1
                    counters["dry_run"] += int(dry_run)
                elif ok is False:
                    counters["skipped_dedup"] += 1

        # EOD per user (nie per KPI).
        if is_eod_window:
            ok = await _try_emit_eod(
                db,
                user=user,
                kpi_results=kpi_results,
                now=now_w,
                dry_run=dry_run,
            )
            if ok is True:
                counters["eod"] += 1
                counters["dry_run"] += int(dry_run)
            elif ok is False:
                counters["skipped_dedup"] += 1

    return counters


# ── Emission ───────────────────────────────────────────────────────────────


async def _try_emit(
    db: AsyncSession,
    *,
    user: User,
    kpi_result: KpiResult,
    nudge_type: KpiNudgeType,
    now: datetime,
    forced_variant: Optional[int] = None,
    dry_run: bool = False,
) -> Optional[bool]:
    """Próba emisji nudge'a dla konkretnego KPI. Zwraca:
    True  — emitowano (log + notification + WS),
    False — zdedupowane (constraint),
    None  — pominięto przez inny guard (np. exception).
    """
    bucket = period_bucket_label(kpi_result.period, now)
    message = render(
        nudge_type=nudge_type,
        kpi_id=kpi_result.kpi_id,
        kpi_title_pl=kpi_result.title_pl,
        user_id=user.id,
        user_name=user.name,
        user_email=user.email,
        current=kpi_result.current,
        target=kpi_result.target,
        progress_pct=kpi_result.progress_pct,
        period_bucket=bucket,
        forced_variant=forced_variant,
    )

    if dry_run:
        existing = await db.scalar(
            select(KpiNudgeLog.id).where(
                and_(
                    KpiNudgeLog.user_id == user.id,
                    KpiNudgeLog.kpi_id == kpi_result.kpi_id,
                    KpiNudgeLog.nudge_type == nudge_type,
                    KpiNudgeLog.period_bucket == bucket,
                )
            )
        )
        if existing is not None:
            return False
        logger.info(
            "kpi_coach_v2 dry_run user=%s kpi=%s type=%s bucket=%s "
            "current=%s target=%s title=%s",
            user.id,
            kpi_result.kpi_id,
            nudge_type.value,
            bucket,
            kpi_result.current,
            kpi_result.target,
            message.title,
        )
        return True

    # 1) Insert kpi_nudge_log (HARD dedup gate).
    log = KpiNudgeLog(
        user_id=user.id,
        kpi_id=kpi_result.kpi_id,
        nudge_type=nudge_type,
        channel=KpiNudgeChannel.toast,
        message_variant=message.variant,
        period_bucket=bucket,
    )
    try:
        async with db.begin_nested():
            db.add(log)
            await db.flush()
    except IntegrityError:
        logger.debug(
            "kpi_coach dedup: user=%s kpi=%s type=%s bucket=%s",
            user.id,
            kpi_result.kpi_id,
            nudge_type.value,
            bucket,
        )
        return False

    # 2) Notification (bell). Dedup "naturalny" przez związek
    # related_entity_id = kpi_nudge_log.id (unikalne per insert).
    notif = Notification(
        user_id=user.id,
        title=message.title,
        message=message.body,
        notification_type=NotificationType.kpi_coach,
        related_entity_type="kpi_nudge_log",
        related_entity_id=log.id,
        link="/?tab=dashboard",
    )
    try:
        async with db.begin_nested():
            db.add(notif)
            await db.flush()
    except IntegrityError:
        # Teoretycznie nie wystąpi (nie mamy dedup-matchu), ale gdyby się
        # zdarzyło — log idzie bez notyfikacji, WS jeszcze pójdzie.
        logger.warning(
            "kpi_coach: notification insert conflict for user=%s nudge_type=%s",
            user.id,
            nudge_type.value,
        )
        notif = None  # type: ignore[assignment]

    # 3) WS push (best-effort). Event = "kpi_nudge".
    try:
        await ws_manager.notify_user(
            user.id,
            {
                "type": "kpi_nudge",
                "data": {
                    "notification_id": notif.id if notif is not None else None,
                    "nudge_type": nudge_type.value,
                    "kpi_id": kpi_result.kpi_id,
                    "state": kpi_result.state,
                    "title": message.title,
                    "message": message.body,
                    "emoji": message.emoji,
                    "tone": message.tone,
                    "variant": message.variant,
                    "current": kpi_result.current,
                    "target": kpi_result.target,
                    "progress_pct": round(kpi_result.progress_pct, 1),
                    "deadline_hours_left": round(kpi_result.deadline_hours_left, 1),
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                },
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("kpi_coach WS push failed for user=%s: %s", user.id, exc)
    return True


async def _try_emit_eod(
    db: AsyncSession,
    *,
    user: User,
    kpi_results: list[KpiResult],
    now: datetime,
    dry_run: bool = False,
) -> Optional[bool]:
    """Emit EOD summary. Dedup: syntetyczne kpi_id + day bucket."""
    day_bucket = period_bucket_label(KpiPeriod.day, now)

    daily_kpis = [r for r in kpi_results if r.period == KpiPeriod.day and r.target > 0]
    if not daily_kpis:
        avg_progress = 0.0
    else:
        # Cap 100% per KPI, żeby one over-achiever nie wykrzywił średniej.
        avg_progress = sum(min(r.progress_pct, 100.0) for r in daily_kpis) / len(
            daily_kpis
        )

    message = render(
        nudge_type=KpiNudgeType.eod_summary,
        kpi_id=_EOD_KPI_ID,
        kpi_title_pl="Podsumowanie dnia",
        user_id=user.id,
        user_name=user.name,
        user_email=user.email,
        current=0,  # nieistotne w szablonach eod
        target=0,
        progress_pct=avg_progress,
        period_bucket=day_bucket,
    )

    if dry_run:
        existing = await db.scalar(
            select(KpiNudgeLog.id).where(
                and_(
                    KpiNudgeLog.user_id == user.id,
                    KpiNudgeLog.kpi_id == _EOD_KPI_ID,
                    KpiNudgeLog.nudge_type == KpiNudgeType.eod_summary,
                    KpiNudgeLog.period_bucket == day_bucket,
                )
            )
        )
        if existing is not None:
            return False
        logger.info(
            "kpi_coach_v2 dry_run user=%s kpi=%s type=%s bucket=%s "
            "avg_progress_pct=%.1f title=%s",
            user.id,
            _EOD_KPI_ID,
            KpiNudgeType.eod_summary.value,
            day_bucket,
            avg_progress,
            message.title,
        )
        return True

    log = KpiNudgeLog(
        user_id=user.id,
        kpi_id=_EOD_KPI_ID,
        nudge_type=KpiNudgeType.eod_summary,
        channel=KpiNudgeChannel.toast,
        message_variant=message.variant,
        period_bucket=day_bucket,
    )
    try:
        async with db.begin_nested():
            db.add(log)
            await db.flush()
    except IntegrityError:
        return False

    notif = Notification(
        user_id=user.id,
        title=message.title,
        message=message.body,
        notification_type=NotificationType.kpi_coach,
        related_entity_type="kpi_nudge_log",
        related_entity_id=log.id,
        link="/?tab=dashboard",
    )
    try:
        async with db.begin_nested():
            db.add(notif)
            await db.flush()
    except IntegrityError:
        notif = None  # type: ignore[assignment]

    try:
        await ws_manager.notify_user(
            user.id,
            {
                "type": "kpi_nudge",
                "data": {
                    "notification_id": notif.id if notif is not None else None,
                    "nudge_type": KpiNudgeType.eod_summary.value,
                    "kpi_id": _EOD_KPI_ID,
                    "state": "summary",
                    "title": message.title,
                    "message": message.body,
                    "emoji": message.emoji,
                    "tone": message.tone,
                    "variant": message.variant,
                    "avg_progress_pct": round(avg_progress, 1),
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                },
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("kpi_coach EOD WS push failed for user=%s: %s", user.id, exc)
    return True


# ── DB helpers ─────────────────────────────────────────────────────────────


async def _fetch_eligible_users(db: AsyncSession) -> list[User]:
    """Aktywni operacyjni rekruterzy z włączonym KPI Coach."""
    result = await db.execute(
        select(User).where(
            and_(
                User.is_active.is_(True),
                User.kpi_coach_enabled.is_(True),
                User.role.in_(tuple(_OPERATIONAL_ROLES)),
            )
        )
    )
    return list(result.scalars().all())


async def _count_reminders(
    db: AsyncSession, *, user_id: int, kpi_id: str, period_bucket: str
) -> int:
    """Ile remind_behind już wysłano dla tego bucketu."""
    return int(
        await db.scalar(
            select(func.count(KpiNudgeLog.id)).where(
                and_(
                    KpiNudgeLog.user_id == user_id,
                    KpiNudgeLog.kpi_id == kpi_id,
                    KpiNudgeLog.nudge_type == KpiNudgeType.remind_behind,
                    KpiNudgeLog.period_bucket == period_bucket,
                )
            )
        )
        or 0
    )


async def _latest_remind_at(
    db: AsyncSession, *, user_id: int, kpi_id: str, period_bucket: str
) -> Optional[datetime]:
    """Kiedy ostatnio wysłano remind_behind dla tego bucketu (UTC)."""
    return await db.scalar(
        select(func.max(KpiNudgeLog.sent_at)).where(
            and_(
                KpiNudgeLog.user_id == user_id,
                KpiNudgeLog.kpi_id == kpi_id,
                KpiNudgeLog.nudge_type == KpiNudgeType.remind_behind,
                KpiNudgeLog.period_bucket == period_bucket,
            )
        )
    )


def _as_warsaw(now: datetime) -> datetime:
    """Duplicate of kpi_engine._as_warsaw to avoid cross-module reach into
    a name-mangled private."""
    if now.tzinfo is None:
        return now.replace(tzinfo=WARSAW)
    return now.astimezone(WARSAW)


__all__ = ["is_in_quiet_hours", "kpi_coach_nudge_mode", "run_scheduled_sweep"]
