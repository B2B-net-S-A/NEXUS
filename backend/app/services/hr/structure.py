"""„Ludzie → Struktura” (etap 2, D4 i D7, 17.10.2026): kto komu podlega.

* ``structure`` — płaska lista kartotek (wszystkie poza ``exited``, jak
  ``people.direct_report_ids``) z przełożonym, liczbą bezpośrednich
  podwładnych, odejściem w toku i podpowiedzią rozjazdu z Microsoft 365.
  Drzewo układa front (``components/hr/structure/structure-tree.ts``).
* ``reassign`` — zmiana przełożonego wielu osób naraz. Działa OD RAZU: bez
  daty „od kiedy” z makiety, bo kartoteka nie ma harmonogramu zmian. Wnioski
  urlopowe i timesheety w toku przechodzą do nowego przełożonego, bo
  akceptującego liczy się w chwili decyzji (``leave_service._decision_scope``,
  ``time_access.Actor.can_approve``). Reguły jak w kartotece
  (``people.validate_managers``: nie sam sobie, aktywne konto, bez pętli —
  dla całego zbioru naraz), ślad ``profile_updated`` per osoba.

Piony (decyzja Artura 17.10.2026): kartoteka ma ``division`` (Front office —
sprzedaż i rekrutacja do podpisania zamówienia, Back office — opieka,
administracja, rozliczenia), a head każdego pionu stoi w
``app_settings['hr_divisions']``. Ekran grupuje drzewo najpierw po pionie;
osoba w pionie z headem i bez przełożonego dostaje podpowiedź „przełożony =
head pionu” (``suggested_manager``) — bez automatycznego zapisu.

Microsoft 365 tylko podpowiada (D7): dzienna synchronizacja profili zapisuje
w ``employee_profiles.m365_manager_upn`` przełożonego z katalogu; gdy różni
się od przełożonego w kartotece, ekran pokazuje rozjazd z „Przyjmij” (= zwykła
zmiana przełożonego). Bez cichej zmiany kartoteki.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection
from typing import Any, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.hr_lifecycle import LifecycleCase, WorkHandover
from app.models.hr_profile import EmployeeProfile
from app.models.user import User
from app.services.hr import audit, people
from app.services.hr_foundation_schema import DIVISIONS, HR_DIVISIONS_SETTING
from app.services.hr_lifecycle_schema import LIVE_CASE_STATUSES

#: Górna granica jednej zmiany (zespół to dziś kilkadziesiąt osób).
MAX_REASSIGN = 200

#: Stan przełożonego wskazanego w kartotece.
#: ``none`` — brak, ``ok`` — osoba z kartoteką w strukturze,
#: ``no_profile`` — aktywne konto bez kartoteki (np. zarząd),
#: ``inactive`` — konto wyłączone albo kartoteka „zakończył współpracę”.
MANAGER_STATES = ("none", "ok", "no_profile", "inactive")

DIVISION_LABELS: dict[str, str] = {
    "front_office": "Front office",
    "back_office": "Back office",
}


async def load_division_heads(db: AsyncSession) -> dict[str, Optional[int]]:
    """Head każdego pionu (``None`` = nie ustawiono). Nieznane klucze pomijamy."""

    raw = await db.scalar(
        select(AppSetting.value).where(AppSetting.key == HR_DIVISIONS_SETTING)
    )
    heads: dict[str, Optional[int]] = {key: None for key in DIVISIONS}
    if isinstance(raw, dict):
        for key in DIVISIONS:
            value = raw.get(key)
            heads[key] = value if isinstance(value, int) and value > 0 else None
    return heads


async def set_division_heads(
    db: AsyncSession, *, heads: dict[str, Optional[int]], actor: User
) -> dict[str, Optional[int]]:
    """Zapis headów pionów (Kadry, admin): aktywne konta, jeden head na pion."""

    unknown = sorted(set(heads) - set(DIVISIONS))
    if unknown:
        raise people.HrPeopleError("Nieznany pion firmy.")
    current = await load_division_heads(db)
    merged = {**current, **heads}
    for user_id in {value for value in merged.values() if value is not None}:
        user = await db.get(User, user_id)
        if user is None or not user.is_active:
            raise people.HrPeopleError("Head pionu musi mieć aktywne konto.")
    await db.execute(
        pg_insert(AppSetting)
        .values(key=HR_DIVISIONS_SETTING, value=merged, updated_by=actor.id)
        .on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": merged, "updated_by": actor.id, "updated_at": func.now()},
        )
    )
    changed = sorted(key for key in DIVISIONS if current[key] != merged[key])
    if changed:
        audit.record(
            db,
            actor_user_id=actor.id,
            subject_user_id=None,
            entity_type="hr_divisions",
            entity_id=None,
            action="division_heads_set",
            details={key: merged[key] for key in changed},
        )
    await db.flush()
    return merged


def _addresses(user: User) -> set[str]:
    return {
        value.strip().lower()
        for value in (user.email, user.microsoft_upn)
        if value and value.strip()
    }


async def _users_by_address(db: AsyncSession, upns: set[str]) -> dict[str, User]:
    """Konta NEXUSA po adresie z katalogu (UPN albo e-mail, bez wielkości liter)."""

    if not upns:
        return {}
    rows = await db.scalars(
        select(User).where(
            or_(
                func.lower(User.email).in_(sorted(upns)),
                func.lower(User.microsoft_upn).in_(sorted(upns)),
            )
        )
    )
    found: dict[str, User] = {}
    for user in rows:
        for address in _addresses(user) & upns:
            # Aktywne konto wygrywa z wyłączonym tym samym adresem.
            if address not in found or (
                user.is_active and not found[address].is_active
            ):
                found[address] = user
    return found


async def _leaving(
    db: AsyncSession, user_ids: Collection[int]
) -> dict[int, dict[str, Any]]:
    """Żywe sprawy odejścia (szkic albo w toku) i przejmujący podwładnych."""

    if not user_ids:
        return {}
    cases = list(
        await db.scalars(
            select(LifecycleCase).where(
                LifecycleCase.kind == "offboarding",
                LifecycleCase.status.in_(LIVE_CASE_STATUSES),
                LifecycleCase.user_id.in_(sorted(user_ids)),
            )
        )
    )
    if not cases:
        return {}
    rows = {
        row.case_id: row
        for row in await db.scalars(
            select(WorkHandover).where(
                WorkHandover.case_id.in_([case.id for case in cases]),
                WorkHandover.work_kind == "reports",
            )
        )
    }
    result: dict[int, dict[str, Any]] = {}
    for case in cases:
        row = rows.get(case.id)
        # Bez wiersza przekazania (sprawa sprzed etapu 2) plan wybierze
        # przełożonego z ostatniego zapisu sprawy — ten sam domyślny wybór.
        receiver_id = row.receiver_user_id if row is not None else case.manager_user_id
        result[int(case.user_id)] = {
            "case_id": case.id,
            "status": case.status,
            "last_working_day": case.last_working_day,
            "reports_receiver_user_id": receiver_id,
            "reports_handover_status": row.status if row is not None else None,
        }
    return result


async def structure(db: AsyncSession) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(EmployeeProfile, User)
            .join(User, User.id == EmployeeProfile.user_id)
            .where(EmployeeProfile.employment_status != "exited")
            .order_by(User.name, User.id)
        )
    ).all()
    in_tree = {profile.user_id for profile, _ in rows}
    reports = Counter(
        profile.manager_user_id for profile, _ in rows if profile.manager_user_id
    )
    leaving = await _leaving(db, in_tree)

    outside_ids = {
        profile.manager_user_id
        for profile, _ in rows
        if profile.manager_user_id and profile.manager_user_id not in in_tree
    }
    receiver_ids = {
        item["reports_receiver_user_id"]
        for item in leaving.values()
        if item["reports_receiver_user_id"]
    }
    heads = await load_division_heads(db)
    head_ids = {value for value in heads.values() if value is not None}
    known: dict[int, User] = {user.id: user for _, user in rows}
    missing = (outside_ids | receiver_ids | head_ids) - set(known)
    if missing:
        for user in await db.scalars(select(User).where(User.id.in_(sorted(missing)))):
            known[user.id] = user
    exited_outside = set()
    if outside_ids:
        exited_outside = set(
            await db.scalars(
                select(EmployeeProfile.user_id).where(
                    EmployeeProfile.user_id.in_(sorted(outside_ids)),
                    EmployeeProfile.employment_status == "exited",
                )
            )
        )

    upns = {
        profile.m365_manager_upn.strip().lower()
        for profile, _ in rows
        if profile.m365_manager_upn and profile.m365_manager_upn.strip()
    }
    by_address = await _users_by_address(db, upns)

    def manager_state(manager_id: Optional[int]) -> str:
        if manager_id is None:
            return "none"
        manager = known.get(manager_id)
        if manager is None or not manager.is_active or manager_id in exited_outside:
            return "inactive"
        return "ok" if manager_id in in_tree else "no_profile"

    people_rows: list[dict[str, Any]] = []
    for profile, user in rows:
        manager = (
            known.get(profile.manager_user_id) if profile.manager_user_id else None
        )
        hint = None
        upn = (profile.m365_manager_upn or "").strip().lower()
        if upn and (manager is None or upn not in _addresses(manager)):
            match = by_address.get(upn)
            hint = {
                "upn": upn,
                "user_id": match.id if match is not None else None,
                "name": match.name if match is not None else None,
                # „Przyjmij” tylko dla aktywnego konta innego niż sama osoba;
                # pętlę i resztę reguł sprawdza zapis.
                "can_accept": match is not None
                and match.is_active
                and match.id != user.id,
            }
        suggested = None
        head_id = heads.get(profile.division) if profile.division else None
        head = known.get(head_id) if head_id else None
        if (
            profile.manager_user_id is None
            and head is not None
            and head.is_active
            and head.id != user.id
        ):
            suggested = {"user_id": head.id, "name": head.name}
        leave = leaving.get(user.id)
        if leave is not None:
            receiver_id = leave["reports_receiver_user_id"]
            receiver = known.get(receiver_id) if receiver_id else None
            leave = {
                **leave,
                "last_working_day": leave["last_working_day"].isoformat(),
                "reports_receiver_name": receiver.name if receiver else None,
            }
        people_rows.append(
            {
                "user_id": user.id,
                "name": user.name,
                "email": user.email,
                "job_title": profile.job_title,
                "department": profile.department,
                "employment_type": profile.employment_type,
                "employment_status": profile.employment_status,
                "division": profile.division,
                "manager_user_id": profile.manager_user_id,
                "manager_name": manager.name if manager else None,
                "manager_state": manager_state(profile.manager_user_id),
                "reports": reports.get(user.id, 0),
                "leaving": leave,
                "m365_hint": hint,
                "suggested_manager": suggested,
            }
        )
    outside = [
        {
            "user_id": manager_id,
            "name": known[manager_id].name if manager_id in known else None,
            "state": manager_state(manager_id),
            "reports": reports.get(manager_id, 0),
        }
        for manager_id in sorted(outside_ids)
    ]
    divisions = [
        {
            "key": key,
            "label": DIVISION_LABELS[key],
            "head_user_id": heads[key],
            "head_name": known[heads[key]].name if heads[key] in known else None,
            "head_active": bool(heads[key] in known and known[heads[key]].is_active),
        }
        for key in DIVISIONS
    ]
    return {
        "people": people_rows,
        "outside_managers": outside,
        "divisions": divisions,
        "total": len(people_rows),
        # Bez przełożonego i bez podwładnych (szczyt drzewa z ludźmi pod sobą
        # to nie „sierota”), poza headami pionów.
        "without_manager": sum(
            1
            for row in people_rows
            if row["manager_state"] == "none"
            and row["reports"] == 0
            and row["user_id"] not in head_ids
        ),
        "inactive_manager": sum(
            1 for row in people_rows if row["manager_state"] == "inactive"
        ),
        "m365_mismatches": sum(1 for row in people_rows if row["m365_hint"]),
    }


async def reassign(
    db: AsyncSession,
    *,
    user_ids: Collection[int],
    manager_user_id: Optional[int],
    actor: User,
) -> dict[str, list[int]]:
    """Nowy przełożony dla wielu osób naraz — od razu, ślad per osoba."""

    ids = sorted(set(user_ids))
    if not ids:
        raise people.HrPeopleError("Wybierz co najmniej jedną osobę.")
    if len(ids) > MAX_REASSIGN:
        raise people.HrPeopleError(
            f"Naraz można zmienić przełożonego najwyżej {MAX_REASSIGN} osobom."
        )
    await people.lock_structure(db)
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
    if any(profile.employment_status == "exited" for profile in profiles):
        raise people.HrPeopleError(
            "Wśród wybranych jest osoba, która zakończyła współpracę — odśwież "
            "stronę i wybierz ponownie."
        )
    await people.validate_managers(db, user_ids=ids, manager_user_id=manager_user_id)
    changed: list[int] = []
    unchanged: list[int] = []
    for profile in profiles:
        if profile.manager_user_id == manager_user_id:
            unchanged.append(profile.user_id)
            continue
        previous = profile.manager_user_id
        profile.manager_user_id = manager_user_id
        profile.updated_by = actor.id
        audit.record(
            db,
            actor_user_id=actor.id,
            subject_user_id=profile.user_id,
            entity_type="employee_profile",
            entity_id=profile.id,
            action="profile_updated",
            details={
                "fields": ["manager_user_id"],
                "source": "structure",
                "previous_manager_user_id": previous,
                "manager_user_id": manager_user_id,
            },
        )
        changed.append(profile.user_id)
    await db.flush()
    return {"changed": changed, "unchanged": unchanged}


async def set_division(
    db: AsyncSession,
    *,
    user_ids: Collection[int],
    division: Optional[str],
    actor: User,
) -> dict[str, list[int]]:
    """Pion dla wielu osób naraz (jak „Zmień przełożonego”), ślad per osoba."""

    ids = sorted(set(user_ids))
    if not ids:
        raise people.HrPeopleError("Wybierz co najmniej jedną osobę.")
    if len(ids) > MAX_REASSIGN:
        raise people.HrPeopleError(
            f"Naraz można zmienić pion najwyżej {MAX_REASSIGN} osobom."
        )
    if division is not None and division not in DIVISIONS:
        raise people.HrPeopleError("Nieznany pion firmy.")
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
        if profile.division == division:
            unchanged.append(profile.user_id)
            continue
        profile.division = division
        profile.updated_by = actor.id
        audit.record(
            db,
            actor_user_id=actor.id,
            subject_user_id=profile.user_id,
            entity_type="employee_profile",
            entity_id=profile.id,
            action="profile_updated",
            details={"fields": ["division"], "source": "structure"},
        )
        changed.append(profile.user_id)
    await db.flush()
    return {"changed": changed, "unchanged": unchanged}


__all__ = [
    "DIVISION_LABELS",
    "MANAGER_STATES",
    "MAX_REASSIGN",
    "load_division_heads",
    "reassign",
    "set_division",
    "set_division_heads",
    "structure",
]
