"""Własny pulpit (0337): zapis układu kafelków, konflikt wersji, walidacja.

Kontrakty (decyzje Artura 21.09.2026):

- brak zapisu = układ roli (wersja 0, ``uses_role_layout``), nie błąd;
- zapisany pusty układ = świadomie pusty pulpit (``role_layout_off``);
- jeden pulpit na osobę, widzi go tylko właściciel (trasa czyta ``current_user``);
- zapis z nieaktualną wersją = 409 (dwie karty przeglądarki);
- kafelek poza siatką, zły link albo metryka niepasująca do typu = 422;
- kafelek nieznanego typu zapisany wcześniej nie wywraca odczytu.
"""

from __future__ import annotations

import os
import uuid

import pytest

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"
)

URL = "/api/users/me/dashboard"


async def _login(role: str = "recruiter") -> tuple[dict[str, str], int]:
    import app.models  # noqa: F401
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token
    from app.models.user import User, UserRole

    marker = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"dash-{marker}@example.com",
            name=f"Pulpit {marker}",
            role=UserRole(role),
            roles=[role],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        uid = user.id
    return {"Authorization": f"Bearer {create_access_token(uid, role)}"}, uid


def _tile(**over) -> dict:
    tile = {
        "id": str(uuid.uuid4()),
        "type": "my_tasks",
        "x": 0,
        "y": 0,
        "w": 6,
        "h": 3,
        "config": {"title": "Moje zadania"},
    }
    tile.update(over)
    return tile


def _metric_tile(**metric_over) -> dict:
    metric = {
        "source": "pipeline_moves",
        "measure": "first_reach",
        "stage": "cv_sent",
        "filters": {"author": "me"},
        "group_by": "none",
        "period": "last_30_days",
    }
    metric.update(metric_over)
    return _tile(type="metric_number", w=3, h=1, config={"metric": metric})


@needs_db
@pytest.mark.asyncio
async def test_empty_dashboard_before_first_save(app_client):
    headers, _ = await _login()
    resp = await app_client.get(URL, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "tiles": [],
        "version": 0,
        "dropped_tiles": [],
        "hidden_panels": [],
        # 04.10.2026: brak zapisu = front pokazuje układ roli.
        "uses_role_layout": True,
    }


