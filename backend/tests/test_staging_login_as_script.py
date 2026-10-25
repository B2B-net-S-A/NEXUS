"""``scripts/staging_login_as.py`` — „Zaloguj jako” tylko na stagingu.

Skrypt wydaje token dowolnej osoby bez hasła, więc jedyną rzeczą, która
dzieli go od przejęcia konta na produkcji, jest odmowa przy
``NEXUS_ENV != staging``. Testy bez bazy: bramka środowiska i claimy tokenu
zgodne z ``POST /api/auth/login``.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.core.security import decode_token
from app.models.user import User, UserRole
from scripts import staging_login_as


@pytest.mark.parametrize("env", ["production", "development"])
def test_refuses_outside_staging(monkeypatch, capsys, env):
    monkeypatch.setattr(settings, "NEXUS_ENV", env)

    def _no_db(*_args, **_kwargs):
        raise AssertionError("poza stagingiem skrypt nie może dotknąć bazy")

    monkeypatch.setattr(staging_login_as, "_token", _no_db)
    monkeypatch.setattr(staging_login_as, "_list_role", _no_db)

    assert (
        staging_login_as.main(["--user-id", "1"]) == staging_login_as.EXIT_NOT_STAGING
    )
    assert (
        staging_login_as.main(["--role", "recruiter"])
        == staging_login_as.EXIT_NOT_STAGING
    )
    assert "wyłącznie na stagingu" in capsys.readouterr().err


def test_token_claims_match_password_login():
    user = User(
        id=42,
        email="dl@example.test",
        name="Test",
        role=UserRole.delivery_lead,
        roles=["recruiter"],
        authorization_version=7,
        force_password_change=False,
        is_active=True,
    )
    user.effective_section_access = {}

    payload = decode_token(staging_login_as.access_token_for(user))

    assert payload["sub"] == "42"
    assert payload["role"] == "delivery_lead"
    assert set(payload["roles"]) == {"delivery_lead", "recruiter"}
    assert payload["av"] == 7
    assert payload["type"] == "access"
