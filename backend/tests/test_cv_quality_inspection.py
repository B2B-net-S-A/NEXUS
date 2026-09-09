"""The CV diagnostic inspection cannot mutate a task or disclose its logs."""

from pathlib import Path
import importlib.util
import json
import pytest

spec = importlib.util.spec_from_file_location(
    "cv_inspect", Path(__file__).parents[2] / ".github/scripts/cv-quality-inspect.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Api:
    tasks = "/tasks"

    def inventory(self):
        return [
            {
                "uuid": "owned-uuid",
                "name": "nexus-cv-quality-eval-123-1",
                "command": "secret",
            }
        ]

    def request(self, method, path):
        assert method == "GET"
        assert path == "/tasks/owned-uuid/executions"
        return [
            {"status": "failed", "message": "Traceback secret-token No such file"},
            {"status": "success", "message": ""},
        ]


def test_read_only_inspection_has_only_fixed_diagnostics():
    result = m.inspect(Api(), "123-1")
    serialized = json.dumps(result)
    assert "secret" not in serialized
    assert "Traceback" not in serialized
    assert result["returned_executions"] == 2
    assert result["executions"][0]["diagnostic_signals"] == [
        "file_missing",
        "python_exception",
    ]
    assert result["executions"][1]["has_completion"] is False


@pytest.mark.parametrize(
    "identity", ["123-2", "999-1", "123-1;echo secret", "../123-1", None]
)
def test_unknown_or_invalid_identity_does_not_read_executions(identity):
    with pytest.raises(m.ops.OpsError):
        m.inspect(Api(), identity)
