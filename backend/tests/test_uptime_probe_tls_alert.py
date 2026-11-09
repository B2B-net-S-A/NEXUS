"""Certyfikat bliski wygaśnięcia otwiera issue, a zielony bieg je zamyka.

Do 08.11.2026 krok „TLS expiry check” zostawiał tylko `::warning::` w logu,
którego nikt nie czyta (audyt rutyn). Issue działa bez laptopa i widzi je rutyna
Dyżurny. Marker jest osobny, bo „NEXUS niedostępny” mówiłby o awarii, której
przy działającym jeszcze certyfikacie nie ma.

Test odpala skrypty kroków 1:1. Podmienione są tylko `openssl` i `date` (GNU
`date -d` nie istnieje na macOS) oraz `gh`, więc bieg nie dotyka sieci.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/uptime-probe.yml"

MARKER = "Certyfikat TLS NEXUS wygasa"
ALARM_STEP = "Alarm — certyfikat TLS wygasa"
RESOLVE_STEP = "Zamknij alarm certyfikatu TLS"
HOSTS = (
    "nexus.b2bnetwork.pl",
    "api.nexus.b2bnetwork.pl",
    "nexus.dynaminds.pl",
    "api.nexus.dynaminds.pl",
)
NOW = 1_800_000_000
DAY = 86_400

FAKE_OPENSSL = """#!/bin/bash
case "$1" in
  s_client)
    while [ "$#" -gt 0 ]; do
      if [ "$1" = "-servername" ]; then echo "$2"; fi
      shift
    done
    ;;
  x509)
    read -r host
    [ -f "$EXPIRY_DIR/$host" ] || exit 1
    echo "notAfter=$(cat "$EXPIRY_DIR/$host")"
    ;;
