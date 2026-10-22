"""Kontrakt budzika okna wdrożeń (`deploy-window` w compose, 15.10.2026).

Merge'e z dnia odracza workflow Deploy (okno 18:00–08:00, decyzja Artura
14.10.2026), a wdrażać miał je wieczorny `schedule` GitHuba. Ten w tym repo
przychodzi z kilkugodzinnym opóźnieniem albo wcale — 15.10 żaden z wieczornych
slotów nie przyszedł i dzienne zmiany czekały na ręczne uruchomienie. Budzik
w osobnym kontenerze o 18:05, 20:05 i 22:05 czasu warszawskiego uruchamia
Deploy przez API GitHuba (`workflow_dispatch` z `window_slot=true`).

Token budzika pozwala uruchomić każdy workflow repo (także zmianę zmiennych
produkcji), więc leży w pliku hosta zamontowanym tylko do budzika — NIE
w skarbcu Coolify: Coolify zapisuje skarbiec do `.env`, a backend i frontend
mają `env_file: .env` (przegląd bezpieczeństwa PR #2252).

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
_TOKEN_MOUNT = "/etc/nexus-deploy-window:/run/deploy-window:ro"


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


def _line(prefix: str) -> str:
    """Prawdziwa linia ``REPO=`` / ``TOKEN_FILE=`` z loop.sh."""
    src = _LOOP_SH.read_text(encoding="utf-8")
    match = re.search(rf"^{prefix}=.*$", src, re.M)
    assert match, f"brak linii {prefix}= w loop.sh"
    return match.group(0)


def _fake_bin(tmp_path: Path, name: str, body: str) -> None:
    path = tmp_path / "bin" / name
    path.parent.mkdir(exist_ok=True)
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _run_sh(tmp_path: Path, snippet: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
        "TMPDIR": str(tmp_path),
    }
    return subprocess.run(
        ["sh", "-c", snippet], capture_output=True, text=True, timeout=30, env=env
    )


def _fake_curl(tmp_path: Path, code: str) -> tuple[Path, Path]:
    """`curl`, który zapisuje argumenty (po jednym w linii) i stdin, zwraca `code`."""
    calls = tmp_path / "curl-calls"
    stdin = tmp_path / "curl-stdin"
    _fake_bin(
        tmp_path,
        "curl",
        f'printf "%s\\n" "$@" >> "{calls}"\n'
        f'echo "---" >> "{calls}"\n'
        f'cat >> "{stdin}"\n'
        'while [ $# -gt 0 ]; do [ "$1" = "-o" ] && printf \'{"message":"x"}\' > "$2"; shift; done\n'
        f'printf "%s" "{code}"\n',
    )
    _fake_bin(tmp_path, "sleep", f'echo "sleep $*" >> "{tmp_path / "sleeps"}"\n')
    return calls, stdin


def _dispatch_script(tmp_path: Path, token: str | None = "tok-test\n") -> str:
    token_file = tmp_path / "token"
    if token is not None:
        token_file.write_text(token, encoding="utf-8")
    return "\n".join(
        [
            _line("REPO"),
            f'TOKEN_FILE="{token_file}"',
            'log() { echo "$*"; }',
            _function("token_ready"),
            _function("dispatch"),
            'dispatch 18:05; echo "rc=$?"',
        ]
    )


def test_token_reaches_only_the_wakeup_container() -> None:
    """Token z pliku hosta, tylko do odczytu, tylko w budziku. Żadna zmienna
    środowiskowa: ta z compose szłaby przez skarbiec Coolify → `.env` → `env_file`
    backendu i frontendu."""
    service = _service()
    assert service["build"]["context"] == "./deploy-window"
    assert service.get("restart") == "unless-stopped"
    assert not service.get("ports"), "budzik niczego nie wystawia"
    assert not service.get("env_file"), "budzik nie czyta `.env` ze skarbca"
    assert not service.get("environment"), "token nie idzie przez zmienne środowiskowe"
    assert service.get("volumes") == [_TOKEN_MOUNT]
    assert service.get("mem_limit")
    assert service.get("cap_drop") == ["ALL"]
    assert "no-new-privileges:true" in (service.get("security_opt") or [])

    compose = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    for name, other in (compose.get("services") or {}).items():
        if name == "deploy-window":
            continue
        assert _TOKEN_MOUNT.split(":")[0] not in str(other.get("volumes")), name
    raw = _COMPOSE.read_text(encoding="utf-8")
    assert "DEPLOY_WINDOW_GITHUB_TOKEN" not in raw
    assert "DEPLOY_WINDOW_GITHUB_TOKEN" not in _LOOP_SH.read_text(encoding="utf-8")
    assert _line("TOKEN_FILE") == 'TOKEN_FILE="/run/deploy-window/token"'


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
    assert "-u 10001" in dockerfile, "plik tokenu na hoście ma właściciela uid 10001"
    assert "tzdata" in dockerfile, "sloty liczone w czasie warszawskim wymagają strefy"


def test_dispatch_runs_deploy_as_window_slot(tmp_path: Path) -> None:
    calls, stdin = _fake_curl(tmp_path, "204")
    out = _run_sh(tmp_path, _dispatch_script(tmp_path))
    assert "rc=0" in out.stdout, out.stdout + out.stderr
    args = calls.read_text(encoding="utf-8").splitlines()
    assert args.count("---") == 1, "jedno wywołanie API przy 204"
    assert (
        "https://api.github.com/repos/B2B-net-S-A/NEXUS/actions/workflows/deploy.yml/dispatches"
        in args
    ), "kanoniczne repo — stara nazwa przekierowuje, a POST za tym nie idzie"
    assert '{"ref":"main","inputs":{"window_slot":"true"}}' in args
    # Nagłówek z tokenem przez `--config -`: argumenty widać w `ps`/`docker top`.
    assert "--config" in args
    assert not any("tok-test" in arg for arg in args)
    assert 'header = "Authorization: Bearer tok-test"' in stdin.read_text(
        encoding="utf-8"
    )
    assert "tok-test" not in out.stdout + out.stderr, "token nie trafia do logu"


def test_missing_token_skips_the_slot_without_calling_api(tmp_path: Path) -> None:
    calls, _ = _fake_curl(tmp_path, "204")
    out = _run_sh(tmp_path, _dispatch_script(tmp_path, token=None))
    assert "rc=1" in out.stdout
    assert "brak czytelnego tokenu" in out.stdout
    assert not calls.exists()


def test_token_path_that_is_a_directory_is_no_token(tmp_path: Path) -> None:
    """Docker tworzy brakującą ścieżkę montowania jako katalog; pusty `Bearer`
    nie może polecieć do API."""
    calls, _ = _fake_curl(tmp_path, "204")
    (tmp_path / "token").mkdir()
    (tmp_path / "token" / "x").write_text("x", encoding="utf-8")
    out = _run_sh(tmp_path, _dispatch_script(tmp_path, token=None))
    assert "rc=1" in out.stdout
    assert not calls.exists()


def test_network_error_does_not_log_the_previous_response(tmp_path: Path) -> None:
    _fake_bin(tmp_path, "curl", 'cat > /dev/null; printf "000"; exit 6\n')
    _fake_bin(tmp_path, "sleep", "")
    (tmp_path / "dispatch-response").write_text("STARA-ODPOWIEDZ", encoding="utf-8")
    out = _run_sh(tmp_path, _dispatch_script(tmp_path))
    assert "HTTP 000" in out.stdout
    assert "STARA-ODPOWIEDZ" not in out.stdout


def test_dispatch_does_not_retry_a_rejected_token(tmp_path: Path) -> None:
    """401/403/404/422 — zły, wygasły albo za słaby token; ponowienie nic nie da."""
    calls, _ = _fake_curl(tmp_path, "401")
    out = _run_sh(tmp_path, _dispatch_script(tmp_path))
    assert "rc=1" in out.stdout
    assert calls.read_text(encoding="utf-8").count("---") == 1
    assert "HTTP 401" in out.stdout
    assert not (tmp_path / "sleeps").exists()


def test_dispatch_retries_server_errors_three_times(tmp_path: Path) -> None:
    calls, _ = _fake_curl(tmp_path, "502")
    out = _run_sh(tmp_path, _dispatch_script(tmp_path))
    assert "rc=1" in out.stdout
    assert calls.read_text(encoding="utf-8").count("---") == 3
    assert (tmp_path / "sleeps").read_text(encoding="utf-8").count("sleep") == 2


def test_each_slot_fires_once_a_day(tmp_path: Path) -> None:
    script = "\n".join(
        [
            'SLOTS="18:05 20:05 22:05"',
            'fired=""',
            'dispatch() { echo "fire $1"; }',
            _function("tick"),
            # Pętla sprawdza zegar co 20 s, więc ta sama minuta przychodzi
            # 2–3 razy; inny dzień to nowy slot.
            "tick 18:04 2026-10-15",
            "tick 18:05 2026-10-15",
            "tick 18:05 2026-10-15",
            "tick 18:06 2026-10-15",
            "tick 20:05 2026-10-15",
            "tick 08:05 2026-10-16",
            "tick 18:05 2026-10-16",
        ]
    )
    out = _run_sh(tmp_path, script)
    assert out.returncode == 0, out.stderr
    assert out.stdout.splitlines() == ["fire 18:05", "fire 20:05", "fire 18:05"]


def test_slots_sit_inside_the_deploy_window() -> None:
    """Okno wdrożeń to 18:00–08:00 (Warszawa); slot w dzień byłby odroczony."""
    src = _LOOP_SH.read_text(encoding="utf-8")
    match = re.search(r'^SLOTS="([^"]+)"$', src, re.M)
    assert match, "brak listy SLOTS w loop.sh"
    for slot in match.group(1).split():
        hour = int(slot.split(":")[0])
        assert hour >= 18 or hour < 8, slot
    assert re.search(r"^export TZ=Europe/Warsaw$", src, re.M)
