"""Awarie automatów rekrutacji: cichy wpis dla rekrutera, alarm dla admina.

Decyzja właściciela (21.09.2026): rekruter NIE dostaje powiadomienia o awarii
automatu — awaria jest wpisem (z polskim powodem) w „Pracy w tle" rekrutacji
i ``logger.error`` (→ Sentry). Dopiero gdy TEN SAM automat padnie
``FAILURE_STREAK_THRESHOLD`` razy z rzędu (globalnie, kolejne biegi), adminowie
dostają JEDNO powiadomienie na serię. Pierwszy sukces zeruje licznik i odblokowuje
następny alarm.

Licznik żyje w ``app_settings['automation_failure_streaks']`` (przeżywa deploy —
u nas restart kontenera to kilka razy dziennie). Aktualizacja idzie pod
``FOR UPDATE`` na wierszu ustawienia, więc dwa równoległe biegi nie zgubią
porażki i nie wyślą alarmu dwa razy. Wszystko tutaj jest fail-soft i we WŁASNEJ
sesji: księgowanie awarii nigdy nie może dołożyć drugiej awarii wołającemu.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, text

logger = logging.getLogger(__name__)

SETTING_KEY = "automation_failure_streaks"
FAILURE_STREAK_THRESHOLD = 3
ACTIVITY_ENTITY = "job_automation"

KIND_FULL_REVIEW = "auto_full_review"
KIND_NEW_CV = "auto_match"
KIND_AUTO_CV = "cv_auto_generate"

# Nazwa automatu po polsku + stabilne id encji powiadomienia (dobowy dedup
# `ix_notif_dedup_daily` patrzy na typ i id encji).
KINDS: dict[str, tuple[str, int]] = {
    KIND_FULL_REVIEW: ("Nocny przegląd bazy", 1),
    KIND_NEW_CV: ("Propozycje z nowych CV", 2),
    KIND_AUTO_CV: ("Auto-CV po „Zweryfikowany”", 3),
}

# Przegląd bazy bez wektora zapytania (runda 6 audytu) — `auto_full_review`.
NO_QUERY_VECTOR = "no_query_vector"

# Polskie powody do „Pracy w tle". Klucz = klasa wyjątku albo kod stanu.
_REASONS_PL = {
    NO_QUERY_VECTOR: (
        "Wyszukiwanie semantyczne było niedostępne — przegląd nie ocenił "
        "dopasowania i zostanie powtórzony."
    ),
    "stalled": "Przegląd stanął bez postępu i został przerwany.",
    "attempts_exhausted": "Przegląd był wielokrotnie przerywany (np. wdrożeniami).",
    "candidate_erased": "W trakcie przeglądu usunięto kandydata — przegląd przerwano.",
    "TimeoutError": "Przekroczono czas oczekiwania na usługę.",
    "AutoMatchUnavailable": "Wyszukiwanie semantyczne było niedostępne.",
    "generation_failed": "Generacja CV zakończyła się błędem.",
}


def reason_pl(error_code: Optional[str]) -> str:
    code = (error_code or "").strip()
    return _REASONS_PL.get(code) or (
        f"Błąd wewnętrzny ({code})." if code else "Błąd wewnętrzny."
    )


def failure_details(error_code: Optional[str], **extra) -> dict:
    """Szczegóły wpisu „Praca w tle": kod + polski powód (bez treści wyjątku)."""
    code = (error_code or "error")[:80]
    return {**extra, "reason": code, "message": reason_pl(code)}


