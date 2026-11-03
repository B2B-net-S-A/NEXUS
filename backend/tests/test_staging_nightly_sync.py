"""Nocna kopia produkcji na staging: bez SSH, Dockera i bazy.

Wnioski ze stagingu idą do decyzji Artura, a bieg działa bez człowieka, więc
pilnujemy trzech rzeczy: flaga z produkcji nie włączy integracji, błąd przed
przełączeniem zostawia poprzednią kopię, porządki nie ruszą cudzej bazy.
"""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import sys

import pytest
import yaml

from app.core.config import Settings
from app.services.scoring_service import _SCORING_CACHE_INPUTS

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "staging_nightly_sync", ROOT / "scripts/staging/nightly_sync.py"
)
sync = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sync
spec.loader.exec_module(sync)

ALLOWED = sync.allowed_flags(
    (ROOT / "backend/app/services/scoring_service.py").read_text()
)
NIGHT = datetime(2026, 11, 2, 23, 5, tzinfo=timezone.utc)
DATE = "20261103"
NEW_DB = f"nexus_staging_nightly_{DATE}"
OLD_DB = "nexus_staging_20261102"


def test_allowlist_reads_scoring_inputs_without_importing_backend():
    assert set(ALLOWED) == (
        set(_SCORING_CACHE_INPUTS)
        | set(sync.RANKING_POOL_FLAGS)
        | set(sync.CLIENT_LIST_FLAGS)
    )


def test_every_allowed_flag_is_a_setting_and_is_passed_by_compose():
    environment = yaml.safe_load((ROOT / "docker-compose.staging.yml").read_text())[
        "services"
    ]["backend"]["environment"]
    for name in ALLOWED:
        assert name in Settings.model_fields, name
        assert name in environment, (
            f"{name}: bez wpisu w compose flaga z produkcji nie dojdzie do backendu"
        )


def test_flags_from_production_cannot_turn_on_integrations():
    environment = yaml.safe_load((ROOT / "docker-compose.staging.yml").read_text())[
        "services"
    ]["backend"]["environment"]
    hard_coded = {
        name
        for name, value in environment.items()
        if value is not None and "${" not in str(value)
    }
    assert {
        "TRAFFIT_SYNC_ENABLED",
        "M365_INTEGRATION_ENABLED",
        "HR_LOOPS_ENABLED",
        "NEXUS_ENV",
    } <= hard_coded
    assert not hard_coded & set(ALLOWED)


def test_flag_file_contains_only_allowed_names_and_simple_values():
    text = sync.flag_lines(
        {
            "HYBRID_POOL_ENABLED": True,
            "MATCH_POOL_SIZE": 2000,
            "VOYAGE_MODEL": "voyage-3",
            "TRAFFIT_SYNC_ENABLED": True,
        },
        ALLOWED,
    )
    assert sorted(text.splitlines()) == [
        "HYBRID_POOL_ENABLED=true",
        "MATCH_POOL_SIZE=2000",
        "VOYAGE_MODEL=voyage-3",
    ]


@pytest.mark.parametrize(
    "value", ["a b", "x\nTRAFFIT_SYNC_ENABLED=true", "$(id)", None, ["a"], "x" * 65]
)
def test_value_that_is_not_simple_stops_the_run(value):
    with pytest.raises(sync.SyncError):
        sync.flag_lines({"VOYAGE_MODEL": value}, ALLOWED)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("12,15", "12,15"),
        (" 12, 15 ,", "12,15"),
        ("", ""),
        # Literówka na produkcji wyłącza tam jednego klienta i nie może zatrzymać kopii.
        ("12,abc", "12"),
        ("12,13\nTRAFFIT_SYNC_ENABLED=true", "12"),
    ],
)
def test_client_list_keeps_only_ids_like_settings_do(value, expected):
    name = "MULTI_CONSULTANT_ORDER_CLIENT_IDS"
    assert sync.flag_lines({name: value}, ALLOWED) == f"{name}={expected}\n"


@pytest.mark.parametrize("value", [None, 12, ["12"]])
def test_client_list_of_other_type_stops_the_run(value):
    with pytest.raises(sync.SyncError):
        sync.flag_lines({"COST_ORDER_CLIENT_IDS": value}, ALLOWED)


