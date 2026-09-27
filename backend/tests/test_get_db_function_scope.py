"""Runda 9 (R9-X1-2): sesja żądania zatwierdzana przed odpowiedzią.

Od FastAPI 0.121 zależność z ``yield`` bez jawnego ``scope`` ma zasięg
„request”: jej część po ``yield`` (dawny commit ``get_db``) biegła PO wysłaniu
odpowiedzi i PO ``BackgroundTasks``. Nieudany commit dawał więc 2xx, a zadanie
w tle nie widziało wierszy z tego żądania. ``get_db`` wchodzi teraz na stos
zależności o zasięgu „function” — test biegnie przez prawdziwe trasowanie
FastAPI, więc zmiana tej mechaniki przy podbiciu wersji go wywróci.
"""

from __future__ import annotations

import inspect

import pytest
from fastapi import BackgroundTasks, Depends, FastAPI, WebSocket
from fastapi.testclient import TestClient

from app.core import database
from app.core.database import get_db


class _FakeSession:
    def __init__(self, events: list[str], fail_commit: bool) -> None:
        self.events = events
        self.fail_commit = fail_commit

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        if self.fail_commit:
            self.events.append("commit_failed")
            raise RuntimeError("commit failed (naruszenie FK)")
        self.events.append("commit")

    async def rollback(self) -> None:
        self.events.append("rollback")

    async def close(self) -> None:
        self.events.append("close")


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch):
    recorded: list[str] = []
    state = {"fail": False}

    def factory() -> _FakeSession:
        return _FakeSession(recorded, state["fail"])

    monkeypatch.setattr(database, "AsyncSessionLocal", factory)
    return recorded, state


def _app(events: list[str]) -> FastAPI:
    async def current_user(db=Depends(get_db)):
        return db

    app = FastAPI()

    @app.post("/write")
    async def write(
        background_tasks: BackgroundTasks,
        user_db=Depends(current_user),
        db=Depends(get_db),
    ) -> dict[str, bool]:
        events.append("handler")
        background_tasks.add_task(events.append, "background")
        return {"same_session": user_db is db}

    @app.post("/fail")
    async def fail(db=Depends(get_db)) -> dict:
        events.append("handler")
        raise ValueError("błąd handlera")

    @app.websocket("/ws")
    async def ws(websocket: WebSocket, db=Depends(get_db)) -> None:
        await websocket.accept()
        events.append("ws_handler")
        await websocket.close()

    return app


def test_get_db_is_not_a_request_scoped_generator() -> None:
    assert not inspect.isasyncgenfunction(get_db)


def test_commit_happens_before_response_and_background_tasks(events) -> None:
    recorded, _ = events
    with TestClient(_app(recorded)) as client:
        resp = client.post("/write")

    assert resp.status_code == 200
    # Jedna sesja dla zależności zagnieżdżonej (current_user) i handlera.
    assert resp.json() == {"same_session": True}
    assert recorded == ["handler", "commit", "close", "background"]


def test_failed_commit_is_not_a_2xx(events) -> None:
    recorded, state = events
    state["fail"] = True
    with TestClient(_app(recorded), raise_server_exceptions=False) as client:
        resp = client.post("/write")

    assert resp.status_code == 500
    assert "background" not in recorded
    assert recorded[:3] == ["handler", "commit_failed", "rollback"]


def test_handler_error_rolls_back(events) -> None:
    recorded, _ = events
    with TestClient(_app(recorded), raise_server_exceptions=False) as client:
        resp = client.post("/fail")

    assert resp.status_code == 500
    assert recorded == ["handler", "rollback", "close"]


def test_websocket_route_gets_a_session(events) -> None:
    recorded, _ = events
    with TestClient(_app(recorded)) as client:
        with client.websocket_connect("/ws"):
            pass

    assert recorded[:3] == ["ws_handler", "commit", "close"]