async def _locked_state(db) -> dict:
    await db.execute(
        text(
            "INSERT INTO app_settings (key, value) VALUES (:key, '{}'::jsonb) "
            "ON CONFLICT (key) DO NOTHING"
        ),
        {"key": SETTING_KEY},
    )
    from app.models.app_setting import AppSetting

    row = await db.scalar(
        select(AppSetting)
        .where(AppSetting.key == SETTING_KEY)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return row


async def _notify_admins(db, *, kind: str, error_code: str, job_id: Optional[int]):
    from app.models.notification import NotificationType
    from app.models.user import User
    from app.services.notification_triggers import emit

    label, entity_id = KINDS[kind]
    admins = (
        await db.scalars(
            select(User.id).where(
                User.is_active.is_(True), User.roles.contains(["admin"])
            )
        )
    ).all()
    sent = 0
    for user_id in admins:
        created = await emit(
            db,
            user_id=user_id,
            title=f"Automat „{label}” nie działa"[:255],
            message=(
                f"{FAILURE_STREAK_THRESHOLD} nieudane biegi z rzędu. "
                f"Ostatni błąd: {error_code}. Rekruterzy nie dostali powiadomień — "
                "awarie są widoczne w „Pracy w tle” rekrutacji."
            ),
            ntype=NotificationType.automation_failing,
            related_entity_type="automation",
            related_entity_id=entity_id,
            link=f"/jobs/{job_id}" if job_id else "/settings",
        )
        sent += int(created is not None)
    return sent


async def _update(kind: str, *, error_code: Optional[str], job_id: Optional[int]):
    if kind not in KINDS:
        raise ValueError(f"Unknown automation kind: {kind!r}")
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        row = await _locked_state(db)
        state = dict(row.value or {})
        entry = dict(state.get(kind) or {})
        now = datetime.now(timezone.utc).isoformat()
        if error_code is None:
            if not entry.get("count") and not entry.get("notified"):
                await db.rollback()
                return 0
            entry = {"count": 0, "notified": False, "last_success_at": now}
        else:
            entry["count"] = int(entry.get("count") or 0) + 1
            entry["last_error"] = error_code[:80]
            entry["last_failure_at"] = now
            if job_id is not None:
                entry["last_job_id"] = job_id
        notify = (
            error_code is not None
            and entry["count"] >= FAILURE_STREAK_THRESHOLD
            and not entry.get("notified")
        )
        if notify:
            entry["notified"] = True
        row.value = {**state, kind: entry}
        if notify:
            await _notify_admins(
                db, kind=kind, error_code=error_code[:80], job_id=job_id
            )
        await db.commit()
        return entry.get("count", 0)


# Automaty, o których TEN proces wie, że nie mają otwartej serii — sukces nie
# musi wtedy dotykać bazy (auto-match księguje sukces przy każdym CV). Restart
# czyści zbiór, więc pierwszy sukces po deployu sprawdza stan w bazie raz.
_known_clean: set[str] = set()


async def record_failure(
    kind: str, error_code: str, *, job_id: Optional[int] = None
) -> None:
    """Zaksięguj nieudany bieg. ``logger.error`` → Sentry. Nigdy nie rzuca."""
    label = KINDS.get(kind, (kind, 0))[0]
    logger.error(
        "[automation] %s failed: %s (job=%s)",
        label,
        (error_code or "error")[:80],
        job_id,
    )
    _known_clean.discard(kind)
    try:
        await _update(kind, error_code=error_code or "error", job_id=job_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[automation] streak not recorded: %s", type(exc).__name__)


async def record_success(kind: str) -> None:
    """Pierwszy sukces kończy serię. Nigdy nie rzuca."""
    if kind in _known_clean:
        return
    try:
        await _update(kind, error_code=None, job_id=None)
        _known_clean.add(kind)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[automation] streak not reset: %s", type(exc).__name__)


async def record_job_failure_event(
    db, *, job_id: int, action: str, error_code: Optional[str], **extra
) -> None:
    """Wpis awarii w „Pracy w tle" rekrutacji. Sesja i commit należą do wołającego."""
    from app.models.activity import Activity

    db.add(
        Activity(
            entity_type=ACTIVITY_ENTITY,
            entity_id=job_id,
            action=action,
            user_id=None,
            details=failure_details(error_code, **extra),
        )
    )
