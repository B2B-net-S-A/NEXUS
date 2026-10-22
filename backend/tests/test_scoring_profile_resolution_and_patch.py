"""Profile wag scoringu: wybór profilu, edycja z ekranu i zgodność ekranu z silnikiem (21.10.2026).

Trzy błędy znalezione przy przeglądzie „Ranking kandydatów” dla Head of Recruitment:

1. `resolve_active_profile` brał `.limit(1)` bez ORDER BY. Przy dwóch aktywnych
   profilach w tym samym zakresie (nic tego nie blokuje — UNIQUE jest tylko na
   nazwie) wygrywał dowolny wiersz, który Postgres oddał pierwszy, więc „Dop.”
   mógł się zmieniać między zapytaniami bez żadnej zmiany wag.
2. `PATCH /api/scoring-weights/{id}` nadpisywał `user_id` i `client_id` tym, co
   przyszło w żądaniu. Ekran wysyła tylko `{name, weights, active}`, więc
   edycja profilu przypiętego do klienta po cichu robiła z niego profil ogólny.
3. Ekran pokazywał wagi domyślne 35/30/12/8/5/10, a silnik od 17.08 liczy
   60/10/15/5/0/10 — ekran opisywał ranking, którego nie ma.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.api import scoring_weights as api
from app.services import scoring_service
from app.services.scoring_service import DEFAULT_PROFILE, resolve_active_profile


class _RecordingDb:
    def __init__(self, row=None):
        self.row = row
        self.statements = []
        self.added = []

    async def scalar(self, stmt):
        self.statements.append(stmt)
        return self.row

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        return None

    async def refresh(self, _row):
        return None


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


@pytest.mark.asyncio
async def test_active_profile_pick_is_deterministic_newest_first():
    db = _RecordingDb()

    profile = await resolve_active_profile(db, user_id=7, client_id=3)

    assert profile is DEFAULT_PROFILE
    assert len(db.statements) == 3  # user → klient → ogólny
    for stmt in db.statements:
        sql = _sql(stmt)
        assert "ORDER BY scoring_weight_profiles.id DESC" in sql, sql


def _row(**overrides):
    base = dict(
        id=5,
        name="Bankowość",
        user_id=None,
        client_id=42,
        weights={},
        active=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


_ADMIN = SimpleNamespace(id=1)

_WEIGHTS = {
    "semantic": 60,
    "skills": 20,
    "salary": 10,
    "location": 10,
    "availability": 0,
    "champion_fit": 0,
}


@pytest.mark.asyncio
async def test_patch_from_screen_keeps_client_binding(monkeypatch):
    async def _no_stale(_db, _profile_id):
        return None

    monkeypatch.setattr(api, "mark_stale_for_profile", _no_stale)
    row = _row()
    payload = api.ScoringWeightProfileCreate.model_validate(
        {"name": "Bankowość", "weights": _WEIGHTS, "active": True}
    )

    await api.update_profile(5, payload, current_user=_ADMIN, db=_RecordingDb(row))

    assert row.client_id == 42
    assert row.user_id is None
    assert row.weights["skills"] == 20


@pytest.mark.asyncio
async def test_patch_can_move_the_profile_from_client_to_person(monkeypatch):
    async def _no_stale(_db, _profile_id):
        return None

    monkeypatch.setattr(api, "mark_stale_for_profile", _no_stale)
    row = _row()
    payload = api.ScoringWeightProfileCreate.model_validate(
        {
            "name": "Bankowość",
            "client_id": None,
            "user_id": 7,
            "weights": _WEIGHTS,
            "active": True,
        }
    )

    await api.update_profile(5, payload, current_user=_ADMIN, db=_RecordingDb(row))

    assert row.client_id is None
    assert row.user_id == 7


# ── Wagi ogólne tylko przez panel (decyzja Artura 22.10.2026, audyt F60) ──
# Stary edytor wysyłał {name, weights, active}, więc każdy „Nowy profil”
# lądował jako profil OGÓLNY i od razu wypierał opublikowane wagi panelu
# (najnowszy aktywny profil ogólny wygrywa) — bez pomiaru na historii.


async def _refused(call) -> HTTPException:
    with pytest.raises(HTTPException) as caught:
        await call
    assert caught.value.status_code == 409
    assert "Ranking kandydatów" in caught.value.detail
    return caught.value


@pytest.mark.asyncio
async def test_create_without_client_or_person_is_refused():
    payload = api.ScoringWeightProfileCreate.model_validate(
        {"name": "Nowy profil", "weights": _WEIGHTS, "active": True}
    )
    db = _RecordingDb()

    await _refused(api.create_profile(payload, current_user=_ADMIN, db=db))

    assert db.added == []


@pytest.mark.asyncio
async def test_general_profile_is_read_only_in_the_old_editor():
    row = _row(client_id=None, name="Wagi ogólne (panel)")
    payload = api.ScoringWeightProfileCreate.model_validate(
        {"name": "Inna nazwa", "weights": _WEIGHTS, "active": True}
    )

    await _refused(
        api.update_profile(5, payload, current_user=_ADMIN, db=_RecordingDb(row))
    )

    assert row.name == "Wagi ogólne (panel)"


@pytest.mark.asyncio
async def test_patch_cannot_turn_a_client_profile_into_a_general_one():
    row = _row()
    payload = api.ScoringWeightProfileCreate.model_validate(
        {"name": "Bankowość", "client_id": None, "weights": _WEIGHTS, "active": True}
    )

    await _refused(
        api.update_profile(5, payload, current_user=_ADMIN, db=_RecordingDb(row))
    )

    assert row.client_id == 42


@pytest.mark.asyncio
async def test_general_profile_cannot_be_deleted_from_the_old_editor():
    row = _row(client_id=None)

    await _refused(api.delete_profile(5, current_user=_ADMIN, db=_RecordingDb(row)))


_PAGE = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "components"
    / "settings"
    / "ranking"
    / "ScoringProfilesAdmin.tsx"
)


@pytest.mark.skipif(not _PAGE.is_file(), reason="brak katalogu frontend w checkoutcie")
def test_settings_screen_shows_engine_default_weights():
    block = re.search(r"const DEFAULT_WEIGHTS[^{]*\{(.*?)\};", _PAGE.read_text(), re.S)
    assert block, "nie znaleziono DEFAULT_WEIGHTS w ScoringProfilesAdmin.tsx"
    screen = {k: float(v) for k, v in re.findall(r"(\w+):\s*(\d+)", block.group(1))}

    engine = {
        "semantic": scoring_service.SEMANTIC_MAX,
        "skills": scoring_service.SKILLS_MAX,
        "salary": scoring_service.SALARY_MAX,
        "location": scoring_service.LOCATION_MAX,
        "availability": scoring_service.AVAILABILITY_MAX,
        "champion_fit": scoring_service.CHAMPION_FIT_MAX,
    }
    assert screen == engine, (
        "Edytor profili (/settings/scoring) proponuje inne wagi domyślne niż silnik. "
        "Zmiana stałych w scoring_service.py = popraw DEFAULT_WEIGHTS w ScoringProfilesAdmin.tsx."
    )
