"""Kartoteki kont integracji OAuth — jednorazowe usunięcie (decyzja Artura 20.10.2026).

„Kartoteka idzie za kontem” (#2342, 19.10.2026) założyła kartotekę także
kontu, w którego imieniu działają scrapery (``oauth_clients.acting_user_id``),
więc stało ono w Akceptacjach → „Urlopy i timesheety” jako „Nie założony”.
Od tej zmiany ``people.is_staff_account`` takich kont nie liczy; tu znikają
kartoteki założone im wcześniej.

Usuwamy tylko kartotekę założoną z konta (``created_from_account``), bez
timesheetów, urlopów, obecności, stawek, dokumentów, spraw i podwładnych —
inna zostaje i trafia do paragonu jako pominięta. Każda kartoteka biegnie
w savepoincie. Jednorazowo (paragon w ``app_settings`` + advisory lock);
paragon i log niosą wyłącznie id i liczby.
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.services.hr import audit

logger = logging.getLogger(__name__)

REPAIR_MARKER = "hr_integration_profile_cleanup_2026_10_20"
REMOVED_ACTION = "profile_removed_integration_account"

#: Dane osoby, przy których kartoteki nie ruszamy (wszystkie po ``user_id``).
_HR_DATA_TABLES = (
    "timesheets",
    "attendance_days",
    "leave_requests",
    "leave_entitlements",
    "employee_rates",
    "payroll_lines",
    "hr_documents",
    "lifecycle_cases",
)

_HAS_HR_DATA_SQL = text(
    "SELECT "
    + " OR ".join(
        f"EXISTS (SELECT 1 FROM {table} WHERE user_id = :uid)"
        for table in _HR_DATA_TABLES
    )
    + " OR EXISTS (SELECT 1 FROM employee_profiles WHERE manager_user_id = :uid)"
)


async def run_integration_profile_cleanup(
    db: AsyncSession,
    *,
    marker: str = REPAIR_MARKER,
    only_user_ids: Optional[Collection[int]] = None,
) -> Optional[dict[str, Any]]:
    """Usuń kartoteki kont integracji raz; ``None`` = już wykonane.

    ``only_user_ids`` zawęża przebieg (testy na współdzielonej bazie).
    Wołający commituje.
    """

    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    if await db.get(AppSetting, marker) is not None:
        return None
    rows = (
        await db.execute(
            text(
                """
                SELECT ep.id, ep.user_id, ep.created_from_account
                FROM employee_profiles ep
                WHERE ep.user_id IN (
                    SELECT acting_user_id FROM oauth_clients
                    WHERE acting_user_id IS NOT NULL
                )
                ORDER BY ep.id
                """
            )
        )
    ).all()
    summary: dict[str, Any] = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "deleted_profiles": [],
        "skipped": {},
    }
    for profile_id, user_id, from_account in rows:
        if only_user_ids is not None and user_id not in only_user_ids:
            continue
        key = str(profile_id)
        if not from_account:
            summary["skipped"][key] = "not_created_from_account"
            continue
        if await db.scalar(_HAS_HR_DATA_SQL, {"uid": user_id}):
            summary["skipped"][key] = "has_hr_data"
            continue
        try:
            async with db.begin_nested():
                await db.execute(
                    text("DELETE FROM employee_profiles WHERE id = :id"),
                    {"id": profile_id},
                )
                audit.record(
                    db,
                    actor_user_id=None,
                    subject_user_id=user_id,
                    entity_type="employee_profile",
                    entity_id=profile_id,
                    action=REMOVED_ACTION,
                    details={"source": "integration_account_cleanup"},
                )
                await db.flush()
        except IntegrityError as exc:
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            summary["skipped"][key] = f"blocked_by_reference ({sqlstate})"
            continue
        summary["deleted_profiles"].append(profile_id)
    db.add(AppSetting(key=marker, value=summary))
    await db.flush()
    logger.info("hr integration profile cleanup: %s", summarize_for_log(summary))
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already applied"
    return (
        f"deleted profiles {len(summary['deleted_profiles'])}, "
        f"skipped {len(summary['skipped'])}"
    )


__all__ = [
    "REMOVED_ACTION",
    "REPAIR_MARKER",
    "run_integration_profile_cleanup",
    "summarize_for_log",
]
