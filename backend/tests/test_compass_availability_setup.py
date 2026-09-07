"""The vault helper must validate destinations and keep dry runs read-only."""

import importlib.util
import io
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "availability_setup",
    Path(__file__).resolve().parents[2] / "scripts/configure-compass-availability.py",
)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def vault(monkeypatch, *, dry_run="true", source="", target=""):
    monkeypatch.setenv("COOLIFY_URL", "https://coolify.example.com")
    monkeypatch.setenv("COOLIFY_TOKEN", "test-runner-token")
    monkeypatch.setenv("COOLIFY_APP_UUID", "nexus-app")
    monkeypatch.setenv("AVAILABILITY_STAGE", "export")
    monkeypatch.setenv("AVAILABILITY_DRY_RUN", dry_run)
    calls = []
    nexus = {
        "uuid": "nexus-app",
        "git_repository": "https://github.com/artur-t-96/Nexus.git",
        "git_branch": "main",
    }
    compass = {
        "uuid": "compass-app",
        "git_repository": "artur-t-96/compass",
        "git_branch": "main",
    }
    replies = {
        "/applications/nexus-app": nexus,
        "/applications": [nexus, compass],
        "/applications/nexus-app/envs": [
            {"key": "COMPASS_AVAILABILITY_SECRET", "value": target}
        ]
        if target
        else [],
        "/applications/compass-app/envs": [
            {"key": "AVAILABILITY_EXPORT_SECRET", "value": source}
        ]
        if source
        else [],
    }

    def send(request, timeout):
        path = request.full_url.split("/api/v1", 1)[1]
        calls.append(
            (request.method, path, json.loads(request.data) if request.data else None)
        )
        return io.BytesIO(json.dumps(replies.get(path, {})).encode())

    monkeypatch.setattr(setup.urllib.request, "urlopen", send)
    return calls


def test_dry_run_has_no_writes_or_secret_output(monkeypatch, capsys):
    calls = vault(monkeypatch, source="private-source-value")
    setup.main()
    assert all(
        method == "GET" and not path.startswith("/deploy") for method, path, _ in calls
    )
    assert "private-source-value" not in capsys.readouterr().out


def test_conflicting_existing_credentials_are_not_replaced(monkeypatch):
    calls = vault(monkeypatch, dry_run="false", source="a" * 48, target="b" * 48)
    with pytest.raises(ValueError, match="disagree"):
        setup.main()
    assert all(method == "GET" for method, _, _ in calls)


def test_only_named_availability_settings_are_written_to_validated_apps(
    monkeypatch, capsys
):
    calls = vault(monkeypatch, dry_run="false")
    setup.main()
    writes = [
        (path, payload)
        for method, path, payload in calls
        if method in {"POST", "PATCH"}
    ]
    assert {(path, payload["key"]) for path, payload in writes} == {
        ("/applications/compass-app/envs", "AVAILABILITY_EXPORT_SECRET"),
        ("/applications/nexus-app/envs", "COMPASS_AVAILABILITY_SECRET"),
        ("/applications/nexus-app/envs", "COMPASS_AVAILABILITY_URL"),
    }
    secret = writes[0][1]["value"]
    assert len(secret) >= 32 and writes[1][1]["value"] == secret
    assert secret not in capsys.readouterr().out
    assert calls[-1][1] == "/deploy?uuid=compass-app&force=false"
