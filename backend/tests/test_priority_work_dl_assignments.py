"""Bezpośrednie przypisania Delivery Leada na stałym rosterze.

Model planowy (HoR publikuje wersjonowany plan co ~3 dni robocze) nie pasował
do rytmu firmy: nowe rekrutacje wpadają codziennie, a DL rozdaje je na bieżąco.
Te testy pilnują nowego kontraktu — DL przypisuje sam, HoR obserwuje.

Testy są bez bazy: sprawdzają granice ról i gałęzie decyzyjne handlera.
Zachowanie z bazą i równoczesne przydziały sprawdzają testy PostgreSQL.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import priority_work
from app.models.job import JobStatus
from app.models.recruitment_priority import PriorityRank
from app.models.skill import Skill  # noqa: F401 - rejestracja relacji ORM
from app.models.user import UserRole

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _transaction_lock_at_unit_boundary(monkeypatch):
    # Real transaction serialization is covered by PostgreSQL integration tests.
    monkeypatch.setattr(priority_work, "allocation_lock", AsyncMock())


class _FakeUser:
    def __init__(self, user_id: int, *roles: UserRole):
        self.id = user_id
        self.is_active = True
        self.role = roles[0]
        # `roles` (lista dodatkowych ról) czyta `role_values` w serwisie —
        # atrapa musi mieć oba pola, inaczej testuje się tylko rolę główną.
        self.roles = [role.value for role in roles]
        self._roles = set(roles)

    def has_any_role(self, *roles: UserRole) -> bool:
        return bool(self._roles & set(roles))

    def has_role(self, role: UserRole) -> bool:
        return role in self._roles


def _payload(**over):
    base = dict(
        job_id=7,
        assignee_user_id=42,
        channel="linkedin",
    )
    base.update(over)
    return priority_work.AssignmentCreateRequest(**base)


async def test_plain_recruiter_cannot_assign() -> None:
    recruiter = _FakeUser(5, UserRole.recruiter)
    with pytest.raises(HTTPException) as err:
        await priority_work.create_priority_assignment(
            _payload(), recruiter, SimpleNamespace()
        )
    assert err.value.status_code == 403


async def test_delivery_lead_cannot_assign_a_foreign_request() -> None:
    """Ta sama granica co przy demandach: DL rządzi tylko swoimi requestami."""
    dl = _FakeUser(5, UserRole.delivery_lead)
    job = SimpleNamespace(
        id=7, delivery_lead_id=999, status=JobStatus.published, is_open=True
    )
    db = SimpleNamespace(scalar=AsyncMock(return_value=job))

    with pytest.raises(HTTPException) as err:
        await priority_work.create_priority_assignment(_payload(), dl, db)

    assert err.value.status_code == 403
    assert "własne" in err.value.detail


async def test_assignment_requires_a_request_handed_off_to_search() -> None:
    """0270: bramką jest `is_open`, nie `status`.

    Do 0270 pytaliśmy o `status == published`, czyli o pole będące lustrem
    Traffita. Po naprawie mapowania statusu obejmuje ono ~305 rekrutacji
    otwartych u klientów, z których zdecydowanej większości nikt w NEXUSIE nie
    przejął — plan Priority Work zapełniłby się requestami, których nikt nie
    prowadzi. `is_open` ustawia dopiero handoff.
    """
    dl = _FakeUser(5, UserRole.delivery_lead)
    job = SimpleNamespace(
        id=7, delivery_lead_id=5, status=JobStatus.published, is_open=False
    )
    db = SimpleNamespace(scalar=AsyncMock(return_value=job))

    with pytest.raises(HTTPException) as err:
        await priority_work.create_priority_assignment(_payload(), dl, db)

    assert err.value.status_code == 422


async def test_assignee_must_hold_an_operational_role() -> None:
    """Nie da się przypisać rekrutacji komuś spoza recruiter/sourcer/TAC."""
    dl = _FakeUser(5, UserRole.delivery_lead)
    job = SimpleNamespace(
        id=7, delivery_lead_id=5, status=JobStatus.published, is_open=True
    )
    outsider = _FakeUser(42, UserRole.user)
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[job, outsider]))

    with pytest.raises(HTTPException) as err:
        await priority_work.create_priority_assignment(_payload(), dl, db)

    assert err.value.status_code == 422
    assert "rekruterowi" in err.value.detail


async def test_channel_must_match_the_assignees_role() -> None:
    """Sourcer pracuje na bazie; przypisanie mu LinkedIna jest błędem DL-a."""
    dl = _FakeUser(5, UserRole.delivery_lead)
    job = SimpleNamespace(
        id=7, delivery_lead_id=5, status=JobStatus.published, is_open=True
    )
    sourcer = _FakeUser(42, UserRole.sourcer)
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[job, sourcer]))

    with pytest.raises(HTTPException) as err:
        await priority_work.create_priority_assignment(
            _payload(channel="linkedin"), dl, db
        )

    assert err.value.status_code == 422
    assert "kanał" in err.value.detail.lower()


async def test_rank_is_optional_and_advisory() -> None:
    """Ranga nie jest wymagana — to informacja porządkująca, nie bramka."""
    assert _payload().rank is None
    assert _payload(rank="C").rank is PriorityRank.C


async def test_sixth_assignment_uses_shared_unbounded_command(monkeypatch):
    dl = _FakeUser(5, UserRole.delivery_lead)
    job = SimpleNamespace(id=7, delivery_lead_id=5, is_open=True)
    recruiter = _FakeUser(42, UserRole.recruiter)
    assignment = SimpleNamespace(
        id=12, position=6, rank=None, channel=priority_work.PriorityChannel.linkedin
    )
    command = AsyncMock(return_value=assignment)
    monkeypatch.setattr(priority_work, "assign_operator", command)
    db = SimpleNamespace(
        scalar=AsyncMock(side_effect=[job, recruiter]), commit=AsyncMock()
    )
    result = await priority_work.create_priority_assignment(_payload(), dl, db)
    assert result["position"] == 6 and result["rank"] is None
    assert command.await_args.kwargs["job"] is job
    assert command.await_args.kwargs["assignee"] is recruiter
    assert command.await_args.kwargs["as_owner"] is False


async def test_delete_is_scoped_to_the_requests_delivery_lead() -> None:
    dl = _FakeUser(5, UserRole.delivery_lead)
    assignment = SimpleNamespace(id=1, job_id=7, plan_member_id=11, rank=PriorityRank.A)
    job = SimpleNamespace(id=7, delivery_lead_id=999)
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[assignment, job]))

    with pytest.raises(HTTPException) as err:
        await priority_work.delete_priority_assignment(1, dl, db)

    assert err.value.status_code == 403


async def test_explicit_rank_is_forwarded_as_numeric_position_and_conflict_is_preserved(
    monkeypatch,
):
    dl = _FakeUser(5, UserRole.delivery_lead)
    job = SimpleNamespace(id=7, delivery_lead_id=5, is_open=True)
    recruiter = _FakeUser(42, UserRole.recruiter)
    command = AsyncMock(side_effect=HTTPException(409, "Pozycja jest już zajęta"))
    monkeypatch.setattr(priority_work, "assign_operator", command)
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[job, recruiter]))
    with pytest.raises(HTTPException) as error:
        await priority_work.create_priority_assignment(_payload(rank="C"), dl, db)
    assert error.value.status_code == 409
    assert command.await_args.kwargs["position"] == 3


async def test_plan_member_creation_is_an_upsert_not_select_then_insert() -> None:
    """`SELECT ... FOR UPDATE` nie blokuje wiersza, którego jeszcze nie ma.

    Dwa równoległe pierwsze przypisania do tej samej osoby oba widziały None,
    oba robiły INSERT, drugie dostawało IntegrityError na
    `uq_priority_plan_member_user` -> 500. Kontrakt: upsert.
    """
    import inspect

    from app.services import priority_work_service

    source = inspect.getsource(priority_work_service.ensure_plan_member)
    assert "pg_insert" in source
    assert "on_conflict_do_nothing" in source
