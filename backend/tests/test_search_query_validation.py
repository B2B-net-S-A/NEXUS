"""Regression from Schemathesis: a NUL in q used to reach PostgreSQL and 500."""

import pytest


@pytest.mark.parametrize("path", ["/api/candidates", "/api/contracts"])
@pytest.mark.parametrize("query", ["\x00", "Ewa\x00QA", "QA\x00"])
async def test_nul_search_is_a_validation_error(
    app_client, app_auth_headers, path, query
):
    response = await app_client.get(path, params={"q": query}, headers=app_auth_headers)
    assert response.status_code == 422, response.text
    assert any(error["loc"] == ["query", "q"] for error in response.json()["detail"])


# The per-parameter guard on `q` left every other text filter unguarded: the
# location ILIKE and the advanced-search phrases still bind NUL into SQL.
@pytest.mark.parametrize(
    "params",
    [
        {"location": "Warszawa\x00"},
        {"q_all": "Java\x00QA"},
        {"q_any": "Java\x00QA"},
        {"q_none": "Java\x00QA"},
    ],
)
async def test_nul_in_other_candidate_filters_is_a_validation_error(
    app_client, app_auth_headers, params
):
    response = await app_client.get(
        "/api/candidates", params=params, headers=app_auth_headers
    )
    assert response.status_code == 422, (response.status_code, response.text)
    (name,) = params
    assert any(error["loc"] == ["query", name] for error in response.json()["detail"])


def test_nul_guard_sits_inside_cors_and_outside_the_unhandled_error_net():
    from fastapi.middleware.cors import CORSMiddleware

    from app.core.null_character_guard import NullCharacterGuardMiddleware
    from app.core.request_correlation import RequestCorrelationMiddleware
    from app.main import UnhandledErrorMiddleware, app

    order = [middleware.cls for middleware in app.user_middleware]  # outermost first
    assert (
        order.index(CORSMiddleware)
        < order.index(RequestCorrelationMiddleware)
        < order.index(NullCharacterGuardMiddleware)
        < order.index(UnhandledErrorMiddleware)
    )
    assert order[-1] is UnhandledErrorMiddleware


async def test_nul_rejection_keeps_cors_and_correlation_headers(app_client):
    from app.core.config import settings

    origin = settings.CORS_ORIGINS[0]
    response = await app_client.get(
        "/api/candidates", params={"location": "\x00"}, headers={"Origin": origin}
    )
    assert response.status_code == 422, response.text
    # Without CORS headers the browser reports "Network Error" instead of 422.
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["x-request-id"]


async def test_nul_in_path_is_a_validation_error(app_client, app_auth_headers):
    response = await app_client.get("/api/candidates/%00", headers=app_auth_headers)
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["type"] == "null_character"
    assert response.json()["detail"][0]["loc"] == ["path"]


async def test_nul_in_json_body_is_rejected_before_the_handler(
    app_client, app_auth_headers
):
    response = await app_client.post(
        "/api/candidates",
        json={"first_name": "Jan\x00", "last_name": "Testowy"},
        headers=app_auth_headers,
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == [
        {
            "type": "null_character",
            "loc": ["body", "first_name"],
            "msg": "Value must not contain the NUL character (U+0000)",
            "input": "Jan\x00",
        }
    ]
