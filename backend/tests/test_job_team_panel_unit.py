"""Zespół dla klienta bez bazy: token, adres, wybór składu, kontrakty repo."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.models.job import JobStatus
from app.services import client_panel as panel_service
from app.services import job_team_panel as service
from app.services.job_team_schema import DOWNGRADE_DDL, TABLE_DDL

BACKEND = Path(__file__).resolve().parents[1]


def test_token_has_the_panel_shape_but_its_own_message() -> None:
    token = service.compute_token(7, "a" * 32)
    assert token == service.compute_token(7, "a" * 32)
    assert token != service.compute_token(7, "b" * 32)
    assert token != service.compute_token(8, "a" * 32)
    # Ten sam numer i nonce panelu rekrutacji nie daje linku zespołu.
    assert token != panel_service.compute_token(7, "a" * 32)
    assert len(token) == panel_service.TOKEN_LENGTH
    assert panel_service._TOKEN_RE.match(token)


def test_rotation_keeps_only_the_digest() -> None:
    team = SimpleNamespace(id=3, panel_token_nonce=None, panel_token_sha256=None)
    assert service.current_token(team) is None
    old = service.issue_token(team)
    assert team.panel_token_sha256 == panel_service.token_digest(old)
    assert old not in (team.panel_token_sha256, team.panel_token_nonce)
    new = service.issue_token(team)
    assert new != old
    assert service.current_token(team) == new


@pytest.mark.parametrize("token", ["", "abc", "A" * 16, "1" * 16, "a" * 17, "a/b"])
async def test_malformed_token_is_404_without_touching_the_database(token) -> None:
    with pytest.raises(HTTPException) as refused:
        await service.load_public_team(None, token)  # type: ignore[arg-type]
    assert refused.value.status_code == 404


def test_team_url_lives_under_k_z(monkeypatch) -> None:
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://nexus.example.com/")
    assert service.team_urls("abc") == (
        "https://nexus.example.com/k/z/abc",
        "nexus.example.com/k/z/abc",
    )


def test_headcount_is_at_least_one() -> None:
    assert service.headcount(SimpleNamespace(headcount=None)) == 1
    assert service.headcount(SimpleNamespace(headcount=0)) == 1
    assert service.headcount(SimpleNamespace(headcount=3)) == 3


# ── Wybór składu ─────────────────────────────────────────────────────────────

_KEYS = {"klucz-a": 10, "klucz-b": 20}
_VISIBLE = {10: {"pa": 1, "pb": 2}, 20: {"pc": 3}}


def test_picks_map_keys_to_jobs_and_public_ids_to_candidates() -> None:
    picks = service.map_picks(
        {"klucz-a": ["pb", "pa", "pb"], "klucz-b": ["pc"]}, _KEYS, _VISIBLE
    )
    assert picks == [
        {"job_id": 10, "candidate_ids": [2, 1]},
        {"job_id": 20, "candidate_ids": [3]},
    ]


def test_empty_position_is_skipped() -> None:
    picks = service.map_picks({"klucz-a": ["pa"], "klucz-b": []}, _KEYS, _VISIBLE)
    assert picks == [{"job_id": 10, "candidate_ids": [1]}]


@pytest.mark.parametrize(
    "picks",
    [
        {"obcy-klucz": ["pa"]},
        # Osoba z innego stanowiska zespołu nie przechodzi pod cudzym kluczem.
        {"klucz-b": ["pa"]},
        {"klucz-a": ["nieznany"]},
        {"klucz-a": [], "klucz-b": []},
    ],
)
def test_unknown_key_person_or_nothing_chosen_is_422(picks) -> None:
    with pytest.raises(HTTPException) as refused:
        service.map_picks(picks, _KEYS, _VISIBLE)
    assert refused.value.status_code == 422


def _job(**extra) -> SimpleNamespace:
    base = {
        "id": 1,
        "title": "Rola",
        "client_id": 5,
        "status": JobStatus.published,
        "team_id": None,
    }
    return SimpleNamespace(**{**base, **extra})


@pytest.mark.parametrize(
    "job",
    [
        _job(client_id=6),
        _job(status=JobStatus.closed),
        _job(team_id=99),
    ],
)
def test_job_from_another_client_closed_or_in_another_team_is_409(job) -> None:
    with pytest.raises(HTTPException) as refused:
        service.check_jobs_joinable([job], client_id=5, team_id=7)
    assert refused.value.status_code == 409


def test_job_of_the_same_team_can_be_joined_again() -> None:
    service.check_jobs_joinable([_job(team_id=7), _job()], client_id=5, team_id=7)


# ── Kształt odpowiedzi publicznej ────────────────────────────────────────────


async def test_public_team_shape_is_built_from_explicit_fields(monkeypatch) -> None:
    job = SimpleNamespace(
        id=10,
        headcount=2,
        delivery_lead_id=None,
        client_id=5,
        status=JobStatus.published,
    )
    position = service.PublicPosition("aaaaaaaaaaaaaaaa", job, SimpleNamespace(id=4))
    team = SimpleNamespace(
        id=1,
        name="Zespół mobilny",
        client_id=5,
        created_by=None,
        panel_expires_at=None,
        panel_token_nonce="x",
    )

    async def fake_view(db, panel, job, focus):
        return {"job": {"title": "Programista"}, "candidates": []}

    async def fake_client_name(db, client_id):
        return "Klient"

    monkeypatch.setattr(panel_service, "public_panel_view", fake_view)
    monkeypatch.setattr(service, "_client_name", fake_client_name)
    body = await service.public_team_view(None, team, [position])  # type: ignore[arg-type]
    assert set(body) == {"team", "hours_per_month", "positions"}
    assert set(body["team"]) == {"name", "client_name", "expires_at", "owner"}
    assert body["team"]["owner"] == {"name": None}
    assert body["hours_per_month"] == 168
    assert body["positions"] == [
        {
            "key": "aaaaaaaaaaaaaaaa",
            "short": "Programista",
            "headcount": 2,
            "view": {"job": {"title": "Programista"}, "candidates": []},
        }
    ]


# ── Kontrakty repo ───────────────────────────────────────────────────────────


def test_migration_and_entrypoint_share_one_ddl_source() -> None:
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert "from app.services import job_team_schema as _job_team_schema" in (
        entrypoint
    )
    assert "*_JOB_TEAMS_DDL," in entrypoint
    # Po tabelach, na które wskazują klucze obce.
    assert entrypoint.index("*_JOB_TEAMS_DDL,") > entrypoint.index(
        "*_CLIENT_PANEL_DDL,"
    )
    migration = (BACKEND / "alembic/versions/0711_job_teams.py").read_text(
        encoding="utf-8"
    )
    assert "schema.TABLE_DDL" in migration
    assert "schema.DOWNGRADE_DDL" in migration
    assert 'down_revision = "0710_framework_rate_categories"' in migration


def test_team_table_is_created_before_the_job_column_points_at_it() -> None:
    create = next(i for i, s in enumerate(TABLE_DDL) if "TABLE IF NOT EXISTS job_teams" in s)
    column = next(i for i, s in enumerate(TABLE_DDL) if "ADD COLUMN IF NOT EXISTS team_id" in s)
    assert create < column
    assert all("IF NOT EXISTS" in s for s in TABLE_DDL)
    assert DOWNGRADE_DDL[-1] == "DROP TABLE IF EXISTS job_teams"


@pytest.mark.parametrize("table", ["job_teams", "job_team_selections"])
def test_tables_are_probed_by_deep_health(table: str) -> None:
    assert f'("{table}", ' in (BACKEND / "app/main.py").read_text(encoding="utf-8")


def test_public_module_has_no_future_annotations() -> None:
    tree = ast.parse(
        (BACKEND / "app/api/public_job_team_panel.py").read_text(encoding="utf-8")
    )
    assert not [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "__future__"
    ]


def test_no_ai_import_in_the_public_path() -> None:
    for name in (
        "app/api/public_job_team_panel.py",
        "app/services/job_team_panel.py",
    ):
        source = (BACKEND / name).read_text(encoding="utf-8")
        assert "ai_feature" not in source
        assert "ai_models" not in source
