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
