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
    DAILY_FLOOR,
    apply_event,
    apply_poligon_event,
    next_morning,
    poligon_status,
    person_state,
    quiet_for_preview,
    shape_for_user,
    start_status,
)
from app.data.novelties import (
    Novelty,
    PoligonPlan,
    in_audience,
    load_novelties,
    load_poligon,
    load_start_tours,
)
from app.models.novelty import NoveltyProgress
from app.services.novelty_schema import TABLE_DDL
from app.services.onboarding_day import POLIGON_ID_PREFIX

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
        if novelty.tier != "dot":
            assert len(novelty.steps) >= 2


def test_novelty_ids_do_not_use_the_poligon_prefix() -> None:
    """Trasa zdarzeń kieruje `poligon-…` do ćwiczeń Poligonu, więc wpis Nowości
    z takim id dostawał zawsze 404 i jego kropka nigdy nie gasła."""
    clash = sorted(n for n in load_novelties() if n.startswith(POLIGON_ID_PREFIX))
    assert not clash, clash


@pytest.mark.parametrize(
    "overrides",
    [
        {"steps": [{"anchor": "a.one", "text": "Krok", "hint": "Opis"}]},  # jeden krok
        {"tier": "process"},  # zmiana procesu bez ekranu
        {
            "path_prefix": "/contracts"
        },  # ekran przy nowości, która nie jest zmianą procesu
        {"audience": {"roles": ["sourcer"]}},  # rola, której nie ma
        {"audience": {"permissions": ["kontrakty"]}},  # uprawnienie z literówką
        {"practice_href": "jobs/990001"},  # ekran ćwiczebny bez ukośnika
        {"practice_href": "/jobs/990001?tab=<x>"},  # znaki spoza adresu
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
    shaped = shape_for_user(_novelty(tier="dot", steps=[]), None, NOW)
    assert shaped["show_card"] is False
    # Drobiazg zalicza się pierwszym kliknięciem — bez obowiązkowego okna.
    assert shaped["required_now"] is False and shaped["can_postpone"] is False


def test_new_tour_is_required_until_postponed_once() -> None:
    """Decyzja Artura z 30.10.2026: każdą nowość do przeklikania trzeba
    przejść — okno przy wejściu na jej ekran, odłożyć można raz do rana."""
    novelty = _novelty()
    fresh = shape_for_user(novelty, None, NOW)
    assert fresh["required_now"] is True and fresh["can_postpone"] is True
    postponed = _row(postponed_until=NOW + timedelta(hours=10))
    assert shape_for_user(novelty, postponed, NOW)["required_now"] is False
    later = shape_for_user(novelty, postponed, NOW + timedelta(hours=11))
    assert later["required_now"] is True and later["can_postpone"] is False
    done = shape_for_user(novelty, _row(completed_at=NOW, completed_via="used"), NOW)
    assert done["required_now"] is False
    # Wyłącznik blokady (awaria, stack E2E) zdejmuje obowiązek z nowości,
    # ale nie ze zmiany procesu.
    off = shape_for_user(novelty, None, NOW, tours_mandatory=False)
    assert off["required_now"] is False and off["can_postpone"] is False
    process = _novelty(tier="process", path_prefix="/contracts")
    assert shape_for_user(process, None, NOW, tours_mandatory=False)["required_now"]


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


def test_postponing_twice_or_a_dot_is_refused() -> None:
    for novelty in (_novelty(tier="process", path_prefix="/contracts"), _novelty()):
        row = _row()
        apply_event(row, novelty, "postponed", NOW)
        assert row.postponed_until is not None
        with pytest.raises(HTTPException) as again:
            apply_event(row, novelty, "postponed", NOW)
        assert again.value.status_code == 409
        assert again.value.detail["code"] == "postpone_used"
    with pytest.raises(HTTPException) as dot:
        apply_event(_row(), _novelty(tier="dot", steps=[]), "postponed", NOW)
    assert dot.value.detail["code"] == "postpone_not_allowed"


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


# ── Poranna porcja (18.11.2026) ───────────────────────────────────────────────


def test_dot_may_carry_steps_and_a_practice_screen() -> None:
    """Porcja przeklikuje każdy wpis, więc drobiazg może mieć kroki do elementu
    na rekrutacji ćwiczebnej."""
    dot = _novelty(
        tier="dot",
        steps=[{"anchor": "a.one", "text": "Krok", "hint": "Opis"}],
        practice_href="/jobs/990001?tab=chat",
    )
    assert dot.practice_href == "/jobs/990001?tab=chat"
    assert shape_for_user(dot, None, NOW)["practice_href"] == "/jobs/990001?tab=chat"


def _day(offset: int) -> str:
    return (DAILY_FLOOR + timedelta(days=offset)).isoformat()


@pytest.fixture
def frozen_daily(monkeypatch):
    """Jedna nowość rekrutera z wczoraj w jednej lekcji — porcja ma dokładnie ją
    (od 23.11.2026 porcja to lekcje: ``test_novelty_lessons.py``)."""
    from app.api import novelties as api
    from app.data.novelties import Lesson

    yesterday = datetime.now(ZoneInfo("Europe/Warsaw")).date() - timedelta(days=1)
    novelty = _novelty(
        id="test-porcja",
        shipped_on=yesterday.isoformat(),
        audience={"roles": ["recruiter"]},
    )
    lesson = Lesson.model_validate(
        {
            "id": "lekcja-test-porcja",
            "title": "Lekcja testowa",
            "novelties": [novelty.id],
            "task": "Zrób to samodzielnie na Poligonie.",
            "solo_href": "/jobs/990001",
            "check": {"kind": "click", "anchor": "jobs.list.scope"},
            "questions": [
                {
                    "q": "Pytanie pierwsze?",
                    "options": ["a", "b", "c"],
                    "answer": 0,
                    "explain": "Bo tak jest.",
                },
                {
                    "q": "Pytanie drugie?",
                    "options": ["a", "b", "c"],
                    "answer": 0,
                    "explain": "Bo tak jest.",
                },
            ],
        }
    )
    monkeypatch.setattr(api, "load_novelties", lambda: {novelty.id: novelty})
    monkeypatch.setattr(api, "load_lessons", lambda: {lesson.id: lesson})
    monkeypatch.setattr(api, "DAILY_FLOOR", yesterday - timedelta(days=7))
    return novelty


@_DB
@pytest.mark.asyncio
async def test_hor_switches_the_daily_gate_alone_and_recruiter_cannot(
    app_client: AsyncClient, frozen_daily
) -> None:
    """Wyłącznik porcji nie rusza Startu ani Poligonu; lista zostaje."""
    _, recruiter = await _user("recruiter")
    _, hor = await _user("head_of_recruitment")
    refused = await app_client.put(
        "/api/novelties/start/gate", json={"daily": False}, headers=recruiter
    )
    assert refused.status_code == 403
    try:
        resp = await app_client.put(
            "/api/novelties/start/gate", json={"daily": False}, headers=hor
        )
        assert resp.status_code == 200 and resp.json()["daily"] is False
        assert resp.json()["enforced"] is True and resp.json()["poligon"] is True
        daily = (await app_client.get("/api/novelties/daily", headers=recruiter)).json()
        assert daily["enforced"] is False and daily["gate_on"] is False
        assert [i["id"] for i in daily["items"]] == ["test-porcja"]
    finally:
        await app_client.put(
            "/api/novelties/start/gate", json={"daily": True}, headers=hor
        )


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
async def test_novelty_behind_a_switch_waits_for_it(
    app_client: AsyncClient, monkeypatch
) -> None:
    """Porcja dnia wyłączona = nie ma obowiązkowej nowości o liczniku."""
    from app.api import novelties as api
    from app.core.config import settings

    novelty = _novelty(
        id="test-przelacznik",
        shipped_on=datetime.now(ZoneInfo("Europe/Warsaw")).date().isoformat(),
        audience={"roles": ["recruiter"]},
        requires_setting="REVIEW_BATCH_ENABLED",
    )
    monkeypatch.setattr(api, "load_novelties", lambda: {novelty.id: novelty})
    monkeypatch.setattr(api, "load_start_tours", lambda: {})
    _, recruiter = await _user("recruiter")

    monkeypatch.setattr(settings, "REVIEW_BATCH_ENABLED", False, raising=False)
    assert (await app_client.get("/api/novelties/mine", headers=recruiter)).json() == []

    monkeypatch.setattr(settings, "REVIEW_BATCH_ENABLED", True, raising=False)
    mine = (await app_client.get("/api/novelties/mine", headers=recruiter)).json()
    assert [n["id"] for n in mine] == ["test-przelacznik"]


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
    # Konta testowe są świeże — bez tego poligon blokowałby je zamiast Startu.
    monkeypatch.setattr(api, "load_poligon", lambda: _poligon_plan(required_roles=[]))
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
        assert resp.status_code == 200 and resp.json() == {
            "enforced": False,
            "poligon": True,
            "daily": True,
        }
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
async def test_hor_switches_the_poligon_gate_alone_and_recruiter_cannot(
    app_client: AsyncClient, frozen_start
) -> None:
    """Wyłącznik Poligonu (Artur, 15.11.2026) nie rusza wyłącznika Startu."""
    _, recruiter = await _user("recruiter")
    _, hor = await _user("head_of_recruitment")
    refused = await app_client.put(
        "/api/novelties/start/gate", json={"poligon": False}, headers=recruiter
    )
    assert refused.status_code == 403
    empty = await app_client.put("/api/novelties/start/gate", json={}, headers=hor)
    assert empty.status_code == 422

    try:
        resp = await app_client.put(
            "/api/novelties/start/gate", json={"poligon": False}, headers=hor
        )
        assert resp.status_code == 200 and resp.json() == {
            "enforced": True,
            "poligon": False,
            "daily": True,
        }
        start = (await app_client.get("/api/novelties/start", headers=hor)).json()
        assert start["poligon_gate_on"] is False and start["gate_on"] is True
    finally:
        await app_client.put(
            "/api/novelties/start/gate", json={"poligon": True}, headers=hor
        )
    start = (await app_client.get("/api/novelties/start", headers=hor)).json()
    assert start["poligon_gate_on"] is True


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


# ── Tylko to, do czego osoba ma dostęp (Artur, 30.10.2026) ────────────────────


class _Person:
    """Osoba po uwierzytelnieniu: role i sekcje z bazy (``effective_section_access``)."""

    def __init__(self, roles: set[str], sections: dict[str, str]) -> None:
        from app.models.user import UserRole

        self._roles = [UserRole(r) for r in roles]
        self.role = self._roles[0]
        self.effective_section_access = sections

    def get_all_roles(self):
        return self._roles


def test_novelty_of_a_section_without_read_access_is_not_for_the_person(
    monkeypatch,
) -> None:
    from app.api import novelties as api

    monkeypatch.setattr(api, "named_permissions_of", lambda user: set())
    board = _novelty(section="pipeline", audience={"roles": ["recruiter"]})
    with_pipeline = _Person({"recruiter"}, {"pipeline": "read"})
    without_pipeline = _Person({"recruiter"}, {"pipeline": "none"})
    assert api._audience_of(with_pipeline, board) is True
    assert api._audience_of(without_pipeline, board) is False
    # Bez sekcji decydują tylko odbiorcy.
    assert api._audience_of(without_pipeline, _novelty()) is True


def test_finance_tour_opens_the_view_with_its_first_anchor() -> None:
    """Goły `/finance` ląduje na „Przeglądzie” (`/accounting`), gdzie kotwic
    zakładek Przychodów i faktur nie ma — przeklikanie startowało od karty
    „miejsca nie widać” (Tester 24.11.2026). Wycieczka Finansów otwiera
    widok `?view=`, w którym leży jej pierwszy krok."""
    for novelty in load_novelties().values():
        if novelty.tier not in ("tour", "process"):
            continue
        start = novelty.practice_href or novelty.href
        if start.split("?")[0] != "/finance":
            continue
        assert "?view=" in start, novelty.id


# Wpisy z listy `/jobs`, których pierwszego elementu nie ma na rekrutacji
# ćwiczebnej, bo zestaw Poligonu (`frontend/src/lib/poligon/dataset.json`) nie
# ma danych, przy których element się pokazuje. Sprawdzone na stagingu
# 24.11.2026 (Poligon, 1280 × 720, rekruter i Delivery Lead). Przeklikanie
# zostaje na liście i po 2 s ma „Nie mam tego — dalej”. Gdy zestaw dostanie
# te dane, wpis dostaje `practice_href`, a wyjątek znika.
JOBS_LIST_START_EXCEPTIONS: dict[str, str] = {
    "polacz-blizniaka-recznie": "rekrutacja bez prawa łączenia bliźniaków",
    "blizniacze-rekrutacje": "brak otwartych podobnych rekrutacji (okno pokazuje błąd)",
    "skad-ptaszek-przy-wymaganiu": "„Kandydaci do dodania” bez osób do podglądu",
    "nowi-aplikowali-na-gorze": "w „Nowych” nikt nie aplikował z ogłoszenia",
    "aplikacje-z-ogloszenia": "zero aplikacji z ogłoszenia",
    "nowi-kolejka-zadzwon-najpierw": "w „Nowych” nie ma osób od systemu",
    "nowi-w-bazie-najpierw": "w „Nowych” nie ma osób od systemu",
    "tablica-krytyczne-zamiennik": "brak zamienników umiejętności krytycznych",
    "tablica-czeka-na-odpowiedz-klienta": "nikt nie czeka na odpowiedź klienta",
    "p0-ultrapilne-24h": "priorytet rekrutacji tylko do odczytu",
    "opublikuj-ogloszenie-jeden-przycisk": "rekrutacja bez ogłoszenia",
    "justjoin-aplikacja-do-nowych": "rekrutacja bez ogłoszenia",
    "opublikuj-na-justjoin": "rekrutacja bez ogłoszenia",
    "wyslij-do-pracuj": "rekrutacja bez ogłoszenia",
    "rekruter-nie-dzwon-aktywne-zamowienie": "nikt nie ma aktywnego zamówienia",
    "podpis-przejmij-obsluge": "umowa bez podpisu elektronicznego",
    "podpis-umowy-z-pliku": "umowa bez „Oznacz jako podpisaną”",
    "dokumenty-do-startu": "klient bez listy dokumentów do startu",
    "zmien-plik-cv-oryginalne": "pliki CV bez nazw",
    "zmiana-nazwy-pliku-cv": "CV firmowe bez nazwy pliku",
    "prosba-o-zgode-pko": "klient ćwiczebny to nie PKO",
    "potwierdzenie-ze-slowami-kandydata": "QC bez błędów blokujących",
    "qc-pod-inna-nazwa": "QC bez podobnego sformułowania",
    "qc-sprawdz-recznie-wskaz-role": "brak umiejętności krytycznych do sprawdzenia",
    "karta-przed-cv-do-klienta": "karta do klienta wyłączona",
    "wiersz-bez-nikogo-z-wyslanych": "brak wierszy, których nie ma nikt z wysłanych",
}


def test_practice_starts_where_the_first_step_is_not_on_the_jobs_list() -> None:
    """Przeklikanie z archiwum ✦ zaczyna tam, gdzie jest element, a nie na liście.

    Powtórka z archiwum (`startNoveltyPractice`) i pokaz lekcji idą na
    `practice_href ?? href` wpisu, a pierwszy krok wpisu bez kroków to jego
    kropka (`withSteps`). 24.11.2026 56 wpisów z 27.10–23.11 zaczynało na
    liście `/jobs` i pisało „Nie widzę tego miejsca”, bo element stoi na
    rekrutacji ćwiczebnej: Tablica, panel osoby, Profil Championa. Na liście
    są tylko kotwice `jobs.list.*`; reszta potrzebuje `practice_href`
    (`/jobs/990001`, `?candidate=<id>`, `?candidate=<id>&panel=screening`,
    `?tab=champion&ptab=client`). Lekcje mają ostrzejszego strażnika bez
    wyjątków (`test_novelty_lessons.py`)."""
    novelties = load_novelties()

    def first_anchor(novelty: Novelty) -> str:
        return novelty.steps[0].anchor if novelty.steps else novelty.dot_anchor

    def starts_on_the_list(novelty: Novelty) -> bool:
        start = novelty.practice_href or novelty.href
        on_list = start.split("?")[0] == "/jobs"
        return on_list and not first_anchor(novelty).startswith("jobs.list.")

    wrong = [
        (novelty.id, first_anchor(novelty))
        for novelty in novelties.values()
        if starts_on_the_list(novelty) and novelty.id not in JOBS_LIST_START_EXCEPTIONS
    ]
    assert wrong == [], (
        f"Przeklikanie na liście /jobs, element gdzie indziej (dopisz practice_href): {wrong}"
    )
    stale = [
        nid
        for nid in JOBS_LIST_START_EXCEPTIONS
        if nid not in novelties or not starts_on_the_list(novelties[nid])
    ]
    assert stale == [], f"Wyjątek już niepotrzebny, usuń go: {stale}"


def test_every_start_tour_on_a_section_screen_names_its_section() -> None:
    """Pozycja Startu blokuje pracę — nie może trafić do osoby, która jej ekranu
    nie otworzy. Ekrany z sekcją w middleware muszą ją mieć w rejestrze."""
    # Kolejność jak w middleware: Generator umów pod /contracts to Sourcing,
    # a Analityka kontraktów — Finanse (jak moduł Finansów).
    screen_section = {
        "/jobs": "pipeline",
        "/candidates": "sourcing",
        "/contracts/b2b-generator": "sourcing",
        "/contracts/analytics": "finance",
        "/contracts": "delivery",
        "/finance": "finance",
        "/insights": "insights",
    }
    for tour in load_start_tours().values():
        expected = next(
            (
                sec
                for prefix, sec in screen_section.items()
                if tour.href.startswith(prefix)
            ),
            None,
        )
        assert (tour.section.value if tour.section else None) == expected, tour.id
    for novelty in load_novelties().values():
        expected = next(
            (
                sec
                for prefix, sec in screen_section.items()
                if novelty.href.startswith(prefix)
            ),
            None,
        )
        if expected is not None:
            assert novelty.section is not None and novelty.section.value == expected, (
                novelty.id
            )


# ── Poligon NEXUSA (decyzje Artura 14.11.2026) ─────────────────────────────


def _poligon_plan(**overrides) -> PoligonPlan:
    base = {
        "roles": ["recruiter", "delivery_lead"],
        "required_roles": ["recruiter"],
        "required_since": "2026-11-15",
        "replaces": {},
        "exercises": [
            {
                "id": "poligon-jeden",
                "module": "Tablica",
                "title": "Jeden",
                "roles": ["recruiter", "delivery_lead"],
            },
            {
                "id": "poligon-dwa",
                "module": "Tablica",
                "title": "Dwa",
                "roles": ["recruiter", "delivery_lead"],
            },
        ],
    }
    base.update(overrides)
    return PoligonPlan.model_validate(base)


class _Newcomer:
    def __init__(
        self,
        role: str,
        created_at: datetime | None,
        *extra: str,
        profile_completed_at: datetime | None = None,
    ) -> None:
        self.role = type("R", (), {"value": role})()
        self.extra = [type("R", (), {"value": r})() for r in extra]
        self.created_at = created_at
        # Onboarding roli zrobiony przy założeniu konta, chyba że test mówi inaczej.
        self.profile_completed_at = profile_completed_at or created_at

    def get_all_roles(self):
        return [self.role, *self.extra]


def test_poligon_registry_replaces_recruiting_start_and_ids_are_unique() -> None:
    plan = load_poligon()
    required = {"recruiter", "delivery_lead", "talent_community_manager"}
    assert required <= set(plan.required_roles) <= set(plan.roles)
    starts = load_start_tours()
    for role in required:
        # Poligon zastępuje każdej z tych ról przeklikania rekrutacji ze Startu.
        assert plan.replaces[role] and set(plan.replaces[role]) <= set(starts)
        assert all(role in starts[t].audience.roles for t in plan.replaces[role])
    assert all(e.id.startswith("poligon-") for e in plan.exercises)
    assert len(plan.exercises) >= 15


def test_poligon_path_per_role() -> None:
    """Rekruter, Delivery Lead i TCM mają własne ścieżki ze wspólnymi modułami."""
    plan = load_poligon()
    recruiter = {e.id for e in plan.exercises_for(["recruiter"])}
    dl = {e.id for e in plan.exercises_for(["delivery_lead"])}
    tcm = {e.id for e in plan.exercises_for(["talent_community_manager"])}
    # 19 ćwiczeń z 14.11 i 8 narzędzi rekrutera z 16.11.2026.
    assert len(recruiter) == 27
    assert {
        "poligon-dl-przeglad-otworz",
        "poligon-dl-wyslij",
        "poligon-dl-poprawki",
        "poligon-dl-terminy-klienta",
    } <= dl
    assert len(dl) == 17
    assert not {i for i in dl if i.startswith("poligon-screening-")}
    assert "poligon-tablica-biore" not in dl | tcm
    assert tcm < recruiter
    # TCM poza wspólnymi modułami ćwiczy listy i zapisane wyszukiwania (16.11.2026).
    assert tcm - dl == {"poligon-baza-lista", "poligon-baza-zapisane-wyszukiwanie"}
    assert {e.module for e in plan.exercises_for(["talent_community_manager"])} == {
        "Lista rekrutacji",
        "Tablica",
        "Panel osoby",
        "Baza kandydatów",
    }
    # Osoba z dwiema rolami przechodzi sumę, w kolejności rejestru.
    both = [e.id for e in plan.exercises_for(["delivery_lead", "recruiter"])]
    assert set(both) == recruiter | dl
    assert both == [e.id for e in plan.exercises if e.id in set(both)]
    assert plan.exercises_for(["finance"]) == []


def test_poligon_registry_refuses_inconsistent_roles() -> None:
    with pytest.raises(ValidationError):
        _poligon_plan(replaces={"finance": []})
    with pytest.raises(ValidationError):
        _poligon_plan(
            exercises=[
                {"id": "poligon-x", "module": "M", "title": "X", "roles": ["finance"]}
            ]
        )
    # Rola wymagana musi mieć choć jedno ćwiczenie — inaczej blokada byłaby pusta.
    with pytest.raises(ValidationError):
        _poligon_plan(
            required_roles=["recruiter", "delivery_lead"],
            exercises=[
                {"id": "poligon-x", "module": "M", "title": "X", "roles": ["recruiter"]}
            ],
        )


def test_poligon_may_be_required_only_for_new_people_in_required_roles() -> None:
    """Szybki filtr bez bazy (ścieżki KPI co minutę): rola z poligonem i konto
    albo onboarding roli od `required_since`."""
    from app.services.onboarding_day import poligon_may_be_required, poligon_open

    plan = _poligon_plan()
    new = datetime(2026, 11, 16, 8, tzinfo=timezone.utc)
    old = datetime(2026, 11, 14, 22, 59, tzinfo=timezone.utc)  # 14.11 23:59 w Warszawie
    assert poligon_may_be_required(_Newcomer("recruiter", new), plan) is True
    assert poligon_may_be_required(_Newcomer("recruiter", old), plan) is False
    assert poligon_may_be_required(_Newcomer("delivery_lead", new), plan) is False
    with_dl = _poligon_plan(required_roles=["recruiter", "delivery_lead"])
    assert poligon_may_be_required(_Newcomer("delivery_lead", new), with_dl) is True
    assert poligon_may_be_required(_Newcomer("delivery_lead", old), with_dl) is False
    # Stare konto po zmianie roli: onboarding roli zerowany albo zrobiony od 15.11.
    assert poligon_may_be_required(
        _Newcomer("delivery_lead", old, profile_completed_at=new), with_dl
    )
    # Konto bez daty (atrapa w testach KPI) — bez zapytania.
    assert poligon_may_be_required(_Newcomer("recruiter", None), plan) is False
    assert poligon_open(_Newcomer("delivery_lead", new), plan) is True
    assert poligon_open(_Newcomer("finance", new), plan) is False
    # Północ w Warszawie: 14.11 23:00 UTC to już 15.11.
    assert poligon_may_be_required(
        _Newcomer("recruiter", datetime(2026, 11, 14, 23, 0, tzinfo=timezone.utc)), plan
    )


# ── Wymagany od nadania roli (decyzja Artura 15.11.2026) ───────────────────

_OCT = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)
_NOV_10 = datetime(2026, 11, 10, 9, tzinfo=timezone.utc)
_NOV_16 = datetime(2026, 11, 16, 9, tzinfo=timezone.utc)
_NOV_20 = datetime(2026, 11, 20, 9, tzinfo=timezone.utc)
_NOV_25 = datetime(2026, 11, 25, 9, tzinfo=timezone.utc)


def _roles_row(at: datetime, before: list[str], after: list[str]):
    """Wiersz `activities` z „Osoby i role” (`roles_changed`)."""
    return ("roles_changed", {"from": before, "to": after}, at)


def _need(roles: set[str], created_at: datetime, rows: list):
    from app.services.onboarding_day import requirement_for, role_changes

    return requirement_for(
        roles=roles,
        created_at=created_at,
        changes=role_changes(rows),
        plan=load_poligon(),
    )


def _path(*roles: str) -> list[str]:
    return [e.id for e in load_poligon().exercises_for(roles)]


def test_poligon_starts_with_the_role_grant_not_the_account() -> None:
    # Konto SSO sprzed 15.11 jako „Pracownik”, rekruter nadany 16.11 → cały poligon.
    granted = _need(
        {"recruiter"}, _OCT, [_roles_row(_NOV_16, ["employee"], ["recruiter"])]
    )
    assert list(granted.exercise_ids) == _path("recruiter")
    assert granted.granted_at == (_NOV_16,)
    # Rekruter nadany przed 15.11 → poligon nie wymagany (miał Start).
    early = _need(
        {"recruiter"}, _OCT, [_roles_row(_NOV_10, ["employee"], ["recruiter"])]
    )
    assert early.required is False
    # „Pracownik” (pierwsze logowanie SSO) — poligonu nie ma.
    assert _need({"employee"}, _NOV_16, []).required is False
    # Konto założone od razu z rolą od 15.11 → wymagany od założenia.
    fresh = _need({"talent_community_manager"}, _NOV_16, [])
    assert list(fresh.exercise_ids) == _path("talent_community_manager")
    assert fresh.granted_at == (_NOV_16,)


def test_role_change_requires_only_the_new_roles_missing_exercises() -> None:
    # Rekruter od 16.11 (poligon zaliczony) → 20.11 Delivery Lead zamiast rekrutera.
    rows = [_roles_row(_NOV_20, ["recruiter"], ["delivery_lead"])]
    dl = _need({"delivery_lead"}, _NOV_16, rows)
    assert list(dl.exercise_ids) == _path("delivery_lead")
    assert dl.granted_at == (_NOV_16, _NOV_20)
    recruiter_done = {
        eid: NoveltyProgress(user_id=1, novelty_id=eid, seen_count=0, completed_at=NOW)
        for eid in _path("recruiter")
    }
    status = poligon_status(
        recruiter_done,
        _path("delivery_lead"),
        open_=True,
        required=True,
        required_ids=list(dl.exercise_ids),
    )
    # Wspólne moduły liczą się raz: zostają tylko ćwiczenia przeglądu DL-a.
    left = [e for e in dl.exercise_ids if e not in status["done_ids"]]
    assert left == [
        "poligon-dl-przeglad-otworz",
        "poligon-dl-wyslij",
        "poligon-dl-poprawki",
        "poligon-dl-terminy-klienta",
    ]
    assert status["total"] - status["done"] == 4

    # Powrót do rekrutera 25.11 → ćwiczenia już zaliczone, nic nie blokuje.
    back = _need(
        {"recruiter"},
        _NOV_16,
        rows + [_roles_row(_NOV_25, ["delivery_lead"], ["recruiter"])],
    )
    back_status = poligon_status(
        recruiter_done,
        _path("recruiter"),
        open_=True,
        required=back.required,
        required_ids=list(back.exercise_ids),
    )
    assert back_status["done"] == back_status["total"]
    assert not start_status(
        [], {}, gate_on=True, impersonating=False, poligon=back_status
    )["enforced"]


def test_role_change_of_a_person_from_before_the_poligon() -> None:
    # Rekruter sprzed 15.11 (bez poligonu) → 20.11 DL: tylko ćwiczenia, których
    # ścieżka rekrutera nie miała — przegląd DL-a i terminy od klienta.
    need = _need(
        {"delivery_lead"},
        _OCT,
        [_roles_row(_NOV_20, ["recruiter"], ["delivery_lead"])],
    )
    assert list(need.exercise_ids) == [
        "poligon-dl-przeglad-otworz",
        "poligon-dl-wyslij",
        "poligon-dl-poprawki",
        "poligon-dl-terminy-klienta",
    ]
    # Zdjęcie roli (admin) przy tej samej roli z poligonem — nic.
    assert (
        _need(
            {"recruiter"},
            _OCT,
            [_roles_row(_NOV_20, ["recruiter", "admin"], ["recruiter"])],
        ).required
        is False
    )


def test_role_changes_read_every_role_history_row() -> None:
    from app.services.onboarding_day import role_changes

    changes = role_changes(
        [
            # „Osoby i role”: oba wiersze w jednej transakcji.
            ("role_changed", {"from": "recruiter", "to": "delivery_lead"}, _NOV_16),
            _roles_row(_NOV_16, ["recruiter"], ["delivery_lead"]),
            # Sama zmiana roli głównej w obrębie listy — zbiór ról bez zmian.
            ("role_changed", {"from": "delivery_lead", "to": "recruiter"}, _NOV_20),
            # Resync z grup Entra: tylko wiersz roli głównej z `all_roles`.
            (
                "admin_aad_role_resynced",
                {
                    "from": "employee",
                    "to": "talent_community_manager",
                    "all_roles": ["talent_community_manager"],
                },
                _NOV_25,
            ),
            # Dawna rola TAC to rekruter; JSON jako tekst też się czyta.
            (
                "sso_aad_roles_updated",
                '{"from": ["tac"], "to": ["recruiter"]}',
                _NOV_10,
            ),
        ]
    )
    assert [(c.at, set(c.removed), set(c.added)) for c in changes] == [
        (_NOV_16, {"recruiter"}, {"delivery_lead"}),
        (_NOV_25, {"employee"}, {"talent_community_manager"}),
    ]


def test_poligon_blocks_a_new_person_until_every_exercise_is_done(monkeypatch) -> None:
    from app.api import novelties as api

    monkeypatch.setattr(api, "load_poligon", lambda: _poligon_plan())
    one = NoveltyProgress(
        user_id=1, novelty_id="poligon-jeden", seen_count=0, completed_at=NOW
    )
    ids = ["poligon-jeden", "poligon-dwa"]
    half = poligon_status({"poligon-jeden": one}, ids, open_=True, required=True)
    assert (half["done"], half["total"], half["done_ids"]) == (1, 2, ["poligon-jeden"])
    status = start_status([], {}, gate_on=True, impersonating=False, poligon=half)
    assert status["enforced"] is True and status["redirect"] == "/poligon"

    two = NoveltyProgress(
        user_id=1, novelty_id="poligon-dwa", seen_count=0, completed_at=NOW
    )
    full = poligon_status(
        {"poligon-jeden": one, "poligon-dwa": two}, ids, open_=True, required=True
    )
    done = start_status([], {}, gate_on=True, impersonating=False, poligon=full)
    assert done["enforced"] is False and done["redirect"] == "/start"
    # Wyłącznik Startu nie zdejmuje blokady poligonu (Artur, 15.11.2026):
    # od 30.10 Start jest wyłączony, a nowa osoba ma stać na poligonie.
    off = start_status(
        [_novelty(id="start-jeden")],
        {},
        gate_on=False,
        impersonating=False,
        poligon=half,
    )
    assert off["enforced"] is True and off["redirect"] == "/poligon"
    # Po zaliczeniu poligonu wyłączony Start nikogo nie zatrzymuje.
    assert not start_status(
        [_novelty(id="start-jeden")],
        {},
        gate_on=False,
        impersonating=False,
        poligon=full,
    )["enforced"]
    # Wyłącznik Poligonu (panel „Nowości”, stack E2E) zdejmuje tę blokadę.
    poligon_off = start_status(
        [], {}, gate_on=False, impersonating=False, poligon=half, poligon_gate_on=False
    )
    assert poligon_off["poligon_gate_on"] is False
    assert not start_status(
        [], {}, gate_on=False, impersonating=False, poligon=half, poligon_gate_on=False
    )["enforced"]
    # Podgląd jako inna osoba niczego nie blokuje.
    assert not start_status([], {}, gate_on=True, impersonating=True, poligon=half)[
        "enforced"
    ]
    assert not start_status([], {}, gate_on=False, impersonating=True, poligon=half)[
        "enforced"
    ]
    # Obecna osoba (poligon nie wymagany) nie jest blokowana niezaliczonym poligonem.
    optional = poligon_status({}, ids, open_=True, required=False)
    assert not start_status(
        [], {}, gate_on=True, impersonating=False, poligon=optional
    )["enforced"]


def test_poligon_exercise_completes_once_and_cannot_be_postponed() -> None:
    row = NoveltyProgress(user_id=1, novelty_id="poligon-jeden", seen_count=0)
    apply_poligon_event(row, "used", NOW)
    assert row.completed_at == NOW and row.completed_via == "used"
    apply_poligon_event(row, "used", NOW + timedelta(hours=1))
    assert row.completed_at == NOW
    with pytest.raises(HTTPException) as refused:
        apply_poligon_event(row, "postponed", NOW)
    assert refused.value.status_code == 409


def test_broken_poligon_exercise_still_counts() -> None:
    """„Coś nie działa — zalicz i dalej” (Artur, 25.11.2026): zepsute ćwiczenie
    zalicza się mimo to, żeby blokada Poligonu nikogo nie trzymała."""
    row = NoveltyProgress(user_id=1, novelty_id="poligon-jeden", seen_count=0)
    apply_poligon_event(row, "broken", NOW)
    assert row.completed_at == NOW and row.completed_via == "used"


@_DB
@pytest.mark.asyncio
async def test_new_recruiter_records_poligon_progress_and_is_sent_to_poligon(
    app_client: AsyncClient, monkeypatch
) -> None:
    from app.api import novelties as api

    plan = _poligon_plan(required_since="2000-01-01")
    monkeypatch.setattr(api, "load_poligon", lambda: plan)
    monkeypatch.setattr(api, "load_start_tours", lambda: {})
    _, recruiter = await _user("recruiter")
    _, finance = await _user("finance")

    start = (await app_client.get("/api/novelties/start", headers=recruiter)).json()
    assert start["poligon"]["required"] is True
    assert start["redirect"] == "/poligon"

    for exercise in ("poligon-jeden", "poligon-dwa"):
        resp = await app_client.post(
            f"/api/novelties/{exercise}/events",
            json={"event": "used"},
            headers=recruiter,
        )
        assert resp.status_code == 204
    start = (await app_client.get("/api/novelties/start", headers=recruiter)).json()
    assert start["poligon"]["done"] == 2 and start["redirect"] == "/start"

    unknown = await app_client.post(
        "/api/novelties/poligon-nie-ma/events",
        json={"event": "used"},
        headers=recruiter,
    )
    assert unknown.status_code == 404
    outsider = await app_client.post(
        "/api/novelties/poligon-jeden/events", json={"event": "used"}, headers=finance
    )
    assert outsider.status_code == 404


def test_poligon_status_counts_only_the_exercises_of_the_persons_roles() -> None:
    from app.services.onboarding_day import poligon_exercises, poligon_replaces

    plan = load_poligon()
    new = datetime(2026, 11, 16, 8, tzinfo=timezone.utc)
    dl = _Newcomer("delivery_lead", new)
    dl_ids = poligon_exercises(dl, plan)
    # Zaliczony cały screening rekrutera nie przybliża DL-a do końca ścieżki.
    progress = {
        e.id: NoveltyProgress(
            user_id=1, novelty_id=e.id, seen_count=0, completed_at=NOW
        )
        for e in plan.exercises
        if e.id.startswith("poligon-screening-")
    }
    status = poligon_status(progress, dl_ids, open_=True, required=True)
    assert status["done"] == 0 and status["total"] == len(dl_ids)
    assert status["exercise_ids"] == dl_ids
    for eid in dl_ids:
        progress[eid] = NoveltyProgress(
            user_id=1, novelty_id=eid, seen_count=0, completed_at=NOW
        )
    done = poligon_status(progress, dl_ids, open_=True, required=True)
    assert done["done"] == done["total"]
    assert not start_status([], {}, gate_on=True, impersonating=False, poligon=done)[
        "enforced"
    ]
    # Przeklikania Startu zastąpione per rola; obecna osoba nie ma wymaganego poligonu.
    assert poligon_replaces(dl, plan) == set(plan.replaces["delivery_lead"])
    assert poligon_replaces(_Newcomer("admin", new), plan) == set()


@_DB
@pytest.mark.asyncio
async def test_new_dl_and_tcm_are_sent_to_poligon_and_record_only_their_path(
    app_client: AsyncClient, monkeypatch
) -> None:
    from app.api import novelties as api

    plan = _poligon_plan(
        roles=["recruiter", "delivery_lead", "talent_community_manager", "admin"],
        required_roles=["recruiter", "delivery_lead", "talent_community_manager"],
        required_since="2000-01-01",
        exercises=[
            {
                "id": "poligon-wspolne",
                "module": "Lista",
                "title": "Wspólne",
                "roles": ["recruiter", "delivery_lead", "talent_community_manager"],
            },
            {
                "id": "poligon-rekruter",
                "module": "Screening",
                "title": "Rekruter",
                "roles": ["recruiter"],
            },
            {
                "id": "poligon-dl",
                "module": "Przegląd",
                "title": "DL",
                "roles": ["delivery_lead"],
            },
        ],
    )
    monkeypatch.setattr(api, "load_poligon", lambda: plan)
    monkeypatch.setattr(api, "load_start_tours", lambda: {})
    _, dl = await _user("delivery_lead")
    _, tcm = await _user("talent_community_manager")
    _, admin = await _user("admin")

    start = (await app_client.get("/api/novelties/start", headers=dl)).json()
    assert start["poligon"]["required"] is True and start["redirect"] == "/poligon"
    assert start["poligon"]["exercise_ids"] == ["poligon-wspolne", "poligon-dl"]
    tcm_start = (await app_client.get("/api/novelties/start", headers=tcm)).json()
    assert tcm_start["poligon"]["exercise_ids"] == ["poligon-wspolne"]
    assert tcm_start["poligon"]["total"] == 1

    # Ćwiczenie spoza ścieżki roli nie istnieje dla tej osoby.
    foreign = await app_client.post(
        "/api/novelties/poligon-rekruter/events", json={"event": "used"}, headers=dl
    )
    assert foreign.status_code == 404
    dl_only = await app_client.post(
        "/api/novelties/poligon-dl/events", json={"event": "used"}, headers=tcm
    )
    assert dl_only.status_code == 404

    for exercise in ("poligon-wspolne", "poligon-dl"):
        resp = await app_client.post(
            f"/api/novelties/{exercise}/events", json={"event": "used"}, headers=dl
        )
        assert resp.status_code == 204
    start = (await app_client.get("/api/novelties/start", headers=dl)).json()
    assert start["poligon"]["done"] == 2 and start["enforced"] is False

    # Admin (poza required_roles) ma poligon otwarty, ale go nie blokuje.
    admin_start = (await app_client.get("/api/novelties/start", headers=admin)).json()
    assert admin_start["poligon"]["required"] is False
    assert admin_start["poligon"]["open"] is True


# ── Poligon dla obecnych: tylko luki (Artur, 16.11.2026) ─────────────────────


def test_work_credits_only_exercises_of_used_features_on_the_persons_path() -> None:
    from app.services.poligon_luki import credited_exercises

    path = [
        "poligon-lista-zakres",
        "poligon-lista-filtry",
        "poligon-lista-otworz",
        "poligon-tablica-biore",
        "poligon-screening-otworz",
        "poligon-screening-zapisz",
        "poligon-panel-wzmianka",
    ]
    credited = credited_exercises({"biore", "screening", "qc_cv"}, path)
    # QC CV nie jest na tej ścieżce, wzmianki osoba nie używa.
    assert credited == path[:6]
    # Kto nic nie robi w NEXUSIE, nie dostaje nawet listy rekrutacji.
    assert credited_exercises(set(), path) == []


def test_luki_campaign_blocks_only_after_the_due_day() -> None:
    from app.services.poligon_luki import default_due, overdue

    assert overdue("2026-11-23", date(2026, 11, 23)) is False
    assert overdue("2026-11-23", date(2026, 11, 24)) is True
    assert default_due(date(2026, 11, 16)) == date(2026, 11, 23)


def test_luki_targets_recruiters_without_leader_roles() -> None:
    from types import SimpleNamespace

    from app.services.poligon_luki import is_target

    def person(*roles: str, active: bool = True) -> SimpleNamespace:
        return SimpleNamespace(
            is_active=active, role=roles[0], get_all_roles=lambda: list(roles)
        )

    assert is_target(person("recruiter"))
    assert is_target(person("talent_community_manager", "recruiter"))
    assert not is_target(person("head_of_recruitment", "recruiter"))
    assert not is_target(person("recruiter", active=False))
    assert not is_target(person("delivery_lead"))


def test_tool_exercises_of_16_11_are_credited_by_work() -> None:
    """Kto używa narzędzia z luk, ma jego ćwiczenie zaliczone z pracy (16.11.2026)."""
    from app.services.poligon_luki import credited_exercises

    path = [e.id for e in load_poligon().exercises_for(["recruiter"])]
    for feature, exercise in {
        "screening_kalendarz": "poligon-kalendarz-telefon",
        "terminy_klient": "poligon-kalendarz-termin-klienta",
        "cv_z_pliku": "poligon-zrodla-cv-z-pliku",
        "zapisane_wyszukiwanie": "poligon-baza-zapisane-wyszukiwanie",
        "pula": "poligon-baza-lista",
        "czat": "poligon-zespol-czat",
        "polecenie_ai_cv": "poligon-zespol-cv-ai",
        "jarvis": "poligon-zespol-jarvis",
    }.items():
        assert exercise in path, exercise
        assert exercise in credited_exercises({feature}, path), feature
        assert exercise not in credited_exercises({"biore"}, path), feature


def test_client_slots_feature_credits_the_side_on_the_persons_path() -> None:
    """Terminy u klienta: DL wpisuje, rekruter wybiera — praca zalicza ćwiczenie jego ścieżki."""
    from app.services.poligon_luki import FEATURES, credited_exercises

    plan = load_poligon()
    recruiter = [e.id for e in plan.exercises_for(["recruiter"])]
    dl = [e.id for e in plan.exercises_for(["delivery_lead"])]
    rec_credit = credited_exercises({"terminy_klient"}, recruiter)
    dl_credit = credited_exercises({"terminy_klient"}, dl)
    assert "poligon-kalendarz-termin-klienta" in rec_credit
    assert "poligon-dl-terminy-klienta" not in rec_credit
    assert "poligon-dl-terminy-klienta" in dl_credit
    assert "poligon-kalendarz-termin-klienta" not in dl_credit
    # Sygnał liczy obie strony wniosku: rekrutera pary i osobę, która wpisała terminy.
    sql = next(f.sql for f in FEATURES if f.key == "terminy_klient")
    assert "recruiter_id" in sql and "created_by" in sql


def test_every_luki_feature_has_a_signal_and_known_exercises() -> None:
    from app.services.poligon_luki import FEATURES, usage_sql

    ids = {e.id for e in load_poligon().exercises}
    assert len({f.key for f in FEATURES}) == len(FEATURES)
    for feature in FEATURES:
        assert set(feature.exercises) <= ids, feature.key
        assert ":ids" in feature.sql, feature.key
    assert usage_sql().count("UNION ALL") == len(FEATURES) - 1


@pytest.fixture
async def luki_campaign(monkeypatch):
    """Obecne konto (poligon niewymagany), bez Startu; sprząta kampanię."""
    from app.api import novelties as api
    from app.core.database import AsyncSessionLocal
    from app.models.app_setting import AppSetting
    from app.services.onboarding_day import PoligonRequirement
    from app.services.poligon_luki import LUKI_KEY

    async def not_required(db, user, plan=None):
        return PoligonRequirement((), ())

    monkeypatch.setattr(api, "poligon_requirement", not_required)
    monkeypatch.setattr(api, "load_start_tours", lambda: {})
    yield
    async with AsyncSessionLocal() as db:
        for key in (LUKI_KEY, api.POLIGON_GATE_KEY):
            row = await db.get(AppSetting, key)
            if row is not None:
                await db.delete(row)
        await db.commit()


async def _used(user_id: int, action: str) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity

    async with AsyncSessionLocal() as db:
        db.add(
            Activity(
                entity_type="pipeline", entity_id=1, action=action, user_id=user_id
            )
        )
        await db.commit()


@_DB
@pytest.mark.asyncio
async def test_hor_sends_poligon_gaps_and_work_counts_as_done(
    app_client: AsyncClient, luki_campaign
) -> None:
    recruiter_id, recruiter = await _user("recruiter")
    _, hor = await _user("head_of_recruitment")
    await _used(recruiter_id, "candidate_claimed")

    refused = await app_client.post(
        "/api/novelties/poligon/luki", json={}, headers=recruiter
    )
    assert refused.status_code == 403
    past = await app_client.post(
        "/api/novelties/poligon/luki", json={"due": "2020-01-01"}, headers=hor
    )
    assert past.status_code == 422

    sent = await app_client.post("/api/novelties/poligon/luki", json={}, headers=hor)
    assert sent.status_code == 200 and sent.json()["people"] >= 1

    start = (await app_client.get("/api/novelties/start", headers=recruiter)).json()
    poligon = start["poligon"]
    assert poligon["luki"]["due"] == sent.json()["due"]
    assert "poligon-tablica-biore" in poligon["luki"]["credited_ids"]
    assert "poligon-tablica-biore" in poligon["done_ids"]
    assert "poligon-screening-zapisz" not in poligon["done_ids"]
    # Do terminu poligon tylko prosi.
    assert poligon["required"] is False and start["enforced"] is False

    matrix = (await app_client.get("/api/novelties/poligon/luki", headers=hor)).json()
    me = next(p for p in matrix["people"] if p["id"] == recruiter_id)
    assert "biore" in me["used"] and me["poligon"]["done"] >= 4
    assert len(matrix["features"]) == 24 and matrix["campaign"]["due"]
    assert (
        await app_client.get("/api/novelties/poligon/luki", headers=recruiter)
    ).status_code == 403


@_DB
@pytest.mark.asyncio
async def test_poligon_gaps_block_after_the_due_day_unless_switched_off(
    app_client: AsyncClient, luki_campaign
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.app_setting import AppSetting
    from app.services.poligon_luki import LUKI_KEY

    recruiter_id, recruiter = await _user("recruiter")
    _, hor = await _user("head_of_recruitment")
    async with AsyncSessionLocal() as db:
        db.add(
            AppSetting(
                key=LUKI_KEY,
                value={
                    "due": "2026-01-02",
                    "users": {str(recruiter_id): {"credited": []}},
                },
            )
        )
        await db.commit()

    start = (await app_client.get("/api/novelties/start", headers=recruiter)).json()
    assert start["poligon"]["required"] is True
    assert start["enforced"] is True and start["redirect"] == "/poligon"

    await app_client.put(
        "/api/novelties/start/gate", json={"poligon": False}, headers=hor
    )
    start = (await app_client.get("/api/novelties/start", headers=recruiter)).json()
    assert start["enforced"] is False
