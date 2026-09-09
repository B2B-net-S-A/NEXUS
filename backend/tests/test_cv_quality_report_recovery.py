"""Recover metrics without another model call; preserve failed-run transport."""

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from scripts.read_cv_quality_report import project, read_receipt
from tests.test_cv_quality_ops import ENV, ops, payload, message


def test_optional_response_schema_fingerprint_survives_receipt_and_transport():
    report = {**payload(), "response_schema_sha256": "d" * 64}
    projected = project(report, "123-1")
    assert projected["response_schema_sha256"] == "d" * 64
    decoded = ops.metric_report(message(report), ops.configuration(ENV), "b" * 64)
    assert decoded["response_schema_sha256"] == "d" * 64


@pytest.mark.parametrize("digest", [None, "", "private contents", "d" * 63])
def test_response_schema_fingerprint_cannot_export_arbitrary_text(digest):
    report = {**payload(), "response_schema_sha256": digest}
    with pytest.raises(ValueError):
        project(report, "123-1")
    with pytest.raises(ops.OpsError):
        ops.metric_report(message(report), ops.configuration(ENV), "b" * 64)


def test_recovery_command_can_only_read_a_fixed_receipt():
    config = ops.configuration(
        {**ENV, "RECOVER_RUN_ID": "456-1", "RECOVER_SOURCE_SHA": "b" * 40}
    )
    assert config["name"].endswith("123-1")
    assert config["identity"] == "456-1"
    assert config["sha"] == "b" * 40 and config["deployment_sha"] == "a" * 40
    assert "scripts.read_cv_quality_report 456-1" in config["command"]
    assert "run_cv_quality_once" not in config["command"]
    with pytest.raises(ops.OpsError):
        ops.configuration(
            {
                **ENV,
                "RECOVER_RUN_ID": "456-1;echo secret",
                "RECOVER_SOURCE_SHA": "b" * 40,
            }
        )


async def test_receipt_recovery_only_selects_exact_key():
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(value={**payload(), "source_text": "PRIVATE"})
    session = AsyncMock()
    session.__aenter__.return_value = db
    result = await read_receipt("123-1", Mock(return_value=session))
    assert db.get.call_args.args[1] == "cv_quality_eval:123-1"
    assert result["results"] == payload()["results"]
    assert result["replayed_receipt"] and "PRIVATE" not in json.dumps(result)
    db.execute.assert_not_called()
    db.commit.assert_not_called()


async def test_invalid_identity_is_rejected_before_opening_database():
    factory = Mock()
    with pytest.raises(ValueError):
        await read_receipt("secret-setting", factory)
    factory.assert_not_called()


def test_project_rejects_free_text_in_metric_fields():
    report = payload()
    report["results"][0]["case_id"] = "private candidate contents"
    with pytest.raises(ValueError):
        project(report, "123-1")


def test_missing_receipt_is_terminal_diagnostic_not_another_model_run():
    with pytest.raises(ops.OpsError, match="receipt_missing"):
        ops.metric_report(
            message(
                {"complete": False, "stop_reason": "receipt_missing", "results": []}
            ),
            ops.configuration(ENV),
            "b" * 64,
        )


def test_failed_evaluation_preserves_report_and_explicit_failure_code(tmp_path):
    # Native shell with small stand-ins for GNU timeout/base64. Never run a
    # provider or require Docker/GNU tools on the user's host.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_timeout = bin_dir / "timeout"
    fake_timeout.write_text(
        f"#!{sys.executable}\n"
        + """import json, pathlib, sys
path = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])
path.write_text(json.dumps({'complete': False, 'results': []}))
print('PRIVATE PROCESS DIAGNOSTICS')
sys.exit(2)
"""
    )
    fake_base64 = bin_dir / "base64"
    fake_base64.write_text(
        f"#!{sys.executable}\n"
        + """import base64, pathlib, sys
print(base64.b64encode(pathlib.Path(sys.argv[-1]).read_bytes()).decode(), end='')
"""
    )
    for script in (fake_timeout, fake_base64):
        script.chmod(0o700)
    command = [
        "bash",
        str(Path(__file__).parents[1] / "scripts/run_cv_quality_once.sh"),
        "123",
        "1",
        "primary",
        "4",
        "a" * 40,
    ]
    result = subprocess.run(
        command,
        env={**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "CV_QUALITY_EXIT=2" in result.stdout and ops.DONE in result.stdout
    assert "PRIVATE" not in result.stdout + result.stderr


def test_recovery_cleanup_checks_exact_command_and_terminal_execution():
    from tests.test_cv_quality_inspection import CleanupApi, c

    class RecoveryApi(CleanupApi):
        def inventory(self):
            rows = super().inventory()
            if rows:
                rows[0]["command"] = c.ops.recovery_command("123-1", "456-1")
            return rows

    api = RecoveryApi()
    assert c.cleanup(api, "123-1")["cleanup"] == "confirmed"
    active = RecoveryApi(status="running")
    with pytest.raises(c.ops.OpsError):
        c.cleanup(active, "123-1")
    assert not active.deleted
