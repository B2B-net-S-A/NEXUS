"""Rada (R6): uchwały w trybie pisemnym wg § 25 projektu statutu."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import delete, func, select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.board_document import BoardDocument, BoardVote, BoardVoteBallot
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services.board.votes import tally
from tests.test_sales_companies_api import _headers, _user

API = "/api/supervisory-board"


# ── § 25 ust. 1 i 4 ─────────────────────────────────────────────────────────


def test_majority_of_votes_cast_with_quorum_of_half() -> None:
    members = [1, 2, 3]
    assert tally(members, {1: "for", 2: "against", 3: "for"}, None).passed
    # Wstrzymujący się nie przesądzają: 1 za, 0 przeciw, 1 wstrzymał się.
    assert tally(members, {1: "for", 2: "abstain"}, None).passed
    # Kworum = połowa członków (3 → 2): jeden głos nie wystarcza.
    lone = tally(members, {1: "for"}, None)
    assert lone.quorum == 2 and not lone.quorum_met and not lone.passed
    assert not tally(members, {1: "abstain", 2: "abstain"}, None).passed


def test_tie_is_decided_by_chair_vote() -> None:
    members = [1, 2, 3, 4]
    ballots = {1: "for", 2: "against"}
    assert tally(members, ballots, chair_user_id=1).passed
    assert tally(members, ballots, chair_user_id=1).tie_broken_by_chair
    assert not tally(members, ballots, chair_user_id=2).passed
    # Przewodniczący się wstrzymał albo nie głosował — remis nie daje większości.
    assert not tally(members, {**ballots, 3: "abstain"}, chair_user_id=3).passed
    assert not tally(members, ballots, chair_user_id=None).passed


def test_ballot_outside_membership_does_not_count() -> None:
    result = tally([1, 2], {1: "for", 99: "for"}, None)
    assert result.voted == 1 and result.votes_for == 1 and result.passed


# ── API ──────────────────────────────────────────────────────────────────────


@pytest.fixture
async def _clean_votes():
    async with AsyncSessionLocal() as db:
        await db.execute(delete(BoardVoteBallot))
        await db.execute(delete(BoardVote))
        await db.execute(delete(BoardDocument))
        # Inne testy zakładają konta Rady — skład liczy tylko konta z tego testu.
        boards = (
            await db.execute(select(User).where(User.role == UserRole.board))
        ).scalars()
        for user in boards:
            user.is_active = False
        await db.commit()
    yield


async def _bells(user_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.notification_type == NotificationType.board_vote,
            )
        )


def _body(**extra) -> dict:
    return {
        "number": "4/2026",
        "title": "Ocena sprawozdania finansowego za 2025",
        "draft": "Rada Nadzorcza pozytywnie ocenia sprawozdanie finansowe za 2025.",
        "deadline": (business_today() + timedelta(days=7)).isoformat(),
        "not_excluded_matter": True,
        **extra,
    }


async def test_written_resolution_flow(app_client, _clean_votes) -> None:
    admin = await _user(role="admin")
    chair = await _user(role="board")
    second = await _user(role="board")
    third = await _user(role="board")

    created = await app_client.post(
        f"{API}/votes", headers=_headers(admin), json=_body(chair_user_id=chair.id)
    )
    assert created.status_code == 201, created.text
    vote = created.json()
    assert sorted(m["id"] for m in vote["members"]) == sorted(
        [chair.id, second.id, third.id]
    )
    assert await _bells(second.id) == 1  # każdy członek dostał projekt
    assert vote["can_vote"] is False  # admin bez roli Rady nie głosuje

    for user, choice in ((chair, "for"), (second, "against"), (second, "for")):
        cast = await app_client.post(
            f"{API}/votes/{vote['id']}/ballot",
            headers=_headers(user),
            json={"choice": choice},
        )
        assert cast.status_code == 200, cast.text
    assert cast.json()["my_choice"] == "for"  # głos można zmienić przed zamknięciem
    assert cast.json()["tally"]["for"] == 2

    denied = await app_client.post(
        f"{API}/votes/{vote['id']}/close", headers=_headers(chair)
    )
    assert denied.status_code == 403
    closed = await app_client.post(
        f"{API}/votes/{vote['id']}/close", headers=_headers(admin)
    )
    assert closed.status_code == 200, closed.text
    body = closed.json()
    assert body["result"]["passed"] is True and body["result"]["voted"] == 2
    async with AsyncSessionLocal() as db:
        doc = await db.get(BoardDocument, body["resolution_document_id"])
        assert doc.category == "resolution_supervisory" and doc.number == "4/2026"
        assert "trybie pisemnym" in doc.subject
    assert await _bells(third.id) == 2  # projekt + wynik

    late = await app_client.post(
        f"{API}/votes/{vote['id']}/ballot",
        headers=_headers(third),
        json={"choice": "for"},
    )
    assert late.status_code == 409


async def test_create_requires_confirmation_and_valid_input(
    app_client, _clean_votes
) -> None:
    admin = await _user(role="admin")
    board = await _user(role="board")
    recruiter = await _user(role="recruiter")
    excluded = await app_client.post(
        f"{API}/votes", headers=_headers(admin), json=_body(not_excluded_matter=False)
    )
    assert excluded.status_code == 422 and "§ 25 ust. 5" in excluded.json()["detail"]
    past = await app_client.post(
        f"{API}/votes",
        headers=_headers(admin),
        json=_body(deadline=(business_today() - timedelta(days=1)).isoformat()),
    )
    assert past.status_code == 422
    outsider_chair = await app_client.post(
        f"{API}/votes", headers=_headers(admin), json=_body(chair_user_id=recruiter.id)
    )
    assert outsider_chair.status_code == 422
    assert (
        await app_client.post(f"{API}/votes", headers=_headers(board), json=_body())
    ).status_code == 403
    assert (
        await app_client.get(f"{API}/votes", headers=_headers(recruiter))
    ).status_code == 403

    vote = (
        await app_client.post(f"{API}/votes", headers=_headers(admin), json=_body())
    ).json()
    bad = await app_client.post(
        f"{API}/votes/{vote['id']}/ballot",
        headers=_headers(board),
        json={"choice": "maybe"},
    )
    assert bad.status_code == 422
    for outsider in (recruiter, admin):  # bez Insights / spoza składu uchwały
        denied = await app_client.post(
            f"{API}/votes/{vote['id']}/ballot",
            headers=_headers(outsider),
            json={"choice": "for"},
        )
        assert denied.status_code == 403, (outsider.role, denied.text)
    withdrawn = await app_client.post(
        f"{API}/votes/{vote['id']}/withdraw", headers=_headers(admin)
    )
    assert withdrawn.json()["status"] == "withdrawn"
    after = await app_client.post(
        f"{API}/votes/{vote['id']}/ballot",
        headers=_headers(board),
        json={"choice": "for"},
    )
    assert after.status_code == 409


async def test_member_added_later_cannot_vote_and_quorum_failure(
    app_client, _clean_votes
) -> None:
    admin = await _user(role="admin")
    first = await _user(role="board")
    await _user(role="board")
    vote = (
        await app_client.post(f"{API}/votes", headers=_headers(admin), json=_body())
    ).json()
    newcomer = await _user(role="board")
    blocked = await app_client.post(
        f"{API}/votes/{vote['id']}/ballot",
        headers=_headers(newcomer),
        json={"choice": "for"},
    )
    assert blocked.status_code == 403
    await app_client.post(
        f"{API}/votes/{vote['id']}/ballot",
        headers=_headers(first),
        json={"choice": "for"},
    )
    closed = (
        await app_client.post(
            f"{API}/votes/{vote['id']}/close", headers=_headers(admin)
        )
    ).json()
    # 2 członków → kworum 1; 1 głos „za” wystarcza.
    assert closed["result"]["passed"] is True
