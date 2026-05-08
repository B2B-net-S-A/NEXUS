"""Schema-level tests for OAuth2 client manager (#6 from Traffit gap roadmap).

Pure Pydantic / scope vocabulary tests — no DB roundtrip. CRUD endpoint
integration coverage will land alongside the token endpoint commit.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.oauth_client import SCOPE_LABELS, OAuthScope
from app.schemas.oauth_client import (
    OAuthClientCreate,
    OAuthClientCreateResponse,
    OAuthClientOut,
    OAuthClientUpdate,
    ScopeInfo,
)


class TestOAuthScopeVocabulary:
    def test_ten_scopes_cover_traffit_parity(self):
        keys = {s.value for s in OAuthScope}
        # Same shape as Traffit (resource:verb), trimmed to NEXUS-relevant.
        assert "candidate:read" in keys
        assert "candidate:write" in keys
        assert "job:read" in keys
        assert "job:write" in keys
        assert "webhook:subscribe" in keys
        # We don't import "advert"/"provision" — out of NEXUS scope.
        assert "advert" not in keys

    def test_every_scope_has_polish_label(self):
        for scope in OAuthScope:
            assert scope in SCOPE_LABELS, f"Missing label for {scope.value}"
            assert SCOPE_LABELS[scope]


class TestCreatePayload:
    def test_minimal(self):
        payload = OAuthClientCreate(name="n8n", scopes=[])
        assert payload.name == "n8n"
        assert payload.scopes == []

    def test_full(self):
        payload = OAuthClientCreate(
            name="ChatGPT plugin",
            scopes=[OAuthScope.candidate_read, OAuthScope.job_read],
        )
        assert len(payload.scopes) == 2

    def test_rejects_empty_name(self):
        with pytest.raises(ValidationError):
            OAuthClientCreate(name="", scopes=[])

    def test_rejects_oversized_name(self):
        with pytest.raises(ValidationError):
            OAuthClientCreate(name="x" * 121, scopes=[])

    def test_rejects_unknown_scope(self):
        with pytest.raises(ValidationError):
            OAuthClientCreate.model_validate(
                {"name": "x", "scopes": ["candidate:nuke"]}
            )


class TestUpdatePayload:
    def test_partial_name_only(self):
        u = OAuthClientUpdate(name="renamed")
        assert u.name == "renamed"
        assert u.scopes is None
        assert u.enabled is None

    def test_partial_disable(self):
        u = OAuthClientUpdate(enabled=False)
        assert u.enabled is False

    def test_replace_scopes(self):
        u = OAuthClientUpdate(scopes=[OAuthScope.webhook_subscribe])
        assert u.scopes == [OAuthScope.webhook_subscribe]


class TestOutSchema:
    def test_out_excludes_secret_field(self):
        # The OAuthClientOut schema MUST NOT have a `secret_hash` or
        # `client_secret` field. This is the single most important
        # invariant — leaking the hash undoes the rationale for hashing.
        fields = set(OAuthClientOut.model_fields.keys())
        assert "secret_hash" not in fields
        assert "client_secret" not in fields
        assert "client_id" in fields  # public identifier IS exposed

    def test_round_trip(self):
        now = datetime.now(timezone.utc)
        out = OAuthClientOut(
            id=1,
            name="n8n",
            client_id="abc123",
            scopes=["candidate:read"],
            enabled=True,
            created_by=42,
            created_at=now,
            updated_at=now,
            last_used_at=None,
        )
        assert out.client_id == "abc123"


class TestCreateResponse:
    def test_includes_plain_secret_once(self):
        now = datetime.now(timezone.utc)
        client = OAuthClientOut(
            id=1,
            name="n8n",
            client_id="abc123",
            scopes=[],
            enabled=True,
            created_by=42,
            created_at=now,
            updated_at=now,
            last_used_at=None,
        )
        response = OAuthClientCreateResponse(
            client=client, client_secret="random-secret-string"
        )
        # Secret is exposed only on create response, never on subsequent reads.
        assert response.client_secret == "random-secret-string"
        # The nested client representation still uses OAuthClientOut → no leak.
        assert "client_secret" not in response.client.model_fields


class TestScopeInfo:
    def test_scope_info_structure(self):
        info = ScopeInfo(value="candidate:read", label="Odczyt kandydatów")
        assert info.value == "candidate:read"
