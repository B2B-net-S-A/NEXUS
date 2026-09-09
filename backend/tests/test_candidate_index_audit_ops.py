import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import run_candidate_index_audit_once as wrapper


def transport():
    path = (
        Path(__file__).resolve().parents[2]
        / ".github/scripts/candidate-index-audit-ops.py"
    )
    spec = importlib.util.spec_from_file_location("index_ops", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manifest():
    return dict(
        fingerprint="a" * 64,
        database_unchanged=True,
        population=2,
        index_points=3,
        counts={"current": 1, "missing": 1},
        orphan_point_ids=[90],
        candidates=[{"private": "never export"}],
    )


def test_audit_is_once_only_and_exports_no_candidate_data(tmp_path, monkeypatch):
    def execute(args, **kwargs):
        Path(args[-1]).write_text(json.dumps(manifest()))
        assert "--apply" not in args
        assert kwargs["timeout"] == 720
        return SimpleNamespace(returncode=0)

    runner = Mock(side_effect=execute)
    monkeypatch.setattr(wrapper.subprocess, "run", runner)
    report = wrapper.audit_once("123-1", root=tmp_path)
    assert report["ok"]
    assert report["orphan_points"] == 1
    assert "candidates" not in report and "private" not in json.dumps(report)
    assert (tmp_path / "nexus-index-audit-123-1").stat().st_mode & 0o777 == 0o700
    assert wrapper.audit_once("123-1", root=tmp_path) is None
    runner.assert_called_once()
    result = transport().extract_report(
        [{"message": wrapper.PREFIX + json.dumps(report)}]
    )
    assert result["population"] == 2


@pytest.mark.parametrize(
    "failure", [subprocess.TimeoutExpired("audit", 720), OSError("private detail")]
)
def test_failure_is_explicit_and_private(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(wrapper.subprocess, "run", Mock(side_effect=failure))
    report = wrapper.audit_once("123-1", root=tmp_path)
    assert not report["ok"]
    assert "private detail" not in json.dumps(report)
    with pytest.raises(RuntimeError):
        transport().extract_report([{"message": wrapper.PREFIX + json.dumps(report)}])


def test_incomplete_population_report_is_rejected():
    report = {**manifest(), "ok": True, "orphan_points": 1, "population": 100}
    with pytest.raises(ValueError, match="Incomplete"):
        transport().extract_report([{"message": wrapper.PREFIX + json.dumps(report)}])


@pytest.mark.parametrize("identity", ["1-1;echo", "1-1\n", "../1", "0-1"])
def test_identity_cannot_change_command_or_output_path(tmp_path, identity):
    with pytest.raises(ValueError):
        wrapper.audit_once(identity, root=tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("success", [True, False])
def test_transport_removes_only_its_task_on_success_or_failure(
    tmp_path, monkeypatch, success
):
    from contextlib import contextmanager

    ops = transport()
    for key, value in {
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
        "CO_URL": "https://coolify.example",
        "APP_UUID": "app",
        "CO_TOKEN": "test-only",
        "RUNNER_TEMP": str(tmp_path),
    }.items():
        monkeypatch.setenv(key, value)
    tasks = [{"uuid": "unrelated", "name": "normal-cron"}]
    report = {**manifest(), "ok": success, "orphan_points": 1}
    commands = []

    @contextmanager
    def request(req, **kwargs):
        if req.method == "POST":
            payload = json.loads(req.data)
            commands.append(payload["command"])
            tasks.append({"uuid": "owned", "name": payload["name"]})
            result = {"uuid": "owned"}
        elif req.method == "DELETE":
            assert req.full_url.endswith("/owned")
            tasks.pop()
            result = None
        elif req.full_url.endswith("/executions"):
            result = [{"message": wrapper.PREFIX + json.dumps(report)}]
        else:
            result = tasks
        yield SimpleNamespace(read=lambda: json.dumps(result).encode())

    monkeypatch.setattr(ops.urllib.request, "urlopen", request)
    if success:
        ops.main()
        assert (tmp_path / "candidate-index-audit/report.json").exists()
    else:
        with pytest.raises(RuntimeError):
            ops.main()
        assert not (tmp_path / "candidate-index-audit/report.json").exists()
    assert tasks == [{"uuid": "unrelated", "name": "normal-cron"}]
    assert commands == [
        "cd /app && python -m scripts.run_candidate_index_audit_once --run-identity 123-1"
    ]
