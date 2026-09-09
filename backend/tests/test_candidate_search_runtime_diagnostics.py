import importlib.util
import json
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from scripts import run_candidate_search_diagnostics_once as runtime
from scripts.report_candidate_search_metrics import summarize_runs


def transport():
    path = (
        Path(__file__).resolve().parents[2]
        / ".github/scripts/candidate-index-audit-ops.py"
    )
    spec = importlib.util.spec_from_file_location("runtime_ops", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_workflow_diagnostic_mode_is_an_opt_in_of_the_existing_audit():
    import yaml

    path = Path(__file__).resolve().parents[2] / ".github/workflows/coolify-ops.yml"
    workflow = yaml.safe_load(path.read_text())
    dispatch = workflow.get("on", workflow.get(True))["workflow_dispatch"]
    option = dispatch["inputs"]["candidate_search_diagnostics"]
    assert option["type"] == "boolean" and option["default"] is False
    assert "candidate-search-diagnostics" not in dispatch["inputs"]["action"]["options"]
    job = workflow["jobs"]["candidate_index_audit"]
    step = next(step for step in job["steps"] if "INDEX_MODE" in step.get("env", {}))
    assert (
        "inputs.action == 'candidate-index-audit' && inputs.candidate_search_diagnostics && 'diagnostics'"
        in step["env"]["INDEX_MODE"]
    )
    assert (
        "inputs.action == 'candidate-index-repair' && 'repair'"
        in step["env"]["INDEX_MODE"]
    )


def sample_report():
    return {
        "ok": True,
        "runtime": dict(
            embedding_model="voyage-3-large",
            collection="nexus_candidates",
            key_present=True,
            worker_enabled=True,
            worker_batch=50,
            worker_interval_seconds=30,
            usd_per_million_tokens=None,
        ),
        "queue": dict(
            by_status={"pending": 100, "done": 20},
            queue_depth=100,
            oldest_pending_age_seconds=120,
            dead=0,
        ),
        "recent_runs": [
            {
                "run_id": str(UUID(int=1)),
                "state": "complete",
                "population": 2,
                "query_characters": 300,
                "measurement_counts": {"stale": 1, "measured": 1},
                **runtime.metrics_projection({}),
            }
        ],
        "metrics_24h": {
            **summarize_runs([]),
            "sample_limit": 1000,
            "sample_truncated": False,
        },
        "synthetic_query_probe": {
            "ok": False,
            "dimensions": None,
            "error_type": "RuntimeError",
            **runtime.metrics_projection({}),
        },
    }


def test_projection_retains_unknown_cost_and_drops_private_payloads():
    data = sample_report()
    data["secret"] = "private"
    for part in [
        data["runtime"],
        data["queue"],
        data["recent_runs"][0],
        data["synthetic_query_probe"],
    ]:
        part["private"] = "candidate CV and API key"
    ops = transport()
    result = ops.extract_diagnostics_report(
        [{"message": runtime.PREFIX + json.dumps(data)}]
    )
    assert "private" not in json.dumps(result)
    assert result["runtime"]["usd_per_million_tokens"] is None
    assert result["recent_runs"][0]["cost_complete"] is None
    assert result["recent_runs"][0]["measurement_counts"] == {"stale": 1, "measured": 1}
    assert result["queue"]["queue_depth"] == 100


@pytest.mark.parametrize("bad", [-1, float("nan"), True, "private"])
def test_invalid_numeric_values_do_not_reach_artifact(bad):
    data = sample_report()
    data["runtime"]["worker_batch"] = bad
    with pytest.raises(ValueError):
        transport().extract_diagnostics_report(
            [{"message": runtime.PREFIX + json.dumps(data)}]
        )


@pytest.mark.asyncio
async def test_once_guard_does_not_repeat_provider_probe(tmp_path, monkeypatch):
    collect = AsyncMock(return_value=sample_report())
    monkeypatch.setattr(runtime, "collect_report", collect)
    assert (await runtime.run_once("123-1", root=tmp_path))["ok"]
    assert await runtime.run_once("123-1", root=tmp_path) is None
    collect.assert_awaited_once()
    assert (tmp_path / "nexus-search-diagnostics-123-1").stat().st_mode & 0o777 == 0o700
    with pytest.raises(ValueError):
        await runtime.run_once("123-1;echo", root=tmp_path)


@pytest.mark.asyncio
async def test_query_probe_preserves_failure_without_exception_message(monkeypatch):
    monkeypatch.setattr(
        runtime,
        "request_vector",
        AsyncMock(side_effect=RuntimeError("private request")),
    )
    result = await runtime.query_probe()
    assert result["ok"] is False
    assert result["error_type"] == "RuntimeError"
    assert result["dimensions"] is None
    assert "private" not in json.dumps(result)


@pytest.mark.asyncio
async def test_probe_observes_provider_usage_without_request_content(monkeypatch):
    from app.services.search_telemetry import record_embedding_attempt

    async def vector(text):
        assert text == "Synthetic candidate search diagnostic"
        record_embedding_attempt(
            model="voyage-3-large", tokens=7, failed=False, elapsed_ms=3
        )
        return [0.1] * 1024

    monkeypatch.setattr(runtime, "request_vector", vector)
    monkeypatch.setattr(runtime.settings, "AI_SEARCH_EMBEDDING_PRICES", {})
    result = await runtime.query_probe()
    assert result["ok"] and result["dimensions"] == 1024
    assert result["observed_tokens"] == 7 and result["provider_calls"] == 1
    assert result["estimated_cost_usd"] is None and result["cost_complete"] is False


def test_diagnostic_transport_uses_fixed_command_and_cleans_owned_task(
    tmp_path, monkeypatch
):
    from contextlib import contextmanager
    from types import SimpleNamespace

    ops = transport()
    for key, value in {
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
        "CO_URL": "https://coolify.example",
        "APP_UUID": "app",
        "CO_TOKEN": "test-only",
        "RUNNER_TEMP": str(tmp_path),
        "INDEX_MODE": "diagnostics",
        "INDEX_AUDIT_IDENTITY": "",
        "INDEX_FINGERPRINT": "",
    }.items():
        monkeypatch.setenv(key, value)
    tasks = []

    @contextmanager
    def request(req, **kwargs):
        if req.method == "POST":
            payload = json.loads(req.data)
            assert (
                payload["command"]
                == "cd /app && python -m scripts.run_candidate_search_diagnostics_once --run-identity 123-1"
            )
            tasks.append({"uuid": "own", "name": payload["name"]})
            result = {}
        elif req.method == "DELETE":
            assert req.full_url.endswith("/own")
            tasks.clear()
            result = None
        elif req.full_url.endswith("/executions"):
            result = [{"message": runtime.PREFIX + json.dumps(sample_report())}]
        else:
            result = tasks
        yield SimpleNamespace(read=lambda: json.dumps(result).encode())

    monkeypatch.setattr(ops.urllib.request, "urlopen", request)
    ops.main()
    assert not tasks
    data = json.loads(
        (tmp_path / "candidate-index-diagnostics/report.json").read_text()
    )
    assert data["runtime"]["worker_enabled"] is True
