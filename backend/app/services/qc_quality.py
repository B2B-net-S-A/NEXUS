"""„Jakość QC” — trafność sprawdzeń QC CV i ich stan (D6, 13.10.2026).

Trafność sprawdzenia = 1 − (pominięte jako „QC się myli” / pokazane) w oknie
30 dni. Pokazane to różne pozycje (para × klucz) we wszystkich przebiegach
okna: `items` i `dismissed_items`. Liczą się tylko powody „QC się myli”
(`cv_finding_dismissals.QC_WRONG_REASONS`) i tylko pominięcia, które nadal
trwają — przywrócone przez rekrutera albo przez zwrot karty nie są dowodem.

Decyzja Artura D6: podpowiedź (uwaga) z trafnością poniżej 70% przy co
najmniej 30 pokazanych sama staje się informacją (`muted` — widać ją, nie
liczy się do uwag). Blokady nigdy nie przechodzą same: poniżej 90% admin
dostaje jedno powiadomienie na serię. Admin może ustawić stan ręcznie
(`active` / `info` / `off`) — tylko dla uwag; stan ręczny wygrywa z automatem.

Stan leży w `app_settings['qc_check_states']`:
``{key: {"auto": "info"|None, "manual": "active"|"info"|"off"|None,
"precision": float|None, "shown": int, "since": iso|None, "alerted": bool}}``.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting

logger = logging.getLogger(__name__)

SETTING_KEY = "qc_check_states"
WINDOW_DAYS = 30
AUTO_MIN_SHOWN = 30
AUTO_INFO_BELOW = 0.70
ALERT_BLOCKING_BELOW = 0.90
MANUAL_STATES = ("active", "info", "off")


def _keys() -> tuple[tuple[str, ...], tuple[str, ...]]:
    from app.services.cv_qc import BLOCKING_KEYS, WARNING_KEYS

    return tuple(BLOCKING_KEYS), tuple(WARNING_KEYS)


async def load_states(db: AsyncSession) -> dict[str, dict[str, Any]]:
    value = await db.scalar(
        select(AppSetting.value).where(AppSetting.key == SETTING_KEY)
    )
    return dict(value) if isinstance(value, dict) else {}


def effective_states(states: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Stan każdej uwagi do policzenia QC: ręczny, potem automat, inaczej
    ``active``. Blokady zawsze ``active``."""
    blocking, warnings = _keys()
    out: dict[str, str] = {key: "active" for key in blocking}
    for key in warnings:
        entry = states.get(key) or {}
        manual = entry.get("manual")
        if manual in MANUAL_STATES:
            out[key] = manual
        elif entry.get("auto") == "info":
            out[key] = "info"
        else:
            out[key] = "active"
    return out


def apply_check_states(checks: list[dict], effective: dict[str, str]) -> None:
    """``info`` — sprawdzenie widać, ale nie liczy się do uwag (`muted`);
    ``off`` — nie dotyczy. Blokad nie dotyka."""
    for check in checks:
        state = effective.get(check["key"], "active")
        if check["severity"] == "blocking" or state == "active":
            continue
        if state == "info":
            check["muted"] = True
        elif state == "off":
            check["status"] = "skip"
            check["summary"] = "Wyłączone w „Jakość QC”"
            check["items"] = []


async def report(
    db: AsyncSession, *, now: Optional[datetime] = None
) -> dict[str, dict[str, Any]]:
    """Pokazane, pominięte jako błąd QC i trafność każdego sprawdzenia."""
    from app.models.cv_finding_dismissal import CvFindingDismissal
    from app.models.cv_qc_run import CvQcRun
    from app.services.cv_finding_dismissals import QC_WRONG_REASONS

    since = (now or datetime.now(timezone.utc)) - timedelta(days=WINDOW_DAYS)
    shown: dict[str, set[tuple[int, int, str]]] = defaultdict(set)
    rows = await db.execute(
        select(CvQcRun.candidate_id, CvQcRun.job_id, CvQcRun.result).where(
            CvQcRun.created_at >= since
        )
    )
    for candidate_id, job_id, result in rows:
        for check in (result or {}).get("checks") or []:
            key = check.get("key")
            if not key:
                continue
            for item in [
                *(check.get("items") or []),
                *(check.get("dismissed_items") or []),
            ]:
                if item.get("key"):
                    shown[key].add((candidate_id, job_id, item["key"]))
    wrong: dict[str, set[tuple[int, int, str]]] = defaultdict(set)
    reasons: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    dismissals = await db.execute(
        select(
            CvFindingDismissal.candidate_id,
            CvFindingDismissal.job_id,
            CvFindingDismissal.check_key,
            CvFindingDismissal.finding_key,
            CvFindingDismissal.reason,
        ).where(
            CvFindingDismissal.source == "qc",
            CvFindingDismissal.restored_at.is_(None),
            CvFindingDismissal.created_at >= since,
        )
    )
    for candidate_id, job_id, check_key, finding_key, reason in dismissals:
        reasons[check_key][reason] += 1
        if reason in QC_WRONG_REASONS:
            wrong[check_key].add((candidate_id, job_id, finding_key))
    blocking, warnings = _keys()
    out: dict[str, dict[str, Any]] = {}
    for key in (*blocking, *warnings):
        count = len(shown[key])
        wrong_count = len(wrong[key] & shown[key]) if count else len(wrong[key])
        out[key] = {
            "shown": count,
            "dismissed_wrong": wrong_count,
            "reasons": dict(reasons[key]),
            "precision": round(1 - wrong_count / count, 3) if count else None,
            "blocking": key in blocking,
        }
    return out


