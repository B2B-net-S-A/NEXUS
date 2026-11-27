"""``scripts/przeglad_dostepow.py``: kwartalny przegląd dostępów tylko do odczytu.

Testy nie łączą się z GitHubem ani serwerem. Pilnują, że stała komenda zdalna
nie wybiera wartości tokenów ani haseł, czyta bazy w trybie read-only, a lista
„do decyzji” łapie konta bez 2FA, zastałe tokeny i konta bez SSO.
Procedura: docs/claude/podstawy/dostepy-onboarding-offboarding.md.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path

import pytest

_REPO = Path(__file__).parents[2]
_PATH = _REPO / "scripts/przeglad_dostepow.py"
_SPEC = importlib.util.spec_from_file_location("przeglad_dostepow", _PATH)
pd = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = pd
_SPEC.loader.exec_module(pd)

TODAY = date(2026, 11, 27)


def test_remote_command_never_selects_secret_columns():
    cmd = pd.remote_command("c=web; ")
    lowered = cmd.lower()
    selects = re.findall(r"select (.*?) from", lowered)
    assert len(selects) == 3
    columns = {c.strip() for s in selects for c in s.split(",")}
    # personal_access_tokens.token, users.password, two_factor_secret, remember_token
    for secret in (
        "token",
        "u.password",
        "password",
        "two_factor_secret",
        "u.two_factor_secret",
        "remember_token",
        "password_hash",
        "two_factor_recovery_codes",
    ):
        assert secret not in columns, secret
    assert "select id, name, tokenable_id" in lowered
    assert "u.two_factor_confirmed_at is not null" in lowered
    assert "(password_hash is not null)" in lowered
    assert lowered.count("default_transaction_read_only = on") == 3


def test_remote_command_masks_break_glass_on_server():
    cmd = pd.remote_command("c=web; ")
    assert "PASSWORD_LOGIN_BREAK_GLASS_EMAILS" in cmd
    assert "…@" in cmd  # maskowanie sedem na serwerze, nie po stronie laptopa


def test_split_sections():
    out = "##KEYS\na\n\nb\n##COOLIFY_USERS\n0|x@y|f|owner\n##BREAK_GLASS\n"
    assert pd.split_sections(out) == {
        "KEYS": ["a", "b"],
        "COOLIFY_USERS": ["0|x@y|f|owner"],
        "BREAK_GLASS": [],
    }


def test_coolify_users_without_2fa_are_findings():
    rows, found = pd.review_coolify_users(["0|a@x|f|owner", "1|b@x|t|owner"])
    assert "2FA=NIE" in rows[0] and "2FA=tak" in rows[1]
    assert [f.text for f in found] == ["konto 0 bez 2FA (Profile → Two-factor)"]


@pytest.mark.parametrize(
    "last_used, expected",
    [
        ("2026-11-27", None),
        ("2026-10-28", None),  # 30 dni = jeszcze w normie
        ("2026-10-06", "nieużywany 52 dni"),
        ("", "nigdy nieużyty"),
    ],
)
def test_coolify_token_staleness(last_used, expected):
    _, found = pd.review_coolify_tokens([f"29|deploy|0|{last_used}|"], TODAY)
    if expected is None:
        assert found == []
    else:
        assert len(found) == 1 and expected in found[0].text


def test_nexus_users_flags_no_sso_and_stale_but_not_automation():
    lines = [
        "11|admin@x|admin|t|t|2026-11-27",
        "244|tcm@x|talent_community_manager|f|f|",
        "27|dl@x|delivery_lead|t|t|2026-10-01",
        "263|e2e@x|automation|f|t|",
    ]
    rows, found = pd.review_nexus_users(lines, TODAY)
    assert len(rows) == 4
    texts = [f.text for f in found]
    assert any("244" in t and "bez SSO" in t for t in texts)
    assert any("244" in t and "nigdy nieużyte" in t for t in texts)
    assert any("27" in t and "57 dni" in t for t in texts)
    assert not any("263" in t for t in texts)
    assert not any(t.startswith("konto 11 ") for t in texts)


def test_keys_without_comment_are_findings():
    rows, found = pd.review_keys(
        [
            "256 SHA256:abc no comment (ED25519)",
            "256 SHA256:def laptop (ED25519)",
        ]
    )
    assert rows == ["SHA256:abc  no comment", "SHA256:def  laptop"]
    assert len(found) == 1 and "SHA256:abc" in found[0].text


def test_github_review_flags_missing_org_2fa_and_write_deploy_key():
    data = {
        "org": {"two_factor_requirement_enabled": False},
        "members": ["a"],
        "members_no_2fa": ["b"],
        "outside": [],
        "collaborators": ["a (admin)"],
        "deploy_keys": [
            {
                "id": 1,
                "title": "ro",
                "read_only": True,
                "last_used": "2026-11-23T21:08:48Z",
            },
            {"id": 2, "title": "rw", "read_only": False, "last_used": None},
        ],
        "secrets": [{"name": "X", "updated_at": "2026-11-24T10:00:00Z"}],
    }
    rows, found = pd.review_github(data, TODAY)
    texts = [f.text for f in found]
    assert any("nie wymaga 2FA" in t for t in texts)
    assert any("bez 2FA: b" in t for t in texts)
    assert any("klucz wdrożeniowy 2 ma zapis" in t for t in texts)
    assert any("klucz wdrożeniowy 2 nieużywany" in t for t in texts)
    assert not any("klucz wdrożeniowy 1" in t for t in texts)
    assert "  X  2026-11-24" in rows


def test_fetch_github_uses_slurp_and_drops_gh_token(monkeypatch):
    calls = []

    def run(argv, env=None, **_k):
        calls.append((argv, env))
        path = argv[-1]
        if path.endswith("/actions/secrets"):
            body = [
                {
                    "total_count": 1,
                    "secrets": [{"name": "S", "updated_at": "2026-01-01"}],
                }
            ]
        elif path.startswith("orgs/") and "/" not in path[len("orgs/") :]:
            body = [{"two_factor_requirement_enabled": True}]
        else:
            body = [[{"login": "u", "role_name": "admin", "id": 1}]]
        return pd.subprocess.CompletedProcess(
            argv, 0, stdout=json.dumps(body), stderr=""
        )

    monkeypatch.setenv("GH_TOKEN", "zly-token")
    monkeypatch.setattr(pd.subprocess, "run", run)
    data = pd.fetch_github()
    assert data["org"]["two_factor_requirement_enabled"] is True
    assert data["members"] == ["u"]
    assert data["secrets"] == [{"name": "S", "updated_at": "2026-01-01"}]
    assert all("--slurp" in argv for argv, _ in calls)
    assert all("GH_TOKEN" not in env for _, env in calls)


def test_unknown_option_rejected(capsys):
    assert pd.main(["--zapis"]) == 2
