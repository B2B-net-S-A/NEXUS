"""Nowości do przeklikania (0625, decyzja Artura 28.10.2026).

Nowość pokazuje się kropką na przycisku i zalicza przeklikaniem albo użyciem
w pracy; zmianę procesu można odłożyć tylko raz; panel „kto już umie” widzą
admin i Head of Recruitment. Baza testowa jest wspólna — testy asertują tylko
po swoich kontach.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from pydantic import ValidationError

from app.api.novelties import (
    apply_event,
    next_morning,
    person_state,
    quiet_for_preview,
    shape_for_user,
    start_status,
)
from app.data.novelties import (
    Novelty,
    in_audience,
    load_novelties,
    load_start_tours,
)
from app.models.novelty import NoveltyProgress
from app.services.novelty_schema import TABLE_DDL

_DB = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL")
BACKEND = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 28, 21, 30, tzinfo=timezone.utc)


def _novelty(**overrides) -> Novelty:
    base = {
        "id": "test-nowosc",
        "title": "Nowość",
        "why": "Po co",
        "tier": "tour",
        "shipped_on": "2026-10-28",
        "where": "Ekran",
        "href": "/jobs",
        "dot_anchor": "jobs.sources.search",
        "steps": [
            {"anchor": "a.one", "text": "Krok 1", "hint": "Opis"},
            {"anchor": "a.two", "text": "Krok 2", "hint": "Opis"},
        ],
    }
    base.update(overrides)
    return Novelty.model_validate(base)


def _row(**values) -> NoveltyProgress:
    return NoveltyProgress(user_id=1, novelty_id="test-nowosc", seen_count=0, **values)


# ── Rejestr ───────────────────────────────────────────────────────────────────


def test_registry_loads_and_every_entry_is_valid() -> None:
    novelties = load_novelties()
    assert novelties, "rejestr nowości jest pusty"
    for novelty in novelties.values():
        if novelty.tier == "dot":
            assert not novelty.steps
        else:
            assert len(novelty.steps) >= 2


@pytest.mark.parametrize(
    "overrides",
    [
        {"tier": "dot"},  # drobiazg z krokami
        {"steps": [{"anchor": "a.one", "text": "Krok", "hint": "Opis"}]},  # jeden krok
        {"tier": "process"},  # zmiana procesu bez ekranu
        {
            "path_prefix": "/contracts"
        },  # ekran przy nowości, która nie jest zmianą procesu
        {"audience": {"roles": ["sourcer"]}},  # rola, której nie ma
        {"audience": {"permissions": ["kontrakty"]}},  # uprawnienie z literówką
    ],
)
def test_registry_refuses_malformed_entries(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        _novelty(**overrides)


def test_audience_by_role_or_permission() -> None:
    by_role = _novelty(audience={"roles": ["recruiter"]})
    assert in_audience(by_role, {"recruiter"}, set())
    assert not in_audience(by_role, {"finance"}, set())
    by_permission = _novelty(audience={"permissions": ["contract_status"]})
    assert in_audience(by_permission, {"finance"}, {"contract_status"})
    assert not in_audience(by_permission, {"recruiter"}, set())
    assert in_audience(_novelty(), {"employee"}, set())


def test_novelty_lives_45_days_and_stays_in_the_panel_for_90() -> None:
    novelty = _novelty()
    assert not novelty.active_on(date(2026, 10, 27))
    assert novelty.active_on(date(2026, 10, 28))
    assert not novelty.active_on(date(2026, 10, 28) + timedelta(days=45))
    assert novelty.in_panel_on(date(2026, 10, 28) + timedelta(days=89))


# ── Stan osoby ────────────────────────────────────────────────────────────────


def test_new_tour_shows_the_card_until_later_and_again_after_a_reminder() -> None:
    novelty = _novelty()
    assert shape_for_user(novelty, None, NOW)["show_card"] is True
    dismissed = _row(card_dismissed_at=NOW)
    assert shape_for_user(novelty, dismissed, NOW)["show_card"] is False
    reminded = _row(card_dismissed_at=NOW, reminded_at=NOW + timedelta(hours=1))
    assert shape_for_user(novelty, reminded, NOW)["show_card"] is True
    done = _row(completed_at=NOW, completed_via="tour")
    shaped = shape_for_user(novelty, done, NOW)
    assert shaped["done"] is True and shaped["show_card"] is False


def test_dot_never_shows_a_card() -> None:
    assert (
        shape_for_user(_novelty(tier="dot", steps=[]), None, NOW)["show_card"] is False
    )


def test_process_change_is_required_until_postponed_once() -> None:
    novelty = _novelty(tier="process", path_prefix="/contracts")
    fresh = shape_for_user(novelty, None, NOW)
    assert fresh["required_now"] is True and fresh["can_postpone"] is True
    postponed = _row(postponed_until=NOW + timedelta(hours=10))
    shaped = shape_for_user(novelty, postponed, NOW)
    assert shaped["required_now"] is False and shaped["can_postpone"] is False
    # Następnego ranka okno wraca i już się nie odłoży.
    later = shape_for_user(novelty, postponed, NOW + timedelta(hours=11))
    assert later["required_now"] is True and later["can_postpone"] is False


def test_events_count_views_and_keep_the_first_way_of_completing() -> None:
    novelty = _novelty()
    row = _row()
    apply_event(row, novelty, "seen", NOW)
    apply_event(row, novelty, "seen", NOW + timedelta(minutes=5))
    assert row.seen_count == 2 and row.first_seen_at == NOW
    apply_event(row, novelty, "toured", NOW)
    apply_event(row, novelty, "used", NOW + timedelta(days=1))
    assert row.completed_via == "tour" and row.completed_at == NOW


def test_postponing_twice_or_a_tour_is_refused() -> None:
    process = _novelty(tier="process", path_prefix="/contracts")
    row = _row()
    apply_event(row, process, "postponed", NOW)
    with pytest.raises(HTTPException) as again:
        apply_event(row, process, "postponed", NOW)
    assert again.value.status_code == 409
    assert again.value.detail["code"] == "postpone_used"
    with pytest.raises(HTTPException) as tour:
        apply_event(_row(), _novelty(), "postponed", NOW)
    assert tour.value.detail["code"] == "postpone_not_allowed"


def test_postponed_until_next_morning_in_company_time() -> None:
    # 28.10 22:30 w Warszawie → 29.10 8:00 w Warszawie.
    back = next_morning(NOW)
    local = back.astimezone(ZoneInfo("Europe/Warsaw"))
    assert (local.date(), local.hour, local.minute) == (date(2026, 10, 29), 8, 0)


def test_preview_as_another_person_forces_nothing() -> None:
    # Zapisy w podglądzie są zablokowane — okna zmiany procesu nie dałoby się zamknąć.
    process = _novelty(tier="process", path_prefix="/contracts")
    quiet = quiet_for_preview(shape_for_user(process, None, NOW))
    assert quiet["required_now"] is False and quiet["show_card"] is False
    assert quiet["can_postpone"] is False and quiet["done"] is False


def test_person_state_in_the_panel() -> None:
    assert person_state(None) == "untouched"
    assert person_state(_row(reminded_at=NOW)) == "untouched"
    assert person_state(_row(first_seen_at=NOW)) == "seen"
    assert (
        person_state(_row(first_seen_at=NOW, completed_at=NOW, completed_via="used"))
        == "used"
    )


# ── Schemat ───────────────────────────────────────────────────────────────────


def test_entrypoint_and_migration_use_the_one_ddl_source() -> None:
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert "from app.services import novelty_schema as _novelty_schema" in entrypoint
    assert "*_NOVELTY_TABLE_DDL," in entrypoint
    migration = (BACKEND / "alembic/versions/0625_novelty_progress.py").read_text(
        encoding="utf-8"
    )
    assert "from app.services.novelty_schema import TABLE_DDL" in migration


def test_model_columns_match_the_ddl() -> None:
    ddl = TABLE_DDL[0]
    ddl_columns = set(
        re.findall(r"^\s+([a-z_]+) (?:INTEGER|VARCHAR|TIMESTAMPTZ)", ddl, re.M)
    )
    assert ddl_columns == set(NoveltyProgress.__table__.columns.keys())


# ── Trasy (z bazą) ────────────────────────────────────────────────────────────


async def _user(
    role: str, roles: list[str] | None = None
) -> tuple[int, dict[str, str]]:
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token
    from app.models.user import User, UserRole

    tag = uuid.uuid4().hex[:8]
    values = roles or [role]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"nov-{role}-{tag}@example.com",
            name=f"Nowosci {role} {tag}",
            role=UserRole(role),
            roles=values,
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        token = create_access_token(
            user.id,
            role,
            roles=values,
            authorization_version=user.authorization_version,
        )
        return user.id, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def frozen_registry(monkeypatch):
    """Jedna nowość na dziś, żeby test nie zależał od dat w rejestrze."""
    from app.api import novelties as api

    novelty = _novelty(
        id="test-wybieram",
        shipped_on=datetime.now(ZoneInfo("Europe/Warsaw")).date().isoformat(),
        audience={"roles": ["recruiter"]},
    )
    monkeypatch.setattr(api, "load_novelties", lambda: {novelty.id: novelty})
    monkeypatch.setattr(api, "load_start_tours", lambda: {})
    return novelty


@_DB
@pytest.mark.asyncio
async def test_recruiter_sees_own_novelty_and_completes_it_by_tour(
    app_client: AsyncClient, frozen_registry
) -> None:
    _, recruiter = await _user("recruiter")
    mine = (await app_client.get("/api/novelties/mine", headers=recruiter)).json()
    assert [n["id"] for n in mine] == ["test-wybieram"]
    assert mine[0]["show_card"] is True and mine[0]["done"] is False

    for event in ("seen", "toured"):
        resp = await app_client.post(
            "/api/novelties/test-wybieram/events",
            json={"event": event},
            headers=recruiter,
        )
        assert resp.status_code == 204
    mine = (await app_client.get("/api/novelties/mine", headers=recruiter)).json()
    assert mine[0]["done"] is True and mine[0]["completed_via"] == "tour"


@_DB
@pytest.mark.asyncio
async def test_novelty_of_another_role_is_hidden_and_refused(
    app_client: AsyncClient, frozen_registry
) -> None:
    _, finance = await _user("finance")
    assert (await app_client.get("/api/novelties/mine", headers=finance)).json() == []
    resp = await app_client.post(
        "/api/novelties/test-wybieram/events", json={"event": "toured"}, headers=finance
    )
    assert resp.status_code == 404


@_DB
@pytest.mark.asyncio
async def test_hor_sees_who_knows_and_reminds_only_those_who_do_not(
    app_client: AsyncClient, frozen_registry
) -> None:
    done_id, done = await _user("recruiter")
    todo_id, _ = await _user("recruiter")
    _, hor = await _user("head_of_recruitment")
    await app_client.post(
        "/api/novelties/test-wybieram/events", json={"event": "used"}, headers=done
    )

    panel = (await app_client.get("/api/novelties/adoption", headers=hor)).json()
    people = {p["user_id"]: p["state"] for p in panel[0]["people"]}
    assert people[done_id] == "used" and people[todo_id] == "untouched"

    resp = await app_client.post(
        "/api/novelties/test-wybieram/remind",
        json={"user_ids": [done_id, todo_id]},
        headers=hor,
    )
    assert resp.status_code == 200 and resp.json() == {"reminded": 1}


@_DB
@pytest.mark.asyncio
async def test_recruiter_cannot_open_the_panel(
    app_client: AsyncClient, frozen_registry
) -> None:
    _, recruiter = await _user("recruiter")
    assert (
        await app_client.get("/api/novelties/adoption", headers=recruiter)
    ).status_code == 403
    resp = await app_client.post(
        "/api/novelties/test-wybieram/remind", json={}, headers=recruiter
    )
    assert resp.status_code == 403


@_DB
@pytest.mark.asyncio
async def test_two_tabs_sending_the_first_event_at_once_do_not_fail(
    app_client: AsyncClient, frozen_registry
) -> None:
    import asyncio

    _, recruiter = await _user("recruiter")
    responses = await asyncio.gather(
        *(
            app_client.post(
                "/api/novelties/test-wybieram/events",
                json={"event": "seen"},
                headers=recruiter,
            )
            for _ in range(4)
        )
    )
    assert [r.status_code for r in responses] == [204] * 4


@_DB
@pytest.mark.asyncio
async def test_admin_preview_shows_no_required_window(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
) -> None:
    from app.api import novelties as api

    process = _novelty(
        id="test-umowa",
        tier="process",
        path_prefix="/contracts",
        shipped_on=datetime.now(ZoneInfo("Europe/Warsaw")).date().isoformat(),
        audience={"roles": ["delivery_lead"]},
    )
    monkeypatch.setattr(api, "load_novelties", lambda: {process.id: process})
    monkeypatch.setattr(api, "load_start_tours", lambda: {})
    dl_id, dl = await _user("delivery_lead")
    own = (await app_client.get("/api/novelties/mine", headers=dl)).json()
    assert own[0]["required_now"] is True
    preview = (
        await app_client.get(
            "/api/novelties/mine",
            headers={**app_auth_headers, "X-Impersonate-User-Id": str(dl_id)},
        )
    ).json()
    assert preview[0]["required_now"] is False and preview[0]["show_card"] is False


# ── Start w NEXUSIE (30.10.2026) ──────────────────────────────────────────────


def test_start_registry_loads_tours_for_every_working_role() -> None:
    tours = load_start_tours()
    assert tours, "Start w NEXUSIE nie może być pusty"
    assert all(t.tier == "tour" and t.id.startswith("start-") for t in tours.values())
    assert not set(tours) & set(load_novelties())
    for role in (
        "recruiter",
        "delivery_lead",
        "head_of_recruitment",
        "finance",
        "employee",
    ):
        assert any(in_audience(t, {role}, set()) for t in tours.values()), role
    # Praktykant i Automatyzacje nie mają czego przeklikać — Start ich nie zatrzyma.
    for role in ("trainee", "automation"):
        assert not any(in_audience(t, {role}, set()) for t in tours.values()), role


def test_start_tour_never_shows_a_dot_card_or_window() -> None:
    tour = _novelty(id="start-test")
    shaped = shape_for_user(tour, None, NOW, start=True)
    assert shaped["start"] is True
    assert shaped["show_card"] is False
    assert shaped["required_now"] is False and shaped["can_postpone"] is False
    assert shape_for_user(_novelty(), None, NOW)["start"] is False


def test_start_blocks_until_every_tour_is_done() -> None:
    one, two = _novelty(id="start-jeden"), _novelty(id="start-dwa")
    done = NoveltyProgress(
        user_id=1, novelty_id="start-jeden", seen_count=0, completed_at=NOW
    )
    half = start_status(
        [one, two], {"start-jeden": done}, gate_on=True, impersonating=False
    )
    assert half["enforced"] is True and (half["done"], half["total"]) == (1, 2)
    assert [i["done"] for i in half["items"]] == [True, False]

    both = {
        **{"start-jeden": done},
        "start-dwa": NoveltyProgress(
            user_id=1, novelty_id="start-dwa", seen_count=3, completed_at=NOW
        ),
    }
    assert (
        start_status([one, two], both, gate_on=True, impersonating=False)["enforced"]
        is False
    )


def test_start_seen_without_completing_still_blocks() -> None:
    tour = _novelty(id="start-jeden")
    seen = NoveltyProgress(user_id=1, novelty_id="start-jeden", seen_count=5)
    assert (
        start_status([tour], {"start-jeden": seen}, gate_on=True, impersonating=False)[
            "enforced"
        ]
        is True
    )


def test_start_gate_off_preview_or_nothing_to_do_never_blocks() -> None:
    tour = _novelty(id="start-jeden")
    off = start_status([tour], {}, gate_on=False, impersonating=False)
    assert off["enforced"] is False and off["gate_on"] is False
    assert (
        start_status([tour], {}, gate_on=True, impersonating=True)["enforced"] is False
    )
    assert start_status([], {}, gate_on=True, impersonating=False)["enforced"] is False


@pytest.fixture
async def frozen_start(monkeypatch):
    from app.api import novelties as api
    from app.core.database import AsyncSessionLocal
    from app.models.app_setting import AppSetting

    tour = _novelty(id="start-test", audience={"roles": ["recruiter"]})
    monkeypatch.setattr(api, "load_novelties", lambda: {})
    monkeypatch.setattr(api, "load_start_tours", lambda: {tour.id: tour})
    # Brak wiersza = blokada włączona; inny test (np. seed E2E) mógł go zostawić.
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, api.START_GATE_KEY)
        if row is not None:
            await db.delete(row)
            await db.commit()
    return tour


@_DB
@pytest.mark.asyncio
async def test_recruiter_is_blocked_until_the_start_tour_is_done(
    app_client: AsyncClient, frozen_start
) -> None:
    _, recruiter = await _user("recruiter")
    start = (await app_client.get("/api/novelties/start", headers=recruiter)).json()
    assert start["enforced"] is True and start["total"] == 1
    mine = (await app_client.get("/api/novelties/mine", headers=recruiter)).json()
    assert [(n["id"], n["start"], n["show_card"]) for n in mine] == [
        ("start-test", True, False)
    ]

    resp = await app_client.post(
        "/api/novelties/start-test/events", json={"event": "toured"}, headers=recruiter
    )
    assert resp.status_code == 204
    start = (await app_client.get("/api/novelties/start", headers=recruiter)).json()
    assert start["enforced"] is False and start["done"] == 1


@_DB
@pytest.mark.asyncio
async def test_hor_switches_the_start_gate_off_and_recruiter_cannot(
    app_client: AsyncClient, frozen_start
) -> None:
    _, recruiter = await _user("recruiter")
    _, hor = await _user("head_of_recruitment")
    refused = await app_client.put(
        "/api/novelties/start/gate", json={"enforced": False}, headers=recruiter
    )
    assert refused.status_code == 403

    try:
        resp = await app_client.put(
            "/api/novelties/start/gate", json={"enforced": False}, headers=hor
        )
        assert resp.status_code == 200 and resp.json() == {"enforced": False}
        start = (await app_client.get("/api/novelties/start", headers=recruiter)).json()
        assert start["enforced"] is False and start["gate_on"] is False
    finally:
        await app_client.put(
            "/api/novelties/start/gate", json={"enforced": True}, headers=hor
        )
    start = (await app_client.get("/api/novelties/start", headers=recruiter)).json()
    assert start["enforced"] is True


@_DB
@pytest.mark.asyncio
async def test_start_progress_shows_in_the_adoption_panel(
    app_client: AsyncClient, frozen_start
) -> None:
    _, hor = await _user("head_of_recruitment")
    await _user("recruiter")
    panel = (await app_client.get("/api/novelties/adoption", headers=hor)).json()
    assert [(p["id"], p["start"], p["active"]) for p in panel] == [
        ("start-test", True, True)
    ]
