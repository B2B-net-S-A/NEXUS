"""Bezpośrednie przypisania Delivery Leada na stałym rosterze.

Model planowy (HoR publikuje wersjonowany plan co ~3 dni robocze) nie pasował
do rytmu firmy: nowe rekrutacje wpadają codziennie, a DL rozdaje je na bieżąco.
Te testy pilnują nowego kontraktu — DL przypisuje sam, HoR obserwuje.

Testy są bez bazy: sprawdzają granice ról i gałęzie decyzyjne handlera.
Zachowanie z bazą (unikalność rangi, sufit 5) pilnują ograniczenia w migracji
0200 i test kontraktowy migracji.
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
    job = SimpleNamespace(id=7, delivery_lead_id=999, status=JobStatus.published)
    db = SimpleNamespace(scalar=AsyncMock(return_value=job))

    with pytest.raises(HTTPException) as err:
        await priority_work.create_priority_assignment(_payload(), dl, db)

    assert err.value.status_code == 403
    assert "własne" in err.value.detail


async def test_assignment_requires_published_request() -> None:
    dl = _FakeUser(5, UserRole.delivery_lead)
    job = SimpleNamespace(id=7, delivery_lead_id=5, status=JobStatus.draft)
    db = SimpleNamespace(scalar=AsyncMock(return_value=job))

    with pytest.raises(HTTPException) as err:
        await priority_work.create_priority_assignment(_payload(), dl, db)

    assert err.value.status_code == 422


async def test_assignee_must_hold_an_operational_role() -> None:
    """Nie da się przypisać rekrutacji komuś spoza recruiter/sourcer/TAC."""
    dl = _FakeUser(5, UserRole.delivery_lead)
    job = SimpleNamespace(id=7, delivery_lead_id=5, status=JobStatus.published)
    outsider = _FakeUser(42, UserRole.user)
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[job, outsider]))

    with pytest.raises(HTTPException) as err:
        await priority_work.create_priority_assignment(_payload(), dl, db)

    assert err.value.status_code == 422
    assert "rekruterowi" in err.value.detail


async def test_channel_must_match_the_assignees_role() -> None:
    """Sourcer pracuje na bazie; przypisanie mu LinkedIna jest błędem DL-a."""
    dl = _FakeUser(5, UserRole.delivery_lead)
    job = SimpleNamespace(id=7, delivery_lead_id=5, status=JobStatus.published)
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


async def test_full_roster_reports_the_ceiling_at_assignment_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sufit 5 wychodzi u DL-a przy przypisaniu, nie u rekrutera w trakcie pracy.

    To jest cała różnica względem modelu planowego: friction ląduje na osobie,
    która ROZDZIELA pracę, a nie na tej, która ją WYKONUJE.
    """
    dl = _FakeUser(5, UserRole.delivery_lead)
    job = SimpleNamespace(id=7, delivery_lead_id=5, status=JobStatus.published)
    recruiter = _FakeUser(42, UserRole.recruiter)
    demand = SimpleNamespace(id=3)
    plan = SimpleNamespace(id=1)
    member = SimpleNamespace(id=11, status=priority_work.PriorityMemberStatus.active)

    db = SimpleNamespace(
        scalar=AsyncMock(side_effect=[job, recruiter, demand, None]),
        flush=AsyncMock(),
        add=lambda *_: None,
    )
    # monkeypatch, nie przypisanie do modułu — przypisanie przeciekłoby na
    # kolejne testy w tej samej sesji.
    monkeypatch.setattr(
        priority_work, "ensure_standing_plan", AsyncMock(return_value=plan)
    )
    monkeypatch.setattr(
        priority_work, "ensure_plan_member", AsyncMock(return_value=member)
    )
    monkeypatch.setattr(priority_work, "next_free_rank", AsyncMock(return_value=None))

    with pytest.raises(HTTPException) as err:
        await priority_work.create_priority_assignment(_payload(), dl, db)

    assert err.value.status_code == 409
    assert "komplet 5" in err.value.detail


async def test_delete_is_scoped_to_the_requests_delivery_lead() -> None:
    dl = _FakeUser(5, UserRole.delivery_lead)
    assignment = SimpleNamespace(id=1, job_id=7, plan_member_id=11, rank=PriorityRank.A)
    job = SimpleNamespace(id=7, delivery_lead_id=999)
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[assignment, job]))

    with pytest.raises(HTTPException) as err:
        await priority_work.delete_priority_assignment(1, dl, db)

    assert err.value.status_code == 403


async def test_explicit_rank_that_is_taken_gets_an_honest_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Jawna ranga przechodzi tę samą kontrolę co automatyczna.

    Wcześniej kolizja wychodziła dopiero jako IntegrityError na INSERT i
    wracała jako „ranga zajęta przez równoległe przypisanie" — a żadnej
    równoległości nie było.
    """
    dl = _FakeUser(5, UserRole.delivery_lead)
    job = SimpleNamespace(id=7, delivery_lead_id=5, status=JobStatus.published)
    recruiter = _FakeUser(42, UserRole.recruiter)
    demand = SimpleNamespace(id=3)
    plan = SimpleNamespace(id=1)
    member = SimpleNamespace(id=11, status=priority_work.PriorityMemberStatus.active)

    db = SimpleNamespace(
        # job, assignee, demand, brak duplikatu joba, ranga ZAJĘTA
        scalar=AsyncMock(side_effect=[job, recruiter, demand, None, 99]),
        flush=AsyncMock(),
        add=lambda *_: None,
    )
    monkeypatch.setattr(
        priority_work, "ensure_standing_plan", AsyncMock(return_value=plan)
    )
    monkeypatch.setattr(
        priority_work, "ensure_plan_member", AsyncMock(return_value=member)
    )
    free = AsyncMock(return_value=PriorityRank.B)
    monkeypatch.setattr(priority_work, "next_free_rank", free)

    with pytest.raises(HTTPException) as err:
        await priority_work.create_priority_assignment(_payload(rank="C"), dl, db)

    assert err.value.status_code == 409
    assert "Ranga C" in err.value.detail
    # Jawna ranga NIE może po cichu wylądować na wolnej — DL prosił o konkretną.
    free.assert_not_awaited()


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
