"""Zespół dla klienta bez bazy: token, adres, wybór składu, gotowe składy, kontrakty repo."""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.models.job import JobStatus
from app.services import client_panel as panel_service
from app.services import job_team_panel as service
from app.services import job_team_rates as rates
from app.services import job_team_variants as variants
from app.services.job_team_schema import (
    DOWNGRADE_DDL,
    TABLE_DDL,
    VARIANTS_DDL,
    VARIANTS_DOWNGRADE_DDL,
)

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


def test_after_secret_key_change_the_link_is_not_rebuilt(monkeypatch) -> None:
    team = SimpleNamespace(id=3, panel_token_nonce=None, panel_token_sha256=None)
    issued = service.issue_token(team)
    monkeypatch.setattr(settings, "SECRET_KEY", settings.SECRET_KEY + "-po-zmianie")
    assert service.current_token(team) is None
    assert team.panel_token_sha256 == panel_service.token_digest(issued)


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
    position = service.PublicPosition(
        "aaaaaaaaaaaaaaaa", job, SimpleNamespace(id=4, show_rate=False)
    )
    team = SimpleNamespace(
        id=1,
        name="Zespół mobilny",
        client_id=5,
        created_by=None,
        panel_expires_at=None,
        panel_token_nonce="x",
        variants=[],
    )

    view = {
        "panel": {"show_rate": False},
        "job": {"title": "Programista"},
        "candidates": [],
    }

    async def fake_view(db, panel, job, focus):
        return view

    async def fake_client_name(db, client_id):
        return "Klient"

    monkeypatch.setattr(panel_service, "public_panel_view", fake_view)
    monkeypatch.setattr(service, "_client_name", fake_client_name)
    body = await service.public_team_view(None, team, [position])  # type: ignore[arg-type]
    assert set(body) == {"team", "hours_per_month", "positions", "variants"}
    assert body["variants"] == []
    assert set(body["team"]) == {"name", "client_name", "expires_at", "owner"}
    assert body["team"]["owner"] == {"name": None}
    assert body["hours_per_month"] == 168
    assert body["positions"] == [
        {
            "key": "aaaaaaaaaaaaaaaa",
            "short": "Programista",
            "headcount": 2,
            # Ukryta stawka: bez szacunku i bez zapytania o historię stawek.
            "estimate": None,
            "view": view,
        }
    ]


# ── Gotowe składy: reguły automatu ───────────────────────────────────────────

_TODAY = date(2026, 11, 16)


def _o(cid: int, **extra) -> variants.Option:
    return variants.Option(candidate_id=cid, order=cid, **extra)


def _picks(groups, key: str) -> dict[int, list[int]]:
    proposed = {v["key"]: v for v in variants.propose(groups, _TODAY)}
    return {p["job_id"]: p["candidate_ids"] for p in proposed[key]["picks"]}


def test_proposal_gives_three_variants_in_a_fixed_order() -> None:
    group = variants.SeatGroup(1, 1, (_o(1),))
    proposed = variants.propose([group], _TODAY)
    assert [v["key"] for v in proposed] == ["fast", "cheap", "evidence"]
    assert [v["name"] for v in proposed] == [
        "Najszybszy start",
        "Najniższa cena",
        "Najwięcej w CV",
    ]
    assert all(len(v["why"]) <= variants.WHY_MAX for v in proposed)
    assert set(proposed[0]) == {
        "key",
        "name",
        "why",
        "picks",
        "hourly_total",
        "start",
        "unknown_start",
    }


def test_fastest_start_puts_no_date_last_and_breaks_ties_by_rate() -> None:
    group = variants.SeatGroup(
        1,
        1,
        (
            _o(1, available_from=None, hourly=50.0),
            _o(2, available_from=date(2026, 12, 1), hourly=200.0),
            _o(3, available_from=date(2026, 12, 1), hourly=150.0),
        ),
    )
    assert _picks([group], "fast") == {1: [3]}
    only_undated = variants.SeatGroup(1, 1, (_o(1, hourly=90.0), _o(2, hourly=80.0)))
    assert _picks([only_undated], "fast") == {1: [2]}


def test_a_date_in_the_past_counts_as_today() -> None:
    # „Od zaraz” to remis niezależnie od tego, jak dawno osoba jest wolna.
    group = variants.SeatGroup(
        1,
        1,
        (
            _o(1, available_from=date(2026, 1, 1), hourly=200.0),
            _o(2, available_from=date(2026, 11, 10), hourly=150.0),
        ),
    )
    assert _picks([group], "fast") == {1: [2]}


def test_lowest_price_puts_no_rate_last_and_breaks_ties_by_start() -> None:
    group = variants.SeatGroup(
        1,
        1,
        (
            _o(1, hourly=None, available_from=_TODAY),
            _o(2, hourly=150.0, available_from=date(2027, 1, 1)),
            _o(3, hourly=150.0, available_from=date(2026, 12, 1)),
        ),
    )
    assert _picks([group], "cheap") == {1: [3]}
    no_rates = variants.SeatGroup(
        1, 1, (_o(1, available_from=None), _o(2, available_from=_TODAY))
    )
    assert _picks([no_rates], "cheap") == {1: [2]}


