"""Publiczny wypis z komunikatów informacyjnych (O12).

Link z maila niesie losowy token; w bazie leży tylko jego SHA-256. Zły token
i każdy inny błąd = to samo 404 z tym samym zdaniem, odpowiedź bez danych
osobowych. GET niczego nie zmienia (skanery linków w poczcie otwierają
adresy same), wypis to POST. Trasy mają limiter, a moduł — bez
``from __future__ import annotations`` (ciało żądania lądowałoby w query).
Dane fikcyjne.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import re
import secrets
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.care_announcement import (
    CareAnnouncement,
    CareAnnouncementOptOut,
    CareAnnouncementRecipient,
)
from app.models.user import UserRole
from tests.care_announcements_seed import (  # noqa: F401  (fixture'y)
    announcement_routes,
    make_client,
    make_consultant,
    make_user,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("announcement_routes")]

PUBLIC = "/api/public/consultant-mail/unsubscribe"
_BACKEND = Path(__file__).resolve().parents[1]


async def _recipient_with_token() -> tuple[str, int, int]:
    author = await make_user(UserRole.talent_community_manager)
    client_id = await make_client()
    contract_id, candidate_id = await make_consultant(client_id)
    token = secrets.token_urlsafe(32)
    async with AsyncSessionLocal() as db:
        announcement = CareAnnouncement(
            code="ZX12",
            kind="informational",
            status="sent",
            subject="Spotkanie konsultantów",
            body="Cześć {imię}",
            audience={"group": "all"},
            created_by=author.id,
            queued_at=author.created_at,
        )
        db.add(announcement)
        await db.flush()
        recipient = CareAnnouncementRecipient(
            announcement_id=announcement.id,
            candidate_id=candidate_id,
            contract_id=contract_id,
            client_id=client_id,
            email="konsultant@example.com",
            first_name="Anna",
            status="sent",
            sent_at=author.created_at,
            unsubscribe_token_sha256=hashlib.sha256(token.encode()).hexdigest(),
        )
        db.add(recipient)
        await db.commit()
        return token, candidate_id, recipient.id


async def test_get_shows_state_without_personal_data_and_changes_nothing(
    app_client,
) -> None:
    token, candidate_id, _ = await _recipient_with_token()
    response = await app_client.get(f"{PUBLIC}/{token}")
    assert response.status_code == 200, response.text
    assert response.json() == {"unsubscribed": False}
    async with AsyncSessionLocal() as db:
        assert await db.get(CareAnnouncementOptOut, candidate_id) is None


async def test_post_unsubscribes_once_and_marks_the_recipient(app_client) -> None:
    token, candidate_id, recipient_id = await _recipient_with_token()
    first = await app_client.post(f"{PUBLIC}/{token}")
    assert first.status_code == 200, first.text
    assert first.json() == {"unsubscribed": True}
    again = await app_client.post(f"{PUBLIC}/{token}")
    assert again.status_code == 200
    async with AsyncSessionLocal() as db:
        opt_out = await db.get(CareAnnouncementOptOut, candidate_id)
        assert opt_out is not None and opt_out.recipient_id == recipient_id
        recipient = await db.get(CareAnnouncementRecipient, recipient_id)
        assert recipient.unsubscribed_at is not None
    state = await app_client.get(f"{PUBLIC}/{token}")
    assert state.json() == {"unsubscribed": True}


async def test_bad_tokens_get_the_same_404(app_client) -> None:
    for token in ("x", secrets.token_urlsafe(32), "a" * 500):
        for method in ("get", "post"):
            response = await getattr(app_client, method)(f"{PUBLIC}/{token}")
            assert response.status_code == 404, (method, token)
            assert response.json()["detail"] == "Link nieprawidłowy lub wygasły."


async def test_raw_token_never_lands_in_the_database(app_client) -> None:
    token, _, recipient_id = await _recipient_with_token()
    await app_client.post(f"{PUBLIC}/{token}")
    async with AsyncSessionLocal() as db:
        stored = await db.scalar(
            select(CareAnnouncementRecipient.unsubscribe_token_sha256).where(
                CareAnnouncementRecipient.id == recipient_id
            )
        )
    assert stored != token and len(stored) == 64


def test_public_routes_have_rate_limits_and_no_future_annotations() -> None:
    from app.api import public_consultant_mail as module

    source = (_BACKEND / "app" / "api" / "public_consultant_mail.py").read_text(
        encoding="utf-8"
    )
    futures = [
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.ImportFrom) and node.module == "__future__"
    ]
    assert futures == []
    for name in ("unsubscribe_state", "unsubscribe"):
        handler_source = inspect.getsource(getattr(module, name))
        assert re.search(r"@limiter\.limit\(", handler_source), name
        assert re.search(r"@limiter\.shared_limit\(", handler_source), name
