"""Etap B2: po SIGTERM proces schodzi z routingu, zanim przestanie słuchać.

Test stawia prawdziwy uvicorn w podprocesie, bo cała wartość zależy od kolejności
obsługi sygnałów w uvicornie (``Server.capture_signals``), której ASGITransport
nie ma. → app/core/shutdown_drain.py
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from app.core import shutdown_drain

BACKEND = Path(__file__).resolve().parents[1]

APP = textwrap.dedent(
    """
    import asyncio
    from contextlib import asynccontextmanager

    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    from app.core.shutdown_drain import install_shutdown_drain, is_draining


    @asynccontextmanager
    async def lifespan(app):
        assert install_shutdown_drain(1.5, asyncio.get_running_loop())
        yield


    app = FastAPI(lifespan=lifespan)


    @app.get("/live")
    async def live():
        if is_draining():
            return JSONResponse({"status": "draining"}, status_code=503)
        return {"status": "alive"}


    @app.post("/work")
    async def work():
        return {"ok": True}
    """
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _status(url: str, method: str = "GET") -> int:
    request = urllib.request.Request(
        url, method=method, data=b"" if method == "POST" else None
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


@pytest.fixture
def server(tmp_path):
    (tmp_path / "drain_app.py").write_text(APP, encoding="utf-8")
    port = _free_port()
    env = {**os.environ, "PYTHONPATH": f"{tmp_path}{os.pathsep}{BACKEND}"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "drain_app:app", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if _status(base + "/live") == 200:
                break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("uvicorn nie wstał")
    yield proc, base
    if proc.poll() is None:
        proc.kill()


def test_sigterm_reports_draining_keeps_serving_then_exits(server) -> None:
    proc, base = server
    started = time.monotonic()
    proc.send_signal(signal.SIGTERM)
    time.sleep(0.3)
    # Sonda Dockera widzi 503, a zapis nadal przechodzi: Traefik zdejmuje
    # kontener, zanim ten przestanie przyjmować połączenia.
    assert _status(base + "/live") == 503
    assert _status(base + "/work", "POST") == 200
    assert proc.poll() is None
    # Uvicorn po zamknięciu podnosi przechwycony sygnał ponownie
    # (`Server.capture_signals`), stąd -SIGTERM, jak bez drenażu.
    assert proc.wait(timeout=10) in (0, -signal.SIGTERM)
    assert time.monotonic() - started >= 1.5


def test_second_sigterm_closes_at_once(server) -> None:
    proc, _ = server
    proc.send_signal(signal.SIGTERM)
    time.sleep(0.3)
    started = time.monotonic()
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=10)
    assert time.monotonic() - started < 1.2


def test_zero_seconds_or_no_uvicorn_installs_nothing() -> None:
    loop = asyncio.new_event_loop()
    try:
        assert not shutdown_drain.install_shutdown_drain(0, loop)
        # Bez uvicorna obsługa SIGTERM to SIG_DFL — nie ma czego owijać.
        previous = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        try:
            assert not shutdown_drain.install_shutdown_drain(5, loop)
        finally:
            signal.signal(signal.SIGTERM, previous)
    finally:
        loop.close()
