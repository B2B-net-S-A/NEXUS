import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    "cv_generation_logs",
    Path(__file__).parents[2] / ".github/scripts/cv-generation-logs.py",
)
logs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(logs)


@pytest.mark.parametrize("uncertain_post", [True, False])
def test_probe_cleanup_recovers_ownership_after_uncertain_creation(
    monkeypatch, uncertain_post
):
    class Api:
        tasks = "/tasks"

        def __init__(self):
            self.records = [{"name": "unrelated", "uuid": "keep", "command": "keep"}]
            self.reads_after_post = 0

        def inventory(self):
            if len(self.records) > 1:
                self.reads_after_post += 1
                if not uncertain_post and self.reads_after_post == 1:
                    return self.records[:1]
            return self.records

        def request(self, method, path, payload=None):
            if method == "GET":
                return {"logs": ""}
            if method == "POST":
                self.records.append({**payload, "uuid": "owned"})
                if uncertain_post:
                    raise logs.ops.OpsError("transport_unknown")
            if method == "DELETE":
                assert path == "/tasks/owned"
                self.records = self.records[:1]

    api = Api()
    monkeypatch.setattr(logs.ops, "Api", lambda env: api)
    monkeypatch.setenv("APP_UUID", "application")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    with pytest.raises(logs.ops.OpsError):
        logs.main()
    assert [row["uuid"] for row in api.records] == ["keep"]
