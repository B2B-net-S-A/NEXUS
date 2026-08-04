"""Atomic commands for the Client ↔ TAC relationship.

The table currently carries two independent concepts:

* ``is_primary`` is the legacy, client-centric notification marker;
* ``is_first_priority_for_tac`` is the new, TAC-centric work priority.

They must never be derived from, or rewritten because of, one another.  Every
command locks the parent Client and TAC User before relationship rows.  That
also serializes the first insert, where there is no assignment row to lock yet.
The database partial unique indexes remain the final race-condition backstop.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.team_structure import ClientTacAssignment
from app.models.user import User


class ClientTacAssignmentError(ValueError):
    """Base class for domain validation failures in relationship commands."""


class ClientTacAssignmentNotFound(ClientTacAssignmentError):
    """The requested Client ↔ TAC assignment does not exist."""


class FirstPrioritySuccessorRequired(ClientTacAssignmentError):
    """A priority assignment cannot be removed while alternatives remain."""


class InvalidFirstPrioritySuccessor(ClientTacAssignmentError):
    """The supplied successor is not another assignment of the same TAC."""


@dataclass(frozen=True)
class ClientTacUpsertResult:
    assignment: ClientTacAssignment
    membership_changed: bool
    legacy_primary_changed: bool
    first_priority_changed: bool


@dataclass(frozen=True)
class ClientTacRemovalResult:
    assignment: ClientTacAssignment
    first_priority_changed: bool


async def _lock_relationship_rows(
    db: AsyncSession,
    *,
    client_id: int,
    tac_user_id: int,
) -> list[ClientTacAssignment]:
    """Lock the deterministic mutation boundary for both relationship axes."""

    # Keep this order identical in every command.  Parent locks protect the
    # empty-set case, which ``SELECT ... FOR UPDATE`` on assignments cannot.
    await db.execute(select(Client.id).where(Client.id == client_id).with_for_update())
    await db.execute(select(User.id).where(User.id == tac_user_id).with_for_update())

    return list(
        (
            await db.execute(
                select(ClientTacAssignment)
                .where(
                    or_(
                        ClientTacAssignment.client_id == client_id,
                        ClientTacAssignment.tac_user_id == tac_user_id,
                    )
                )
                .order_by(ClientTacAssignment.id.asc())
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )


def _target_assignment(
    rows: list[ClientTacAssignment],
    *,
    client_id: int,
    tac_user_id: int,
) -> ClientTacAssignment | None:
    return next(
        (
            row
            for row in rows
            if row.client_id == client_id and row.tac_user_id == tac_user_id
        ),
        None,
    )


def _tac_assignments(
    rows: list[ClientTacAssignment], tac_user_id: int
) -> list[ClientTacAssignment]:
    return [row for row in rows if row.tac_user_id == tac_user_id]


def _validate_successor(
    rows: list[ClientTacAssignment],
    *,
    current_client_id: int,
    successor_client_id: int | None,
) -> ClientTacAssignment:
    if successor_client_id is None:
        raise FirstPrioritySuccessorRequired(
            "successor_client_id is required while this TAC has other clients"
        )
    successor = next(
        (
            row
            for row in rows
            if row.client_id == successor_client_id
            and row.client_id != current_client_id
        ),
        None,
    )
    if successor is None:
        raise InvalidFirstPrioritySuccessor(
            "successor_client_id must reference another client assigned to this TAC"
        )
    return successor


async def upsert_client_tac_assignment(
    db: AsyncSession,
    *,
    client_id: int,
    tac_user_id: int,
    is_primary: bool | None,
    is_first_priority_for_tac: bool | None,
) -> ClientTacUpsertResult:
    """Create/update an assignment without coupling its two priority flags."""

    rows = await _lock_relationship_rows(
        db, client_id=client_id, tac_user_id=tac_user_id
    )
    target = _target_assignment(rows, client_id=client_id, tac_user_id=tac_user_id)
    tac_rows = _tac_assignments(rows, tac_user_id)
    client_rows = [row for row in rows if row.client_id == client_id]

    membership_changed = target is None
    legacy_changed = False
    priority_changed = False

    if is_primary is True:
        previous_legacy = next(
            (
                row
                for row in client_rows
                if row.is_primary and row.tac_user_id != tac_user_id
            ),
            None,
        )
        if previous_legacy is not None:
            previous_legacy.is_primary = False
            legacy_changed = True
            # Demote before promotion to satisfy the legacy partial unique
            # index even when SQLAlchemy orders UPDATE statements differently.
            await db.flush()

    if target is None:
        requested_priority = is_first_priority_for_tac
        if requested_priority is None:
            # Safe default only for a TAC's first relationship.  Later clients
            # never become an arbitrary priority owner.
            requested_priority = not tac_rows

        if requested_priority:
            previous_priority = next(
                (row for row in tac_rows if row.is_first_priority_for_tac is True),
                None,
            )
            if previous_priority is not None:
                previous_priority.is_first_priority_for_tac = False
                priority_changed = True
                await db.flush()

        target = ClientTacAssignment(
            client_id=client_id,
            tac_user_id=tac_user_id,
            is_primary=bool(is_primary),
            is_first_priority_for_tac=requested_priority,
        )
        db.add(target)
        legacy_changed = bool(is_primary) or legacy_changed
        priority_changed = bool(requested_priority) or priority_changed
    else:
        if is_primary is not None and target.is_primary != is_primary:
            target.is_primary = is_primary
            legacy_changed = True

        if is_first_priority_for_tac is True:
            previous_priority = next(
                (
                    row
                    for row in tac_rows
                    if row is not target and row.is_first_priority_for_tac is True
                ),
                None,
            )
            if previous_priority is not None:
                previous_priority.is_first_priority_for_tac = False
                priority_changed = True
                await db.flush()
            if target.is_first_priority_for_tac is not True:
                target.is_first_priority_for_tac = True
                priority_changed = True
        elif is_first_priority_for_tac is False:
            alternatives = [row for row in tac_rows if row is not target]
            if target.is_first_priority_for_tac is True and alternatives:
                raise FirstPrioritySuccessorRequired(
                    "Use the first-priority endpoint with successor_client_id "
                    "to disable this TAC's current priority client"
                )
            if target.is_first_priority_for_tac is not False:
                target.is_first_priority_for_tac = False
                priority_changed = True

    if legacy_changed or priority_changed or membership_changed:
        await db.flush()

    return ClientTacUpsertResult(
        assignment=target,
        membership_changed=membership_changed,
        legacy_primary_changed=legacy_changed,
        first_priority_changed=priority_changed,
    )


async def set_first_priority_for_tac(
    db: AsyncSession,
    *,
    client_id: int,
    tac_user_id: int,
    enabled: bool,
    successor_client_id: int | None = None,
) -> ClientTacAssignment:
    """Atomically promote, demote, or hand over a TAC's priority client."""

    rows = await _lock_relationship_rows(
        db, client_id=client_id, tac_user_id=tac_user_id
    )
    target = _target_assignment(rows, client_id=client_id, tac_user_id=tac_user_id)
    if target is None:
        raise ClientTacAssignmentNotFound("Assignment not found")

    tac_rows = _tac_assignments(rows, tac_user_id)
    alternatives = [row for row in tac_rows if row is not target]

    if enabled:
        if successor_client_id is not None:
            raise InvalidFirstPrioritySuccessor(
                "successor_client_id is only valid when enabled is false"
            )
        previous_priority = next(
            (row for row in alternatives if row.is_first_priority_for_tac is True),
            None,
        )
        if previous_priority is not None:
            previous_priority.is_first_priority_for_tac = False
            await db.flush()
        if target.is_first_priority_for_tac is not True:
            target.is_first_priority_for_tac = True
            await db.flush()
        return target

    if target.is_first_priority_for_tac is True and alternatives:
        successor = _validate_successor(
            alternatives,
            current_client_id=client_id,
            successor_client_id=successor_client_id,
        )
        target.is_first_priority_for_tac = False
        await db.flush()
        successor.is_first_priority_for_tac = True
        await db.flush()
    else:
        if successor_client_id is not None:
            raise InvalidFirstPrioritySuccessor(
                "successor_client_id is only valid when handing over the current priority"
            )
        if target.is_first_priority_for_tac is not False:
            target.is_first_priority_for_tac = False
            await db.flush()

    return target