async def _locked_states(db: AsyncSession) -> AppSetting:
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    await db.execute(
        pg_insert(AppSetting)
        .values(key=SETTING_KEY, value={})
        .on_conflict_do_nothing(index_elements=[AppSetting.key])
    )
    row = await db.scalar(
        select(AppSetting)
        .where(AppSetting.key == SETTING_KEY)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert row is not None
    return row


async def refresh_states(
    db: AsyncSession, *, now: Optional[datetime] = None
) -> dict[str, dict[str, Any]]:
    """Zadanie dzienne: trafność → automat ``info`` dla uwag, alert dla
    blokad. Bez commitu."""
    now = now or datetime.now(timezone.utc)
    numbers = await report(db, now=now)
    row = await _locked_states(db)
    states = {k: dict(v) for k, v in (row.value or {}).items() if isinstance(v, dict)}
    alerts: list[tuple[str, float]] = []
    for key, stats in numbers.items():
        entry = states.get(key, {})
        precision = stats["precision"]
        enough = stats["shown"] >= AUTO_MIN_SHOWN and precision is not None
        entry["precision"] = precision
        entry["shown"] = stats["shown"]
        if stats["blocking"]:
            low = enough and precision < ALERT_BLOCKING_BELOW
            if low and not entry.get("alerted"):
                alerts.append((key, precision))
            entry["alerted"] = bool(low)
        else:
            low = enough and precision < AUTO_INFO_BELOW
            if low and entry.get("auto") != "info":
                entry["auto"], entry["since"] = "info", now.isoformat()
            elif not low and entry.get("auto") == "info":
                entry["auto"], entry["since"] = None, now.isoformat()
        states[key] = entry
    row.value = states
    for key, precision in alerts:
        await _alert_admins(db, key, precision)
    return states


async def set_manual(
    db: AsyncSession, key: str, state: Optional[str], *, user_id: int
) -> dict[str, dict[str, Any]]:
    """Ręczny stan uwagi (``None`` = wróć do automatu). Bez commitu."""
    _, warnings = _keys()
    if key not in warnings:
        raise ValueError("Ręczny stan można ustawić tylko dla uwag, nie blokad.")
    if state is not None and state not in MANUAL_STATES:
        raise ValueError("Nieznany stan sprawdzenia.")
    row = await _locked_states(db)
    states = {k: dict(v) for k, v in (row.value or {}).items() if isinstance(v, dict)}
    entry = states.get(key, {})
    entry["manual"] = state
    entry["manual_by"] = user_id
    entry["manual_at"] = datetime.now(timezone.utc).isoformat()
    states[key] = entry
    row.value = states
    row.updated_by = user_id
    return states


async def _alert_admins(db: AsyncSession, key: str, precision: float) -> None:
    from app.models.notification import NotificationType
    from app.models.user import User
    from app.services.cv_qc import LABELS
    from app.services.notification_triggers import emit

    admins = (
        await db.scalars(
            select(User.id).where(
                User.is_active.is_(True), User.roles.contains(["admin"])
            )
        )
    ).all()
    label = LABELS.get(key, key)
    for user_id in admins:
        await emit(
            db,
            user_id=user_id,
            title=f"QC CV: blokada „{label}” myli się zbyt często"[:255],
            message=(
                f"Trafność {round(precision * 100)}% z ostatnich {WINDOW_DAYS} dni "
                "(rekruterzy oznaczają jej uwagi jako nieprawdziwe). Blokada działa "
                "dalej — sprawdź pominięcia w „Jakość QC”."
            ),
            ntype=NotificationType.automation_failing,
            related_entity_type="qc_check",
            related_entity_id=None,
            link="/settings/ai/qc-quality",
        )
