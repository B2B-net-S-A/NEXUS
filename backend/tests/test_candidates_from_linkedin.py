"""The retired JWT-based LinkedIn endpoint must not accept candidate writes.

The supported extension flow uses isolated keys on /api/extension/*.
"""

from httpx import AsyncClient


async def test_retired_linkedin_endpoint_rejects_candidate_writes(
    app_client: AsyncClient,
) -> None:
    response = await app_client.post(
        "/api/candidates/from-linkedin",
        json={"linkedin_url": "https://www.linkedin.com/in/test-retired-profile/"},
    )
    assert response.status_code == 405, response.text
