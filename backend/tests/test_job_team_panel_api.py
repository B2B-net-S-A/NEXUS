"""Zespół dla klienta przez API: bramki, link, wyciek pól, wybór składu. Dane fikcyjne."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.client import Client
from app.models.client_panel import ClientPanel, ClientPanelCandidate
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.job_team_panel import JobTeam, JobTeamSelection
from app.models.notification import Notification, NotificationType
from app.models.user import UserRole
from app.services import client_panel as panel_service
from app.services import job_team_panel as service
from tests.test_client_panel_api import (
    _assert_no_private_data,
    _author,
    _candidate,
    _user,
)

BASE = "/api/job-teams"


class World:
    dl_id: int
    dl_headers: dict[str, str]
    recruiter_id: int
    client_id: int
    job_a: int
    job_b: int
    anna: int
    bartek: int


async def _job(db, world: World, client_id: int, title: str, **extra: Any) -> int:
    fields: dict[str, Any] = {"status": JobStatus.published, **extra}
    job = Job(
        title=title,
        client_id=client_id,
        recruiter_id=world.recruiter_id,
        delivery_lead_id=world.dl_id,
        description="Treść zapytania klienta",
        location="Warszawa",
        remote_policy=RemotePolicy.hybrid,
        must_skills=[{"name": "Python"}],
        nice_skills=[],
        working_title="Tytuł roboczy wewnętrzny",
        **fields,
    )
    db.add(job)
    await db.flush()
    return job.id


async def _world() -> World:
    world = World()
    world.dl_id, world.dl_headers = await _user(UserRole.delivery_lead)
    world.recruiter_id, _ = await _user(UserRole.recruiter)
    tag = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Klient Zespołu {tag}")
        db.add(client)
        await db.flush()
        world.client_id = client.id
        world.job_a = await _job(
            db,
            world,
            client.id,
            f"Android {tag}",
            headcount=2,
            rate_budget_hourly_min=Decimal("120.00"),
            rate_budget_hourly=Decimal("160.00"),
        )
        world.job_b = await _job(db, world, client.id, f"Backend {tag}")
        world.anna = await _candidate(db, job_id=world.job_a, actor=world.recruiter_id)
        world.bartek = await _candidate(
            db, job_id=world.job_b, actor=world.recruiter_id, name="Bartek"
        )
        await db.commit()
    return world


async def _create(app_client: AsyncClient, world: World) -> dict:
    response = await app_client.post(
        BASE,
        headers=world.dl_headers,
        json={"name": "  Zespół   mobilny ", "job_ids": [world.job_a, world.job_b]},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _enable(app_client: AsyncClient, world: World, team_id: int, **extra) -> str:
    response = await app_client.put(
        f"{BASE}/{team_id}/panel",
        headers=world.dl_headers,
        json={"enabled": True, **extra},
    )
    assert response.status_code == 200, response.text
    return response.json()["panel"]["url"].rsplit("/k/z/", 1)[1]


async def _public(app_client: AsyncClient, token: str) -> Any:
    return await app_client.get(f"/api/public/team-panel/{token}")


# ── Zakładanie i skład ───────────────────────────────────────────────────────


async def test_create_returns_team_detail_with_positions_and_rates(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    detail = await _create(app_client, world)
    assert set(detail) == {
        "id",
        "name",
        "client_id",
        "client_name",
        "hours_per_month",
        "positions",
        "panel",
        "selections",
    }
    assert detail["name"] == "Zespół mobilny"
    assert detail["client_id"] == world.client_id
    assert detail["hours_per_month"] == 168
    assert detail["panel"] == {
        "enabled": False,
        "show_rate": True,
        "expires_at": None,
        "url": None,
        "short_url": None,
    }
    first = detail["positions"][0]
    assert first["job_id"] == world.job_a
    assert first["headcount"] == 2
    assert (first["budget_min"], first["budget_max"]) == (120.0, 160.0)
    assert first["closed"] is False
    assert first["delivery_lead"]["id"] == world.dl_id
    person = first["candidates"][0]
    assert set(person) == {
        "candidate_id",
        "name",
        "stage",
        "sent_at",
        "available_from",
        "client_rate",
        "expected_rate",
    }
    assert person["candidate_id"] == world.anna
    assert person["client_rate"] == {"value": 150.5, "unit": "hourly", "currency": "PLN"}
    assert person["expected_rate"]["value"] == 987.65
    assert detail["positions"][1]["headcount"] == 1

    by_job = await app_client.get(f"{BASE}/by-job/{world.job_b}", headers=world.dl_headers)
    assert by_job.json() == {"team": {"id": detail["id"], "name": "Zespół mobilny"}}

    listing = await app_client.get(
        BASE, params={"client_id": world.client_id}, headers=world.dl_headers
    )
    assert listing.json() == [
        {
            "id": detail["id"],
            "name": "Zespół mobilny",
            "client_id": world.client_id,
            "client_name": detail["client_name"],
            "positions": 2,
            "seats": 3,
        }
    ]


async def test_create_refuses_other_client_closed_and_taken_jobs(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        other = Client(name=f"Inny klient {uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.flush()
        foreign = await _job(db, world, other.id, "Obca rola")
        closed = await _job(
            db, world, world.client_id, "Zamknięta", status=JobStatus.closed
        )
        await db.commit()
    for job_ids in ([world.job_a, foreign], [world.job_a, closed]):
        refused = await app_client.post(
            BASE, headers=world.dl_headers, json={"name": "X", "job_ids": job_ids}
        )
        assert refused.status_code == 409, refused.text
    await _create(app_client, world)
    taken = await app_client.post(
        BASE, headers=world.dl_headers, json={"name": "Y", "job_ids": [world.job_a]}
    )
    assert taken.status_code == 409
    assert "innym zespole" in taken.json()["detail"]
    missing = await app_client.post(
        BASE, headers=world.dl_headers, json={"name": "Z", "job_ids": [10**9]}
    )
    assert missing.status_code == 404
    empty = await app_client.post(
        BASE, headers=world.dl_headers, json={"name": "Z", "job_ids": []}
    )
    assert empty.status_code == 422


async def test_patch_renames_adds_and_removes(app_client: AsyncClient) -> None:
    world = await _world()
    detail = await _create(app_client, world)
    url = f"{BASE}/{detail['id']}"
    async with AsyncSessionLocal() as db:
        extra = await _job(db, world, world.client_id, "Tester")
        await db.commit()
    changed = await app_client.patch(
        url,
        headers=world.dl_headers,
        json={"name": "Nowa nazwa", "add_job_ids": [extra], "remove_job_ids": [world.job_b]},
    )
    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert body["name"] == "Nowa nazwa"
    assert [p["job_id"] for p in body["positions"]] == [world.job_a, extra]
    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, world.job_b)).team_id is None
    last = await app_client.patch(
        url,
        headers=world.dl_headers,
        json={"remove_job_ids": [world.job_a, extra]},
    )
    assert last.status_code == 422
    foreign = await app_client.patch(
        url, headers=world.dl_headers, json={"remove_job_ids": [world.job_b]}
    )
    assert foreign.status_code == 422


# ── Link zespołu ─────────────────────────────────────────────────────────────


async def test_enabling_the_team_link_enables_position_panels(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    detail = await _create(app_client, world)
    token = await _enable(app_client, world, detail["id"], show_rate=False)
    async with AsyncSessionLocal() as db:
        team = await db.get(JobTeam, detail["id"])
        assert team.panel_token_sha256 == panel_service.token_digest(token)
        assert token not in (team.panel_token_sha256, team.panel_token_nonce)
        days = (team.panel_expires_at - datetime.now(timezone.utc)).days
        assert 59 <= days <= 60
        panels = (
            await db.scalars(
                select(ClientPanel).where(
                    ClientPanel.job_id.in_([world.job_a, world.job_b])
                )
            )
        ).all()
        assert len(panels) == 2
        assert all(p.enabled and not p.show_rate for p in panels)
        assert all(p.expires_at == team.panel_expires_at for p in panels)
        actions = (
            await db.scalars(
                select(Activity.action).where(
                    Activity.entity_type == "job",
                    Activity.entity_id == world.job_a,
                )
            )
        ).all()
        assert "job_team_panel_enabled" in actions

    response = await _public(app_client, token)
    assert response.status_code == 200, response.text
    assert response.headers["x-robots-tag"] == "noindex"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"

    off = await app_client.put(
        f"{BASE}/{detail['id']}/panel",
        headers=world.dl_headers,
        json={"enabled": False},
    )
    assert off.json()["panel"]["url"] is None
    assert (await _public(app_client, token)).status_code == 404
    async with AsyncSessionLocal() as db:
        panels = (
            await db.scalars(
                select(ClientPanel).where(
                    ClientPanel.job_id.in_([world.job_a, world.job_b])
                )
            )
        ).all()
        assert not any(p.enabled for p in panels)


async def test_enabling_the_team_link_keeps_a_rate_the_dl_hid_on_a_position(
    app_client: AsyncClient,
) -> None:
    # Przegląd bezpieczeństwa 15.11.2026: włączenie linku zespołu nadpisywało
    # `show_rate` panelu stanowiska, więc ukryta przez DL-a stawka wychodziła.
    world = await _world()
    async with AsyncSessionLocal() as db:
        db.add(ClientPanel(job_id=world.job_a, enabled=False, show_rate=False))
        await db.commit()
    detail = await _create(app_client, world)
    token = await _enable(app_client, world, detail["id"])
    async with AsyncSessionLocal() as db:
        panels = {
            p.job_id: p
            for p in (
                await db.scalars(
                    select(ClientPanel).where(
                        ClientPanel.job_id.in_([world.job_a, world.job_b])
                    )
                )
            ).all()
        }
    assert panels[world.job_a].enabled and not panels[world.job_a].show_rate
    assert panels[world.job_b].enabled and panels[world.job_b].show_rate
    view = (await _public(app_client, token)).json()
    hidden = [p for p in view["positions"] if not p["view"]["panel"]["show_rate"]]
    assert len(hidden) == 1
    assert all(c["rate"] is None for c in hidden[0]["view"]["candidates"])

    # Jawna decyzja na zespole („Pokazuj stawki”) obejmuje wszystkie stanowiska.
    response = await app_client.put(
        f"{BASE}/{detail['id']}/panel",
        headers=world.dl_headers,
        json={"show_rate": True},
    )
    assert response.status_code == 200, response.text
    async with AsyncSessionLocal() as db:
        panel = await db.scalar(
            select(ClientPanel).where(ClientPanel.job_id == world.job_a)
        )
        assert panel.show_rate


async def test_rotate_expired_and_unknown(app_client: AsyncClient) -> None:
    world = await _world()
    detail = await _create(app_client, world)
    url = f"{BASE}/{detail['id']}/panel/rotate-link"
    assert (
        await app_client.post(url, headers=world.dl_headers)
    ).status_code == 409
    token = await _enable(app_client, world, detail["id"])
    old_key = (await _public(app_client, token)).json()["positions"][0]["key"]
    rotated = await app_client.post(url, headers=world.dl_headers)
    assert rotated.status_code == 200
    new_token = rotated.json()["panel"]["url"].rsplit("/k/z/", 1)[1]
    assert new_token != token
    assert (await _public(app_client, token)).status_code == 404
    fresh = (await _public(app_client, new_token)).json()
    assert fresh["positions"][0]["key"] != old_key
    assert (
        await app_client.get(f"/api/public/panel/{old_key}")
    ).status_code == 404

    async with AsyncSessionLocal() as db:
        team = await db.get(JobTeam, detail["id"])
        team.panel_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()
    assert (await _public(app_client, new_token)).status_code == 410
    assert (await _public(app_client, "a" * 16)).status_code == 404


async def test_closed_position_is_skipped_and_all_closed_refuses_the_link(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    detail = await _create(app_client, world)
    token = await _enable(app_client, world, detail["id"])
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world.job_b)
        job.status = JobStatus.closed
        await db.commit()
    body = (await _public(app_client, token)).json()
    assert [p["headcount"] for p in body["positions"]] == [2]

    await app_client.put(
        f"{BASE}/{detail['id']}/panel", headers=world.dl_headers, json={"enabled": False}
    )
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world.job_a)
        job.status = JobStatus.closed
        await db.commit()
    refused = await app_client.put(
        f"{BASE}/{detail['id']}/panel", headers=world.dl_headers, json={"enabled": True}
    )
    assert refused.status_code == 409


async def test_public_team_shape_has_no_private_fields(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    detail = await _create(app_client, world)
    token = await _enable(app_client, world, detail["id"])
    response = await _public(app_client, token)
    assert response.status_code == 200, response.text
    body = response.json()
    # Klucze wymagań to dane rekrutacji, nie pola.
    _assert_no_private_data(body, allowed=frozenset({"python"}))
    assert set(body) == {"team", "hours_per_month", "positions"}
    assert set(body["team"]) == {"name", "client_name", "expires_at", "owner"}
    assert set(body["team"]["owner"]) == {"name"}
    assert body["team"]["name"] == "Zespół mobilny"
    position = body["positions"][0]
    assert set(position) == {"key", "short", "headcount", "view"}
    assert set(position["view"]) == {
        "panel",
        "job",
        "owner",
        "requirements",
        "candidates",
    }
    # Klucz to działający link panelu stanowiska: szczegóły idą jego trasami.
    public_id = position["view"]["candidates"][0]["public_id"]
    detail_view = await app_client.get(
        f"/api/public/panel/{position['key']}/candidates/{public_id}"
    )
    assert detail_view.status_code == 200, detail_view.text
    assert str(detail["id"]) not in {str(v) for v in body["team"].values()}


# ── Wybór składu ─────────────────────────────────────────────────────────────


async def test_selection_is_saved_mapped_and_rings_the_dl(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    detail = await _create(app_client, world)
    token = await _enable(app_client, world, detail["id"])
    body = (await _public(app_client, token)).json()
    picks = {
        p["key"]: [c["public_id"] for c in p["view"]["candidates"]]
        for p in body["positions"]
    }
    sent = await app_client.post(
        f"/api/public/team-panel/{token}/selection",
        json=_author(picks=picks, note="Prosimy o rozmowy w czwartek"),
    )
    assert sent.status_code == 204, sent.text
    assert sent.headers["cache-control"] == "no-store"
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(JobTeamSelection).where(JobTeamSelection.team_id == detail["id"])
        )
        assert row.picks == [
            {"job_id": world.job_a, "candidate_ids": [world.anna]},
            {"job_id": world.job_b, "candidate_ids": [world.bartek]},
        ]
        assert row.author_email == "jan@obcy.example.com"
        assert row.ip_hash and "." not in row.ip_hash
        bells = (
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == world.dl_id,
                    Notification.related_entity_type == "job_team_selection",
                )
            )
        ).all()
        assert len(bells) == 1
        assert bells[0].notification_type == NotificationType.client_panel_request
        assert "czwartek" not in bells[0].message
        assert "Jan" not in bells[0].message
    team = (
        await app_client.get(f"{BASE}/{detail['id']}", headers=world.dl_headers)
    ).json()
    selection = team["selections"][0]
    assert selection["note"] == "Prosimy o rozmowy w czwartek"
    assert selection["picks"][0]["candidates"][0]["candidate_id"] == world.anna


async def test_selection_refuses_unknown_key_person_and_hidden(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    detail = await _create(app_client, world)
    token = await _enable(app_client, world, detail["id"])
    body = (await _public(app_client, token)).json()
    key_a, key_b = (p["key"] for p in body["positions"])
    anna_public = body["positions"][0]["view"]["candidates"][0]["public_id"]
    url = f"/api/public/team-panel/{token}/selection"
    for picks in (
        {"a" * 16: [anna_public]},
        {key_b: [anna_public]},
        {key_a: ["nieznany"]},
        {key_a: []},
        {},
    ):
        refused = await app_client.post(url, json=_author(picks=picks))
        assert refused.status_code == 422, (picks, refused.text)
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(ClientPanelCandidate).where(
                ClientPanelCandidate.public_id == anna_public
            )
        )
        row.hidden = True
        await db.commit()
    hidden = await app_client.post(url, json=_author(picks={key_a: [anna_public]}))
    assert hidden.status_code == 422
    trap = await app_client.post(
        url, json=_author(picks={key_a: ["x"]}, honeypot="bot")
    )
    assert trap.status_code == 204
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(JobTeamSelection).where(
                    JobTeamSelection.team_id == detail["id"]
                )
            )
        ) is None


async def test_daily_selection_limit_gives_429(app_client: AsyncClient) -> None:
    world = await _world()
    detail = await _create(app_client, world)
    token = await _enable(app_client, world, detail["id"])
    async with AsyncSessionLocal() as db:
        db.add_all(
            JobTeamSelection(
                team_id=detail["id"],
                picks=[],
                author_name="Jan",
                author_email="jan@example.com",
            )
            for _ in range(service.DAILY_SELECTION_LIMIT)
        )
        await db.commit()
    limited = await app_client.post(
        f"/api/public/team-panel/{token}/selection",
        json=_author(picks={"a" * 16: ["x"]}),
    )
    assert limited.status_code == 429


# ── Bramki ───────────────────────────────────────────────────────────────────


async def test_dl_of_a_foreign_recruitment_gets_403(app_client: AsyncClient) -> None:
    world = await _world()
    detail = await _create(app_client, world)
    _, stranger = await _user(UserRole.delivery_lead)
    url = f"{BASE}/{detail['id']}"
    assert (await app_client.get(url, headers=stranger)).status_code == 403
    assert (
        await app_client.put(f"{url}/panel", headers=stranger, json={"enabled": True})
    ).status_code == 403
    assert (
        await app_client.patch(url, headers=stranger, json={"name": "x"})
    ).status_code == 403
    assert (
        await app_client.post(
            BASE, headers=stranger, json={"name": "x", "job_ids": [world.job_a]}
        )
    ).status_code == 403
    listing = await app_client.get(
        BASE, params={"client_id": world.client_id}, headers=stranger
    )
    assert listing.json() == []


async def test_a_team_with_one_foreign_job_is_closed_to_its_partial_dl(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    detail = await _create(app_client, world)
    other_dl, other_headers = await _user(UserRole.delivery_lead)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world.job_b)
        job.delivery_lead_id = other_dl
        await db.commit()
    assert (
        await app_client.get(f"{BASE}/{detail['id']}", headers=other_headers)
    ).status_code == 403


@pytest.mark.parametrize("role", [UserRole.recruiter, UserRole.user])
async def test_roles_without_the_permission_get_403(
    app_client: AsyncClient, role: UserRole
) -> None:
    world = await _world()
    detail = await _create(app_client, world)
    _, headers = await _user(role)
    assert (
        await app_client.get(f"{BASE}/{detail['id']}", headers=headers)
    ).status_code == 403
    assert (await app_client.get(BASE, headers=headers)).status_code == 403


async def test_internal_routes_require_a_login(app_client: AsyncClient) -> None:
    assert (await app_client.get(BASE)).status_code == 401
    assert (await app_client.get(f"{BASE}/1")).status_code == 401
    assert (await app_client.get(f"{BASE}/by-job/1")).status_code == 401
