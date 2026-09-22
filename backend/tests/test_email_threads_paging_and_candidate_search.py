"""FE-08/FE-09: lista wątków ze stronicowaniem i wyszukiwanie zawężone do kandydata.

* FE-08 — wyszukiwarka w profilu kandydata A pokazywała maile kandydata B,
  a kliknięcie takiego wyniku otwierało pusty wątek. ``candidate_id`` zawęża
  trafienia do maili tego kandydata.
* FE-09 — lista wątków urywała się na 50 bez informacji o reszcie. Teraz ma
  ``offset`` i ``total``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus
from app.models.m365 import Email
from app.models.user import User


async def _admin_id(app_client: AsyncClient) -> int:
    admin_email = app_client.headers.get("X-Test-Admin-Email")
    assert admin_email
    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == admin_email))
        assert user is not None
        return user.id


async def _candidate() -> int:
    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Mail",
            lastname=f"Paging-{uuid.uuid4().hex[:6]}",
            email=f"mail-{uuid.uuid4().hex[:8]}@example.com",
            status=CandidateStatus.active,
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _email(
    *,
    user_id: int,
    candidate_id: int | None,
    subject: str,
    body: str,
    received_at: datetime,
) -> int:
    suffix = uuid.uuid4().hex[:12]
    async with AsyncSessionLocal() as db:
        row = Email(
            user_id=user_id,
            candidate_id=candidate_id,
            m365_message_id=f"msg-{suffix}",
            m365_conversation_id=f"conv-{suffix}",
            subject=subject,
            from_address="sender@example.com",
            body_text=body,
            body_html=f"<p>{body}</p>",
            body_preview=body[:100],
            received_at=received_at,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


async def _cleanup(ids: list[int], candidate_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Email).where(Email.id.in_(ids)))
        await db.execute(delete(Candidate).where(Candidate.id.in_(candidate_ids)))
        await db.commit()


async def test_search_is_scoped_to_candidate_when_requested(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    user_id = await _admin_id(app_client)
    cand_a = await _candidate()
    cand_b = await _candidate()
    token = f"zzq{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc)
    ids = [
        await _email(
            user_id=user_id,
            candidate_id=cand_a,
            subject=f"Rozmowa {token}",
            body=f"Treść {token} kandydata A",
            received_at=now,
        ),
        await _email(
            user_id=user_id,
            candidate_id=cand_b,
            subject=f"Rozmowa {token}",
            body=f"Treść {token} kandydata B",
            received_at=now,
        ),
    ]
    try:
        unscoped = await app_client.get(
            "/api/microsoft365/emails/search",
            params={"q": token},
            headers=app_auth_headers,
        )
        assert unscoped.status_code == 200, unscoped.text
        assert {h["candidate_id"] for h in unscoped.json()["items"]} == {
            cand_a,
            cand_b,
        }

        scoped = await app_client.get(
            "/api/microsoft365/emails/search",
            params={"q": token, "candidate_id": cand_a},
            headers=app_auth_headers,
        )
        assert scoped.status_code == 200, scoped.text
        body = scoped.json()
        assert body["total"] == 1
        assert [h["candidate_id"] for h in body["items"]] == [cand_a]
    finally:
        await _cleanup(ids, [cand_a, cand_b])


async def test_thread_list_pages_with_total(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    user_id = await _admin_id(app_client)
    cand = await _candidate()
    base = datetime.now(timezone.utc)
    ids = [
        await _email(
            user_id=user_id,
            candidate_id=cand,
            subject=f"Wątek {i}",
            body="treść",
            received_at=base - timedelta(minutes=i),
        )
        for i in range(5)
    ]
    try:
        first = await app_client.get(
            f"/api/candidates/{cand}/emails",
            params={"limit": 2, "offset": 0},
            headers=app_auth_headers,
        )
        assert first.status_code == 200, first.text
        page1 = first.json()
        assert page1["total"] == 5
        assert [t["subject"] for t in page1["items"]] == ["Wątek 0", "Wątek 1"]

        last = await app_client.get(
            f"/api/candidates/{cand}/emails",
            params={"limit": 2, "offset": 4},
            headers=app_auth_headers,
        )
        assert last.status_code == 200, last.text
        page3 = last.json()
        assert page3["total"] == 5
        assert [t["subject"] for t in page3["items"]] == ["Wątek 4"]
    finally:
        await _cleanup(ids, [cand])
