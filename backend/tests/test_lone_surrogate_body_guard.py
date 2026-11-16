"""Osierocony surogat UTF-16 w JSON-ie to 422, nie 500 (pentest 13.11.2026).

``{"email": "\\ud800"}`` to poprawny JSON, a ``json.loads`` daje z niego napis
z samotnym surogatem, którego nie da się zakodować w UTF-8. Domyślny handler
``RequestValidationError`` odsyłał ``input`` i serializacja odpowiedzi padała
na ``UnicodeEncodeError`` → 500 w ``UnhandledErrorMiddleware``, na każdej
trasie z ciałem, także anonimowo (``POST /api/auth/login``).
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

_LOGIN = "/api/auth/login"


async def _post(raw: bytes):
    from app.core.rate_limit import limiter

    was_enabled = limiter.enabled
    limiter.enabled = False
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as ac:
            return await ac.post(
                _LOGIN, content=raw, headers={"Content-Type": "application/json"}
            )
    finally:
        limiter.enabled = was_enabled


@pytest.mark.asyncio
async def test_lone_surrogate_in_invalid_field_is_422():
    response = await _post(b'{"email": "\\ud800", "password": "x"}')

    assert response.status_code == 422, response.text
    assert response.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [
        b'{"email": "osoba@example.com", "password": "\\ud800"}',
        b'{"email": "osoba@example.com", "password": "a\\udfffb"}',
        b'{"email": "osoba@example.com", "password": "x", "\\ud800": 1}',
    ],
    ids=["high-surrogate", "low-surrogate", "in-a-key"],
)
async def test_lone_surrogate_in_valid_field_is_422_before_the_handler(raw):
    response = await _post(raw)

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_surrogate_pair_is_an_ordinary_character():
    """Para ``\\ud83d\\ude00`` to emoji — nie wolno jej odrzucić."""
    response = await _post(b'{"email": "\\ud83d\\ude00", "password": "x"}')

    # Niepoprawny e-mail, ale zwykłe 422 walidacji z czytelnym ``input``.
    assert response.status_code == 422, response.text
    assert "\U0001f600" in response.text
