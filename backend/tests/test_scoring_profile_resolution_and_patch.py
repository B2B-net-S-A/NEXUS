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
async def test_patch_can_still_unbind_client_explicitly(monkeypatch):
    async def _no_stale(_db, _profile_id):
        return None

    monkeypatch.setattr(api, "mark_stale_for_profile", _no_stale)
    row = _row()
    payload = api.ScoringWeightProfileCreate.model_validate(
        {"name": "Bankowość", "client_id": None, "weights": _WEIGHTS, "active": True}
    )

    await api.update_profile(5, payload, current_user=_ADMIN, db=_RecordingDb(row))

    assert row.client_id is None


_PAGE = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "app"
    / "settings"
    / "scoring"
    / "page.tsx"
)


@pytest.mark.skipif(not _PAGE.is_file(), reason="brak katalogu frontend w checkoutcie")
def test_settings_screen_shows_engine_default_weights():
    block = re.search(r"const DEFAULT_WEIGHTS[^{]*\{(.*?)\};", _PAGE.read_text(), re.S)
    assert block, "nie znaleziono DEFAULT_WEIGHTS w page.tsx"
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
        "Ekran /settings/scoring pokazuje inne wagi domyślne niż silnik. "
        "Zmiana stałych w scoring_service.py = popraw DEFAULT_WEIGHTS w page.tsx."
    )
