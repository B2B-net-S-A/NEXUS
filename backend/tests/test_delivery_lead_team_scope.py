"""Zespół Delivery Leada bez przypisań TAC (decyzja Artura 22.09.2026).

Do 22.09 `allowed_operator_user_ids` DL-a liczył się wyłącznie
z `ClientTacAssignment`; funkcji TAC nie używamy, więc zespół był pusty.
Teraz to ludzie otwartych rekrutacji DL-a: prowadzący, TAC i aktywni
współpracownicy — z rekrutacji, których jest DL-em, i z rekrutacji jego
klientów. Zamknięte rekrutacje i nieaktywne konta nie wchodzą.

Baza testowa wspólna i nieczyszczona — asercje tylko na własnych wierszach.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_collaborator import JobCollaborator
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services.access_scope import ScopeKind, resolve_dashboard_scope


def _user(role: UserRole, *, active: bool = True) -> User:
    unique = uuid.uuid4().hex[:8]
    return User(
        email=f"dl-team-{role.value}-{unique}@example.com",
        password_hash="x",
        name=f"DL team {role.value}",
        role=role,
        roles=[role.value],
        is_active=active,
        profile_completed=True,
    )


@pytest.mark.asyncio
async def test_delivery_lead_team_comes_from_its_recruitments() -> None:
    async with AsyncSessionLocal() as db:
        dl = _user(UserRole.delivery_lead)
        owner = _user(UserRole.recruiter)
        collaborator = _user(UserRole.sourcer)
        client_owner = _user(UserRole.recruiter)
        closed_owner = _user(UserRole.recruiter)
        inactive = _user(UserRole.recruiter, active=False)
        stranger = _user(UserRole.recruiter)
        db.add_all(
            [dl, owner, collaborator, client_owner, closed_owner, inactive, stranger]
        )
        own_client = Client(name=f"DlTeamOwn-{uuid.uuid4().hex[:6]}")
        other_client = Client(name=f"DlTeamOther-{uuid.uuid4().hex[:6]}")
        db.add_all([own_client, other_client])
        await db.flush()
        db.add(
            DeliveryLeadClientAssignment(
                client_id=own_client.id, delivery_lead_user_id=dl.id
            )
        )
        led = Job(
            title="Led by DL",
            status=JobStatus.published,
            client_id=other_client.id,
            delivery_lead_id=dl.id,
            recruiter_id=owner.id,
        )
        of_client = Job(
            title="Client of DL",
            status=JobStatus.published,
            client_id=own_client.id,
            recruiter_id=client_owner.id,
        )
        closed = Job(
            title="Closed",
            status=JobStatus.closed,
            client_id=own_client.id,
            recruiter_id=closed_owner.id,
        )
        of_inactive = Job(
            title="Inactive owner",
            status=JobStatus.published,
            client_id=own_client.id,
            recruiter_id=inactive.id,
        )
        foreign = Job(
            title="Foreign",
            status=JobStatus.published,
            client_id=other_client.id,
            recruiter_id=stranger.id,
        )
        db.add_all([led, of_client, closed, of_inactive, foreign])
        await db.flush()
        db.add(JobCollaborator(job_id=led.id, user_id=collaborator.id))
        await db.commit()

        scope = await resolve_dashboard_scope(dl, db)

    assert scope.kind is ScopeKind.delivery_clients
    team = scope.allowed_operator_user_ids
    assert {owner.id, collaborator.id, client_owner.id} <= team
    assert not {closed_owner.id, inactive.id, stranger.id} & team
