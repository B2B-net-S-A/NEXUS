"""„Składa raport godzin: tak / nie” dla wielu osób naraz (18.10.2026).

``employee_profiles.timesheet_required`` ma domyślnie ``true`` dla każdej
kartoteki, więc po imporcie przypomnienie 1.–5. dnia miesiąca
(``time_reminders``), kolejka akceptacji i raport płac liczyłyby raport
godzin także od osób, których Compass z niego zwalniał. Kadry ustawiają flagę
hurtem w „Ludzie → Katalog” — jak pion w „Strukturze”: kartoteki pod blokadą
wiersza, ślad ``profile_updated`` per zmieniona osoba.

Wartości na produkcji ustawiają Kadry albo admin — żadna migracja ich nie
zmienia.
"""

from __future__ import annotations

from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_profile import EmployeeProfile
from app.models.user import User
from app.services.hr import audit, people

MAX_PEOPLE = 200


async def set_timesheet_required(
    db: AsyncSession,
    *,
    user_ids: Collection[int],
    required: bool,
    actor: User,
) -> dict[str, list[int]]:
    """Flaga dla wybranych kartotek; brak którejś kartoteki = ``LookupError``."""

    ids = sorted(set(user_ids))
    if not ids:
        raise people.HrPeopleError("Wybierz co najmniej jedną osobę.")
    if len(ids) > MAX_PEOPLE:
        raise people.HrPeopleError(
            f"Naraz można zmienić najwyżej {MAX_PEOPLE} kartotek."
        )
    profiles = list(
        await db.scalars(
            select(EmployeeProfile)
            .where(EmployeeProfile.user_id.in_(ids))
            .order_by(EmployeeProfile.user_id)
            .with_for_update()
        )
    )
    if len(profiles) != len(ids):
        raise LookupError(sorted(set(ids) - {p.user_id for p in profiles}))
    changed: list[int] = []
    unchanged: list[int] = []
    for profile in profiles:
        if bool(profile.timesheet_required) == required:
            unchanged.append(profile.user_id)
            continue
        profile.timesheet_required = required
        profile.updated_by = actor.id
        audit.record(
            db,
            actor_user_id=actor.id,
            subject_user_id=profile.user_id,
            entity_type="employee_profile",
            entity_id=profile.id,
            action="profile_updated",
            details={
                "fields": ["timesheet_required"],
                "timesheet_required": required,
                "source": "directory",
            },
        )
        changed.append(profile.user_id)
    await db.flush()
    return {"changed": changed, "unchanged": unchanged}


__all__ = ["MAX_PEOPLE", "set_timesheet_required"]
