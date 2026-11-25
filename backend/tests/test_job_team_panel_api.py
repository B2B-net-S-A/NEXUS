"""Zespół dla klienta przez API: bramki, link, wyciek pól, wybór składu, gotowe
składy i rozmowy z całym składem. Dane fikcyjne."""

from __future__ import annotations

import json
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
from app.models.candidate import Candidate, CandidateStatus
from app.models.client import Client
from app.models.client_interview_slot_request import ClientInterviewSlotRequest
from app.models.client_panel import (
    ClientPanel,
    ClientPanelCandidate,
    ClientPanelRequest,
)
from app.models.contract import RateUnit
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.job_team_panel import JobTeam, JobTeamSelection
from app.models.notification import Notification, NotificationType
from app.models.user import UserRole
from app.services import client_panel as panel_service
from app.services import client_panel_requests as requests_service
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
        "variants",
        "variants_approved_at",
    }
    assert detail["variants"] == []
    assert detail["variants_approved_at"] is None
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
    # Ekrany wewnętrzne: tytuł dla zespołu, nie nazwa od klienta z numerem.
    assert first["title"] == "Tytuł roboczy wewnętrzny"
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


async def test_show_rate_on_the_team_keeps_a_position_the_dl_disabled(
    app_client: AsyncClient,
) -> None:
    # Audyt 24.11.2026 (r3): „Pokazuj stawki” na zespole wołało synchronizację
    # paneli stanowisk jak przy włączeniu linku, więc stanowisko wyłączone
    # przez DL-a wracało do klienta.
    world = await _world()
    detail = await _create(app_client, world)
    token = await _enable(app_client, world, detail["id"])
    off = await app_client.put(
        f"/api/client-panel/jobs/{world.job_b}",
        headers=world.dl_headers,
        json={"enabled": False},
    )
    assert off.status_code == 200, off.text
    async with AsyncSessionLocal() as db:
        expires_b = (
            await db.scalar(select(ClientPanel).where(ClientPanel.job_id == world.job_b))
        ).expires_at

    for body in ({"show_rate": False}, {"show_rate": True}, {"enabled": True}):
        response = await app_client.put(
            f"{BASE}/{detail['id']}/panel", headers=world.dl_headers, json=body
        )
        assert response.status_code == 200, response.text
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
        assert panels[world.job_a].enabled
        assert not panels[world.job_b].enabled, body
        assert panels[world.job_b].expires_at == expires_b
        view = (await _public(app_client, token)).json()
        assert [p["headcount"] for p in view["positions"]] == [2], body
    # Jawna zmiana stawki dalej obejmuje stanowiska zespołu.
    assert panels[world.job_a].show_rate and panels[world.job_b].show_rate


