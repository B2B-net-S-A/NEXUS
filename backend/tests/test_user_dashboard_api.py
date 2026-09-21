"""Własny pulpit (0336): zapis układu kafelków, konflikt wersji, walidacja.

Kontrakty (decyzje Artura 21.09.2026):

- brak zapisu = pusty pulpit (wersja 0), nie błąd;
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
    assert resp.json() == {"tiles": [], "version": 0, "dropped_tiles": []}


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
