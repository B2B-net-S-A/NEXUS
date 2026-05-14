"""Integration tests for GET /api/microsoft365/emails/search (Phase 4.4).

Exercises:
- FTS happy path: query matches subject / body / sender.
- ts_headline output contains <mark>...</mark> wrappers.
- Multi-tenant isolation: another user's rows are not returned.
- Limit clamping (>100 → 422 from Query validator).
- Min q length (q="a" → 422).

Runs in CI against the postgres service container after `alembic upgrade heads`,
which creates the generated `search_vector` column from migration 0103.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.m365 import Email
from app.models.user import User, UserRole


def _utc(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, 0, 0, tzinfo=timezone.utc)


async def _create_user(email: str, name: str = "Other User") -> User:
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password("not-used-T3st_PassX!"),
            name=name,
            role=UserRole.admin,
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u


async def _get_user_id(email: str) -> int:
    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None, f"user {email} not seeded"
        return user.id


async def _seed_email(
    *,
    user_id: int,
    msg_id: str,
    conv_id: str,
    subject: str,
    body_text: str,
    from_address: str,
    from_name: str | None = None,
    received_at: datetime | None = None,
) -> int:
    async with AsyncSessionLocal() as db:
        email = Email(
            user_id=user_id,
            m365_message_id=msg_id,
            m365_conversation_id=conv_id,
            subject=subject,
            from_address=from_address,
            from_name=from_name,
            body_text=body_text,
            body_html=f"<p>{body_text}</p>",
            body_preview=body_text[:200],
            received_at=received_at or _utc(2026, 5, 14),
        )
        db.add(email)
        await db.commit()
        await db.refresh(email)
        return email.id


@pytest_asyncio.fixture
async def seeded_emails(app_client: AsyncClient):
    """Seed three emails for the test admin plus one for a stranger.

    Yields a dict with the email ids so tests can assert membership without
    relying on row order. Tears down both sets at the end.
    """
    admin_email = app_client.headers.get("X-Test-Admin-Email")
    assert admin_email, "admin not seeded by app_client fixture"
    admin_user_id = await _get_user_id(admin_email)

    stranger_email = f"pytest-stranger-{uuid.uuid4().hex[:8]}@example.com"
    stranger = await _create_user(stranger_email, "Stranger")

    prefix = uuid.uuid4().hex[:8]
    own = {
        "match_subject": await _seed_email(
            user_id=admin_user_id,
            msg_id=f"msg-{prefix}-1",
            conv_id=f"conv-{prefix}-1",
            subject="Pilna rozmowa rekrutacyjna w piątek",
            body_text="Cześć, wracam z propozycją na poniedziałek.",
            from_address="recruiter@b2bnet.pl",
            from_name="Anna Nowak",
        ),
        "match_body": await _seed_email(
            user_id=admin_user_id,
            msg_id=f"msg-{prefix}-2",
            conv_id=f"conv-{prefix}-2",
            subject="Zaproszenie",
            body_text=(
                "Witam, czy moglibyśmy umówić rozmowę rekrutacyjna "
                "na środę? Pasuje Panu termin?"
            ),
            from_address="hr@example.com",
            from_name="Kasia Kowalska",
            received_at=_utc(2026, 5, 13),
        ),
        "no_match": await _seed_email(
            user_id=admin_user_id,
            msg_id=f"msg-{prefix}-3",
            conv_id=f"conv-{prefix}-3",
            subject="Newsletter tygodniowy",
            body_text="Najnowsze trendy w branży IT.",
            from_address="news@example.com",
        ),
    }

    stranger_email_id = await _seed_email(
        user_id=stranger.id,
        msg_id=f"msg-{prefix}-stranger",
        conv_id=f"conv-{prefix}-stranger",
        subject="rekrutacyjna oferta specjalna",
        body_text="To nie powinno trafić do admina.",
        from_address="stranger@example.com",
    )

    yield {"own": own, "stranger": stranger_email_id, "stranger_user_id": stranger.id}

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(Email).where(
                Email.id.in_([*own.values(), stranger_email_id]),
            )
        )
        await db.execute(delete(User).where(User.id == stranger.id))
        await db.commit()


async def test_search_requires_auth(app_client: AsyncClient):
    r = await app_client.get("/api/microsoft365/emails/search?q=foo")
    assert r.status_code in (401, 403)


async def test_search_min_q_length(app_client: AsyncClient, app_auth_headers: dict):
    r = await app_client.get(
        "/api/microsoft365/emails/search?q=a", headers=app_auth_headers
    )
    assert r.status_code == 422


async def test_search_rejects_oversized_limit(
    app_client: AsyncClient, app_auth_headers: dict
):
    r = await app_client.get(
        "/api/microsoft365/emails/search?q=test&limit=200",
        headers=app_auth_headers,
    )
    assert r.status_code == 422


async def test_search_matches_subject_and_body(
    app_client: AsyncClient,
    app_auth_headers: dict,
    seeded_emails: dict,
):
    """`rekrutacyjna` is in two of the admin's mails — subject and body."""
    r = await app_client.get(
        "/api/microsoft365/emails/search?q=rekrutacyjna",
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {hit["id"] for hit in body["items"]}
    assert seeded_emails["own"]["match_subject"] in ids
    assert seeded_emails["own"]["match_body"] in ids
    assert seeded_emails["own"]["no_match"] not in ids
    # Multi-tenant: stranger's row must not leak.
    assert seeded_emails["stranger"] not in ids


async def test_search_snippet_has_mark_wrapper(
    app_client: AsyncClient,
    app_auth_headers: dict,
    seeded_emails: dict,
):
    r = await app_client.get(
        "/api/microsoft365/emails/search?q=rozmow%C4%99",
        headers=app_auth_headers,
    )
    assert r.status_code == 200
    items = r.json()["items"]
    body_hit = next(
        (h for h in items if h["id"] == seeded_emails["own"]["match_body"]),
        None,
    )
    assert body_hit is not None, items
    snippet = body_hit["snippet"] or ""
    assert "<mark>" in snippet and "</mark>" in snippet


async def test_search_pagination_total_consistent(
    app_client: AsyncClient,
    app_auth_headers: dict,
    seeded_emails: dict,
):
    """Total count from window aggregate equals match count, irrespective of
    offset/limit slicing."""
    full = await app_client.get(
        "/api/microsoft365/emails/search?q=rekrutacyjna",
        headers=app_auth_headers,
    )
    paged = await app_client.get(
        "/api/microsoft365/emails/search?q=rekrutacyjna&limit=1&offset=0",
        headers=app_auth_headers,
    )
    assert full.status_code == 200 and paged.status_code == 200
    assert full.json()["total"] == paged.json()["total"]
    assert len(paged.json()["items"]) == 1


async def test_search_no_results(
    app_client: AsyncClient, app_auth_headers: dict, seeded_emails: dict
):
    r = await app_client.get(
        "/api/microsoft365/emails/search?q=xyzqwertyunlikelyword",
        headers=app_auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0
