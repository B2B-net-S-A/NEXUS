"""Tokeny wybite przez python-jose przechodzą przez kod na PyJWT.

25.11.2026 backend przeszedł z python-jose na PyJWT (alert GHSA-3qf3-8w2g-rqmx,
jose bez wydania z poprawką). Sesje, stany logowania OAuth, tokeny klientów
i linki z maili wydane przed wdrożeniem mają działać dalej, więc każdy rodzaj
tokenu jest tu stałą. Wybił je kod z maina sprzed zmiany (python-jose 3.5.0)
przy zegarze ``_MINTED_AT`` i kluczach poniżej, a test sprawdza je dzisiejszymi
funkcjami weryfikacji. Tego samego dnia PyJWT wybijał z tych danych tokeny
identyczne bajt w bajt, więc cofnięcie wdrożenia też nikogo nie wylogowuje.

Tokeny leżą w kawałkach (nagłówek, treść, podpis), bo gitleaks ma regułę na
cały JWT. To nie sekrety: podpisują je wyłącznie klucze tego testu.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
import time_machine

from app.api import auth_microsoft
from app.api.oauth_token import require_scope
from app.core.config import settings
from app.core.security import (
    decode_token,
    token_authorization_version_matches,
    token_is_revoked,
)
from app.models.oauth_client import OAuthScope
from app.services.cv_generator_b2b import consent_binding
from app.services.job_portals import jjit_connection
from app.services.m365 import actionable_messages
from app.services.m365 import oauth as m365_oauth

# Klucze tylko tego testu (SECRET_KEY i M365_STATE_SIGNING_KEY przy wybijaniu).
_SESSION_KEY = "s" * 48
_STATE_KEY = "m" * 48
_MINTED_AT = datetime(2026, 11, 25, 9, 30, 15, 123456, tzinfo=timezone.utc)
_HEADER = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"  # {"alg":"HS256","typ":"JWT"}

_JOSE_TOKENS = {
    # create_access_token(42, "recruiter", roles=[...], authorization_version=3,
    #                     section_access={...}, finance_orders=True)
    "access": (
        "eyJzdWIiOiI0MiIsInJvbGUiOiJyZWNydWl0ZXIiLCJ0eXBlIjoiYWNjZXNzIiwiZXhwIjox"
        "Nzk1NjI3ODE1LCJpYXQiOjE3OTU1OTkwMTUuMTIzNDU2LCJhdiI6Mywicm9sZXMiOlsicmVj"
        "cnVpdGVyIiwiZGVsaXZlcnlfbGVhZCJdLCJzYSI6eyJkZWxpdmVyeSI6InJlYWQiLCJyZWNy"
        "dWl0bWVudCI6IndyaXRlIn0sImZvIjp0cnVlfQ",
        "dcmevL6pfqgqtU-YYSJSVR1czeqsnBcP1GPCqISrOnE",
    ),
    # create_refresh_token(42, authorization_version=3)
    "refresh": (
        "eyJzdWIiOiI0MiIsInR5cGUiOiJyZWZyZXNoIiwiZXhwIjoxNzk4MTkxMDE1LCJpYXQiOjE3"
        "OTU1OTkwMTUuMTIzNDU2LCJhdiI6M30",
        "t0Ft91WTUAkEUwSCg7qOvEtaybxf0eDYpRYC__-yFJQ",
    ),
    # auth_microsoft._sign_login_state(_browser_binding("legacy-browser-nonce"))
    "sso_login_state": (
        "eyJuIjoic3NvLWxlZ2FjeS1ub25jZS1ubm5ubm5ubm5ubm5ubm4iLCJiYiI6IjNjNzEzYzRi"
        "YjZjYTFkNWMzZGQwMTdmYzllOTZiZWRlY2EzYTlhNzU4N2Q4YjQxZDY5MzAxMzc4ZTBhZmM1"
        "NDkiLCJpYXQiOjE3OTU1OTkwMTUsImV4cCI6MTc5NTU5OTYxNSwicHVycG9zZSI6InNzb19s"
        "b2dpbiJ9",
        "SUcGiaRZ0FrrX7NaAPDfsjJtbDum7Nc_mSl5OBybWYs",
    ),
    # m365.oauth.sign_state(7, nonce="legacy-m365-nonce")
    "m365_state": (
        "eyJzdWIiOiI3IiwibiI6ImxlZ2FjeS1tMzY1LW5vbmNlIiwiaWF0IjoxNzk1NTk5MDE1LCJl"
        "eHAiOjE3OTU1OTk2MTUsInB1cnBvc2UiOiJtMzY1X29hdXRoX3N0YXRlIn0",
        "tptgvjA0eAbRQP0KOe3zWbwIsQOBxWG5vCxDJBKux_I",
    ),
    # jjit_connection.sign_state(7, "legacy-jjit-nonce")
    "jjit_state": (
        "eyJzdWIiOiI3IiwibiI6ImxlZ2FjeS1qaml0LW5vbmNlIiwiaWF0IjoxNzk1NTk5MDE1LCJl"
        "eHAiOjE3OTU1OTk2MTUsInB1cnBvc2UiOiJqaml0X29hdXRoX3N0YXRlIn0",
        "1eGw2d9JPPoYVAUpA_il2cfHEzu7yuVBadC_Km5dL4U",
    ),
    # oauth_token._create_client_token(client_id="legacy-integration",
    #                                  ["candidate:read", "job:read"])
    "oauth_client": (
        "eyJzdWIiOiJsZWdhY3ktaW50ZWdyYXRpb24iLCJ0eXBlIjoiY2xpZW50Iiwic2NvcGUiOiJj"
        "YW5kaWRhdGU6cmVhZCBqb2I6cmVhZCIsImV4cCI6MTc5NTYwMjYxNX0",
        "z6Ty3GRj40315kKWPcbZFag-MN5dMDYhT4m3tGI3ot4",
    ),
    # consent_binding.issue("cv/legacy/zgoda.png", 42, subject(candidate_id=101,
    #                       stage_id=202, client_id=303), check={"verdict": "ok"})
    "cv_consent": (
        "eyJhdWQiOiJuZXh1czpjdi1jb25zZW50OnYxIiwiaWF0IjoxNzk1NTk5MDE1LCJleHAiOjE3"
        "OTU2Mjc4MTUsIm93bmVyIjo0MiwiY29udGV4dCI6eyJtb2RlIjoiY2FuZGlkYXRlIiwiY2Fu"
        "ZGlkYXRlX2lkIjoxMDEsInN0YWdlX2lkIjoyMDIsImNsaWVudF9pZCI6MzAzfSwic3RvcmFn"
        "ZV9rZXkiOiJjdi9sZWdhY3kvemdvZGEucG5nIiwiY2hlY2siOnsidmVyZGljdCI6Im9rIn19",
        "zjzj4ypmFxekKx0XTJnIw-yBCOb7ybJvuKf1-AQkm0w",
    ),
    # actionable_messages.sign_confirmation_token(event_id=11, candidate_id=101)
    "interview_confirmation": (
        "eyJldmVudF9pZCI6MTEsImNhbmRpZGF0ZV9pZCI6MTAxLCJhY3Rpb24iOiJjb25maXJtX2lu"
        "dGVydmlldyIsInB1cnBvc2UiOiJpbnRlcnZpZXdfY29uZmlybWF0aW9uIiwiaWF0IjoxNzk1"
        "NTk5MDE1LCJleHAiOjE3OTYyMDM4MTV9",
        "JZgXuZN2i9BpvpzyjjNYa7Scg2YANEc6zVuP1il_oRU",
    ),
}


def _jose_token(kind: str) -> str:
    claims, signature = _JOSE_TOKENS[kind]
    return ".".join((_HEADER, claims, signature))


@pytest.fixture(autouse=True)
def _legacy_keys_and_clock(monkeypatch):
    """Klucze z chwili wybicia; zegar pół minuty później, w ważności tokenów."""
    monkeypatch.setattr(settings, "SECRET_KEY", _SESSION_KEY)
    monkeypatch.setattr(settings, "M365_STATE_SIGNING_KEY", _STATE_KEY)
    with time_machine.travel(_MINTED_AT + timedelta(seconds=30), tick=False):
        yield


def test_session_tokens_keep_every_claim():
    access = decode_token(_jose_token("access"))
    assert access == {
        "sub": "42",
        "role": "recruiter",
        "type": "access",
        "exp": 1795627815,
        "iat": 1795599015.123456,
        "av": 3,
        "roles": ["recruiter", "delivery_lead"],
        "sa": {"delivery": "read", "recruitment": "write"},
        "fo": True,
    }
    assert decode_token(_jose_token("refresh")) == {
        "sub": "42",
        "type": "refresh",
        "exp": 1798191015,
        "iat": 1795599015.123456,
        "av": 3,
    }
    assert token_authorization_version_matches(access, 3)
    # ``iat`` z mikrosekundami dalej rozstrzyga podłogę unieważnienia (runda 13).
    assert not token_is_revoked(access, _MINTED_AT)
    assert token_is_revoked(access, _MINTED_AT + timedelta(microseconds=1))


def test_session_token_still_needs_the_secret_key(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "x" * 48)
    with pytest.raises(jwt.InvalidSignatureError):
        decode_token(_jose_token("access"))


def test_oauth_login_states_started_before_the_deploy_finish_after_it():
    sso = auth_microsoft._verify_login_state(_jose_token("sso_login_state"))
    assert sso.browser_binding == auth_microsoft._browser_binding(
        "legacy-browser-nonce"
    )
    assert sso.pkce_verifier == auth_microsoft._pkce_verifier_for(
        "sso-legacy-nonce-nnnnnnnnnnnnnnn"
    )

    expires_at = datetime(2026, 11, 25, 9, 40, 15, tzinfo=timezone.utc)
    mailbox = m365_oauth.verify_state(_jose_token("m365_state"))
    assert mailbox.user_id == 7
    assert mailbox.verifier == m365_oauth.pkce_verifier_for("legacy-m365-nonce")
    assert mailbox.expires_at == expires_at

    portal = jjit_connection.verify_state(_jose_token("jjit_state"))
    assert portal.user_id == 7
    assert portal.verifier == jjit_connection.pkce_verifier_for("legacy-jjit-nonce")
    assert portal.expires_at == expires_at


def test_oauth_state_still_needs_the_state_key(monkeypatch):
    monkeypatch.setattr(settings, "M365_STATE_SIGNING_KEY", "x" * 48)
    with pytest.raises(jwt.InvalidSignatureError):
        m365_oauth.verify_state(_jose_token("m365_state"))


class _OneClientDb:
    def __init__(self, client):
        self._client = client

    async def execute(self, _stmt):
        return SimpleNamespace(scalar_one_or_none=lambda: self._client)


async def test_oauth_client_token_passes_require_scope():
    from fastapi.security import HTTPAuthorizationCredentials

    token = _jose_token("oauth_client")
    assert decode_token(token) == {
        "sub": "legacy-integration",
        "type": "client",
        "scope": "candidate:read job:read",
        "exp": 1795602615,
    }
    client = SimpleNamespace(
        client_id="legacy-integration", enabled=True, scopes=["candidate:read"]
    )
    principal = await require_scope(OAuthScope.candidate_read)(
        creds=HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
        db=_OneClientDb(client),
    )
    assert principal.client_id == "legacy-integration"
    assert principal.scopes == ["candidate:read"]


def test_cv_consent_receipt_and_interview_link_still_verify():
    context = consent_binding.subject(candidate_id=101, stage_id=202, client_id=303)
    assert consent_binding.verify(_jose_token("cv_consent"), 42, context) == {
        "storage_key": "cv/legacy/zgoda.png",
        "binding": {
            "version": 1,
            "uploaded_by": 42,
            "subject": context,
            "uploaded_at": 1795599015,
            "check": {"verdict": "ok"},
        },
    }

    payload = actionable_messages.verify_confirmation_token(
        _jose_token("interview_confirmation")
    )
    assert payload["event_id"] == 11
    assert payload["candidate_id"] == 101
    assert payload["action"] == "confirm_interview"