def test_settings_snippet_filters_secrets_on_the_server():
    for name in (
        "SECRET_KEY",
        "VOYAGE_API_KEY",
        "SMTP_PASSWORD",
        "SENTRY_DSN",
        "DATABASE_URL",
        "GITHUB_TOKEN",
    ):
        assert re.search(sync.SECRET_NAME, name), name
    for name in ALLOWED + ("TRAFFIT_SYNC_ENABLED", "ANTHROPIC_MAX_TOKENS"):
        assert not re.search(sync.SECRET_NAME, name), name
    assert "secret.search(k)" in sync.SETTINGS_SNIPPET


def test_other_differences_skip_allowed_flags_and_strings():
    prod = {
        "TRAFFIT_SYNC_ENABLED": True,
        "SOME_LIMIT": 5,
        "SAME": 1,
        "MATCH_POOL_SIZE": 2000,
        "VOYAGE_MODEL": "a",
    }
    staging = {
        "TRAFFIT_SYNC_ENABLED": False,
        "SOME_LIMIT": 6,
        "SAME": 1,
        "MATCH_POOL_SIZE": 3000,
        "VOYAGE_MODEL": "b",
    }
    assert sync.other_differences(prod, staging, ALLOWED) == {
        "SOME_LIMIT": [5, 6],
        "TRAFFIT_SYNC_ENABLED": [True, False],
    }


@pytest.mark.parametrize(
    ("hour", "allowed"),
    [
        (21, False),
        (22, True),
        (23, True),
        (0, True),
        (1, False),
        (2, False),
        (7, False),
        (12, False),
    ],
)
def test_window_is_only_at_night(hour, allowed):
    now = datetime(2026, 11, 3, hour, 0, tzinfo=timezone.utc)
    assert (sync.window_refusal(now) is None) is allowed


def test_dump_deadline_is_before_production_backup():
    assert sync.dump_deadline(NIGHT) == datetime(
        2026, 11, 3, 2, 15, tzinfo=timezone.utc
    )
    after = datetime(2026, 11, 3, 0, 30, tzinfo=timezone.utc)
    assert sync.dump_deadline(after) == datetime(
        2026, 11, 3, 2, 15, tzinfo=timezone.utc
    )


def test_env_switch_changes_only_the_database_line():
    text = f"A=1\nSTAGING_DATABASE_NAME={OLD_DB}\nB=nexus_staging_20261102\n"
    assert (
        sync.switched_env(text, NEW_DB)
        == f"A=1\nSTAGING_DATABASE_NAME={NEW_DB}\nB=nexus_staging_20261102\n"
    )


@pytest.mark.parametrize(
    "text", ["A=1\n", "STAGING_DATABASE_NAME=a\nSTAGING_DATABASE_NAME=b\n"]
)
def test_env_without_single_database_line_stops_the_run(text):
    with pytest.raises(sync.SyncError):
        sync.active_database(text)


def test_retention_never_touches_other_databases():
    protected = {
        "nexus",
        "nexus_sales",
        "nexus_branch_bo",
        "nexus_staging_20261102",
        "nexus_staging_20261022b",
        "nexus_staging_nightly",
        "nexus_staging_nightly_2026",
        "nexus_staging_nightly_20261101x",
        "nexus_test_prep",
    }
    drop, remove = sync.retention_plan(
        protected, {"notes", "2026"}, set(), active=OLD_DB, connected=set()
    )
    assert drop == []
    assert remove == []


def _night(day: int) -> str:
    return f"nexus_staging_nightly_202611{day:02d}"


def test_retention_keeps_two_last_good_copies():
    databases = {_night(day) for day in (1, 2, 3, 4)}
    dates = {f"202611{day:02d}" for day in (1, 2, 3, 4)}
    drop, remove = sync.retention_plan(
        databases, dates, dates, active=_night(4), connected=set()
    )
    assert drop == [_night(1), _night(2)]
    assert remove == ["20261101", "20261102"]


def test_failed_night_does_not_push_out_a_good_copy():
    databases = {_night(day) for day in (1, 2, 3)}
    dates = {"20261101", "20261102", "20261103"}
    drop, remove = sync.retention_plan(
        databases, dates, {"20261101", "20261102"}, active=_night(2), connected=set()
    )
    assert drop == [_night(3)]
    assert remove == ["20261103"]


