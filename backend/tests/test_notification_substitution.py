"""Przekazanie powiadomień zastępcy (zgłoszenie z 09.11.2026).

Bez bazy: reguła, kto dostaje wiersz, i klasyfikacja typów powiadomień.
"""

from datetime import date
from types import SimpleNamespace

import pytest

from app.models.notification import NotificationType
from app.services import board_tasks, notification_substitution as sub
from app.services.workforce_availability import (
    Delegation,
    WorkforceContext,
    compatible_substitute,
)

OWNER = 140
SUBSTITUTE = 91


def _context() -> WorkforceContext:
    return WorkforceContext(
        delegations={
            OWNER: Delegation(
                owner_id=OWNER,
                performer_id=SUBSTITUTE,
                start_date=date(2026, 11, 9),
                end_date=date(2026, 11, 13),
                source_ids=("x",),
            )
        }
    )


def _db(actor: int | None = None) -> SimpleNamespace:
    info = {} if actor is None else {sub.ACTOR_KEY: actor}
    return SimpleNamespace(info=info)


@pytest.fixture(autouse=True)
def _workforce(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(_db):
        return _context()

    monkeypatch.setattr(sub, "workforce_context", fake)


def test_every_notification_type_is_classified_once() -> None:
    """Nowy typ bez decyzji: praca bieżąca czy sprawa osobista = czerwony test."""
    every = set(NotificationType)
    assert sub.CURRENT_WORK_TYPES | sub.PERSONAL_TYPES == every
    assert not sub.CURRENT_WORK_TYPES & sub.PERSONAL_TYPES


@pytest.mark.asyncio
async def test_current_work_goes_to_substitute() -> None:
    route = await sub.notification_route(
        _db(), OWNER, NotificationType.interview_slots_requested
    )
    assert route == sub.Route(user_id=SUBSTITUTE, on_behalf_of=OWNER)


@pytest.mark.asyncio
async def test_personal_type_stays_with_the_absent_person() -> None:
    route = await sub.notification_route(
        _db(), OWNER, NotificationType.hr_bonus_assigned
    )
    assert route == sub.Route(user_id=OWNER, on_behalf_of=None)


@pytest.mark.asyncio
async def test_person_without_substitute_keeps_notification() -> None:
    route = await sub.notification_route(
        _db(), 7, NotificationType.interview_slots_requested
    )
    assert route == sub.Route(user_id=7, on_behalf_of=None)


@pytest.mark.asyncio
async def test_substitute_is_not_told_about_own_action() -> None:
    """Zastępca sam wpisał terminy: dzwonek nie ma do kogo iść."""
    route = await sub.notification_route(
        _db(actor=SUBSTITUTE), OWNER, NotificationType.interview_slots_requested
    )
    assert route.skip is True


@pytest.mark.asyncio
async def test_engine_failure_keeps_nominal_recipient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(_db):
        raise RuntimeError("awaria")

    monkeypatch.setattr(sub, "workforce_context", broken)
    route = await sub.notification_route(
        _db(), OWNER, NotificationType.interview_slots_requested
    )
    assert route == sub.Route(user_id=OWNER, on_behalf_of=None)


def _user(*roles: str) -> SimpleNamespace:
    return SimpleNamespace(role=roles[0], roles=list(roles))


@pytest.mark.parametrize(
    ("owner", "substitute", "expected"),
    [
        (("recruiter",), ("delivery_lead",), True),
        (("recruiter",), ("recruiter",), True),
        (("delivery_lead",), ("recruiter",), False),
        (("delivery_lead",), ("delivery_lead",), True),
        (("talent_community_manager",), ("recruiter",), False),
        (("delivery_lead", "recruiter"), ("delivery_lead",), True),
    ],
)
def test_who_can_substitute(owner, substitute, expected) -> None:
    assert compatible_substitute(_user(*owner), _user(*substitute)) is expected


@pytest.mark.parametrize(
    ("owner", "substitute", "gap"),
    [
        (("delivery_lead",), ("recruiter",), "delivery_lead"),
        (("talent_community_manager",), ("recruiter",), "talent_community_manager"),
        (("recruiter",), ("delivery_lead",), None),
        (("finance",), ("recruiter",), None),
        (("employee",), ("employee",), None),
    ],
)
def test_substitute_role_gap(owner, substitute, gap) -> None:
    """Ostrzegamy tylko o pracy, którą przekazuje silnik zastępstw."""
    assert sub.substitute_role_gap(_user(*owner), _user(*substitute)) == gap


def _delivery_lead(user_id: int) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, has_role=lambda _role: True)


def test_review_follows_substitution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(board_tasks, "operational_owner_ids", lambda _u: {14, 27})
    assert board_tasks.reviews_as_dl(
        _delivery_lead(14), delivery_lead_id=27, client_id=None, portfolio=frozenset()
    )


def test_review_of_someone_else_stays_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(board_tasks, "operational_owner_ids", lambda _u: {14})
    assert not board_tasks.reviews_as_dl(
        _delivery_lead(14), delivery_lead_id=27, client_id=None, portfolio=frozenset()
    )
