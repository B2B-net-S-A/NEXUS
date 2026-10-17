"""Termin sekretu rejestracji „NEXUS Kadry” — sonda i alarm do adminów.

Jedna rejestracja obsługuje autoodpowiedzi, wydarzenia i przekierowania
urlopowe, czytnik skrzynki administracja@, odczyt urządzeń z Intune i odczyt
profili z katalogu. Sekret w Entra ID ma termin (najdłużej 2 lata); po nim
wszystko to staje naraz, a jedynym śladem są ``auth`` w ``last_error``.

Graph nie powie nam terminu bez dodatkowego uprawnienia
(``Application.Read.All`` do własnej rejestracji), więc termin podajemy sami:
``HR_M365_CLIENT_SECRET_EXPIRES_ON`` ustawiany razem z sekretem przez workflow
„Coolify set env” przy każdej rotacji.

* stan (``state``): ``ok`` > 30 dni, ``expiring`` 1–30 dni, ``expired`` w dniu
  terminu i po nim, ``missing`` — brak daty, a rejestracja pracuje na żywo
  (``HR_M365_MODE``, ``EQUIPMENT_INTUNE_MODE`` = ``live`` albo czytnik
  administracja@), ``not_set`` — brak daty i nic jej nie używa,
* sonda ``hr_m365`` (``health.py``): ``degraded: secret_expires_in_<n>d``,
  ``unhealthy: secret_expired`` (uptime-probe otwiera zgłoszenie),
  ``degraded: secret_expiry_unknown``,
* alarm ``automation_failing`` (tylko admini, mail od razu) raz przy progu
  30, 14, 7 i 1 dnia oraz raz w dniu terminu (albo po nim, gdy pętla stała) —
  rezerwacja ``hr_job_runs`` z kluczem (termin, próg), więc nowy termin po
  rotacji zaczyna od nowa, a pętla uruchomiona po kilku dniach przerwy wysyła
  tylko bieżący próg.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User, UserRole
from app.services.hr import job_runs
from app.services.hr.notify import notify_each
from app.services.hr.m365.executor import utc_now, warsaw_hour, warsaw_today

logger = logging.getLogger(__name__)

JOB_KIND = "hr_m365_secret_expiry"
WARNING_DAYS = 30
ALERT_DAYS: tuple[int, ...] = (30, 14, 7, 1)
#: Alarmy od 7:00 Warszawy — mail do adminów nie wychodzi w nocy.
ALERT_HOUR = 7
SETTINGS_LINK = "/settings/hr"

_ROTATE = (
    "Dodaj nowy sekret w Entra ID (rejestracja „NEXUS Kadry”) i ustaw "
    "HR_M365_CLIENT_SECRET oraz HR_M365_CLIENT_SECRET_EXPIRES_ON workflowem "
    "„Coolify set env”."
)
_STOPS = (
    "autoodpowiedzi i przekierowania urlopowe, czytnik administracja@, "
    "odczyt profili i urządzeń z Microsoft 365"
)


def expires_on() -> Optional[date]:
    value = getattr(settings, "HR_M365_CLIENT_SECRET_EXPIRES_ON", None)
    return value if isinstance(value, date) else None


def registration_live() -> bool:
    """Czy coś pracuje na żywo tokenem rejestracji „NEXUS Kadry”."""

    from app.services.admin_cases.mail_ingest import ingest_enabled
    from app.services.equipment.intune_graph import current_mode as intune_mode
    from app.services.hr.m365.executor import current_mode

    return current_mode() == "live" or intune_mode() == "live" or ingest_enabled()


def status(today: date) -> dict[str, Any]:
    """Stan terminu dla karty M365 i sondy."""

    expires = expires_on()
    if expires is None:
        return {
            "expires_on": None,
            "days_left": None,
            "state": "missing" if registration_live() else "not_set",
        }
    days_left = (expires - today).days
    if days_left <= 0:
        state = "expired"
    elif days_left <= WARNING_DAYS:
        state = "expiring"
    else:
        state = "ok"
    return {"expires_on": expires.isoformat(), "days_left": days_left, "state": state}


def health_verdict(today: date) -> Optional[str]:
    """Werdykt sondy ``hr_m365`` albo ``None``, gdy z terminem wszystko w porządku."""

    info = status(today)
    if info["state"] == "expired":
        return "unhealthy: secret_expired"
    if info["state"] == "expiring":
        return f"degraded: secret_expires_in_{info['days_left']}d"
    if info["state"] == "missing":
        return "degraded: secret_expiry_unknown"
    return None


def alert_step(days_left: int) -> Optional[str]:
    """Próg alarmu dla liczby dni do terminu (``None`` = jeszcze nie czas)."""

    if days_left <= 0:
        return "expired"
    for threshold in sorted(ALERT_DAYS):
        if days_left <= threshold:
            return f"{threshold}d"
    return None


def _day(value: date) -> str:
    return f"{value.day}.{value.month:02d}.{value.year}"


def alert_text(expires: date, days_left: int) -> tuple[str, str]:
    name = "Sekret aplikacji „NEXUS Kadry”"
    if days_left < 0:
        return (
            f"{name} wygasł",
            f"Termin minął {_day(expires)}. Stoją {_STOPS}. {_ROTATE}",
        )
    when = {0: "dziś", 1: "jutro"}.get(days_left, f"za {days_left} dni")
    return (
        f"{name} wygasa {when}",
        f"Termin: {_day(expires)}. Potem staną {_STOPS}. {_ROTATE}",
    )


async def _notify_admins(db: AsyncSession, expires: date, days_left: int) -> int:
    from app.models.notification import NotificationType

    users = await db.scalars(select(User).where(User.is_active.is_(True)))
    admins = sorted(user.id for user in users if user.has_role(UserRole.admin))
    title, message = alert_text(expires, days_left)
    sent = await notify_each(
        db,
        admins,
        title=title[:255],
        message=message,
        ntype=NotificationType.automation_failing,
        link=SETTINGS_LINK,
        # Bez numeru encji: ``automation_failing`` niosą też alarmy innych
        # automatów, a dzienny odsiew nie zna rodzaju encji — ten sam numer
        # połknąłby alarm. Raz na próg pilnuje rezerwacja przebiegu.
        log_tag="hr_m365_secret_expiry",
    )
    await db.commit()
    return sent


async def run_once(
    db: AsyncSession, *, now: Optional[datetime] = None
) -> dict[str, Any]:
    """Alarm do adminów raz na próg; bez daty, przed 7:00 i poza progami — nic."""

    expires = expires_on()
    if expires is None:
        return {"status": "no_date"}
    now = now or utc_now()
    if warsaw_hour(now) < ALERT_HOUR:
        return {"status": "too_early"}
    days_left = (expires - warsaw_today(now)).days
    step = alert_step(days_left)
    if step is None:
        return {"status": "ok", "days_left": days_left}
    run_id = await job_runs.claim(db, JOB_KIND, f"{expires.isoformat()}:{step}", now)
    if run_id is None:
        return {"status": "already_sent", "days_left": days_left}
    try:
        sent = await _notify_admins(db, expires, days_left)
    except Exception as exc:  # noqa: BLE001 — alarm do ponowienia w kolejnym obrocie
        logger.exception("hr_m365_secret_expiry failed")
        await db.rollback()
        await job_runs.finish(
            db, run_id, status="failed", counts={}, error=type(exc).__name__
        )
        return {"status": "failed", "days_left": days_left}
    counts = {"days_left": days_left, "step": step, "notified": sent}
    await job_runs.finish(db, run_id, status="done", counts=counts)
    return {"status": "notified", **counts}
