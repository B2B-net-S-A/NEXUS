"""A typo or copied production URL must fail before seeding any data."""

import json
import stat

import pytest

from qa.prepare import NoRedirects, stack_url, write_private_json


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://api.nexus.dynaminds.pl",
        "http://localhost:8000.evil.example",
        "http://localhost:8000@api.nexus.dynaminds.pl",
        "http://localhost:8000/path",
    ],
)
def test_refuses_non_stack_targets(monkeypatch, url):
    monkeypatch.setenv("QA_CONFIRM", "nexus-e2e")
    monkeypatch.setenv("E2E_API_URL", url)
    with pytest.raises(RuntimeError):
        stack_url()


def test_local_address_alone_does_not_authorize_seeding(monkeypatch):
    monkeypatch.setenv("E2E_API_URL", "http://localhost:8000")
    monkeypatch.delenv("QA_CONFIRM", raising=False)
    with pytest.raises(RuntimeError):
        stack_url()


def test_redirect_cannot_escape_the_test_target():
    with pytest.raises(RuntimeError):
        NoRedirects().redirect_request(
            None, None, 302, "Found", {}, "https://api.nexus.dynaminds.pl"
        )


@pytest.mark.parametrize("existing", [False, True])
def test_session_file_is_private_even_when_replacing_a_public_file(tmp_path, existing):
    path = tmp_path / "workload.json"
    if existing:
        path.write_text("stale")
        path.chmod(0o644)
    write_private_json(path, {"sessions": {"test": "fixture-only"}})
    assert json.loads(path.read_text()) == {"sessions": {"test": "fixture-only"}}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
