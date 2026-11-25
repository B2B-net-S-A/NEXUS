"""Oddanie osoby z blokadą „Biorę” (0777, decyzja Artura 25.11.2026).

* „Oddaj” — osoba z blokadą oddaje ją komuś z zespołu na pełne 12 h;
* „Zwolnij” — blokada kończy się teraz, „Biorę” może kliknąć każdy;
* „Poproś o oddanie” — prośba w panelu i dzwonku, odpowiedź „Oddaj”/„Zostaw”.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.notification import Notification, NotificationType
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import UserRole
from app.services import candidate_claim
from tests.test_pipeline_v4_claim_and_rules import (
    _add,
    _cleanup,
    _login,
    _process,
    _seed_candidate,
    _seed_job,
    _seed_user,
)

pytestmark = pytest.mark.asyncio

_HANDOVER = NotificationType.candidate_claim_handover
_REQUEST = NotificationType.candidate_claim_request
_ANSWER = NotificationType.candidate_claim_request_answer


@pytest_asyncio.fixture
async def api_client():
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


async def _notifications(
    user_id: int, ntype: NotificationType = _HANDOVER
) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Notification).where(
                        Notification.user_id == user_id,
                        Notification.notification_type == ntype,
                    )
                )
            ).all()
        )


async def _card(client, headers, job_id: int, cand_id: int) -> dict:
    board = await client.get(f"/api/pipeline/kanban/{job_id}", headers=headers)
    assert board.status_code == 200, board.text
    cards = [
        item
        for col in board.json()["columns"]
        for item in col["items"]
        if item["candidate_id"] == cand_id
    ]
    assert len(cards) == 1
    return cards[0]


async def _team(n_others: int = 1):
    """Rekrutacja z właścicielką blokady i ``n_others`` rekruterami w zespole."""
    owner = await _seed_user(UserRole.recruiter)
    others = [await _seed_user(UserRole.recruiter) for _ in range(n_others)]
    job_id, _ = await _seed_job(owner[0], collaborator_ids=tuple(o[0] for o in others))
    return owner, others, job_id


def _body(cand_id: int, job_id: int, **extra) -> dict:
    return {"candidate_id": cand_id, "job_id": job_id, **extra}


async def test_holder_hands_the_person_over_for_full_12h(api_client):
    owner, [other], job_id = await _team()
    cand_id = await _seed_candidate()
    owner_h = await _login(api_client, owner[1], owner[2])
    other_h = await _login(api_client, other[1], other[2])
    try:
        await _add(api_client, owner_h, job_id, cand_id, "manual_search")
        # Blokada trwa już 2 h — nowa osoba dostaje pełne 12 h od teraz.
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(RecruitmentProcess)
                .where(
                    RecruitmentProcess.candidate_id == cand_id,
                    RecruitmentProcess.job_id == job_id,
                )
                .values(claimed_until=datetime.now(timezone.utc) + timedelta(hours=10))
            )
            await db.commit()

        given = await api_client.post(
            "/api/pipeline/claim/handover",
            headers=owner_h,
            json=_body(cand_id, job_id, to_user_id=other[0]),
        )
        assert given.status_code == 200, given.text
        assert given.json()["claim_user_id"] == other[0]

        proc = await _process(cand_id, job_id)
        assert proc.claimed_by_user_id == other[0]
        remaining = proc.claimed_until - datetime.now(timezone.utc)
        assert timedelta(hours=11, minutes=58) < remaining <= timedelta(hours=12)

        [notif] = await _notifications(other[0])
        assert "oddał(a) Ci osobę" in notif.title
        assert notif.related_entity_id == proc.id
        async with AsyncSessionLocal() as db:
            act = await db.scalar(
                select(Activity).where(
                    Activity.action == "candidate_claim_handed_over",
                    Activity.user_id == owner[0],
                )
            )
        assert act is not None and act.details["to_user_id"] == other[0]

        # Karta i ruch idą za nową osobą; dawna właścicielka już nie rusza karty.
        card = await _card(api_client, other_h, job_id, cand_id)
        assert card["claim_user_id"] == other[0]
        assert card["taken_by_user_id"] == other[0]
        blocked = await api_client.post(
            "/api/pipeline/move",
            headers=owner_h,
            json=_body(cand_id, job_id, stage="verified"),
        )
        assert blocked.status_code == 423, blocked.text
    finally:
        await _cleanup([cand_id], job_id)


async def test_handover_refusals(api_client):
    owner, [other], job_id = await _team()
    dl_only = await _seed_user(UserRole.delivery_lead)
    cand_id = await _seed_candidate()
    owner_h = await _login(api_client, owner[1], owner[2])
    other_h = await _login(api_client, other[1], other[2])
    try:
        await _add(api_client, owner_h, job_id, cand_id, "manual_search")
        url = "/api/pipeline/claim/handover"

        # Nie swoją osobę oddać nie można.
        resp = await api_client.post(
            url, headers=other_h, json=_body(cand_id, job_id, to_user_id=other[0])
        )
        assert resp.status_code == 403, resp.text
        # Sobie i osobie bez roli rekrutera — 422.
        for target in (owner[0], dl_only[0]):
            resp = await api_client.post(
                url, headers=owner_h, json=_body(cand_id, job_id, to_user_id=target)
            )
            assert resp.status_code == 422, (target, resp.text)
        assert (await _process(cand_id, job_id)).claimed_by_user_id == owner[0]

        # Po upływie blokady nie ma czego oddawać.
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(RecruitmentProcess)
                .where(
                    RecruitmentProcess.candidate_id == cand_id,
                    RecruitmentProcess.job_id == job_id,
                )
                .values(claimed_until=datetime.now(timezone.utc) - timedelta(minutes=1))
            )
            await db.commit()
        resp = await api_client.post(
            url, headers=owner_h, json=_body(cand_id, job_id, to_user_id=other[0])
        )
        assert resp.status_code == 409, resp.text
    finally:
        await _cleanup([cand_id], job_id)


async def test_release_frees_the_person_and_keeps_the_card_name(api_client):
    owner, [other], job_id = await _team()
    cand_id = await _seed_candidate()
    owner_h = await _login(api_client, owner[1], owner[2])
    other_h = await _login(api_client, other[1], other[2])
    try:
        await _add(api_client, owner_h, job_id, cand_id, "manual_search")
        refused = await api_client.post(
            "/api/pipeline/claim/release", headers=other_h, json=_body(cand_id, job_id)
        )
        assert refused.status_code == 403, refused.text

        released = await api_client.post(
            "/api/pipeline/claim/release", headers=owner_h, json=_body(cand_id, job_id)
        )
        assert released.status_code == 200, released.text

        card = await _card(api_client, other_h, job_id, cand_id)
        assert card.get("claim_user_id") is None
        assert card["taken_by_user_id"] == owner[0]
        assert card["can_take"] is True

        again = await api_client.post(
            "/api/pipeline/claim/release", headers=owner_h, json=_body(cand_id, job_id)
        )
        assert again.status_code == 409, again.text

        take = await api_client.post(
            "/api/pipeline/claim", headers=other_h, json=_body(cand_id, job_id)
        )
        assert take.status_code == 200, take.text
        # Zwolniona blokada to nie przejęcie — bez dzwonka „przejął(a)”.
        assert take.json()["taken_over_from"] is None
    finally:
        await _cleanup([cand_id], job_id)


async def test_request_decline_then_accept(api_client):
    owner, [asker, third], job_id = await _team(n_others=2)
    cand_id = await _seed_candidate()
    owner_h = await _login(api_client, owner[1], owner[2])
    asker_h = await _login(api_client, asker[1], asker[2])
    third_h = await _login(api_client, third[1], third[2])
    url = "/api/pipeline/claim/request"
    try:
        await _add(api_client, owner_h, job_id, cand_id, "manual_search")

        # O własną osobę się nie prosi, a powód musi coś mówić.
        own = await api_client.post(
            url, headers=owner_h, json=_body(cand_id, job_id, reason="moja")
        )
        assert own.status_code == 409, own.text
        short = await api_client.post(
            url, headers=asker_h, json=_body(cand_id, job_id, reason="x")
        )
        assert short.status_code == 422, short.text

        asked = await api_client.post(
            url,
            headers=asker_h,
            json=_body(cand_id, job_id, reason="Znam ją od lat, mam relację"),
        )
        assert asked.status_code == 200, asked.text
        [to_owner] = await _notifications(owner[0], _REQUEST)
        assert "prosi o Twoją osobę" in to_owner.title
        assert "Znam ją od lat" in to_owner.message

        card = await _card(api_client, owner_h, job_id, cand_id)
        assert card["claim_request_user_id"] == asker[0]
        assert card["claim_request_reason"] == "Znam ją od lat, mam relację"

        # Druga osoba czeka, aż pierwsza prośba się rozstrzygnie.
        second = await api_client.post(
            url, headers=third_h, json=_body(cand_id, job_id, reason="Też ją znam")
        )
        assert second.status_code == 409, second.text

        # Odpowiada tylko osoba z blokadą.
        not_holder = await api_client.post(
            f"{url}/answer", headers=asker_h, json=_body(cand_id, job_id, accept=True)
        )
        assert not_holder.status_code == 403, not_holder.text

        declined = await api_client.post(
            f"{url}/answer", headers=owner_h, json=_body(cand_id, job_id, accept=False)
        )
        assert declined.status_code == 200, declined.text
        proc = await _process(cand_id, job_id)
        assert proc.claimed_by_user_id == owner[0]
        assert proc.claim_request_user_id is None
        [to_asker] = await _notifications(asker[0], _ANSWER)
        assert "zostawia osobę u siebie" in to_asker.title
        no_request = await api_client.post(
            f"{url}/answer", headers=owner_h, json=_body(cand_id, job_id, accept=True)
        )
        assert no_request.status_code == 409, no_request.text

        await api_client.post(
            url,
            headers=asker_h,
            json=_body(cand_id, job_id, reason="Proszę jeszcze raz"),
        )
        accepted = await api_client.post(
            f"{url}/answer", headers=owner_h, json=_body(cand_id, job_id, accept=True)
        )
        assert accepted.status_code == 200, accepted.text
        proc = await _process(cand_id, job_id)
        assert proc.claimed_by_user_id == asker[0]
        assert proc.claim_request_user_id is None
        titles = [n.title for n in await _notifications(asker[0])]
        assert any("oddał(a) Ci osobę" in t for t in titles)
    finally:
        await _cleanup([cand_id], job_id)


async def test_request_on_a_free_person_says_take_it(api_client):
    owner, [other], job_id = await _team()
    cand_id = await _seed_candidate()
    owner_h = await _login(api_client, owner[1], owner[2])
    other_h = await _login(api_client, other[1], other[2])
    try:
        await _add(api_client, owner_h, job_id, cand_id, "manual_search")
        await api_client.post(
            "/api/pipeline/claim/request",
            headers=other_h,
            json=_body(cand_id, job_id, reason="Znam tę osobę"),
        )
        # Zwolnienie przy otwartej prośbie: proszący dostaje znać, że może brać.
        released = await api_client.post(
            "/api/pipeline/claim/release", headers=owner_h, json=_body(cand_id, job_id)
        )
        assert released.status_code == 200, released.text
        [notif] = await _notifications(other[0], _ANSWER)
        assert "zwolnił(a) osobę" in notif.title

        free = await api_client.post(
            "/api/pipeline/claim/request",
            headers=other_h,
            json=_body(cand_id, job_id, reason="Znam tę osobę"),
        )
        assert free.status_code == 409, free.text
        assert "Biorę" in free.json()["detail"]
    finally:
        await _cleanup([cand_id], job_id)


def _proc(**kw) -> SimpleNamespace:
    base = dict(
        claimed_by_user_id=1,
        claimed_until=datetime(2026, 11, 25, 20, tzinfo=timezone.utc),
        claim_request_user_id=2,
        claim_request_reason="znam",
        claim_request_at=datetime(2026, 11, 25, 10, tzinfo=timezone.utc),
    )
    return SimpleNamespace(**{**base, **kw})


def test_pending_request_only_while_someone_else_holds_the_lock() -> None:
    now = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
    request = candidate_claim.pending_request(_proc(), now)
    assert request is not None and request.user_id == 2
    # Blokada wygasła albo zwolniona: prośba nic nie znaczy.
    assert candidate_claim.pending_request(_proc(claimed_until=now), now) is None
    # Prosząca osoba sama ma blokadę.
    assert candidate_claim.pending_request(_proc(claimed_by_user_id=2), now) is None
    # Prosząca osoba ma nieaktywne konto.
    assert candidate_claim.pending_request(_proc(), now, {2}) is None
    assert (
        candidate_claim.pending_request(_proc(claim_request_user_id=None), now) is None
    )


def test_new_claim_and_release_drop_the_request() -> None:
    now = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
    proc = _proc()
    candidate_claim.release_claim(proc, now)
    assert proc.claimed_by_user_id == 1 and proc.claimed_until == now
    assert proc.claim_request_user_id is None
    proc = _proc()
    candidate_claim.set_claim(proc, 3, now)
    assert proc.claim_request_user_id is None and proc.claim_request_at is None
