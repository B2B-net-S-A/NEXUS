"""Kontrakt budzika okna wdrożeń (`deploy-window` w compose, 15.10.2026).

Merge'e z dnia odracza workflow Deploy (okno 19:00–07:00, decyzja Artura
14.10.2026), a wdrażać miał je wieczorny `schedule` GitHuba. Ten w tym repo
przychodzi z kilkugodzinnym opóźnieniem albo wcale — 15.10 żaden z wieczornych
slotów nie przyszedł i dzienne zmiany czekały na ręczne uruchomienie. Budzik
w osobnym kontenerze o 19:05, 21:05 i 23:05 czasu warszawskiego uruchamia
Deploy przez API GitHuba (`workflow_dispatch` z `window_slot=true`).

Funkcje powłoki są wycinane z PRAWDZIWEGO ``loop.sh`` i uruchamiane w ``sh``
z podstawionymi ``curl``/``sleep`` — test na kopii dowodziłby tylko kopii.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_REPO = Path(__file__).resolve().parents[2]
_COMPOSE = _REPO / "docker-compose.yml"
_DIR = _REPO / "deploy-window"
_LOOP_SH = _DIR / "loop.sh"
_DOCKERFILE = _DIR / "Dockerfile"


def _service() -> dict:
    compose = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    services = compose.get("services") or {}
    assert "deploy-window" in services, "brak budzika okna wdrożeń w docker-compose.yml"
    return services["deploy-window"]


def _function(name: str) -> str:
    src = _LOOP_SH.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\(\) \{{.*?^\}}", src, re.S | re.M)
    assert match, f"nie znaleziono {name}() — zmienił się kształt loop.sh"
    return match.group(0)


def _fake_bin(tmp_path: Path, name: str, body: str) -> None:
    path = tmp_path / "bin" / name
    path.parent.mkdir(exist_ok=True)
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _run_sh(tmp_path: Path, snippet: str, **env: str) -> subprocess.CompletedProcess:
    full_env = {
        **os.environ,
        "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
        "TMPDIR": str(tmp_path),
        **env,
    }
    return subprocess.run(
        ["sh", "-c", snippet], capture_output=True, text=True, timeout=30, env=full_env
    )


def _fake_curl(tmp_path: Path, code: str) -> Path:
    """`curl`, który zapisuje argumenty (po jednym w linii) i zwraca `code`."""
    calls = tmp_path / "curl-calls"
    _fake_bin(
        tmp_path,
        "curl",
        f'printf "%s\\n" "$@" >> "{calls}"\n'
        f'echo "---" >> "{calls}"\n'
        'while [ $# -gt 0 ]; do [ "$1" = "-o" ] && printf \'{"message":"x"}\' > "$2"; shift; done\n'
        f'printf "%s" "{code}"\n',
    )
    _fake_bin(tmp_path, "sleep", f'echo "sleep $*" >> "{tmp_path / "sleeps"}"\n')
    return calls


def _repo_line() -> str:
    """Prawdziwa linia ``REPO=`` z loop.sh — domyślna nazwa repo jest częścią
    kontraktu (stara ``artur-t-96/Nexus`` przekierowuje, a POST za tym nie idzie)."""
    src = _LOOP_SH.read_text(encoding="utf-8")
    match = re.search(r"^REPO=.*$", src, re.M)
    assert match, "brak linii REPO= w loop.sh"
    return match.group(0)


def _dispatch_script() -> str:
    return "\n".join(
        [
            "unset DEPLOY_WINDOW_REPO",
            _repo_line(),
            'TOKEN="tok-test"',
            'log() { echo "$*"; }',
            _function("dispatch"),
            'dispatch 19:05; echo "rc=$?"',
        ]
    )


def test_service_is_isolated_and_off_without_token() -> None:
    """Token leży tylko w budziku: backend wystawiony do internetu go nie dostaje,
    a pusta wartość domyślna znaczy „budzik śpi”, nie restart w kółko."""
    service = _service()
    assert service["build"]["context"] == "./deploy-window"
    assert service.get("restart") == "unless-stopped"
    assert not service.get("ports"), "budzik niczego nie wystawia"
    assert service.get("mem_limit"), "mały kontener ma limit pamięci w bazowym compose"
    env = service.get("environment") or {}
    assert env == {"DEPLOY_WINDOW_GITHUB_TOKEN": "${DEPLOY_WINDOW_GITHUB_TOKEN:-}"}
    compose = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    for name, other in (compose.get("services") or {}).items():
        if name == "deploy-window":
            continue
        assert "DEPLOY_WINDOW_GITHUB_TOKEN" not in str(other.get("environment")), name


def test_no_token_is_hardcoded_and_image_is_pinned() -> None:
    for path in (_LOOP_SH, _DOCKERFILE):
        text = path.read_text(encoding="utf-8")
        assert not re.search(
            r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}", text
        ), path
    dockerfile = _DOCKERFILE.read_text(encoding="utf-8")
    assert re.search(r"^FROM alpine:[\d.]+@sha256:[0-9a-f]{64}$", dockerfile, re.M)
    assert re.search(r"^USER (?!root)\S+$", dockerfile, re.M), (
        "kontener nie działa jako root"
    )
    assert "tzdata" in dockerfile, "sloty liczone w czasie warszawskim wymagają strefy"


def test_dispatch_runs_deploy_as_window_slot(tmp_path: Path) -> None:
    calls = _fake_curl(tmp_path, "204")
    out = _run_sh(tmp_path, _dispatch_script())
    assert "rc=0" in out.stdout, out.stdout + out.stderr
    args = calls.read_text(encoding="utf-8").splitlines()
    assert args.count("---") == 1, "jedno wywołanie API przy 204"
    assert (
        "https://api.github.com/repos/B2B-net-S-A/NEXUS/actions/workflows/deploy.yml/dispatches"
        in args
    )
    assert "Authorization: Bearer tok-test" in args
    assert '{"ref":"main","inputs":{"window_slot":"true"}}' in args
    assert "tok-test" not in out.stdout + out.stderr, "token nie trafia do logu"


def test_dispatch_does_not_retry_a_rejected_token(tmp_path: Path) -> None:
    """401/403/404/422 — zły, wygasły albo za słaby token; ponowienie nic nie da."""
    calls = _fake_curl(tmp_path, "401")
    out = _run_sh(tmp_path, _dispatch_script())
    assert "rc=1" in out.stdout
    assert calls.read_text(encoding="utf-8").count("---") == 1
    assert "HTTP 401" in out.stdout
    assert not (tmp_path / "sleeps").exists()


def test_dispatch_retries_server_errors_three_times(tmp_path: Path) -> None:
    calls = _fake_curl(tmp_path, "502")
    out = _run_sh(tmp_path, _dispatch_script())
    assert "rc=1" in out.stdout
    assert calls.read_text(encoding="utf-8").count("---") == 3
    assert (tmp_path / "sleeps").read_text(encoding="utf-8").count("sleep") == 2


def test_each_slot_fires_once_a_day(tmp_path: Path) -> None:
    script = "\n".join(
        [
            'SLOTS="19:05 21:05 23:05"',
            'fired=""',
            'dispatch() { echo "fire $1"; }',
            _function("tick"),
            # Pętla sprawdza zegar co 20 s, więc ta sama minuta przychodzi
            # 2–3 razy; inny dzień to nowy slot.
            "tick 19:04 2026-10-15",
            "tick 19:05 2026-10-15",
            "tick 19:05 2026-10-15",
            "tick 19:06 2026-10-15",
            "tick 21:05 2026-10-15",
            "tick 07:05 2026-10-16",
            "tick 19:05 2026-10-16",
        ]
    )
    out = _run_sh(tmp_path, script)
    assert out.returncode == 0, out.stderr
    assert out.stdout.splitlines() == ["fire 19:05", "fire 21:05", "fire 19:05"]


def test_slots_sit_inside_the_deploy_window() -> None:
    """Okno wdrożeń to 19:00–07:00 (Warszawa); slot w dzień byłby odroczony."""
    src = _LOOP_SH.read_text(encoding="utf-8")
    match = re.search(r'^SLOTS="([^"]+)"$', src, re.M)
    assert match, "brak listy SLOTS w loop.sh"
    for slot in match.group(1).split():
        hour = int(slot.split(":")[0])
        assert hour >= 19 or hour < 7, slot
    assert re.search(r"^export TZ=Europe/Warsaw$", src, re.M)
