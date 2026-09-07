"""One source of availability and effective operational ownership.

Ownership is never rewritten for a leave: every read and command can resolve
the same original owner. A valid cached delegation expires at its known end
even if COMPASS is temporarily unreachable. New allocation requires fresh data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import object_session

from app.core.config import settings
from app.models.recruitment_allocation import (
    RecruitmentAllocationEvent,
    WorkforceAvailabilityState,
)
from app.models.user import User

WARSAW = ZoneInfo("Europe/Warsaw")
STALE_SECONDS = 300
OPERATIONAL_COVER_ROLES = frozenset(
    {"recruiter", "sourcer", "tac", "delivery_lead", "head_of_recruitment", "admin"}
)


class AvailabilityAbsence(BaseModel):
    id: UUID
    start_date: date
    end_date: date
    substitute_id: UUID | None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.start_date > self.end_date:
            raise ValueError("Invalid absence interval")
        return self


class AvailabilityPerson(BaseModel):
    id: UUID
    email: str = Field(min_length=3)
    employment_status: str
    available: bool
    absences: list[AvailabilityAbsence]


class AvailabilitySnapshot(BaseModel):
    schema_version: Literal[1]
    basis: Literal["calendar_full_day_approved_absences"]
    complete: Literal[True]
    generated_at: datetime
    date: date
    working_day: bool
    window_end: date
    count: int = Field(gt=0)
    snapshot_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    people: list[AvailabilityPerson] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_complete(self):
        if (
            self.count != len(self.people)
            or len({p.id for p in self.people}) != self.count
        ):
            raise ValueError("Incomplete or duplicate workforce snapshot")
        if self.generated_at.tzinfo is None or self.window_end < self.date:
            raise ValueError("Invalid snapshot clock")
        for person in self.people:
            if person.available and (
                not self.working_day
                or person.employment_status not in {"active", "offboarding"}
                or any(a.start_date <= self.date <= a.end_date for a in person.absences)
            ):
                raise ValueError("Conflicting availability")
        return self


@dataclass(frozen=True)
class Delegation:
    owner_id: int
    performer_id: int
    start_date: date
    end_date: date
    source_ids: tuple[str, ...]

    def as_payload(self) -> dict:
        return {
            "owner_id": self.owner_id,
            "performer_id": self.performer_id,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "source_ids": list(self.source_ids),
        }


@dataclass
class WorkforceContext:
    fresh: bool = False
    snapshot_version: str | None = None
    generated_at: datetime | None = None
    available_ids: set[int] = field(default_factory=set)
    people: dict[int, AvailabilityPerson] = field(default_factory=dict)
    delegations: dict[int, Delegation] = field(default_factory=dict)
    issues: list[dict] = field(default_factory=list)

    def performer(self, owner_id: int | None) -> int | None:
        delegation = self.delegations.get(owner_id)
        return delegation.performer_id if delegation else owner_id

    def owners_for(self, performer_id: int) -> set[int]:
        owners = (
            {performer_id} if self.performer(performer_id) == performer_id else set()
        )
        owners.update(
            owner
            for owner, item in self.delegations.items()
            if item.performer_id == performer_id
        )
        return owners


def _roles(user: User) -> set[str]:
    values = [getattr(user, "role", None), *(getattr(user, "roles", None) or [])]
    return {str(getattr(value, "value", value)) for value in values if value}


def compatible_substitute(owner: User, substitute: User) -> bool:
    target_roles = _roles(substitute)
    if "admin" in target_roles:
        return True
    capability_groups = {
        "recruiter": {"recruiter", "tac"},
        "sourcer": {"sourcer", "recruiter", "tac"},
        "tac": {"tac"},
        "delivery_lead": {"delivery_lead"},
        "head_of_recruitment": {"head_of_recruitment"},
    }
    required = _roles(owner) & capability_groups.keys()
    return bool(required) and all(
        target_roles & capability_groups[role] for role in required
    )


def resolve_workforce(
    snapshot: AvailabilitySnapshot | None,
    users: list[User],
    *,
    now: datetime,
    last_success_at: datetime | None,
) -> WorkforceContext:
    context = WorkforceContext()
    if snapshot is None:
        context.issues.append({"code": "availability_unavailable"})
        return context
    today = now.astimezone(WARSAW).date()
    success = last_success_at
    if success is not None and success.tzinfo is None:
        success = success.replace(tzinfo=timezone.utc)
    age = (now - snapshot.generated_at).total_seconds()
    context.fresh = bool(
        success
        and -60 <= age <= STALE_SECONDS
        and 0 <= (now - success).total_seconds() <= STALE_SECONDS
        and snapshot.date == today
    )
    context.snapshot_version = snapshot.snapshot_version
    context.generated_at = snapshot.generated_at
    if not context.fresh:
        context.issues.append({"code": "availability_stale"})

    by_email: dict[str, list[AvailabilityPerson]] = {}
    for person in snapshot.people:
        by_email.setdefault(person.email.strip().casefold(), []).append(person)
    users_by_email: dict[str, list[User]] = {}
    active = {user.id: user for user in users if user.is_active}
    for user in active.values():
        users_by_email.setdefault(user.email.strip().casefold(), []).append(user)
    source_to_user: dict[UUID, int] = {}
    for user in active.values():
        key = user.email.strip().casefold()
        matches = by_email.get(key, [])
        if len(matches) != 1 or len(users_by_email[key]) != 1:
            if _roles(user) & OPERATIONAL_COVER_ROLES:
                context.issues.append(
                    {
                        "user_id": user.id,
                        "code": "identity_ambiguous" if matches else "identity_missing",
                    }
                )
            continue
        person = matches[0]
        context.people[user.id] = person
        source_to_user[person.id] = user.id
        if context.fresh and person.available:
            context.available_ids.add(user.id)

    for owner_id, person in context.people.items():
        absences = [
            item
            for item in person.absences
            if item.start_date <= today <= item.end_date
        ]
        if not absences:
            continue
        substitutes = {item.substitute_id for item in absences}
        code = None
        performer_id = None
        if len(substitutes) != 1:
            code = "substitution_conflict"
        elif None in substitutes:
            code = "substitute_missing"
        else:
            performer_id = source_to_user.get(next(iter(substitutes)))
            substitute = context.people.get(performer_id)
            if performer_id == owner_id:
                code = "substitution_cycle"
            elif substitute is None:
                code = "substitute_unmapped"
            elif not compatible_substitute(active[owner_id], active[performer_id]):
                code = "substitute_role_invalid"
            elif substitute.employment_status not in {"active", "offboarding"}:
                code = "substitute_unavailable"
            elif any(
                item.start_date <= today <= item.end_date
                for item in substitute.absences
            ):
                code = "substitute_absent"
            elif (
                snapshot.date == today
                and snapshot.working_day
                and not substitute.available
            ):
                code = "substitute_unavailable"
        if code:
            context.issues.append(
                {"user_id": owner_id, "substitute_id": performer_id, "code": code}
            )
            continue
        context.delegations[owner_id] = Delegation(
            owner_id=owner_id,
            performer_id=performer_id,
            start_date=min(item.start_date for item in absences),
            end_date=max(item.end_date for item in absences),
            source_ids=tuple(sorted(str(item.id) for item in absences)),
        )
    return context


async def workforce_context(
    db: AsyncSession, *, refresh: bool = False
) -> WorkforceContext:
    if not settings.COMPASS_AVAILABILITY_ENABLED:
        return WorkforceContext()
    key = "workforce_context"
    if not refresh and key in db.info:
        return db.info[key]
    state = await db.get(WorkforceAvailabilityState, 1)
    snapshot = (
        AvailabilitySnapshot.model_validate(state.snapshot)
        if state and state.snapshot
        else None
    )
    users = list((await db.scalars(select(User).where(User.is_active.is_(True)))).all())
    context = resolve_workforce(
        snapshot,
        users,
        now=datetime.now(timezone.utc),
        last_success_at=state.last_success_at if state else None,
    )
    if context.delegations:
        from app.services.section_permissions import (
            ProductSection,
            SectionAccess,
            resolve_effective_section_access_for_users,
            section_access_for_user,
        )

        await resolve_effective_section_access_for_users(db, users)
        by_id = {user.id: user for user in users}
        for owner_id, delegation in list(context.delegations.items()):
            substitute = by_id[delegation.performer_id]
            if any(
                section_access_for_user(substitute, section) < SectionAccess.write
                for section in (ProductSection.pipeline, ProductSection.sourcing)
            ):
                context.delegations.pop(owner_id)
                context.issues.append(
                    {
                        "code": "substitute_role_invalid",
                        "user_id": owner_id,
                        "performer_id": substitute.id,
                    }
                )
    db.info[key] = context
    return context


async def effective_owner_ids(db: AsyncSession, user_id: int) -> set[int]:
    return (await workforce_context(db)).owners_for(user_id)


async def effective_owner_id(db: AsyncSession, owner_id: int | None) -> int | None:
    return (await workforce_context(db)).performer(owner_id)


def operational_owner_ids(user: User) -> set[int]:
    """Use request-session context without adding serializable attributes to User."""
    session = object_session(user) if hasattr(user, "_sa_instance_state") else None
    context = session.info.get("workforce_context") if session is not None else None
    return context.owners_for(user.id) if context is not None else {user.id}


def open_operational_job_clause(job_id_column, owners: set[int]):
    """Closed jobs remain actionable only through an explicitly owned open task."""
    from sqlalchemy import func
    from app.models.calendar_event import CalendarEvent, EventStatus
    from app.models.recruitment_process import RecruitmentProcess, ProcessStatus

    processes = select(RecruitmentProcess.job_id).where(
        RecruitmentProcess.owner_user_id.in_(owners),
        RecruitmentProcess.status == ProcessStatus.open,
        RecruitmentProcess.priority_compliant_at_open.is_(True),
    )
    events = select(CalendarEvent.job_id).where(
        func.coalesce(CalendarEvent.operational_owner_id, CalendarEvent.created_by).in_(
            owners
        ),
        CalendarEvent.status == EventStatus.scheduled,
        CalendarEvent.job_id.is_not(None),
    )
    return or_(job_id_column.in_(processes), job_id_column.in_(events))


def operational_owner_clause(column, user: User):
    owners = operational_owner_ids(user)
    if owners != {user.id} and getattr(column.table, "name", None) == "jobs":
        from app.models.job import Job

        inherited = owners - {user.id}
        return or_(
            column == user.id,
            and_(
                column.in_(inherited),
                or_(
                    Job.is_open.is_(True),
                    open_operational_job_clause(Job.id, inherited),
                ),
            ),
        )
    return column == user.id if owners == {user.id} else column.in_(sorted(owners))


def operational_job_owner_clause(column, job_id_column, user: User):
    """A cover grants current job work, never every historical assignment."""
    owners = operational_owner_ids(user)
    if owners == {user.id}:
        return column == user.id
    from app.models.job import Job

    inherited = owners - {user.id}
    current_jobs = select(Job.id).where(Job.is_open.is_(True))
    return or_(
        column == user.id,
        and_(
            column.in_(inherited),
            or_(
                job_id_column.in_(current_jobs),
                open_operational_job_clause(job_id_column, inherited),
            ),
        ),
    )


async def sync_availability(db: AsyncSession) -> bool:
    """Replace only validated complete snapshots; never erase last-known cover on error."""
    await db.execute(
        insert(WorkforceAvailabilityState).values(id=1).on_conflict_do_nothing()
    )
    state = await db.get(WorkforceAvailabilityState, 1)
    now = datetime.now(timezone.utc)
    state.last_attempt_at = now
    try:
        if (
            not settings.COMPASS_AVAILABILITY_URL
            or not settings.COMPASS_AVAILABILITY_SECRET
        ):
            raise ValueError("availability_not_configured")
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.get(
                settings.COMPASS_AVAILABILITY_URL,
                headers={
                    "Authorization": f"Bearer {settings.COMPASS_AVAILABILITY_SECRET}",
                    "User-Agent": "dynaminds-smoke-test/1.0 (+nexus-availability)",
                },
            )
            response.raise_for_status()
            snapshot = AvailabilitySnapshot.model_validate(response.json())
        if (
            snapshot.date != now.astimezone(WARSAW).date()
            or not -60 <= (now - snapshot.generated_at).total_seconds() <= STALE_SECONDS
        ):
            raise ValueError("availability_source_stale")
        changed = (
            not state.snapshot
            or state.snapshot.get("snapshot_version") != snapshot.snapshot_version
        )
        state.snapshot = snapshot.model_dump(mode="json")
        state.last_success_at = now
        state.last_error = None
        if changed:
            db.add(RecruitmentAllocationEvent(topic="availability_changed"))
        await db.commit()
        db.info.pop("workforce_context", None)
        return True
    except Exception as exc:
        # Exception text can contain upstream URLs or employee data. Persist only a category.
        state.last_error = type(exc).__name__
        await db.commit()
        return False
