"""Import kartotek z ``profiles`` Compassa do ``employee_profiles`` i pul urlopowych.

Reguły:

* osoba łączy się z kontem NEXUSA po e-mailu (bez wielkości liter); bez konta
  → pominięta z powodem „brak konta w NEXUSIE” (konto zakłada admin, import
  nie tworzy kont),
* konsultanci (rola ``consultant`` — Akademia) i osoby zewnętrzne
  (``is_external``) zostają w Compassie,
* kartoteka założona wcześniej ręcznie w NEXUSIE wygrywa: import dopina
  ``compass_profile_id`` i uzupełnia tylko puste pola (decyzja ``manual``
  w mapie id — kolejne przebiegi też tylko uzupełniają),
* przełożony z ``manager_id`` w drugim przebiegu, gdy obie osoby mają konta,
* pula urlopowa z Compassa (jedna, bez roku) trafia do bieżącego roku
  kalendarza firmy; ``NULL`` = brak puli, jak w Compassie,
* ``employment_type`` ``NULL`` Compass traktował jak umowę o pracę — tak samo tu,
  z powodem w raporcie.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.hr_ops import HrImportBatch
from app.models.hr_profile import EmployeeProfile, LeaveEntitlement
from app.models.user import User
from app.services.hr_foundation_schema import (
    EMPLOYMENT_STATUSES,
    EMPLOYMENT_TYPES,
    LOCATIONS,
)

from .bundle import Bundle
from .core import ModulePlan, RowPlan, mapped_target, remember

MODULE = "profiles"
TABLE = "profiles"

#: Pola kartoteki brane z Compassa (klucz NEXUSA ← wartość po normalizacji).
PROFILE_FIELDS = (
    "employment_type",
    "employment_status",
    "default_location",
    "hired_on",
    "work_start_date",
    "last_working_day",
    "can_log_overtime",
    "job_title",
    "department",
    "phone",
)
ENTITLEMENT_FIELDS = ("entitlement_days", "carried_over_days", "used_initial_days")


def source_id(row: Mapping[str, Any]) -> str:
    return f"{TABLE}:{row.get('id')}"


def _text(value: Any, limit: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).replace("\x00", "").strip()
    return text[:limit] or None


def _date(value: Any) -> Optional[date]:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _days(value: Any, *, default: Optional[Decimal]) -> Optional[Decimal]:
    if value is None:
        return default
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return default
    return number.quantize(Decimal("0.1"))


def normalize(row: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Wiersz Compassa → pola kartoteki NEXUSA + uwagi (powody do raportu)."""
    notes: list[str] = []
    employment_type = row.get("employment_type")
    if employment_type not in EMPLOYMENT_TYPES:
        notes.append("brak formy zatrudnienia — przyjęta umowa o pracę")
        employment_type = "uop"
    status = row.get("employment_status")
    if status not in EMPLOYMENT_STATUSES:
        notes.append("nieznany status — przyjęty „aktywny”")
        status = "active"
    location = row.get("default_location")
    if location not in LOCATIONS:
        location = "onsite"
    fields = {
        "employment_type": employment_type,
        "employment_status": status,
        "default_location": location,
        "hired_on": _date(row.get("hired_at")),
        "work_start_date": _date(row.get("work_start_date")),
        "last_working_day": _date(row.get("termination_date")),
        "can_log_overtime": bool(row.get("can_log_overtime")),
        "job_title": _text(row.get("job_title"), 200),
        "department": _text(row.get("department"), 200),
        "phone": _text(row.get("phone"), 64),
    }
    return fields, notes


def entitlement_values(row: Mapping[str, Any]) -> dict[str, Optional[Decimal]]:
    return {
        "entitlement_days": _days(row.get("leave_entitlement_days"), default=None),
        "carried_over_days": _days(
            row.get("leave_carried_over_days"), default=Decimal("0")
        ),
        "used_initial_days": _days(
            row.get("leave_used_initial_days"), default=Decimal("0")
        ),
    }


async def _users_by_email(db: AsyncSession) -> dict[str, int]:
    rows = (await db.execute(select(User.id, func.lower(User.email)))).all()
    return {email: user_id for user_id, email in rows if email}