async def test_changing_the_client_of_a_team_job_is_refused(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    # Audyt 24.11.2026 (r3): zmiana klienta zostawiała rekrutację w zespole
    # starego klienta, a link zespołu pokazywał ją dalej.
    world = await _world()
    detail = await _create(app_client, world)
    async with AsyncSessionLocal() as db:
        other = Client(name=f"Inny Klient {uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        other_id = other.id
    refused = await app_client.patch(
        f"/api/jobs/{world.job_a}",
        headers=app_auth_headers,
        json={"client_id": other_id, "title": "Nowy tytuł"},
    )
    assert refused.status_code == 409, refused.text
    assert "zdejmij ją z zespołu" in refused.text
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world.job_a)
        assert (job.client_id, job.team_id) == (world.client_id, detail["id"])
        assert job.title != "Nowy tytuł"
    # Ten sam klient (okno edycji odsyła komplet pól) przechodzi.
    same = await app_client.patch(
        f"/api/jobs/{world.job_a}",
        headers=app_auth_headers,
        json={"client_id": world.client_id},
    )
    assert same.status_code == 200, same.text


async def test_changing_the_client_closes_the_job_panel_and_its_link(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    world = await _world()
    enabled = await app_client.put(
        f"/api/client-panel/jobs/{world.job_a}",
        headers=world.dl_headers,
        json={"enabled": True},
    )
    assert enabled.status_code == 200, enabled.text
    token = enabled.json()["url"].rsplit("/k/", 1)[1]
    assert (await app_client.get(f"/api/public/panel/{token}")).status_code == 200
    async with AsyncSessionLocal() as db:
        other = Client(name=f"Inny Klient {uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.commit()
        other_id = other.id
    moved = await app_client.patch(
        f"/api/jobs/{world.job_a}",
        headers=app_auth_headers,
        json={"client_id": other_id},
    )
    assert moved.status_code == 200, moved.text
    assert (await app_client.get(f"/api/public/panel/{token}")).status_code == 404
    async with AsyncSessionLocal() as db:
        panel = await db.scalar(
            select(ClientPanel).where(ClientPanel.job_id == world.job_a)
        )
        assert not panel.enabled
        # Nowy sekret: ponowne włączenie nie ożywia ramek w CV starego klienta.
        assert panel_service.current_token(panel) not in (None, token)
        audits = (
            await db.scalars(
                select(Activity).where(
                    Activity.entity_type == "job",
                    Activity.entity_id == world.job_a,
                    Activity.action == "client_panel_disabled",
                )
            )
        ).all()
    assert [a.details for a in audits] == [
        {"reason": "client_changed", "previous_client_id": world.client_id}
    ]


async def test_team_link_skips_a_position_of_another_client(
    app_client: AsyncClient,
) -> None:
    # Dane sprzed odmowy w PATCH (albo zapis z pominięciem API): stanowisko
    # innego klienta w zespole nie trafia do linku zespołu.
    world = await _world()
    detail = await _create(app_client, world)
    token = await _enable(app_client, world, detail["id"])
    async with AsyncSessionLocal() as db:
        other = Client(name=f"Inny Klient {uuid.uuid4().hex[:6]}")
        db.add(other)
        await db.flush()
        job = await db.get(Job, world.job_b)
        job.client_id = other.id
        await db.commit()
    view = (await _public(app_client, token)).json()
    assert [p["headcount"] for p in view["positions"]] == [2]


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
    assert set(body) == {"team", "hours_per_month", "positions", "variants"}
    assert body["variants"] == []
    assert set(body["team"]) == {"name", "client_name", "expires_at", "owner"}
    assert set(body["team"]["owner"]) == {"name"}
    assert body["team"]["name"] == "Zespół mobilny"
    position = body["positions"][0]
    assert set(position) == {"key", "short", "headcount", "estimate", "view"}
    # Stanowisko ze stawką godzinową na liście nie dostaje szacunku.
    assert position["estimate"] is None
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


# ── Gotowe składy (Z3) ───────────────────────────────────────────────────────


def _variant(world: World, **extra: Any) -> dict[str, Any]:
    return {
        "key": "fast",
        "name": "  Najszybszy   start ",
        "why": "Cały skład od grudnia.",
        "picks": [
            {"job_id": world.job_a, "candidate_ids": [world.anna]},
            {"job_id": world.job_b, "candidate_ids": [world.bartek]},
        ],
        **extra,
    }


async def test_proposal_gives_three_variants_from_sent_people(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    detail = await _create(app_client, world)
    response = await app_client.get(
        f"{BASE}/{detail['id']}/variants/proposal", headers=world.dl_headers
    )
    assert response.status_code == 200, response.text
    proposed = response.json()["variants"]
    assert [v["key"] for v in proposed] == ["fast", "cheap", "evidence"]
    for variant in proposed:
        assert {p["job_id"]: p["candidate_ids"] for p in variant["picks"]} == {
            world.job_a: [world.anna],
            world.job_b: [world.bartek],
        }
        # Dwie osoby po 150,50 zł/h, start nieznany (brak dat w danych testowych).
        assert variant["hourly_total"] == 301.0
        assert variant["unknown_start"] == 2
    # Propozycja niczego nie zapisuje.
    async with AsyncSessionLocal() as db:
        team = await db.get(JobTeam, detail["id"])
        assert team.variants == [] and team.variants_approved_at is None


async def test_proposal_skips_people_hidden_or_marked_not_fit(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    detail = await _create(app_client, world)
    token = await _enable(app_client, world, detail["id"])
    body = (await _public(app_client, token)).json()
    async with AsyncSessionLocal() as db:
        extra = await _candidate_on(db, world.job_a, world, "Cezary")
        await db.commit()
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(ClientPanelCandidate).where(
                ClientPanelCandidate.public_id
                == body["positions"][0]["view"]["candidates"][0]["public_id"]
            )
        )
        row.hidden = True
        panel_b = await db.scalar(
            select(ClientPanel).where(ClientPanel.job_id == world.job_b)
        )
        db.add(
            ClientPanelRequest(
                panel_id=panel_b.id,
                job_id=world.job_b,
                candidate_id=world.bartek,
                kind="not_fit",
                author_name="Jan",
                author_email="jan@example.com",
            )
        )
        await db.commit()
    proposed = (
        await app_client.get(
            f"{BASE}/{detail['id']}/variants/proposal", headers=world.dl_headers
        )
    ).json()["variants"]
    for variant in proposed:
        assert variant["picks"] == [{"job_id": world.job_a, "candidate_ids": [extra]}]


async def _candidate_on(db, job_id: int, world: World, name: str) -> int:
    return await _candidate(db, job_id=job_id, actor=world.recruiter_id, name=name)


async def test_dl_approves_variants_and_can_withdraw_them(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    detail = await _create(app_client, world)
    url = f"{BASE}/{detail['id']}/variants"
    saved = await app_client.put(
        url, headers=world.dl_headers, json={"variants": [_variant(world)]}
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["variants_approved_at"]
    assert body["variants"] == [
        {
            "key": "fast",
            "name": "Najszybszy start",
            "why": "Cały skład od grudnia.",
            "picks": [
                {
                    "job_id": world.job_a,
                    "candidates": [
                        {
                            "candidate_id": world.anna,
                            "name": body["positions"][0]["candidates"][0]["name"],
                        }
                    ],
                },
                {
                    "job_id": world.job_b,
                    "candidates": [
                        {
                            "candidate_id": world.bartek,
                            "name": body["positions"][1]["candidates"][0]["name"],
                        }
                    ],
                },
            ],
        }
    ]
    async with AsyncSessionLocal() as db:
        team = await db.get(JobTeam, detail["id"])
        assert team.variants_approved_by == world.dl_id
        actions = (
            await db.scalars(
                select(Activity.action).where(
                    Activity.entity_type == "job", Activity.entity_id == world.job_b
                )
            )
        ).all()
        assert "job_team_variants_approved" in actions

    withdrawn = await app_client.put(url, headers=world.dl_headers, json={"variants": []})
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["variants"] == []
    assert withdrawn.json()["variants_approved_at"] is None


async def test_variants_refuse_foreign_job_unsent_person_and_too_many_people(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    detail = await _create(app_client, world)
    async with AsyncSessionLocal() as db:
        outside = await _job(db, world, world.client_id, "Poza zespołem")
        unsent = await _candidate(
            db, job_id=world.job_b, actor=world.recruiter_id, name="Dorota", sent=False
        )
        second = await _candidate_on(db, world.job_b, world, "Ewa")
        await db.commit()
    url = f"{BASE}/{detail['id']}/variants"
    for picks in (
        [{"job_id": outside, "candidate_ids": [world.anna]}],
        [{"job_id": world.job_b, "candidate_ids": [unsent]}],
        # Osoba z innego stanowiska zespołu.
        [{"job_id": world.job_b, "candidate_ids": [world.anna]}],
        # Backend ma jedno miejsce.
        [{"job_id": world.job_b, "candidate_ids": [world.bartek, second]}],
    ):
        refused = await app_client.put(
            url,
            headers=world.dl_headers,
            json={"variants": [_variant(world, picks=picks)]},
        )
        assert refused.status_code == 422, (picks, refused.text)
    for bad in (
        {"variants": [_variant(world, name="   ")]},
        {"variants": [_variant(world, name="x" * 61)]},
        {"variants": [_variant(world, why="x" * 241)]},
        {"variants": [_variant(world, key=f"k{i}") for i in range(4)]},
    ):
        refused = await app_client.put(url, headers=world.dl_headers, json=bad)
        assert refused.status_code == 422, refused.text
    async with AsyncSessionLocal() as db:
        assert (await db.get(JobTeam, detail["id"])).variants == []


async def test_variants_are_closed_to_non_managers(app_client: AsyncClient) -> None:
    world = await _world()
    detail = await _create(app_client, world)
    _, stranger = await _user(UserRole.delivery_lead)
    _, recruiter = await _user(UserRole.recruiter)
    url = f"{BASE}/{detail['id']}/variants"
    for headers in (stranger, recruiter):
        assert (
            await app_client.get(f"{url}/proposal", headers=headers)
        ).status_code == 403
        assert (
            await app_client.put(
                url, headers=headers, json={"variants": [_variant(world)]}
            )
        ).status_code == 403
    assert (await app_client.get(f"{url}/proposal")).status_code == 401


async def test_client_sees_only_approved_variants_without_hidden_people(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    detail = await _create(app_client, world)
    token = await _enable(app_client, world, detail["id"])
    assert (await _public(app_client, token)).json()["variants"] == []
    await app_client.put(
        f"{BASE}/{detail['id']}/variants",
        headers=world.dl_headers,
        json={
            "variants": [
                _variant(world),
                _variant(
                    world,
                    key="tylko-android",
                    name="Sam Android",
                    picks=[{"job_id": world.job_a, "candidate_ids": [world.anna]}],
                ),
            ]
        },
    )
    body = (await _public(app_client, token)).json()
    _assert_no_private_data(body, allowed=frozenset({"python"}))
    key_a, key_b = (p["key"] for p in body["positions"])
    anna_public = body["positions"][0]["view"]["candidates"][0]["public_id"]
    bartek_public = body["positions"][1]["view"]["candidates"][0]["public_id"]
    assert body["variants"] == [
        {
            "key": "fast",
            "name": "Najszybszy start",
            "why": "Cały skład od grudnia.",
            "picks": {key_a: [anna_public], key_b: [bartek_public]},
        },
        {
            "key": "tylko-android",
            "name": "Sam Android",
            "why": "Cały skład od grudnia.",
            "picks": {key_a: [anna_public]},
        },
    ]
    for variant in body["variants"]:
        assert set(variant) == {"key", "name", "why", "picks"}

    # DL ukrywa Annę: wypada ze składów, skład bez nikogo znika.
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(ClientPanelCandidate).where(
                ClientPanelCandidate.public_id == anna_public
            )
        )
        row.hidden = True
        await db.commit()
    body = (await _public(app_client, token)).json()
    assert body["variants"] == [
        {
            "key": "fast",
            "name": "Najszybszy start",
            "why": "Cały skład od grudnia.",
            "picks": {key_b: [bartek_public]},
        }
    ]

    await app_client.put(
        f"{BASE}/{detail['id']}/variants", headers=world.dl_headers, json={"variants": []}
    )
    assert (await _public(app_client, token)).json()["variants"] == []


# ── Rozmowy z całym składem (Z3) ─────────────────────────────────────────────


def _start(days: int) -> str:
    base = datetime.now(timezone.utc) + timedelta(days=days)
    return base.replace(hour=9, minute=0, second=0, microsecond=0).isoformat()


async def _team_with_link(app_client: AsyncClient) -> tuple[World, dict, str, dict]:
    world = await _world()
    detail = await _create(app_client, world)
    token = await _enable(app_client, world, detail["id"])
    body = (await _public(app_client, token)).json()
    picks = {
        p["key"]: [c["public_id"] for c in p["view"]["candidates"]]
        for p in body["positions"]
    }
    return world, detail, token, picks


async def test_team_interviews_create_one_request_per_person(
    app_client: AsyncClient,
) -> None:
    world, _, token, picks = await _team_with_link(app_client)
    url = f"/api/public/team-panel/{token}/interviews"
    created = await app_client.post(
        url,
        json=_author(
            duration_minutes=45,
            slots=[{"start": _start(3)}, {"start": _start(4)}],
            interviewers="Dwie osoby z zespołu",
            prep_note="Proszę o kamerkę",
            picks=picks,
        ),
    )
    assert created.status_code == 200, created.text
    assert created.json() == {"created": 2, "skipped": []}
    assert created.headers["cache-control"] == "no-store"
    _assert_no_private_data(created.json())
    async with AsyncSessionLocal() as db:
        requests = (
            await db.scalars(
                select(ClientInterviewSlotRequest).where(
                    ClientInterviewSlotRequest.job_id.in_([world.job_a, world.job_b])
                )
            )
        ).all()
        assert {r.candidate_id for r in requests} == {world.anna, world.bartek}
        assert all(r.created_by == world.dl_id for r in requests)
        assert all(len(r.slots) == 2 for r in requests)
        assert all("Proszę o kamerkę" in r.note for r in requests)
        # Ta sama droga co prośba o jedną osobę: karta na „Rozmowie u klienta”,
        # wiersz sprawy w panelu stanowiska z wnioskiem.
        latest = await db.scalar(
            select(CandidateStage.stage)
            .where(
                CandidateStage.candidate_id == world.bartek,
                CandidateStage.job_id == world.job_b,
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )
        assert latest == PipelineStage.client_interview
        rows = (
            await db.scalars(
                select(ClientPanelRequest).where(
                    ClientPanelRequest.job_id.in_([world.job_a, world.job_b]),
                    ClientPanelRequest.kind == "interview",
                )
            )
        ).all()
        assert len(rows) == 2 and all(r.slot_request_id for r in rows)

    # Drugi raz: czekające terminy = pominięte, nie błąd.
    again = await app_client.post(
        url, json=_author(slots=[{"start": _start(5)}], picks=picks)
    )
    assert again.status_code == 200, again.text
    assert again.json()["created"] == 0
    assert sorted(s["reason"] for s in again.json()["skipped"]) == [
        "open_request",
        "open_request",
    ]
    assert {s["public_id"] for s in again.json()["skipped"]} == {
        pid for ids in picks.values() for pid in ids
    }


async def test_team_interviews_skip_one_open_request_and_create_the_rest(
    app_client: AsyncClient,
) -> None:
    world, _, token, picks = await _team_with_link(app_client)
    key_a, key_b = picks
    first = await app_client.post(
        f"/api/public/panel/{key_a}/candidates/{picks[key_a][0]}/interview",
        json=_author(slots=[{"start": _start(3)}]),
    )
    assert first.status_code == 201, first.text
    team = await app_client.post(
        f"/api/public/team-panel/{token}/interviews",
        json=_author(slots=[{"start": _start(4)}], picks=picks),
    )
    assert team.status_code == 200, team.text
    assert team.json() == {
        "created": 1,
        "skipped": [
            {"key": key_a, "public_id": picks[key_a][0], "reason": "open_request"}
        ],
    }


async def test_team_interviews_respect_limits_and_validation(
    app_client: AsyncClient,
) -> None:
    world, _, token, picks = await _team_with_link(app_client)
    url = f"/api/public/team-panel/{token}/interviews"
    key_a, key_b = picks
    for payload in (
        _author(slots=[{"start": _start(d)} for d in range(1, 8)], picks=picks),
        _author(slots=[{"start": "2020-01-01T09:00:00Z"}], picks=picks),
        _author(slots=[], picks=picks),
        _author(slots=[{"start": _start(3)}], picks={"a" * 16: picks[key_a]}),
        _author(slots=[{"start": _start(3)}], picks={key_b: picks[key_a]}),
        _author(slots=[{"start": _start(3)}], picks={}),
        _author(slots=[{"start": _start(3)}], duration_minutes=5, picks=picks),
    ):
        refused = await app_client.post(url, json=payload)
        assert refused.status_code == 422, (payload, refused.text)
    trap = await app_client.post(
        url, json=_author(slots=[{"start": _start(3)}], picks=picks, honeypot="bot")
    )
    assert trap.json() == {"created": 0, "skipped": []}

    # Prośby wyłączone na jednym stanowisku: jego osoby pominięte.
    async with AsyncSessionLocal() as db:
        panel = await db.scalar(
            select(ClientPanel).where(ClientPanel.job_id == world.job_b)
        )
        panel.allow_actions = False
        await db.commit()
    partial = await app_client.post(
        url, json=_author(slots=[{"start": _start(3)}], picks=picks)
    )
    assert partial.status_code == 200, partial.text
    assert partial.json() == {
        "created": 1,
        "skipped": [
            {"key": key_b, "public_id": picks[key_b][0], "reason": "actions_disabled"}
        ],
    }

    # Dzienny limit panelu stanowiska = 429 jak przy prośbie o jedną osobę.
    async with AsyncSessionLocal() as db:
        panel = await db.scalar(
            select(ClientPanel).where(ClientPanel.job_id == world.job_a)
        )
        db.add_all(
            ClientPanelRequest(
                panel_id=panel.id,
                job_id=world.job_a,
                kind="question",
                author_name="Jan",
                author_email="jan@example.com",
                body="?",
            )
            for _ in range(requests_service.DAILY_WRITE_LIMIT)
        )
        await db.commit()
    limited = await app_client.post(
        url, json=_author(slots=[{"start": _start(6)}], picks={key_a: picks[key_a]})
    )
    assert limited.status_code == 429


async def test_team_interviews_unknown_and_expired_links(
    app_client: AsyncClient,
) -> None:
    world, detail, token, picks = await _team_with_link(app_client)
    payload = _author(slots=[{"start": _start(3)}], picks=picks)
    unknown = await app_client.post(
        f"/api/public/team-panel/{'a' * 16}/interviews", json=payload
    )
    assert unknown.status_code == 404
    async with AsyncSessionLocal() as db:
        team = await db.get(JobTeam, detail["id"])
        team.panel_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()
    expired = await app_client.post(
        f"/api/public/team-panel/{token}/interviews", json=payload
    )
    assert expired.status_code == 410
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(ClientInterviewSlotRequest).where(
                    ClientInterviewSlotRequest.job_id == world.job_a
                )
            )
        ) is None


# ── Podpowiedź stawki z historii klienta (Z4) ────────────────────────────────

# Kategorie kompetencji z danych referencyjnych (0371): 2 = software_development.
_CATEGORY = 2
_OTHER_CATEGORY = 3


async def _rated_pair(
    db,
    job_id: int,
    world: World,
    value: str,
    *,
    unit: RateUnit = RateUnit.hourly,
    currency: str = "PLN",
    days_ago: int = 30,
) -> int:
    """Osoba z jedną stawką do klienta na rekrutacji ``job_id``."""
    tag = uuid.uuid4().hex[:6]
    candidate = Candidate(
        name="Osoba", lastname=f"Historyczna{tag}", status=CandidateStatus.active
    )
    db.add(candidate)
    await db.flush()
    db.add(
        CandidateStage(
            candidate_id=candidate.id,
            job_id=job_id,
            stage=PipelineStage.cv_sent,
            moved_by=world.recruiter_id,
            moved_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
            client_rate_value=Decimal(value),
            client_rate_unit=unit,
            client_rate_currency=currency,
        )
    )
    await db.flush()
    return candidate.id


async def _history(db, world: World, client_id: int, category: int) -> int:
    """Zamknięta rekrutacja klienta w kategorii — źródło historii stawek."""
    return await _job(
        db,
        world,
        client_id,
        f"Historia {uuid.uuid4().hex[:6]}",
        status=JobStatus.closed,
        competence_category_id=category,
    )


async def _set_category(job_id: int, category: int | None) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.competence_category_id = category
        await db.commit()


async def test_rate_hint_uses_only_this_client_category_and_window(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    await _set_category(world.job_a, _CATEGORY)
    await _set_category(world.job_b, _OTHER_CATEGORY)
    async with AsyncSessionLocal() as db:
        past = await _history(db, world, world.client_id, _CATEGORY)
        for value in ("100.00", "120.00", "140.00"):
            await _rated_pair(db, past, world, value)
        # Nie wchodzą: stawka dzienna, inna waluta, starsza niż 365 dni.
        await _rated_pair(db, past, world, "1500.00", unit=RateUnit.daily)
        await _rated_pair(db, past, world, "33.30", currency="EUR")
        await _rated_pair(db, past, world, "90.00", days_ago=400)
        # Para, której NAJNOWSZA stawka jest dzienna: starszej godzinowej nie bierzemy.
        changed = await _rated_pair(db, past, world, "95.00", days_ago=60)
        db.add(
            CandidateStage(
                candidate_id=changed,
                job_id=past,
                stage=PipelineStage.client_interview,
                moved_by=world.recruiter_id,
                moved_at=datetime.now(timezone.utc) - timedelta(days=20),
                client_rate_value=Decimal("1400.00"),
                client_rate_unit=RateUnit.daily,
                client_rate_currency="PLN",
            )
        )
        # Inny klient w tej samej kategorii: nigdy nie wchodzi.
        stranger = Client(name=f"Inny Klient {uuid.uuid4().hex[:6]}")
        db.add(stranger)
        await db.flush()
        foreign = await _history(db, world, stranger.id, _CATEGORY)
        for value in ("977.31", "977.32", "977.33"):
            await _rated_pair(db, foreign, world, value)
        # Druga kategoria tego klienta ma tylko dwie pary: za mało.
        thin = await _history(db, world, world.client_id, _OTHER_CATEGORY)
        for value in ("555.55", "560.00"):
            await _rated_pair(db, thin, world, value)
        await db.commit()

    detail = await _create(app_client, world)
    by_job = {position["job_id"]: position for position in detail["positions"]}
    # Własna stawka stanowiska (150,50 przy pierwszej osobie) nie wchodzi.
    assert by_job[world.job_a]["rate_hint"] == {
        "p25": 110.0,
        "median": 120.0,
        "p75": 130.0,
        "count": 3,
    }
    assert by_job[world.job_b]["rate_hint"] is None

    await _set_category(world.job_b, None)
    detail = await app_client.get(f"{BASE}/{detail['id']}", headers=world.dl_headers)
    assert detail.json()["positions"][1]["rate_hint"] is None


async def test_client_sees_an_estimate_only_without_real_rates(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    await _set_category(world.job_a, _CATEGORY)
    await _set_category(world.job_b, _CATEGORY)
    async with AsyncSessionLocal() as db:
        past = await _history(db, world, world.client_id, _CATEGORY)
        for value in ("100.00", "120.00", "140.00"):
            await _rated_pair(db, past, world, value)
        stranger = Client(name=f"Inny Klient {uuid.uuid4().hex[:6]}")
        db.add(stranger)
        await db.flush()
        foreign = await _history(db, world, stranger.id, _CATEGORY)
        for value in ("977.31", "977.32", "977.33"):
            await _rated_pair(db, foreign, world, value)
        # Drugie stanowisko nie ma jeszcze żadnej stawki godzinowej na liście.
        stages = await db.scalars(
            select(CandidateStage).where(CandidateStage.job_id == world.job_b)
        )
        for stage in stages.all():
            stage.client_rate_value = None
            stage.client_rate_unit = None
            stage.client_rate_currency = None
        await db.commit()

    detail = await _create(app_client, world)
    token = await _enable(app_client, world, detail["id"])
    body = (await _public(app_client, token)).json()
    by_job = {
        position["view"]["job"]["title"]: position for position in body["positions"]
    }
    android, backend = (
        next(p for title, p in by_job.items() if title.startswith(prefix))
        for prefix in ("Android", "Backend")
    )
    # Stanowisko ze stawką: klient widzi cenę, nie szacunek.
    assert android["estimate"] is None
    # Bez stawki: p25–p75 historii TEGO klienta (jego trzy pary + 150,50
    # z pierwszego stanowiska), nic o liczbie par, medianie ani innym kliencie.
    assert backend["estimate"] == {"min": 115.0, "max": 142.62}
    assert set(backend["estimate"]) == {"min", "max"}
    text = json.dumps(body, ensure_ascii=False)
    for leaked in ("977.3", '"count"', "median", "p25", "p75", "rate_hint"):
        assert leaked not in text, leaked

    hidden = await app_client.put(
        f"{BASE}/{detail['id']}/panel",
        headers=world.dl_headers,
        json={"show_rate": False},
    )
    assert hidden.status_code == 200, hidden.text
    body = (await _public(app_client, token)).json()
    assert [position["estimate"] for position in body["positions"]] == [None, None]


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
