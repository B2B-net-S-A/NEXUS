"""Runda 12 audytu — obszar BACK (status requestu, zmiana hasła).

Bez bazy: kształt wyrażeń SQL i podłoga unieważnienia tokenów. Ścieżki
z bazą są w ``test_audit_r11_pipe.py``, ``test_job_similar_links.py``,
``test_session_revocation.py`` i ``test_password_reset.py``.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from types import SimpleNamespace

import app.models  # noqa: F401  (register every mapper)
import pytest
from jose import jwt
from sqlalchemy.dialects import postgresql


def _champion_branch(expr) -> str:
    compiled = str(
        expr.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    # Warunek gałęzi „champion” = tekst między poprzednim WHEN a THEN 'champion'.
    head = compiled.split("THEN 'champion'")[0]
    return head.rsplit("WHEN", 1)[1].strip()


# ── BACK-1: „Mamy championa” tylko przy „Szukamy” — status = pigułka stanu ──


def test_request_status_champion_branch_equals_request_stage() -> None:
    from app.services import job_similarity as sim

    sq = sim.request_status_subquery([1])
    status_branch = _champion_branch(sim.request_status_expr(sq))
    stage_branch = _champion_branch(sim.request_stage_expr(sq))
    assert status_branch == stage_branch
    assert "jobs.work_state = 'searching'" in status_branch
    assert "NOT IN" not in status_branch


# ── BACK-2: zmiana hasła oddaje nową sesję zamiast wylogowywać ──────────────


def test_change_password_returns_token_pair_minted_after_floor() -> None:
    from app.api import auth

    route = next(
        r
        for r in auth.router.routes
        if getattr(r, "path", "").endswith("/change-password")
    )
    assert route.response_model is auth.TokenResponse
    assert route.status_code in (None, 200)

    source = inspect.getsource(auth.change_password)
    floor_at = source.index("tokens_valid_after = datetime.now(timezone.utc)")
    assert "func.now()" not in source.split("tokens_valid_after")[1][:40]
    # Tokeny wybijane PO podłodze i bez ``fpc``.
    assert source.index("create_access_token(") > floor_at
    assert "force_password_change=False" in source


def test_token_minted_after_python_floor_is_not_revoked() -> None:
    from app.core.config import settings
    from app.core.security import create_access_token, token_is_revoked

    floor = datetime.now(timezone.utc)
    token = create_access_token(1, "recruiter")
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    assert "fpc" not in payload
    assert not token_is_revoked(payload, floor)


class _FakeDb:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_change_password_success_gives_current_session_fresh_tokens(
    monkeypatch,
) -> None:
    from app.api import auth
    from app.core.config import settings
    from app.core.security import hash_password, token_is_revoked
    from app.models.user import UserRole

    async def _no_sections(_db, user):
        user.effective_section_access = {}

    monkeypatch.setattr(auth, "resolve_effective_section_access", _no_sections)
    monkeypatch.setattr(auth, "send_password_changed_notification", lambda **_: None)

    user = SimpleNamespace(
        id=42,
        email="r12-back@example.com",
        name="R12",
        role=UserRole.recruiter,
        password_hash=hash_password("stare-haslo-123"),
        force_password_change=True,
        force_password_change_at=datetime.now(timezone.utc),
        tokens_valid_after=None,
        authorization_version=3,
        effective_section_access=None,
        get_all_roles=lambda: [UserRole.recruiter],
    )
    handler = inspect.unwrap(auth.change_password)
    result = await handler(
        request=SimpleNamespace(client=None),
        data=auth.ChangePasswordRequest(
            current_password="stare-haslo-123", new_password="nowe-haslo-456"
        ),
        current_user=user,
        db=_FakeDb(),
    )

    assert user.force_password_change is False
    assert isinstance(user.tokens_valid_after, datetime)
    access = jwt.decode(result.access_token, settings.SECRET_KEY, algorithms=["HS256"])
    refresh = jwt.decode(
        result.refresh_token, settings.SECRET_KEY, algorithms=["HS256"]
    )
    assert access["sub"] == "42" and refresh["type"] == "refresh"
    assert "fpc" not in access
    assert access["av"] == 3 and refresh["av"] == 3
    # Nowa para przeżywa podłogę, którą ta sama zmiana postawiła.
    assert not token_is_revoked(access, user.tokens_valid_after)
    assert not token_is_revoked(refresh, user.tokens_valid_after)
