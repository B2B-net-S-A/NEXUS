"""Coolify transport tests use an in-memory API; no production credentials."""

import base64
import copy
import importlib.util
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    "cv_quality_ops", Path(__file__).parents[2] / ".github/scripts/cv-quality-ops.py"
)
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)
ENV = {
    "OPS_RUN_ID": "123",
    "OPS_RUN_ATTEMPT": "1",
    "EVAL_MODELS": "primary",
    "EVAL_CASES": "1",
    "EXPECTED_SHA": "a" * 40,
}
CONFIG = ops.configuration(ENV)
HASH = "b" * 64


def payload(**changes):
    report = {
        "runtime_sha": "a" * 40,
        "run_identity": "123-1",
        "corpus_sha256": HASH,
        "prompt_sha256": "c" * 64,
        "cases_per_model": 1,
        "requested_models": ["claude-test"],
        "complete": True,
        "results": [
            {
                "case_id": "synthetic_positive",
                "requested_model": "claude-test",
                "actual_models": ["claude-test"],
                "operation_id": "test-operation",
                "expected_supported": True,
                "outcome": "accepted",
                "passed": True,
                "elapsed_ms": 100,
                "provider_calls": 1,
                "metering_complete": True,
                "input_tokens": 100,
                "output_tokens": 100,
                "estimated_cost_usd": "0.001",
            }
        ],
        **changes,
    }
    return report


def message(report=None):
    encoded = base64.b64encode(json.dumps(report or payload()).encode()).decode()
    return f"{ops.BEGIN}\n{encoded}\n{ops.END}\nCV_QUALITY_EXIT=0\n{ops.DONE}"


class FakeApi:
    tasks = "/tasks"

    def __init__(
        self, *, previous=False, uncertain=False, missing=False, delete_failure=False
    ):
        self.records = (
            [{"name": ops.PREFIX + "other", "uuid": "unrelated"}] if previous else []
        )
        self.calls = []
        self.uncertain = uncertain
        self.missing = missing
        self.delete_failure = delete_failure

    def inventory(self):
        return copy.deepcopy(self.records)

    def request(self, method, path, data=None):
        self.calls.append((method, path))
        if method == "POST":
            self.records.append({**data, "uuid": "owned-task"})
            if self.uncertain:
                raise ops.OpsError("transport_unknown")
            return {"uuid": "owned-task"}
        if method == "DELETE":
            if self.delete_failure:
                raise ops.OpsError("transport_unknown")
            self.records = []
            return None
        if path.endswith("/executions"):
            return [] if self.missing else [{"message": message()}]
        raise AssertionError(path)


def execute(api, tmp_path, *, health=None):
    ticks = iter([0, 0, 2101])
    return ops.run(
        api,
        CONFIG,
        tmp_path,
        HASH,
        clock=lambda: next(ticks),
        sleep=lambda _: None,
        health=health or (lambda: CONFIG["sha"]),
    )


@pytest.mark.parametrize(
    "key,value",
    [
        ("OPS_RUN_ID", "1;true"),
        ("OPS_RUN_ATTEMPT", "0"),
        ("EVAL_MODELS", "arbitrary"),
        ("EVAL_CASES", "41"),
        ("EXPECTED_SHA", "main"),
        ("EVAL_CASES", "1\n"),
    ],
)
def test_command_accepts_only_bounded_fixed_inputs(key, value):
    with pytest.raises(ops.OpsError):
        ops.configuration({**ENV, key: value})


def test_closed_projection_drops_text_even_when_remote_adds_it():
    data = payload(source_text="SHOULD NEVER LEAVE BACKEND")
    data["results"][0]["model_explanation"] = "SHOULD NEVER LEAVE BACKEND"
    result = ops.metric_report(message(data), CONFIG, HASH)
    assert result["success"] is True
    assert "SHOULD NEVER" not in json.dumps(result)


@pytest.mark.parametrize(
    "change",
    [
        {"runtime_sha": "d" * 40},
        {"corpus_sha256": "e" * 64},
        {"run_identity": "999-1"},
        {"cases_per_model": 40},
        {"results": []},
    ],
)
def test_wrong_or_missing_evidence_cannot_claim_success(change):
    with pytest.raises(ops.OpsError):
        ops.metric_report(message(payload(**change)), CONFIG, HASH)


def test_malformed_terminal_report_is_error_not_a_pass():
    assert ops.metric_report("still running", CONFIG, HASH) is None
    with pytest.raises(ops.OpsError):
        ops.metric_report(ops.DONE, CONFIG, HASH)


def test_only_new_owned_task_is_deleted_after_persisting_metrics(tmp_path):
    api = FakeApi()
    assert execute(api, tmp_path) == 0
    assert api.calls == [
        ("POST", "/tasks"),
        ("GET", "/tasks/owned-task/executions"),
        ("DELETE", "/tasks/owned-task"),
    ]
    assert json.loads((tmp_path / "report.json").read_text())["success"] is True
    assert (
        json.loads((tmp_path / "transport.json").read_text())["cleanup"] == "confirmed"
    )


def test_preexisting_task_is_never_deleted_or_restarted(tmp_path):
    api = FakeApi(previous=True)
    assert execute(api, tmp_path) == 2
    assert api.calls == []


def test_uncertain_creation_never_retries_post_or_deletes_by_name(tmp_path):
    api = FakeApi(uncertain=True)
    assert execute(api, tmp_path) == 2
    assert api.calls == [("POST", "/tasks")]
    assert (
        json.loads((tmp_path / "transport.json").read_text())["cleanup"]
        == "creation_unknown_requires_inspection"
    )


def test_missing_execution_is_unknown_with_no_synthetic_success_report(tmp_path):
    api = FakeApi(missing=True)
    assert execute(api, tmp_path) == 2
    assert sum(method == "POST" for method, _ in api.calls) == 1
    assert not (tmp_path / "report.json").exists()
    assert (
        json.loads((tmp_path / "transport.json").read_text())["outcome"]
        == "execution_timeout_unknown"
    )


def test_cleanup_failure_remains_visible_with_task_identity(tmp_path):
    execute(FakeApi(delete_failure=True), tmp_path)
    state = json.loads((tmp_path / "transport.json").read_text())
    assert state["task_uuid"] == "owned-task"
    assert state["cleanup"] == "unknown_requires_inspection"


def test_stale_runtime_never_creates_task(tmp_path):
    api = FakeApi()
    assert execute(api, tmp_path, health=lambda: "old") == 2
    assert api.calls == []


def test_runner_cancellation_exits_polling_and_cleans_up_owned_task(tmp_path):
    class CancelledApi(FakeApi):
        def request(self, method, path, data=None):
            if path.endswith("/executions"):
                raise ops.Interrupted("runner_interrupted")
            return super().request(method, path, data)

    api = CancelledApi()
    assert execute(api, tmp_path) == 2
    state = json.loads((tmp_path / "transport.json").read_text())
    assert state["outcome"] == "runner_interrupted"
    assert state["cleanup"] == "confirmed"
    assert api.calls[-1] == ("DELETE", "/tasks/owned-task")