async def remove_client_tac_assignment(
    db: AsyncSession,
    *,
    client_id: int,
    tac_user_id: int,
    successor_client_id: int | None = None,
) -> ClientTacRemovalResult:
    """Delete an assignment, requiring an atomic handover when necessary."""

    rows = await _lock_relationship_rows(
        db, client_id=client_id, tac_user_id=tac_user_id
    )
    target = _target_assignment(rows, client_id=client_id, tac_user_id=tac_user_id)
    if target is None:
        raise ClientTacAssignmentNotFound("Assignment not found")

    alternatives = [
        row for row in _tac_assignments(rows, tac_user_id) if row is not target
    ]
    priority_changed = False
    if target.is_first_priority_for_tac is True and alternatives:
        successor = _validate_successor(
            alternatives,
            current_client_id=client_id,
            successor_client_id=successor_client_id,
        )
        target.is_first_priority_for_tac = False
        await db.flush()
        successor.is_first_priority_for_tac = True
        await db.flush()
        priority_changed = True
    elif successor_client_id is not None:
        raise InvalidFirstPrioritySuccessor(
            "successor_client_id is only valid when removing the current priority"
        )

    await db.delete(target)
    await db.flush()
    return ClientTacRemovalResult(
        assignment=target,
        first_priority_changed=priority_changed,
    )


async def toggle_legacy_primary_tac(
    db: AsyncSession,
    *,
    client_id: int,
    tac_user_id: int,
) -> ClientTacAssignment:
    """Toggle only the legacy client-centric marker, for compatibility."""

    rows = await _lock_relationship_rows(
        db, client_id=client_id, tac_user_id=tac_user_id
    )
    target = _target_assignment(rows, client_id=client_id, tac_user_id=tac_user_id)
    if target is None:
        raise ClientTacAssignmentNotFound("Assignment not found")

    if not target.is_primary:
        previous_primary = next(
            (
                row
                for row in rows
                if row.client_id == client_id and row is not target and row.is_primary
            ),
            None,
        )
        if previous_primary is not None:
            previous_primary.is_primary = False
            await db.flush()

    target.is_primary = not target.is_primary
    await db.flush()
    return target
