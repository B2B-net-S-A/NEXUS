"""Kod błędu synchronizacji M365 dla karty w Ustawieniach (UAT B61)."""

import pytest

from app.services.m365.error_codes import classify_m365_error

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("text", "code"),
    [
        (None, None),
        ("", None),
        ("GraphRequestError(\"Graph 503: 'retry_after cap exceeded (4x)'\")", "graph_throttled"),
        ("GraphRequestError('Graph 429: too many requests')", "graph_throttled"),
        ("M365ReauthRequired('refresh token invalid')", "reauth_required"),
        ("refresh token invalid — user must reconnect", "reauth_required"),
        ("token_cipher_unreadable_user_must_reconnect", "reauth_required"),
        ("timeout after 900s", "timeout"),
        ("3 błędów importu — kursor folderów z błędami nie przesunięty.", "import_errors"),
        ("Delta cursor for inbox invalidated 3× in 24h — manual intervention required.", "delta_reset"),
        ("KeyError('id')", "unknown"),
    ],
)
def test_classify_m365_error(text, code):
    assert classify_m365_error(text) == code
