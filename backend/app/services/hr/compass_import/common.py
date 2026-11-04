"""Wspólne klocki importerów modułów: osoby, daty, teksty, mapa id.

Osoba Compassa (``profiles.id``) staje się kontem NEXUSA w tej kolejności:

1. mapa id kartotek (``module='profiles'``, ``profiles:<uuid>`` →
   ``employee_profiles.id`` → ``user_id``),
2. kartoteka z dopiętym ``compass_profile_id`` (kartoteka ręczna),
3. e-mail z tabeli ``profiles`` paczki → konto NEXUSA (bez wielkości liter).

``subject`` zwraca konto tylko wtedy, gdy osoba ma kartotekę — urlopy,
timesheety, stawki i sprawy dotyczą osób z kartoteką. ``account`` wystarcza
dla ról pobocznych (kto zdecydował, zastępca, autor, przypisany).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ
from app.models.hr_ops import HrImportIdMap
from app.models.hr_profile import EmployeeProfile
from app.models.user import User

from .bundle import Bundle
from .core import ModulePlan

NO_PROFILE = "osoba bez kartoteki w NEXUSIE"
_ZONE = ZoneInfo(DEFAULT_TZ)


@dataclass
class ImportPlan(ModulePlan):
    """Plan z dodatkowymi licznikami w raporcie (same liczby, bez kwot)."""

    extra: dict[str, Any] = field(default_factory=dict)

    def report(self) -> dict[str, Any]:
        report = super().report()
        if self.extra:
            report["extra"] = self.extra
        return report


def source_id(table: str, row: Mapping[str, Any]) -> str:
    return f"{table}:{row.get('id')}"


def text(value: Any, limit: Optional[int] = None) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).replace("\x00", "").strip()
    if limit is not None:
        cleaned = cleaned[:limit].strip()
    return cleaned or None


def parse_date(value: Any) -> Optional[date]:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def parse_datetime(value: Any) -> Optional[datetime]:
    """Znacznik czasu z Compassa; bez strefy = UTC (tak zapisuje Supabase)."""

    if value in (None, ""):
        return None
    raw = str(value).strip().replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def local_date(value: Any) -> Optional[date]:
    """Dzień kalendarza firmy dla znacznika czasu (sama data zostaje datą)."""

    if value in (None, ""):
        return None
    if len(str(value).strip()) == 10:
        return parse_date(value)
    moment = parse_datetime(value)
    return None if moment is None else moment.astimezone(_ZONE).date()


def decimal(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def parse_uuid(value: Any) -> Optional[uuid.UUID]:
    if value in (None, ""):
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def small_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def join_notes(notes: Iterable[str]) -> str:
    return "; ".join(note for note in notes if note)


def changed_fields(obj: Any, values: Mapping[str, Any]) -> list[str]:
    return [key for key, value in values.items() if getattr(obj, key) != value]


async def module_map(db: AsyncSession, module: str) -> dict[str, HrImportIdMap]:
    rows = await db.scalars(select(HrImportIdMap).where(HrImportIdMap.module == module))
    return {row.source_id: row for row in rows}


@dataclass
class People:
    accounts: dict[str, int]
    profiles: dict[int, EmployeeProfile]
    rows: dict[str, Mapping[str, Any]]

    def account(self, compass_id: Any) -> Optional[int]:
        if compass_id in (None, ""):
            return None
        return self.accounts.get(str(compass_id))

    def subject(self, compass_id: Any) -> Optional[int]:
        user_id = self.account(compass_id)
        return user_id if user_id in self.profiles else None

    def profile(self, user_id: Optional[int]) -> Optional[EmployeeProfile]:
        return None if user_id is None else self.profiles.get(user_id)

    def compass_row(self, compass_id: Any) -> Optional[Mapping[str, Any]]:
        return self.rows.get(str(compass_id))


async def load_people(db: AsyncSession, bundle: Bundle) -> People:
    profiles = {
        profile.user_id: profile
        for profile in await db.scalars(select(EmployeeProfile))
    }
    by_profile_id = {profile.id: profile.user_id for profile in profiles.values()}
    accounts: dict[str, int] = {}
    rows = {str(row.get("id")): row for row in bundle.rows("profiles") if row.get("id")}

    users_by_email = {
        email: user_id
        for user_id, email in (
            await db.execute(select(User.id, func.lower(User.email)))
        ).all()
        if email
    }
    for compass_id, row in rows.items():
        email = str(row.get("email") or "").strip().lower()
        if email and email in users_by_email:
            accounts[compass_id] = users_by_email[email]
    for profile in profiles.values():
        if profile.compass_profile_id is not None:
            accounts[str(profile.compass_profile_id)] = profile.user_id
    for mapping in await db.scalars(
        select(HrImportIdMap).where(
            HrImportIdMap.module == "profiles",
            HrImportIdMap.target_table == "employee_profiles",
        )
    ):
        compass_id = mapping.source_id.split(":", 1)[-1]
        try:
            user_id = by_profile_id.get(int(mapping.target_id))
        except ValueError:
            user_id = None
        if user_id is not None:
            accounts[compass_id] = user_id
    return People(accounts=accounts, profiles=profiles, rows=rows)