@needs_db
@pytest.mark.asyncio
async def test_save_then_read_back_and_version_moves(app_client):
    headers, _ = await _login()
    tiles = [_tile(), _metric_tile()]
    resp = await app_client.put(
        URL, headers=headers, json={"tiles": tiles, "expected_version": 0}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 1

    got = (await app_client.get(URL, headers=headers)).json()
    assert got["version"] == 1
    assert [t["id"] for t in got["tiles"]] == [t["id"] for t in tiles]
    assert got["tiles"][1]["config"]["metric"]["stage"] == "cv_sent"


@needs_db
@pytest.mark.asyncio
async def test_stale_version_is_a_conflict_not_a_silent_overwrite(app_client):
    headers, _ = await _login()
    first = await app_client.put(
        URL, headers=headers, json={"tiles": [_tile()], "expected_version": 0}
    )
    assert first.status_code == 200
    stale = await app_client.put(
        URL, headers=headers, json={"tiles": [], "expected_version": 0}
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "DASHBOARD_VERSION_CONFLICT"
    assert len((await app_client.get(URL, headers=headers)).json()["tiles"]) == 1


@needs_db
@pytest.mark.asyncio
async def test_each_person_sees_only_their_own_dashboard(app_client):
    a, _ = await _login()
    b, _ = await _login()
    await app_client.put(
        URL, headers=a, json={"tiles": [_tile()], "expected_version": 0}
    )
    assert (await app_client.get(URL, headers=b)).json()["tiles"] == []


@pytest.mark.parametrize(
    "bad",
    [
        _tile(x=10, w=4),  # wychodzi poza 12 kolumn
        _tile(type="nie_ma_takiego"),
        _tile(
            type="note",
            config={"links": [{"label": "x", "url": "javascript:alert(1)"}]},
        ),
        _tile(config={"link_to": "https://evil.example.com"}),
        # Runda 8 (R8-N10-5): `/\host` przeglądarka czyta jak `//host`.
        _tile(config={"link_to": "/\\evil.example.com"}),
        _tile(
            type="note",
            config={"links": [{"label": "x", "url": "/\\evil.example.com"}]},
        ),
        _tile(
            type="note",
            config={"links": [{"label": "x", "url": "/\tevil"}]},
        ),
        _tile(config={"nieznane": 1}),
        _tile(type="metric_number", config={}),  # metryka bez definicji
        _metric_tile(group_by="week", measure="first_reach", stage="cv_sent")
        | {"type": "metric_funnel"},
    ],
)
def test_invalid_tiles_are_rejected(bad):
    from pydantic import ValidationError

    from app.services.dashboard_tiles import DashboardLayout

    with pytest.raises(ValidationError):
        DashboardLayout.model_validate({"tiles": [bad]})


def test_duplicate_tile_ids_are_rejected():
    from pydantic import ValidationError

    from app.services.dashboard_tiles import DashboardLayout

    tile = _tile()
    with pytest.raises(ValidationError):
        DashboardLayout.model_validate({"tiles": [tile, dict(tile)]})


def test_unknown_stored_tile_is_dropped_on_read_not_fatal():
    from app.services.dashboard_tiles import load_layout

    good = _tile()
    layout, dropped = load_layout(
        {"tiles": [good, {"id": str(uuid.uuid4()), "type": "usuniety_typ"}]}
    )
    assert [str(t.id) for t in layout.tiles] == [good["id"]]
    assert dropped and dropped[0]["type"] == "usuniety_typ"


@needs_db
@pytest.mark.asyncio
async def test_invalid_layout_returns_422_in_polish(app_client):
    headers, _ = await _login()
    resp = await app_client.put(
        URL, headers=headers, json={"tiles": [_tile(x=11, w=2)], "expected_version": 0}
    )
    assert resp.status_code == 422
    assert "12 kolumn" in resp.text


@needs_db
@pytest.mark.asyncio
async def test_parallel_first_save_from_two_tabs_is_200_and_409_not_500(app_client):
    """Audyt 22.09 r2 (DATA-05): dwa pierwsze zapisy naraz nie dają 500."""
    import asyncio

    headers, _ = await _login()
    first, second = await asyncio.gather(
        app_client.put(
            URL, headers=headers, json={"tiles": [_tile()], "expected_version": 0}
        ),
        app_client.put(
            URL, headers=headers, json={"tiles": [_tile()], "expected_version": 0}
        ),
    )
    assert sorted([first.status_code, second.status_code]) == [200, 409]
    read = await app_client.get(URL, headers=headers)
    assert read.json()["version"] == 1


@needs_db
@pytest.mark.asyncio
async def test_rejected_first_save_leaves_an_empty_dashboard(app_client):
    headers, _ = await _login()
    stale = await app_client.put(
        URL, headers=headers, json={"tiles": [_tile()], "expected_version": 3}
    )
    assert stale.status_code == 409
    read = await app_client.get(URL, headers=headers)
    assert read.status_code == 200
    assert read.json()["tiles"] == []
    assert read.json()["version"] == 0


PANEL_URL = f"{URL}/panels/cv_in_transit"


@needs_db
@pytest.mark.asyncio
async def test_panel_removed_from_the_dashboard_survives_a_tile_save(app_client):
    """„Usuń z pulpitu” listy nad kafelkami zapisuje się na koncie i nie ginie
    przy zapisie układu (zapis kafelków przepisuje cały `layout`)."""
    headers, _ = await _login()
    hide = await app_client.put(PANEL_URL, headers=headers, json={"hidden": True})
    assert hide.status_code == 200, hide.text
    # Sama decyzja o liście nie rusza wersji układu ani pustego pulpitu.
    assert hide.json() == {
        "tiles": [],
        "version": 0,
        "dropped_tiles": [],
        "hidden_panels": ["cv_in_transit"],
        "uses_role_layout": True,
    }

    saved = await app_client.put(
        URL, headers=headers, json={"tiles": [_tile()], "expected_version": 0}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["hidden_panels"] == ["cv_in_transit"]
    read = await app_client.get(URL, headers=headers)
    assert read.json()["hidden_panels"] == ["cv_in_transit"]
    assert len(read.json()["tiles"]) == 1

    restore = await app_client.put(PANEL_URL, headers=headers, json={"hidden": False})
    assert restore.status_code == 200
    assert restore.json()["hidden_panels"] == []
    assert restore.json()["version"] == 1
    assert len(restore.json()["tiles"]) == 1


@needs_db
@pytest.mark.asyncio
async def test_unknown_panel_is_rejected_and_each_person_hides_their_own(app_client):
    headers, _ = await _login()
    other, _ = await _login()
    bad = await app_client.put(
        f"{URL}/panels/my_tasks", headers=headers, json={"hidden": True}
    )
    assert bad.status_code == 422
    assert (
        await app_client.put(PANEL_URL, headers=headers, json={"hidden": True})
    ).status_code == 200
    assert (await app_client.get(URL, headers=other)).json()["hidden_panels"] == []


def test_first_save_inserts_the_row_before_locking_it():
    """Wyścig dwóch kart nie odtwarza się deterministycznie w jednym procesie
    (ASGI szereguje żądania), więc pilnujemy kolejności w źródle: pusty wiersz
    `ON CONFLICT DO NOTHING` PRZED `SELECT … FOR UPDATE`."""
    import inspect

    from app.api import user_dashboard

    src = inspect.getsource(user_dashboard.save_my_dashboard)
    assert "on_conflict_do_nothing" in src
    assert src.index("on_conflict_do_nothing") < src.index("with_for_update")


@needs_db
@pytest.mark.asyncio
async def test_saving_an_empty_layout_turns_the_role_layout_off(app_client):
    """Usunięcie ostatniego kafelka to decyzja „chcę pusty pulpit” — bez
    znacznika przy następnym wejściu wróciłby układ roli (04.10.2026)."""
    headers, _ = await _login()
    first = await app_client.put(
        URL, headers=headers, json={"tiles": [_tile()], "expected_version": 0}
    )
    assert first.json()["uses_role_layout"] is False
    emptied = await app_client.put(
        URL, headers=headers, json={"tiles": [], "expected_version": 1}
    )
    assert emptied.status_code == 200, emptied.text
    assert emptied.json()["uses_role_layout"] is False
    assert (await app_client.get(URL, headers=headers)).json()[
        "uses_role_layout"
    ] is False

    # Kafelek dodany później zdejmuje znacznik — pusty pulpit znowu znaczy
    # „pusty z wyboru” dopiero po kolejnym pustym zapisie.
    again = await app_client.put(
        URL, headers=headers, json={"tiles": [_tile()], "expected_version": 2}
    )
    assert again.json()["uses_role_layout"] is False


@needs_db
@pytest.mark.asyncio
async def test_hiding_a_panel_keeps_the_role_layout(app_client):
    headers, _ = await _login()
    resp = await app_client.put(PANEL_URL, headers=headers, json={"hidden": True})
    assert resp.status_code == 200, resp.text
    assert resp.json()["uses_role_layout"] is True
    assert (await app_client.get(URL, headers=headers)).json()[
        "uses_role_layout"
    ] is True


def test_board_scope_is_only_for_the_request_board():
    from pydantic import ValidationError

    from app.services.dashboard_tiles import DashboardTile

    ok = DashboardTile.model_validate(
        _tile(type="request_board", w=12, h=8, config={"board_scope": "my_category"})
    )
    assert ok.config.board_scope == "my_category"
    with pytest.raises(ValidationError):
        DashboardTile.model_validate(_tile(config={"board_scope": "my_lead"}))
    with pytest.raises(ValidationError):
        DashboardTile.model_validate(
            _tile(type="request_board", w=12, h=8, config={"board_scope": "team"})
        )
