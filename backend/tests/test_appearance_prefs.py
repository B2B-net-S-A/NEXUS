"""Świat wyglądu na koncie (0694): lustro DDL, lustro listy światów, zapis.

Prod alembic bywa osierocony — `entrypoint.sh` JEST wdrożeniem, a model
`User` deklaruje `appearance_prefs`, więc brak lustra = każdy odczyt
użytkownika (w tym logowanie) pada. Lista światów żyje też we froncie
(`frontend/src/lib/worlds/world-ids.ts`): serwer odrzuca nieznany świat,
więc świat dodany tylko we froncie kończyłby się 422 przy zapisie.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.services.appearance_prefs import (
    WORLD_IDS,
    AppearancePrefs,
    AppearancePrefsUpdate,
    apply_appearance_update,
    effective_appearance,
)

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0694_user_appearance_prefs.py"
FRONTEND_IDS = BACKEND.parent / "frontend" / "src" / "lib" / "worlds" / "world-ids.ts"


def _collapse(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0693", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_chains_after_client_einvoices() -> None:
    module = _migration_module()
    assert module.revision == "0694_user_appearance_prefs"
    assert module.down_revision == "0693_trainings"


def test_every_ddl_statement_is_mirrored_in_entrypoint() -> None:
    raw = (BACKEND / "entrypoint.sh").read_text()
    entrypoint = _collapse(re.sub(r'"\s*\n\s*"', "", raw))
    for statement in _migration_module().DDL_STATEMENTS:
        collapsed = _collapse(statement)
        assert "IF NOT EXISTS" in collapsed, collapsed
        assert collapsed in entrypoint, statement


def test_world_list_matches_frontend() -> None:
    source = FRONTEND_IDS.read_text(encoding="utf-8")
    block = source.split("export const WORLD_IDS", 1)[1].split("] as const", 1)[0]
    assert tuple(re.findall(r'"([a-z]+)"', block)) == WORLD_IDS


def test_unknown_world_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AppearancePrefsUpdate(world="disco")
    with pytest.raises(ValidationError):
        AppearancePrefsUpdate(world_before_season="disco")


def test_stored_garbage_reads_as_no_world() -> None:
    assert effective_appearance(None) == AppearancePrefs()
    assert effective_appearance("sakura") == AppearancePrefs()
    assert (
        effective_appearance({"world": "disco", "world_before_season": 7})
        == AppearancePrefs()
    )
    assert effective_appearance({"world": "sakura"}).world == "sakura"


def test_update_changes_only_sent_fields() -> None:
    current = AppearancePrefs(world="winter", world_before_season="latte")
    merged = apply_appearance_update(current, AppearancePrefsUpdate(world="latte"))
    assert merged == AppearancePrefs(world="latte", world_before_season="latte")
    cleared = apply_appearance_update(
        merged, AppearancePrefsUpdate(world_before_season=None)
    )
    assert cleared.world_before_season is None


@pytest.mark.asyncio
async def test_world_is_saved_on_the_account(app_client) -> None:
    from app.models.user import UserRole
    from tests._jarvis_helpers import make_user

    _, headers = await make_user(UserRole.recruiter)
    first = await app_client.get("/api/users/me/preferences", headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["appearance"] == {"world": None, "world_before_season": None}

    saved = await app_client.patch(
        "/api/users/me/preferences",
        json={"appearance": {"world": "winter", "world_before_season": "sakura"}},
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["appearance"] == {
        "world": "winter",
        "world_before_season": "sakura",
    }

    again = await app_client.get("/api/users/me/preferences", headers=headers)
    assert again.json()["appearance"]["world"] == "winter"

    bad = await app_client.patch(
        "/api/users/me/preferences",
        json={"appearance": {"world": "disco"}},
        headers=headers,
    )
    assert bad.status_code == 422
