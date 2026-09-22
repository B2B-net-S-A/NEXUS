"""Załącznik M365, którego pobranie padło, wraca do kolejki (INT-08).

Do 09.2026: błąd LISTOWANIA załączników zwracał pustą listę (mail zapisany,
delta potwierdzona, CV nie powstaje nigdy), a błąd pobrania pojedynczego
pliku zostawiał ``download_failed`` bez żadnego ponowienia — parser wymaga
``storage_path``. Teraz listowanie podnosi wyjątek (kursor delty stoi),
a pętla ``m365_cv_parse`` ponawia pobranie do pięciu razy.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import delete, update

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.m365 import (
    Email,
    EmailAttachment,
    EmailDirection,
    M365Connection,
)
from app.models.user import User, UserRole
from app.services.m365 import attachment_handler
from app.tasks import m365_cv_parse


def test_download_attempts_counter_parses_legacy_and_numbered_errors():
    assert attachment_handler.download_attempts(None) == 0
    assert attachment_handler.download_attempts("size_exceeded: 9 > 1") == 0
    assert attachment_handler.download_attempts("download_failed: boom") == 1
    assert attachment_handler.download_attempts("download_failed[3]: boom") == 3

    row = SimpleNamespace(parse_error="download_failed: boom")
    attachment_handler.mark_download_failed(row, RuntimeError("again"))
    assert row.parse_error.startswith("download_failed[2]: ")


@pytest.mark.asyncio
async def test_listing_failure_is_raised_not_swallowed():
    class _Gc:
        async def get(self, url: str, params: Any = None) -> Any:
            raise RuntimeError("Graph 503")

    email = SimpleNamespace(has_attachments=True, m365_message_id="m-1", id=1)
    with pytest.raises(RuntimeError):
        await attachment_handler.download_for_email(None, _Gc(), email)


@pytest.mark.asyncio
async def test_sync_counts_attachment_listing_failure_as_message_error(monkeypatch):
    """Błąd listowania = błąd wiadomości → kursor delty NIE jest zapisany."""
    from app.services.m365 import sync as sync_mod

    async def _upsert(db, gc, conn, msg, folder):  # noqa: ANN001 — atrapa
        await attachment_handler.download_for_email(
            db, gc, SimpleNamespace(has_attachments=True, m365_message_id="m", id=1)
        )

    class _Gc:
        async def paginate(self, url, params=None):  # noqa: ANN001
            yield {
                "value": [{"id": "m"}],
                "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/messages/delta?$deltatoken=z",
            }

        async def get(self, url: str, params: Any = None) -> Any:
            raise RuntimeError("Graph 503")

    class _Db:
        async def commit(self) -> None:
            return None

    monkeypatch.setattr(sync_mod, "_upsert_message", _upsert)
    conn = SimpleNamespace(
        id=1,
        user_id=1,
        delta_token_inbox=None,
        delta_reset_count=0,
        delta_last_reset_at=None,
    )
    result = sync_mod.SyncResult(connection_id=1)
    await sync_mod._sync_messages_for_folder(
        _Db(),
        _Gc(),
        conn,
        result,
        folder="inbox",
        cursor_attr="delta_token_inbox",
        is_backfill=True,
    )
    assert result.errors == 1
    assert conn.delta_token_inbox is None


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(attachment_handler, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(attachment_handler, "M365_ROOT", tmp_path / "microsoft365")
    monkeypatch.setattr(m365_cv_parse.settings, "M365_INTEGRATION_ENABLED", True)
    return tmp_path


async def _seed(parse_error: str) -> SimpleNamespace:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"att-retry-{suffix}@example.com",
            password_hash=hash_password("P@ss"),
            name="Att Retry",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(user)
        await db.flush()
        conn = M365Connection(
            user_id=user.id,
            tenant_id="t",
            mailbox_upn=f"att-retry-{suffix}@example.com",
            access_token_ct="x",
            refresh_token_ct="x",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        email = Email(
            user_id=user.id,
            m365_message_id=f"msg-{suffix}",
            m365_conversation_id="c",
            from_address="kandydat@example.com",
            received_at=datetime.now(timezone.utc),
            direction=EmailDirection.received,
            has_attachments=True,
        )
        db.add_all([conn, email])
        await db.flush()
        att = EmailAttachment(
            email_id=email.id,
            m365_attachment_id=f"att-{suffix}",
            filename="Jan_Kowalski_CV.pdf",
            content_type="application/pdf",
            size_bytes=3,
            is_cv_candidate=True,
            parse_error=parse_error,
        )
        db.add(att)
        await db.flush()
        # Przerwa między próbami liczona od updated_at — cofamy ją w czasie.
        await db.execute(
            update(EmailAttachment)
            .where(EmailAttachment.id == att.id)
            .values(updated_at=datetime.now(timezone.utc) - timedelta(hours=1))
        )
        await db.commit()
        return SimpleNamespace(user_id=user.id, attachment_id=att.id)


async def _cleanup(ids: SimpleNamespace) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Email).where(Email.user_id == ids.user_id))
        await db.execute(
            delete(M365Connection).where(M365Connection.user_id == ids.user_id)
        )
        await db.execute(delete(User).where(User.id == ids.user_id))
        await db.commit()


def _fake_graph(content: bytes | None):
    class _Gc:
        def __init__(self, connection: Any, db: Any) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        async def download(self, url: str) -> bytes:
            if content is None:
                raise RuntimeError("Graph 504")
            return content

    return _Gc


async def _retry_until(attachment_id: int) -> EmailAttachment:
    # Wspólna baza testów może mieć inne wiersze do ponowienia — przechodzimy,
    # aż nasz zostanie obsłużony (każdy bieg bierze jeden wiersz).
    for _ in range(20):
        async with AsyncSessionLocal() as db:
            row = await db.get(EmailAttachment, attachment_id)
            if row.updated_at > datetime.now(timezone.utc) - timedelta(minutes=5):
                return row
        if not await m365_cv_parse.run_m365_attachment_retry_once():
            break
    async with AsyncSessionLocal() as db:
        return await db.get(EmailAttachment, attachment_id)


@pytest.mark.asyncio
async def test_failed_download_is_retried_and_cleared(storage, monkeypatch):
    ids = await _seed("download_failed: ReadTimeout('x')")
    try:
        monkeypatch.setattr(m365_cv_parse, "GraphClient", _fake_graph(b"pdf"))
        row = await _retry_until(ids.attachment_id)
        assert row.storage_path, "pobranie nie zostało ponowione"
        assert row.parse_error is None, "parser CV czeka na wiersz bez błędu"
        assert row.sha256
        assert (storage / row.storage_path).read_bytes() == b"pdf"
    finally:
        await _cleanup(ids)


@pytest.mark.asyncio
async def test_retry_failure_bumps_counter(storage, monkeypatch):
    ids = await _seed("download_failed[2]: x")
    try:
        monkeypatch.setattr(m365_cv_parse, "GraphClient", _fake_graph(None))
        row = await _retry_until(ids.attachment_id)
        assert row.storage_path is None
        assert row.parse_error.startswith("download_failed[3]: ")
    finally:
        await _cleanup(ids)


@pytest.mark.asyncio
async def test_fifth_failure_is_final(storage, monkeypatch):
    ids = await _seed("download_failed[5]: x")
    try:
        called = []

        class _Gc:
            def __init__(self, *a: Any) -> None:
                called.append(1)

        monkeypatch.setattr(m365_cv_parse, "GraphClient", _Gc)
        for _ in range(5):
            if not await m365_cv_parse.run_m365_attachment_retry_once():
                break
        async with AsyncSessionLocal() as db:
            row = await db.get(EmailAttachment, ids.attachment_id)
        assert row.parse_error == "download_failed[5]: x"
    finally:
        await _cleanup(ids)
