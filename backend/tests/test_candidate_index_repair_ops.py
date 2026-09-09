import json
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import run_candidate_index_repair_once as wrapper
from tests.test_candidate_index_audit_ops import transport


def reviewed(tmp_path):
    directory = tmp_path / "nexus-index-audit-123-1"
    directory.mkdir()
    (directory / "manifest.json").write_text("{}")


def test_repair_uses_only_reviewed_manifest_and_is_once_only(tmp_path, monkeypatch):
    reviewed(tmp_path)
    receipt = dict(queued=3, already_pending=2, deleted=0, orphans_reported_only=4)
    runner = Mock(
        return_value=SimpleNamespace(returncode=0, stdout=json.dumps(receipt).encode())
    )
    monkeypatch.setattr(wrapper.subprocess, "run", runner)
    result = wrapper.repair_once("124-1", "123-1", "a" * 64, root=tmp_path)
    assert result["state"] == "enqueued"
    assert result["queued"] == 3
    command = runner.call_args.args[0]
    assert command[-4:] == [
        "--apply",
        str(tmp_path / "nexus-index-audit-123-1/manifest.json"),
        "--fingerprint",
        "a" * 64,
    ]
    assert wrapper.repair_once("124-1", "123-1", "a" * 64, root=tmp_path) is None
    runner.assert_called_once()
    ops = transport()
    executions = [{"message": wrapper.PREFIX + json.dumps(result)}]
    assert ops.extract_repair_report(executions, "a" * 64, "123-1")["deleted"] == 0
    with pytest.raises(ValueError, match="reviewed"):
        ops.extract_repair_report(executions, "b" * 64, "123-1")


def test_missing_manifest_never_regenerates_plan(tmp_path, monkeypatch):
    runner = Mock()
    monkeypatch.setattr(wrapper.subprocess, "run", runner)
    assert (
        wrapper.repair_once("124-1", "123-1", "a" * 64, root=tmp_path)["error"]
        == "reviewed_manifest_missing"
    )
    runner.assert_not_called()


def test_timeout_preserves_unknown_commit_outcome(tmp_path, monkeypatch):
    reviewed(tmp_path)
    monkeypatch.setattr(
        wrapper.subprocess,
        "run",
        Mock(side_effect=subprocess.TimeoutExpired("repair", 720)),
    )
    result = wrapper.repair_once("124-1", "123-1", "a" * 64, root=tmp_path)
    assert result == {"ok": False, "error": "repair_outcome_unknown"}


@pytest.mark.parametrize(
    "audit_id,fingerprint",
    [("123-1\n", "a" * 64), ("../123", "a" * 64), ("123-1", "a" * 64 + ";echo")],
)
def test_repair_rejects_paths_and_shell_syntax(tmp_path, audit_id, fingerprint):
    with pytest.raises(ValueError):
        wrapper.repair_once("124-1", audit_id, fingerprint, root=tmp_path)
