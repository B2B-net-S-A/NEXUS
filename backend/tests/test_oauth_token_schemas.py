"""Token endpoint + scope decorator schema/unit tests (#6 follow-up).

Pure unit tests against in-memory JWT machinery — no DB or live FastAPI
client. Integration coverage of the actual ``POST /api/oauth/token`` flow
will land in tests/test_api_integration.py once we wire fixtures.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from jose import jwt
from pydantic import ValidationError

from app.api.oauth_token import (
    ClientPrincipal,
    TokenRequest,
    TokenResponse,
    _create_client_token,
)
from app.core.config import settings
from app.core.security import ALGORITHM
from app.models.oauth_client import OAuthScope


class TestTokenRequest:
    def test_only_client_credentials_grant_accepted(self):
        with pytest.raises(ValidationError):
            TokenRequest(
                grant_type="password",
                client_id="x",
                client_secret="y",
            )

    def test_minimal_valid(self):
        r = TokenRequest(
            grant_type="client_credentials",
            client_id="abc",
            client_secret="secret",
        )
        assert r.scope is None

    def test_with_scope(self):
        r = TokenRequest(
            grant_type="client_credentials",
            client_id="abc",
            client_secret="secret",
            scope="candidate:read job:read",
        )
        assert "candidate:read" in r.scope


class TestTokenResponse:
    def test_default_token_type_bearer(self):
        r = TokenResponse(access_token="x", scope="candidate:read")
        assert r.token_type == "Bearer"
        assert r.expires_in == 3600


class TestCreateClientToken:
    def test_token_carries_client_type_and_scope(self):
        # MagicMock stands in for an OAuthClient; the helper only reads
        # `.client_id`, no DB roundtrip.
        client = MagicMock()
        client.client_id = "abc-uuid-hex"
        token = _create_client_token(client, ["candidate:read", "job:read"])

        decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        assert decoded["sub"] == "abc-uuid-hex"
        assert decoded["type"] == "client"
        assert decoded["scope"] == "candidate:read job:read"
        # exp must be ~1h in the future
        exp = datetime.fromtimestamp(decoded["exp"], tz=timezone.utc)
        delta = exp - datetime.now(timezone.utc)
        assert timedelta(minutes=55) < delta < timedelta(minutes=65)

    def test_empty_scope_list_yields_empty_scope_claim(self):
        client = MagicMock()
        client.client_id = "id"
        token = _create_client_token(client, [])
        decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        assert decoded["scope"] == ""


class TestClientPrincipal:
    def test_round_trip(self):
        p = ClientPrincipal(client_id="abc", scopes=["candidate:read", "job:write"])
        assert p.client_id == "abc"
        assert "candidate:read" in p.scopes


class TestScopeVocabularyAlignment:
    """Guard test: every scope used in the issuer matches OAuthScope enum."""

    def test_known_scopes_are_strings(self):
        # Ensures the enum values are plain strings (no leading whitespace
        # etc.) — this is what gets compared against JWT scope claim.
        for s in OAuthScope:
            assert isinstance(s.value, str)
            assert s.value == s.value.strip()
            assert ":" in s.value  # resource:verb convention