def test_most_in_projects_breaks_ties_by_rate_then_sending_order() -> None:
    group = variants.SeatGroup(
        1,
        1,
        (
            _o(1, in_projects=2, hourly=180.0),
            _o(2, in_projects=3, hourly=200.0),
            _o(3, in_projects=3, hourly=170.0),
        ),
    )
    assert _picks([group], "evidence") == {1: [3]}
    tie = variants.SeatGroup(1, 1, (_o(5, in_projects=1), _o(4, in_projects=1)))
    assert _picks([tie], "evidence") == {1: [4]}


def test_headcount_above_one_takes_that_many_people() -> None:
    group = variants.SeatGroup(
        1, 2, (_o(1, hourly=300.0), _o(2, hourly=100.0), _o(3, hourly=200.0))
    )
    assert _picks([group], "cheap") == {1: [2, 3]}


def test_hidden_and_not_fit_people_are_never_proposed() -> None:
    group = variants.SeatGroup(
        1,
        2,
        (
            _o(1, hourly=100.0, hidden=True),
            _o(2, hourly=110.0, not_fit=True),
            _o(3, hourly=500.0),
        ),
    )
    for key in ("fast", "cheap", "evidence"):
        assert _picks([group], key) == {1: [3]}


def test_fewer_people_than_seats_and_empty_positions() -> None:
    short = variants.SeatGroup(1, 3, (_o(1), _o(2)))
    empty = variants.SeatGroup(2, 1, ())
    assert _picks([short, empty], "fast") == {1: [1, 2]}


def test_summary_sums_known_rates_and_takes_the_latest_start() -> None:
    groups = [
        variants.SeatGroup(
            1, 1, (_o(1, hourly=150.5, available_from=date(2026, 12, 1)),)
        ),
        variants.SeatGroup(2, 1, (_o(2, hourly=None, available_from=None),)),
        variants.SeatGroup(3, 1, (_o(3, hourly=99.5, available_from=date(2026, 1, 1)),)),
    ]
    fast = variants.propose(groups, _TODAY)[0]
    assert fast["hourly_total"] == 250.0
    assert fast["start"] == "2026-12-01"
    assert fast["unknown_start"] == 1
    nothing = variants.propose([variants.SeatGroup(1, 1, (_o(1),))], _TODAY)[0]
    assert (nothing["hourly_total"], nothing["start"], nothing["unknown_start"]) == (
        None,
        None,
        1,
    )


def test_identical_variants_are_kept() -> None:
    group = variants.SeatGroup(
        1, 1, (_o(1, hourly=100.0, available_from=_TODAY, in_projects=5),)
    )
    proposed = variants.propose([group], _TODAY)
    assert len(proposed) == 3
    assert len({str(v["picks"]) for v in proposed}) == 1


# ── Gotowe składy: zapis DL-a ────────────────────────────────────────────────


def _variant(**extra) -> dict:
    return {
        "key": "fast",
        "name": "Najszybszy",
        "why": "",
        "picks": [{"job_id": 10, "candidate_ids": [1]}],
        **extra,
    }


_SEATS = {10: 1, 20: 2}
_SENT = {10: {1, 2}, 20: {3, 4, 5}}


def test_valid_variants_drop_empty_positions_and_duplicates() -> None:
    saved = variants.validate_variants(
        [
            _variant(
                picks=[
                    {"job_id": 10, "candidate_ids": []},
                    {"job_id": 20, "candidate_ids": [3, 4, 3]},
                ]
            )
        ],
        seats=_SEATS,
        sent=_SENT,
    )
    assert saved == [
        {
            "key": "fast",
            "name": "Najszybszy",
            "why": "",
            "picks": [{"job_id": 20, "candidate_ids": [3, 4]}],
        }
    ]
    assert variants.validate_variants([], seats=_SEATS, sent=_SENT) == []


@pytest.mark.parametrize(
    "items",
    [
        # Rekrutacja spoza zespołu.
        [_variant(picks=[{"job_id": 99, "candidate_ids": [1]}])],
        # Osoba bez wysłanego CV na tym stanowisku.
        [_variant(picks=[{"job_id": 10, "candidate_ids": [3]}])],
        # Więcej osób niż miejsc.
        [_variant(picks=[{"job_id": 10, "candidate_ids": [1, 2]}])],
        [_variant(picks=[{"job_id": 10, "candidate_ids": []}])],
        [
            _variant(
                picks=[
                    {"job_id": 10, "candidate_ids": [1]},
                    {"job_id": 10, "candidate_ids": [2]},
                ]
            )
        ],
        [_variant(), _variant()],
    ],
)
def test_invalid_variants_are_422(items) -> None:
    with pytest.raises(HTTPException) as refused:
        variants.validate_variants(items, seats=_SEATS, sent=_SENT)
    assert refused.value.status_code == 422