async def plan(db: AsyncSession, bundle: Bundle) -> ModulePlan:
    result = ModulePlan(module=MODULE)
    users = await _users_by_email(db)
    rows = bundle.rows(TABLE)
    by_compass_id = {str(row.get("id")): row for row in rows}
    year = business_today().year

    for row in rows:
        sid = source_id(row)
        if not row.get("id") or not row.get("email"):
            result.rows.append(RowPlan(sid, "skip", "wiersz bez id albo e-maila"))
            continue
        if row.get("role") == "consultant":
            result.rows.append(RowPlan(sid, "skip", "konsultant — zostaje w Akademii"))
            continue
        if row.get("is_external"):
            result.rows.append(RowPlan(sid, "skip", "osoba zewnętrzna"))
            continue
        user_id = users.get(str(row["email"]).strip().lower())
        if user_id is None:
            result.rows.append(RowPlan(sid, "skip", "brak konta w NEXUSIE"))
            continue

        fields, notes = normalize(row)
        manager_user_id: Optional[int] = None
        manager_row = by_compass_id.get(str(row.get("manager_id")))
        if manager_row is not None and manager_row.get("email"):
            manager_user_id = users.get(str(manager_row["email"]).strip().lower())
            if manager_user_id == user_id:
                manager_user_id = None
        if row.get("manager_id") and manager_user_id is None:
            notes.append("przełożony bez konta w NEXUSIE")
        fields["manager_user_id"] = manager_user_id
        payload = {
            "user_id": user_id,
            "compass_profile_id": str(row["id"]),
            "fields": fields,
            "entitlement": entitlement_values(row),
            "year": year,
        }

        profile = await db.scalar(
            select(EmployeeProfile).where(EmployeeProfile.user_id == user_id)
        )
        mapping = await mapped_target(db, MODULE, sid)
        entitlement = await db.scalar(
            select(LeaveEntitlement).where(
                LeaveEntitlement.user_id == user_id, LeaveEntitlement.year == year
            )
        )
        reason = "; ".join(notes)
        if profile is None:
            result.rows.append(RowPlan(sid, "create", reason, payload))
            continue
        manual = mapping is None or mapping.decision == "manual"
        payload["manual"] = manual
        changes = _changes(profile, entitlement, payload, fill_only=manual)
        if not changes:
            result.rows.append(RowPlan(sid, "unchanged", reason, payload))
        elif manual:
            payload["changes"] = changes
            result.rows.append(
                RowPlan(
                    sid,
                    "conflict",
                    "kartoteka założona ręcznie w NEXUSIE — import tylko uzupełnia puste pola",
                    payload,
                )
            )
        else:
            payload["changes"] = changes
            result.rows.append(RowPlan(sid, "update", reason, payload))
    return result


def _changes(
    profile: EmployeeProfile,
    entitlement: Optional[LeaveEntitlement],
    payload: dict[str, Any],
    *,
    fill_only: bool,
) -> list[str]:
    changed: list[str] = []
    for key, value in payload["fields"].items():
        current = getattr(profile, key)
        if fill_only:
            if current in (None, "") and value not in (None, ""):
                changed.append(key)
        elif current != value:
            changed.append(key)
    linked = (
        None if profile.compass_profile_id is None else str(profile.compass_profile_id)
    )
    if linked is None or (not fill_only and linked != payload["compass_profile_id"]):
        changed.append("compass_profile_id")
    wanted = payload["entitlement"]
    if entitlement is None:
        changed.append("entitlement")
    elif not fill_only:
        for key in ENTITLEMENT_FIELDS:
            if getattr(entitlement, key) != wanted[key]:
                changed.append(f"entitlement.{key}")
                break
    return changed


async def apply(
    db: AsyncSession,
    module_plan: ModulePlan,
    batch: HrImportBatch,
    actor_user_id: Optional[int],
) -> dict[str, int]:
    written = {"profiles_created": 0, "profiles_updated": 0, "entitlements_written": 0}
    for row in module_plan.rows:
        if row.action not in ("create", "update", "conflict"):
            continue
        payload = row.payload
        user_id = payload["user_id"]
        manual = row.action == "conflict" or payload.get("manual", False)
        profile = await db.scalar(
            select(EmployeeProfile).where(EmployeeProfile.user_id == user_id)
        )
        if profile is None:
            profile = EmployeeProfile(user_id=user_id, updated_by=actor_user_id)
            db.add(profile)
            for key, value in payload["fields"].items():
                setattr(profile, key, value)
            written["profiles_created"] += 1
        else:
            for key, value in payload["fields"].items():
                current = getattr(profile, key)
                if manual and current not in (None, ""):
                    continue
                if value is None and manual:
                    continue
                setattr(profile, key, value)
            profile.updated_by = actor_user_id
            written["profiles_updated"] += 1
        if profile.compass_profile_id is None or not manual:
            profile.compass_profile_id = payload["compass_profile_id"]
        await db.flush()

        entitlement = await db.scalar(
            select(LeaveEntitlement).where(
                LeaveEntitlement.user_id == user_id,
                LeaveEntitlement.year == payload["year"],
            )
        )
        if entitlement is None:
            db.add(
                LeaveEntitlement(
                    user_id=user_id,
                    year=payload["year"],
                    reason="Import z Compassa",
                    set_by=actor_user_id,
                    **payload["entitlement"],
                )
            )
            written["entitlements_written"] += 1
        elif not manual:
            for key, value in payload["entitlement"].items():
                setattr(entitlement, key, value)
            entitlement.reason = "Import z Compassa"
            entitlement.set_by = actor_user_id
            written["entitlements_written"] += 1

        await remember(
            db,
            module=MODULE,
            source_id=row.source_id,
            target_table="employee_profiles",
            target_id=profile.id,
            decision="manual" if manual else "auto",
            batch=batch,
        )
    await db.flush()
    return written
