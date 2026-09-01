"""Brak nagłówka Authorization musi dawać 401, nigdy 403.

Kontrakt między backendem a frontendem:

    401 = nie wiemy kim jesteś (sesja martwa)  → frontend wylogowuje i wysyła na /login
    403 = wiemy kim jesteś, ale nie wolno ci   → frontend zostaje na miejscu

Domyślny ``HTTPBearer(auto_error=True)`` z FastAPI łamie ten kontrakt: na BRAK
nagłówka ``Authorization`` rzuca 403 "Not authenticated". Skutkiem był bug, w
którym po wygaśnięciu sesji użytkownik nadal oglądał pulpit (widgety z
komunikatem „Brak uprawnień do tego widoku") zamiast ekranu logowania —
interceptor w ``frontend/src/lib/api.ts`` reaguje wyłącznie na 401.

Te testy nie wymagają żywego serwera ani bazy — sprawdzają samą bramkę
autoryzacji, więc łapią regresję nawet gdy ktoś przywróci ``auto_error=True``.
"""

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User


@pytest.fixture
def app() -> FastAPI:
    """Minimalna aplikacja z jednym chronionym endpointem."""
    app = FastAPI()

    @app.get("/protected")
    async def protected(current_user: User = Depends(get_current_user)):
        return {"id": current_user.id}

    # Sesja DB nie jest potrzebna: na ścieżkach testowanych poniżej
    # get_current_user odrzuca żądanie zanim dotknie bazy.
    async def _no_db():
        yield None

    app.dependency_overrides[get_db] = _no_db
    return app


@pytest.fixture
async def app_client(app: FastAPI):
    """Nazwa `app_client`, nie `client` — konwencja repo dla testów in-process.

    `tests/conftest.py::pytest_collection_modifyitems` pomija każdy test, który
    używa fixture `client` bez `app_client`, traktując go jako wymagający
    żywego serwera (RUN_LIVE_TESTS). Fixture nazwana `client` sprawiłaby, że te
    testy byłyby cicho SKIPPED w CI — czyli bezwartościowe jako zabezpieczenie
    przed regresją.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_missing_authorization_header_is_401(app_client: AsyncClient):
    resp = await app_client.get("/protected")
    assert resp.status_code == 401, (
        "Brak nagłówka Authorization musi dawać 401. 403 nie wylogowuje "
        "użytkownika na froncie i zostawia go w powłoce aplikacji."
    )


async def test_empty_authorization_header_is_401(app_client: AsyncClient):
    resp = await app_client.get("/protected", headers={"Authorization": ""})
    assert resp.status_code == 401


async def test_wrong_scheme_is_401(app_client: AsyncClient):
    # Basic zamiast Bearer — poświadczeń Bearer brak, więc to nadal „nie wiemy kim jesteś".
    resp = await app_client.get("/protected", headers={"Authorization": "Basic abc123"})
    assert resp.status_code == 401


async def test_malformed_bearer_token_is_401(app_client: AsyncClient):
    resp = await app_client.get(
        "/protected", headers={"Authorization": "Bearer nie.jest.jwt"}
    )
    assert resp.status_code == 401


async def test_401_carries_www_authenticate_header(app_client: AsyncClient):
    """Bez tego nagłówka odpowiedź nie jest poprawnym 401 wg RFC 7235."""
    resp = await app_client.get("/protected")
    assert resp.headers.get("WWW-Authenticate") == "Bearer"