def test_text_for_the_client_is_plain_and_bounded() -> None:
    assert (
        variants.clean_text("  Skład\n\tA\x00 ", limit=60, required=True) == "Skład A"
    )
    with pytest.raises(ValueError):
        variants.clean_text("   ", limit=60, required=True)
    with pytest.raises(ValueError):
        variants.clean_text("x" * 61, limit=60, required=True)
    assert variants.clean_text("", limit=240, required=False) == ""
    assert variants.clean_key(" Fast ") == "fast"
    for bad in ("", "a b", "<x>", "x" * 41, "-a"):
        with pytest.raises(ValueError):
            variants.clean_key(bad)


# ── Gotowe składy: widok klienta ─────────────────────────────────────────────


def test_public_variants_use_position_keys_and_drop_people_the_client_cannot_see() -> (
    None
):
    stored = [
        {
            "key": "fast",
            "name": "Najszybszy",
            "why": "Bo szybko",
            "picks": [
                {"job_id": 10, "candidate_ids": [1, 2]},
                {"job_id": 20, "candidate_ids": [3]},
                # Stanowisko, którego klient już nie widzi.
                {"job_id": 30, "candidate_ids": [7]},
            ],
        },
        # Nikogo z tego składu klient nie widzi: skład wypada.
        {
            "key": "cheap",
            "name": "Tani",
            "why": "",
            "picks": [{"job_id": 10, "candidate_ids": [9]}],
        },
    ]
    seen = {10: ("klucz-a", {1: "pa"}), 20: ("klucz-b", {3: "pc"})}
    assert service.public_variants(stored, seen) == [
        {
            "key": "fast",
            "name": "Najszybszy",
            "why": "Bo szybko",
            "picks": {"klucz-a": ["pa"], "klucz-b": ["pc"]},
        }
    ]
    assert service.public_variants([], seen) == []


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
    variants_migration = (
        BACKEND / "alembic/versions/0713_job_team_variants.py"
    ).read_text(encoding="utf-8")
    assert "schema.VARIANTS_DDL" in variants_migration
    assert "schema.VARIANTS_DOWNGRADE_DDL" in variants_migration
    assert 'down_revision = "0712_client_reports"' in variants_migration
    assert "*_job_team_schema.VARIANTS_DDL" in entrypoint


def test_variant_columns_are_idempotent_and_dropped_in_reverse() -> None:
    assert all("IF NOT EXISTS" in s for s in VARIANTS_DDL)
    assert all("IF EXISTS" in s for s in VARIANTS_DOWNGRADE_DDL)
    assert "variants JSONB NOT NULL" in VARIANTS_DDL[0]
    assert "REFERENCES users(id) ON DELETE SET NULL" in VARIANTS_DDL[2]


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
        "app/services/job_team_variants.py",
    ):
        source = (BACKEND / name).read_text(encoding="utf-8")
        assert "ai_feature" not in source
        assert "ai_models" not in source


# ── Podpowiedź stawki (Z4) ───────────────────────────────────────────────────


def test_rate_hint_needs_three_pairs_and_interpolates_quartiles() -> None:
    assert rates.summarize([]) is None
    assert rates.summarize([120.0, 140.0]) is None
    assert rates.summarize([140.0, 100.0, 120.0]) == {
        "p25": 110.0,
        "median": 120.0,
        "p75": 130.0,
        "count": 3,
    }
    assert rates.summarize([100.0, 110.0, 130.0, 170.0]) == {
        "p25": 107.5,
        "median": 120.0,
        "p75": 140.0,
        "count": 4,
    }


def test_client_estimate_carries_only_the_quartile_range() -> None:
    assert rates.public_estimate(None) is None
    hint = {"p25": 110.0, "median": 120.0, "p75": 130.0, "count": 3}
    assert rates.public_estimate(hint) == {"min": 110.0, "max": 130.0}


def _view(show_rate: bool, *candidate_rates) -> dict:
    return {
        "panel": {"show_rate": show_rate},
        "candidates": [{"rate": rate} for rate in candidate_rates],
    }


def test_estimate_only_without_a_shown_hourly_rate() -> None:
    hint = {"p25": 110.0, "median": 120.0, "p75": 130.0, "count": 3}
    daily = {"value": "1200.00", "unit": "daily", "currency": "PLN"}
    hourly = {"value": "150.00", "unit": "hourly", "currency": "PLN"}
    assert service._estimate(_view(True), hint) == {"min": 110.0, "max": 130.0}
    assert service._estimate(_view(True, None, daily), hint) == {
        "min": 110.0,
        "max": 130.0,
    }
    assert service._estimate(_view(True, daily, hourly), hint) is None
    assert service._estimate(_view(False), hint) is None
    assert service._estimate(_view(True), None) is None