esac
"""

# `date -d X +%s` oddaje X, bo fake `openssl` podaje notAfter jako epokę.
FAKE_DATE = f"""#!/bin/bash
if [ "$1" = "-d" ]; then echo "$2"; else echo {NOW}; fi
"""

# Otwarte issue leżą w $GH_OPEN_ISSUES, a każde wywołanie trafia do $GH_LOG.
FAKE_GH = """#!/bin/bash
echo "$*" >> "$GH_LOG"
if [ "$1 $2" = "issue list" ]; then cat "$GH_OPEN_ISSUES"; fi
"""


def _step(name: str) -> dict:
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["probe"][
        "steps"
    ]
    return next(step for step in steps if step.get("name") == name)


def _executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def sandbox(tmp_path: Path) -> dict[str, str]:
    if not (shutil.which("bash") and shutil.which("jq")):
        pytest.skip("kroki sondy wymagają bash i jq")
    bin_dir = tmp_path / "bin"
    expiry_dir = tmp_path / "expiry"
    runner_temp = tmp_path / "runner_temp"
    for directory in (bin_dir, expiry_dir, runner_temp):
        directory.mkdir()
    _executable(bin_dir / "openssl", FAKE_OPENSSL)
    _executable(bin_dir / "date", FAKE_DATE)
    _executable(bin_dir / "gh", FAKE_GH)
    (tmp_path / "gh_open.json").write_text("[]", encoding="utf-8")
    (tmp_path / "gh.log").touch()
    (tmp_path / "output.txt").touch()
    return {
        "PATH": f"{bin_dir}:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "EXPIRY_DIR": str(expiry_dir),
        "RUNNER_TEMP": str(runner_temp),
        "GITHUB_OUTPUT": str(tmp_path / "output.txt"),
        "GH_LOG": str(tmp_path / "gh.log"),
        "GH_OPEN_ISSUES": str(tmp_path / "gh_open.json"),
        "REPO": "owner/repo",
        "RUN_URL": "https://example.test/run/1",
    }


def _set_days(env: dict[str, str], **days_by_host: int) -> None:
    for host in HOSTS:
        days = days_by_host.get(host.replace(".", "_"), 90)
        Path(env["EXPIRY_DIR"], host).write_text(
            str(NOW + days * DAY), encoding="utf-8"
        )


def _run_step(name: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", _step(name)["run"]],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=REPO_ROOT,
        env=env,
    )


def _output(env: dict[str, str]) -> dict[str, str]:
    lines = Path(env["GITHUB_OUTPUT"]).read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


def _gh_calls(env: dict[str, str]) -> str:
    return Path(env["GH_LOG"]).read_text(encoding="utf-8")


@pytest.mark.parametrize(("days", "expiring"), [(13, "1"), (14, "0"), (-1, "1")])
def test_threshold_is_under_14_days(
    sandbox: dict[str, str], days: int, expiring: str
) -> None:
    _set_days(sandbox, api_nexus_b2bnetwork_pl=days)
    proc = _run_step("TLS expiry check", sandbox)
    assert proc.returncode == 0, proc.stderr
    assert _output(sandbox)["expiring"] == expiring


def test_alarm_names_only_the_expiring_host(sandbox: dict[str, str]) -> None:
    _set_days(sandbox, nexus_dynaminds_pl=5)
    assert _run_step("TLS expiry check", sandbox).returncode == 0
    body = Path(sandbox["RUNNER_TEMP"], "tls-alert.md").read_text(encoding="utf-8")
    assert "`nexus.dynaminds.pl`" in body
    assert "5" in body
    assert "nexus.b2bnetwork.pl" not in body


def test_expiring_certificate_keeps_the_probe_green_and_opens_its_own_issue(
    sandbox: dict[str, str],
) -> None:
    """Czerwony krok otworzyłby alarm „niedostępny”, a NEXUS przecież działa."""
    _set_days(sandbox, nexus_b2bnetwork_pl=3)
    assert _run_step("TLS expiry check", sandbox).returncode == 0
    proc = _run_step(ALARM_STEP, sandbox)
    assert proc.returncode == 0, proc.stderr
    calls = _gh_calls(sandbox)
    assert f"--title ⚠️ {MARKER}" in calls
    assert "niedostępny" not in calls


def test_green_run_closes_the_open_issue(sandbox: dict[str, str]) -> None:
    Path(sandbox["GH_OPEN_ISSUES"]).write_text(
        f'[{{"number": 77, "title": "⚠️ {MARKER}"}}]', encoding="utf-8"
    )
    _set_days(sandbox)
    assert _run_step("TLS expiry check", sandbox).returncode == 0
    assert _output(sandbox)["expiring"] == "0"
    proc = _run_step(RESOLVE_STEP, sandbox)
    assert proc.returncode == 0, proc.stderr
    assert "issue close 77" in _gh_calls(sandbox)


def test_failed_check_neither_opens_nor_closes(sandbox: dict[str, str]) -> None:
    """Brak odczytu jednego hosta to nie dowód, że certyfikat jest w porządku."""
    _set_days(sandbox, nexus_b2bnetwork_pl=3)
    os.remove(Path(sandbox["EXPIRY_DIR"], "api.nexus.dynaminds.pl"))
    assert _run_step("TLS expiry check", sandbox).returncode != 0
    assert "expiring" not in _output(sandbox)


def test_alarm_steps_are_gated_on_the_step_output() -> None:
    assert _step("TLS expiry check")["id"] == "tls"
    assert _step(ALARM_STEP)["if"] == "${{ steps.tls.outputs.expiring == '1' }}"
    assert _step(RESOLVE_STEP)["if"] == "${{ steps.tls.outputs.expiring == '0' }}"


def test_github_hiccup_while_alarming_cannot_turn_the_probe_red() -> None:
    """Czerwony job otwiera „NEXUS niedostępny”, a to nie ta awaria."""
    assert _step(ALARM_STEP)["continue-on-error"] is True


@pytest.mark.parametrize("name", [ALARM_STEP, RESOLVE_STEP])
def test_alarm_steps_have_token_and_repo(name: str) -> None:
    env = _step(name)["env"]
    assert env["GH_TOKEN"] == "${{ github.token }}"
    assert env["REPO"] == "${{ github.repository }}"


def test_github_hiccup_while_resolving_cannot_turn_the_probe_red() -> None:
    assert _step(RESOLVE_STEP)["continue-on-error"] is True
