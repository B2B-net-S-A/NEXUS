"""Stare adresy usuniętych modułów: 410 z komunikatem, reszta bez zmian."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.retired_modules import install_retired_modules, retired_message


@pytest.mark.parametrize(
    "path",
    [
        "/api/academy",
        "/api/academy/programs/5",
        "/api/integrations/v1/academy/programs",
        "/api/trainee/today",
        "/api/analytics/v1/overview",
        "/api/cloudtalk/agents",
        "/api/calls/webhook",
        "/api/calls/cloudtalk-status",
        "/api/admin/traffit/transfer",
    ],
)
def test_retired_addresses_are_recognised(path: str) -> None:
    assert retired_message(path)


@pytest.mark.parametrize(
    "path",
    ["/api/academyx", "/api/calls", "/api/calls/123", "/api/candidates/1", "/academy"],
)
def test_other_addresses_are_not_retired(path: str) -> None:
    assert retired_message(path) is None


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    install_retired_modules(app)

    @app.get("/api/admin/traffit/sync/status")
    async def still_alive() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/academy/programs/{program_id}")
    async def academy_program(program_id: int) -> None:
        raise HTTPException(status_code=404, detail=f"Brak programu {program_id}")

    @app.get("/api/candidates/{candidate_id}")
    async def missing(candidate_id: int) -> None:
        raise HTTPException(status_code=404, detail=f"Brak kandydata {candidate_id}")

    return TestClient(app)


def test_removed_route_answers_410_for_any_method(client: TestClient) -> None:
    for method in ("get", "post", "patch", "put", "delete"):
        response = getattr(client, method)("/api/academy/sessions")
        assert response.status_code == 410
        assert "Akademia" in response.json()["detail"]


def test_surviving_route_under_retired_prefix_still_answers(client: TestClient) -> None:
    assert client.get("/api/admin/traffit/sync/status").json() == {"ok": True}


def test_404_raised_by_a_surviving_route_stays_404(client: TestClient) -> None:
    response = client.get("/api/academy/programs/9")
    assert response.status_code == 404
    assert response.json() == {"detail": "Brak programu 9"}


def test_webhook_path_with_token_is_not_retired() -> None:
    assert retired_message("/api/calls/webhook/token") is None


def test_ordinary_404_keeps_its_own_detail(client: TestClient) -> None:
    response = client.get("/api/candidates/7")
    assert response.status_code == 404
    assert response.json() == {"detail": "Brak kandydata 7"}
    assert client.get("/api/nieznane").status_code == 404