def test_marker_without_database_does_not_count_as_a_good_copy():
    databases = {_night(1), _night(2), _night(3)}
    dates = {"20261101", "20261102", "20261103", "20261104"}
    drop, remove = sync.retention_plan(
        databases, dates, dates, active=_night(3), connected=set()
    )
    assert drop == [_night(1)]
    assert sorted(remove) == ["20261101", "20261104"]


def test_connected_or_active_copy_stays_with_its_dump():
    databases = {_night(day) for day in (1, 2, 3, 4, 5)}
    dates = {f"202611{day:02d}" for day in (1, 2, 3, 4, 5)}
    drop, remove = sync.retention_plan(
        databases, dates, dates, active=_night(1), connected={_night(2)}
    )
    assert drop == [_night(3)]
    assert remove == ["20261103"]


def test_parity_line_is_parsed():
    assert sync.parse_parity("log\nranker_version=abc kopia=abc stale=12\n") == (
        "ranker_version=abc kopia=abc stale=12",
        12,
    )
    assert sync.parse_parity("ranker_version=abc kopia=None stale=0")[1] == 0
    with pytest.raises(sync.SyncError):
        sync.parse_parity("traceback")


class FakeCfg:
    ssh_host = "operator@production.example"
    ssh_identity = Path("/key")


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(sync.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(sync, "prod_container", lambda cfg, prefix: "a" * 64)


def _clone_results(monkeypatch, results):
    calls = []

    def fake(arguments, *, timeout, what):
        calls.append(timeout)
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(sync, "clone_step", fake)
    return calls


def test_dump_interrupted_by_deploy_is_retried(no_sleep, monkeypatch):
    terminated = sync.SyncError(
        "Zrzut produkcji: source_connection_terminated (exit 1)"
    )
    calls = _clone_results(monkeypatch, [terminated, terminated, "/copy/manifest.json"])
    result = sync.dump_production(FakeCfg, NEW_DB, Path("/copy"))
    assert result == Path("/copy/manifest.json")
    assert len(calls) == 3


def test_dump_gives_up_after_limited_attempts(no_sleep, monkeypatch):
    errors = [
        sync.SyncError("source_connection_closed") for _ in range(sync.DUMP_ATTEMPTS)
    ]
    calls = _clone_results(monkeypatch, errors)
    with pytest.raises(sync.SyncError):
        sync.dump_production(FakeCfg, NEW_DB, Path("/copy"))
    assert len(calls) == sync.DUMP_ATTEMPTS


def test_dump_other_error_is_not_retried(no_sleep, monkeypatch):
    calls = _clone_results(monkeypatch, [sync.SyncError("source_no_space")])
    with pytest.raises(sync.SyncError):
        sync.dump_production(FakeCfg, NEW_DB, Path("/copy"))
    assert len(calls) == 1


def test_dump_retry_keeps_the_first_deadline(no_sleep, monkeypatch):
    """Po terminie `dump_deadline` dałby kolejny dzień, a zrzut wszedłby w backup."""
    moments = iter(
        [
            datetime(2026, 11, 3, 2, 14, tzinfo=timezone.utc),
            datetime(2026, 11, 3, 2, 14, 30, tzinfo=timezone.utc),
            datetime(2026, 11, 3, 2, 16, tzinfo=timezone.utc),
        ]
    )

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return next(moments)

    monkeypatch.setattr(sync, "datetime", Clock)
    calls = _clone_results(monkeypatch, [sync.SyncError("source_connection_reset")])
    with pytest.raises(sync.SyncError, match="termin"):
        sync.dump_production(FakeCfg, NEW_DB, Path("/copy"))
    assert calls == [30]


def test_missing_production_container_is_awaited(monkeypatch):
    monkeypatch.setattr(sync.time, "sleep", lambda seconds: None)
    answers = [sync.SyncError("0 zamiast 1"), sync.SyncError("0 zamiast 1"), "id"]

    def fake(cfg, prefix):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(sync, "prod_container", fake)
    assert sync.wait_for_prod_container(FakeCfg, "postgres-ocgkw") == "id"


def test_refresh_waits_for_copy_and_passes_flags():
    script = (ROOT / "scripts/staging/refresh_code.sh").read_text()
    assert script.index("nightly-sync.pid") < script.index('git -C "$REPO" fetch')
    assert ".env.staging-flags.local" in script


class Harness:
    """Bieg `sync()` z podmienionymi krokami zewnętrznymi."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.env_file = tmp_path / "env" / ".env.staging.local"
        self.env_file.parent.mkdir()
        self.env_file.write_text(f"X=1\nSTAGING_DATABASE_NAME={OLD_DB}\n")
        self.started: list[str] = []
        self.cfg = sync.Config.__new__(sync.Config)
        self.cfg.env_file = self.env_file
        self.cfg.flags_file = self.env_file.with_name(".env.staging-flags.local")
        self.cfg.root = tmp_path / "nightly"
        self.cfg.settings_snapshot = tmp_path / "differences.json"
        self.report = sync.Report(tmp_path / "report")
        self.parity = [
            (1, "ranker_version=a kopia=a stale=200", 200, []),
            (0, "ranker_version=a kopia=a stale=0", 0, []),
        ]
        self.reembedded = False

        def fake_start(cfg, sha):
            self.started.append(sync.active_database(cfg.env_file.read_text()))

        def fake_align(report):
            self.reembedded = True

        def fake_dump(cfg, database, output_root):
            manifest = output_root / "manifest.json"
            manifest.write_text(json.dumps({"dump": {"bytes": 2**30}}))
            return manifest

        for name, value in {
            "local_postgres": lambda: "pg",
            "existing_databases": lambda postgres: {OLD_DB},
            "origin_main": lambda cfg: "a" * 40,
            "read_prod_settings": lambda cfg, allowed: {"MATCH_POOL_SIZE": 2000},
            "read_staging_settings": lambda allowed: {},
            "dump_production": fake_dump,
            "restore_copy": lambda postgres, database, manifest: None,
            "build_code": lambda cfg, sha: None,
            "start_staging": fake_start,
            "wait_healthy": lambda postgres, database, sha: None,
            "align_qdrant": fake_align,
            "run_parity": lambda: self.parity.pop(0),
        }.items():
            monkeypatch.setattr(sync, name, value)

    def run(self) -> int:
        return sync.sync(self.cfg, self.report, NIGHT, DATE)[0]

    @property
    def database(self) -> str:
        return sync.active_database(self.env_file.read_text())


@pytest.fixture
def harness(tmp_path, monkeypatch) -> Harness:
    return Harness(tmp_path, monkeypatch)


def test_good_night_switches_database_writes_flags_and_marks_copy(harness):
    harness.parity.pop(0)
    assert harness.run() == sync.EXIT_OK
    assert harness.database == NEW_DB
    assert harness.cfg.flags_file.read_text() == "MATCH_POOL_SIZE=2000\n"
    assert harness.reembedded
    assert (harness.cfg.root / DATE / sync.OK_MARKER).exists()
    assert not harness.report.waiting


def _fail(*args, **kwargs):
    raise sync.SyncError("powód")


@pytest.mark.parametrize(
    "step", ["read_prod_settings", "dump_production", "restore_copy", "build_code"]
)
def test_error_before_switch_leaves_previous_copy(harness, monkeypatch, step):
    monkeypatch.setattr(sync, step, _fail)
    assert harness.run() == sync.EXIT_BEFORE_SWITCH
    assert harness.database == OLD_DB
    assert not harness.cfg.flags_file.exists()
    assert harness.started == []
    assert not (harness.cfg.root / DATE / sync.OK_MARKER).exists()
    assert "powód" in harness.report.waiting[0]


def test_existing_target_database_stops_before_touching_production(
    harness, monkeypatch
):
    monkeypatch.setattr(sync, "existing_databases", lambda postgres: {NEW_DB})
    monkeypatch.setattr(
        sync,
        "read_prod_settings",
        lambda cfg, allowed: pytest.fail("nie powinno czytać produkcji"),
    )
    assert harness.run() == sync.EXIT_BEFORE_SWITCH
    assert harness.database == OLD_DB


def test_outside_window_nothing_happens(harness, monkeypatch):
    monkeypatch.setattr(
        sync,
        "read_prod_settings",
        lambda cfg, allowed: pytest.fail("nie powinno czytać produkcji"),
    )
    code, _ = sync.sync(
        harness.cfg,
        harness.report,
        datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc),
        DATE,
    )
    assert code == sync.EXIT_SKIPPED
    assert harness.database == OLD_DB


def test_unhealthy_new_copy_rolls_back_database_and_flags(harness, monkeypatch):
    harness.cfg.flags_file.write_text("MATCH_POOL_SIZE=1\n")
    calls = []

    def fake_wait(postgres, database, sha):
        calls.append(database)
        return "baza niezdrowa" if database == NEW_DB else None

    monkeypatch.setattr(sync, "wait_healthy", fake_wait)
    assert harness.run() == sync.EXIT_ROLLED_BACK
    assert harness.database == OLD_DB
    assert harness.cfg.flags_file.read_text() == "MATCH_POOL_SIZE=1\n"
    assert harness.started == [NEW_DB, OLD_DB]
    assert calls == [NEW_DB, OLD_DB]
    assert not (harness.cfg.root / DATE / sync.OK_MARKER).exists()
    assert "zdrowy" in harness.report.waiting[0]


def test_first_rollback_removes_flag_file(harness, monkeypatch):
    monkeypatch.setattr(sync, "start_staging", _fail)
    assert harness.run() == sync.EXIT_ROLLED_BACK
    assert not harness.cfg.flags_file.exists()
    assert harness.database == OLD_DB


def test_qdrant_failure_after_switch_stays_on_new_copy_and_reports(
    harness, monkeypatch
):
    monkeypatch.setattr(sync, "align_qdrant", _fail)
    assert harness.run() == sync.EXIT_RANKING
    assert harness.database == NEW_DB
    assert (harness.cfg.root / DATE / sync.OK_MARKER).exists()
    assert "powód" in harness.report.waiting[0]


def test_ranking_mismatch_is_reported(harness):
    harness.parity = [
        (1, "ranker_version=a kopia=b stale=0", 0, ["UWAGA: inny stempel"])
    ]
    assert harness.run() == sync.EXIT_RANKING
    assert "inny stempel" in harness.report.waiting[0]


def test_too_many_stale_people_skip_embedding(monkeypatch):
    report = sync.Report(Path("."))
    monkeypatch.setattr(
        sync, "run_parity", lambda: (1, "x", sync.MAX_REEMBED_PEOPLE + 1, [])
    )
    monkeypatch.setattr(
        sync, "run_cmd", lambda *a, **k: pytest.fail("nie powinno wołać Voyage")
    )
    sync.align_qdrant(report)
    assert "stale=" in report.waiting[0]


def test_only_new_setting_differences_reach_morning_report(harness, monkeypatch):
    monkeypatch.setattr(
        sync, "read_staging_settings", lambda allowed: {"SOME_LIMIT": 2, "OTHER": 2}
    )
    prod = {"SOME_LIMIT": 1, "OTHER": 1}
    sync.report_setting_differences(harness.cfg, prod, ALLOWED, harness.report)
    assert "SOME_LIMIT" in harness.report.waiting[0]
    second = sync.Report(harness.report.directory)
    sync.report_setting_differences(harness.cfg, prod, ALLOWED, second)
    assert second.waiting == []


def test_report_leaves_ok_trace_and_details_only_when_needed(tmp_path):
    report = sync.Report(tmp_path)
    report.write(exit_code=sync.EXIT_OK, sha="abc")
    assert "main=abc" in (tmp_path / "staging-kopia.ok").read_text()
    assert not (tmp_path / "staging-kopia.md").exists()
    report.waiting.append("x")
    report.write(exit_code=sync.EXIT_BEFORE_SWITCH, sha="abc")
    assert "## Czeka na Artura" in (tmp_path / "staging-kopia.md").read_text()


def test_stale_lock_is_taken_over_and_live_one_blocks(tmp_path):
    lock = tmp_path / "sync.pid"
    assert sync.acquire_lock(lock)
    assert not sync.acquire_lock(lock)
    lock.write_text("999999")
    assert sync.acquire_lock(lock)
