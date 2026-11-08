"""Sondy GitHuba patrzą na domenę, pod którą NEXUS naprawdę działa.

Od 19.10.2026 aplikacja żyje pod `nexus.b2bnetwork.pl`, a stary front od #3077
przekierowuje tam 307. Sonda na starym adresie mierzyła więc przekierowanie,
a certyfikatów nowych hostów nie sprawdzał nikt.

Druga część odpala krok „Backend health” 1:1 na lokalnym serwerze, bo #3151
to był błąd zachowania prawdziwego `curl`-a: przy `--retry` bez `-o` do pliku
odpowiedzi kolejnych prób sklejają się na stdout. `no available server` z 503
plus zdrowy JSON z drugiej próby dawały błąd parsowania `jq` i fałszywy alarm.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github/workflows"
PROBE = WORKFLOWS / "uptime-probe.yml"
DISK = WORKFLOWS / "disk-alert.yml"

NEW_HOSTS = {"nexus.b2bnetwork.pl", "api.nexus.b2bnetwork.pl"}
OLD_HOSTS = {"nexus.dynaminds.pl", "api.nexus.dynaminds.pl"}

HEALTHY = json.dumps({"status": "healthy", "version": "abc"})
UNHEALTHY = json.dumps({"status": "unhealthy", "version": "abc"})
GATEWAY_DOWN = "no available server"


def _probe_step(name: str) -> dict:
    steps = yaml.safe_load(PROBE.read_text(encoding="utf-8"))["jobs"]["probe"]["steps"]
    return next(step for step in steps if step.get("name") == name)


@pytest.mark.parametrize("workflow", [PROBE, DISK], ids=lambda p: p.name)
def test_probes_do_not_call_the_old_domain(workflow: Path) -> None:
    text = workflow.read_text(encoding="utf-8")
    assert not re.findall(r"https://(?:api\.)?nexus\.dynaminds\.pl", text)


def test_frontend_step_checks_the_new_domain() -> None:
    assert "https://nexus.b2bnetwork.pl/" in _probe_step("Frontend")["run"]


def test_backend_step_checks_the_new_domain() -> None:
    assert "https://api.nexus.b2bnetwork.pl/api/health" in _probe_step("Backend health")["run"]


def test_tls_loop_covers_new_and_still_served_old_hosts() -> None:
    match = re.search(r"for host in ([^;]+);", _probe_step("TLS expiry check")["run"])
    assert match, "nie rozpoznano pętli po hostach w kroku TLS"
    assert set(match.group(1).split()) == NEW_HOSTS | OLD_HOSTS


def _serve(responses: list[tuple[int, str]]) -> tuple[ThreadingHTTPServer, list[int]]:
    """Serwer oddaje kolejne odpowiedzi; ostatnia powtarza się bez końca."""
    remaining = list(responses)
    served: list[int] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - nazwa z http.server
            status, body = remaining.pop(0) if len(remaining) > 1 else remaining[0]
            payload = body.encode("utf-8")
            served.append(status)
            self.send_response(status)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, served


def _run_backend_step(
    tmp_path: Path, responses: list[tuple[int, str]]
) -> tuple[subprocess.CompletedProcess[str], list[int]]:
    """Skrypt kroku 1:1, z podmienionym adresem i skróconą przerwą między próbami."""
    if not (shutil.which("curl") and shutil.which("jq")):
        pytest.skip("krok sondy wymaga curl i jq")
    server, served = _serve(responses)
    try:
        run = _probe_step("Backend health")["run"]
        local_url = f"http://127.0.0.1:{server.server_port}/api/health"
        patched, url_subs = re.subn(r"https://api\.nexus\.[a-z0-9.]+/api/health", local_url, run)
        assert url_subs == 1, "nie rozpoznano adresu /api/health w kroku"
        patched, delay_subs = re.subn(r"--retry-delay \d+", "--retry-delay 1", patched)
        assert delay_subs == 1, "nie rozpoznano przerwy między próbami w kroku"
        script = tmp_path / "backend_health.sh"
        script.write_text(patched, encoding="utf-8")
        proc = subprocess.run(
            ["bash", str(script)],
            capture_output=True,
            text=True,
            timeout=30,
            env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
        )
    finally:
        server.shutdown()
        server.server_close()
    return proc, served


def test_gateway_error_then_healthy_is_green(tmp_path: Path) -> None:
    """Regresja #3151: pierwsza próba trafia w restart, druga jest zdrowa."""
    proc, served = _run_backend_step(tmp_path, [(503, GATEWAY_DOWN), (200, HEALTHY)])
    assert served == [503, 200]
    assert proc.returncode == 0, proc.stderr
    assert GATEWAY_DOWN not in proc.stdout


def test_gateway_error_then_unhealthy_stays_red(tmp_path: Path) -> None:
    proc, served = _run_backend_step(tmp_path, [(503, GATEWAY_DOWN), (503, UNHEALTHY)])
    assert served == [503, 503, 503]
    assert proc.returncode != 0


def test_persistent_gateway_error_stays_red(tmp_path: Path) -> None:
    proc, served = _run_backend_step(tmp_path, [(503, GATEWAY_DOWN)])
    assert served == [503, 503, 503]
    assert proc.returncode != 0


def test_healthy_on_first_try_is_green(tmp_path: Path) -> None:
    proc, served = _run_backend_step(tmp_path, [(200, HEALTHY)])
    assert served == [200]
    assert proc.returncode == 0, proc.stderr
