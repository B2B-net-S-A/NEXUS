"""Jednorazowość wysyłki maila z NEXUSA (INT-04/05/07, audyt 22.09.2026).

Na żywej bazie, z atrapą Graph:
 * równoległe wysyłki z tym samym ``client_request_id`` → jeden mail;
 * ponowienie po sukcesie zwraca zapisany wiersz bez wywołania Graph;
 * inna treść w tej samej minucie (bez ``client_request_id``) to druga
   wiadomość (INT-05 — dawniej po cichu gubiona);
 * utracona odpowiedź na ``/send`` zostawia wiersz ``uncertain`` i ponowienie
   NIE wysyła drugi raz;
 * jednoznaczna odmowa Graph (4xx) zwalnia rezerwację;
 * odpowiedź zapisuje ``internetMessageId``;
 * compose do nieistniejącego kandydata = 404 bez żadnego wywołania Graph.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate, CandidateStatus
from app.models.m365 import Email, EmailDirection, M365Connection
from app.models.user import User, UserRole
from app.services.m365 import sender as sender_mod
from app.services.m365.graph_client import GraphRequestError


class _Graph:
    """Wspólny rejestr wywołań atrapy Graph dla jednego testu."""

    def __init__(self) -> None:
        self.posts: list[str] = []
        self.sends = 0
        self.draft_gate: asyncio.Event | None = None
        self.fail_send: BaseException | None = None
        self.fail_draft: BaseException | None = None
        self.draft_body: dict | None = None
        self.patches: list[Any] = []
        self._n = 0

    def factory(self):
        graph = self

        class _Client:
            def __init__(self, connection: Any, db: Any) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc: Any) -> None:
                return None

            async def get(self, url: str, params: Any = None) -> Any:
                return {"value": []}

            async def patch(self, url: str, json: Any = None) -> Any:
                graph.patches.append(json)
                return {}

            async def post(self, url: str, json: Any = None, **_kw: Any) -> Any:
                graph.posts.append(url)
                if url.endswith("/send"):
                    if graph.fail_send is not None:
                        raise graph.fail_send
                    graph.sends += 1
                    return {}
                # Szkic (nowa wiadomość albo createReply).
                if graph.fail_draft is not None:
                    raise graph.fail_draft
                if graph.draft_gate is not None:
                    await graph.draft_gate.wait()
                graph._n += 1
                token = uuid.uuid4().hex[:10]
                draft = {
                    "id": f"draft-{token}",
                    "conversationId": f"conv-{token}",
                    "internetMessageId": f"<{token}@nexus.test>",
                }
                if graph.draft_body is not None and url.endswith("/createReply"):
                    draft["body"] = graph.draft_body
                return draft

        return _Client


@pytest_asyncio.fixture
async def mailbox(monkeypatch):
    monkeypatch.setattr(sender_mod.settings, "M365_SIGNATURE_INJECTION_ENABLED", False)

    async def _eligible(db, connection):  # noqa: ANN001 — atrapa bramki roli
        return None

    monkeypatch.setattr(sender_mod, "require_eligible_connection_owner", _eligible)
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"send-once-{suffix}@example.com",
            password_hash=hash_password("P@ss"),
            name="Send Once",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(user)
        await db.flush()
        candidate = Candidate(
            name="Anna",
            lastname=f"Wysylka{suffix}",
            email=f"cand-{suffix}@example.com",
            status=CandidateStatus.active,
        )
        db.add(candidate)
        await db.flush()
        conn = M365Connection(
            user_id=user.id,
            tenant_id="tenant",
            mailbox_upn=f"send-once-{suffix}@example.com",
            access_token_ct="x",
            refresh_token_ct="x",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(conn)
        await db.commit()
        ids = SimpleNamespace(
            user_id=user.id, candidate_id=candidate.id, connection_id=conn.id
        )
    graph = _Graph()
    monkeypatch.setattr(sender_mod, "GraphClient", graph.factory())
    yield ids, graph
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Email).where(Email.user_id == ids.user_id))
        await db.execute(
            delete(M365Connection).where(M365Connection.id == ids.connection_id)
        )
        await db.execute(delete(Candidate).where(Candidate.id == ids.candidate_id))
        await db.execute(delete(User).where(User.id == ids.user_id))
        await db.commit()


async def _send(ids, *, request_id=None, body="<p>Treść</p>", subject="Temat"):
    async with AsyncSessionLocal() as db:
        conn = await db.get(M365Connection, ids.connection_id)
        row = await sender_mod.send_new(
            db,
            conn,
            to=["kandydat@example.com"],
            subject=subject,
            body_html=body,
            candidate_id=ids.candidate_id,
            client_request_id=request_id,
            commit_reservation=True,
        )
        await db.commit()
        return row.id, row.send_state


async def _rows(user_id: int) -> list[Email]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Email).where(Email.user_id == user_id).order_by(Email.id)
                )
            ).all()
        )


@pytest.mark.asyncio
async def test_parallel_sends_with_one_request_id_send_one_mail(mailbox):
    ids, graph = mailbox
    graph.draft_gate = asyncio.Event()
    request_id = str(uuid.uuid4())

    first = asyncio.create_task(_send(ids, request_id=request_id))
    # Pierwsze żądanie zarezerwowało wiersz i czeka na szkic w Graph.
    for _ in range(100):
        if graph.posts:
            break
        await asyncio.sleep(0.02)
    with pytest.raises(sender_mod.EmailSendConflict) as info:
        await _send(ids, request_id=request_id)
    assert info.value.state == "pending"
    graph.draft_gate.set()
    email_id, state = await first

    assert graph.sends == 1, "równoległe żądanie wysłało drugi mail"
    assert state == "sent"
    rows = await _rows(ids.user_id)
    assert [r.id for r in rows] == [email_id]
    assert rows[0].m365_message_id.startswith("draft-")
    assert rows[0].m365_internet_message_id


@pytest.mark.asyncio
async def test_retry_after_success_returns_row_without_graph(mailbox):
    ids, graph = mailbox
    request_id = str(uuid.uuid4())
    first_id, _ = await _send(ids, request_id=request_id)
    calls = len(graph.posts)
    again_id, state = await _send(ids, request_id=request_id)
    assert again_id == first_id
    assert state == "sent"
    assert len(graph.posts) == calls, "ponowienie wywołało Graph"


@pytest.mark.asyncio
async def test_different_body_same_minute_is_a_second_message(mailbox):
    ids, graph = mailbox
    await _send(ids, body="<p>Pierwsza treść</p>")
    await _send(ids, body="<p>Ważna korekta treści</p>")
    assert graph.sends == 2
    assert len(await _rows(ids.user_id)) == 2


@pytest.mark.asyncio
async def test_corrected_body_with_same_request_id_is_sent(mailbox):
    """FIX-06: ten sam UUID formularza, ale poprawiona treść → nowa wysyłka."""
    ids, graph = mailbox
    request_id = str(uuid.uuid4())
    first_id, _ = await _send(ids, request_id=request_id, body="<p>Wersja 1</p>")
    second_id, state = await _send(
        ids, request_id=request_id, body="<p>Wersja 2 — poprawiona</p>"
    )
    assert second_id != first_id, "poprawiona treść po cichu nie wyszła"
    assert state == "sent"
    assert graph.sends == 2
    # Ta sama treść z tym samym UUID nadal jest ponowieniem.
    again_id, _ = await _send(
        ids, request_id=request_id, body="<p>Wersja 2 — poprawiona</p>"
    )
    assert again_id == second_id
    assert graph.sends == 2


def test_request_key_depends_on_content_fingerprint():
    fp1 = sender_mod.content_fingerprint(
        subject="S", to=["A@x.pl"], cc=[], body_html="<p>1</p>"
    )
    fp2 = sender_mod.content_fingerprint(
        subject="S", to=["a@x.pl"], cc=[], body_html="<p>2</p>"
    )
    same = sender_mod.content_fingerprint(
        subject="S ", to=["a@x.pl"], cc=[], body_html="<p>1</p>"
    )
    assert fp1 == same
    k1 = sender_mod.request_key(user_id=1, client_request_id="u", content_sha=fp1)
    k2 = sender_mod.request_key(user_id=1, client_request_id="u", content_sha=fp2)
    assert k1 != k2


@pytest.mark.asyncio
async def test_lost_send_response_leaves_uncertain_row_and_blocks_resend(mailbox):
    ids, graph = mailbox
    graph.fail_send = httpx.ReadTimeout("lost")
    request_id = str(uuid.uuid4())
    with pytest.raises(sender_mod.EmailSendConflict) as info:
        await _send(ids, request_id=request_id)
    assert info.value.first_attempt is True

    rows = await _rows(ids.user_id)
    assert len(rows) == 1
    assert rows[0].send_state == "uncertain"
    assert rows[0].m365_message_id.startswith("draft-")

    graph.fail_send = None
    calls = len(graph.posts)
    with pytest.raises(sender_mod.EmailSendConflict) as info:
        await _send(ids, request_id=request_id)
    assert info.value.state == "uncertain"
    assert len(graph.posts) == calls
    assert graph.sends == 0


@pytest.mark.asyncio
async def test_definite_graph_refusal_releases_reservation(mailbox):
    ids, graph = mailbox
    graph.fail_draft = GraphRequestError(400, {"error": "bad"})
    request_id = str(uuid.uuid4())
    with pytest.raises(GraphRequestError):
        await _send(ids, request_id=request_id)
    assert await _rows(ids.user_id) == []

    graph.fail_draft = None
    _, state = await _send(ids, request_id=request_id)
    assert state == "sent"
    assert graph.sends == 1


@pytest.mark.asyncio
async def test_reply_is_reserved_and_stores_internet_message_id(mailbox):
    ids, graph = mailbox
    async with AsyncSessionLocal() as db:
        original = Email(
            user_id=ids.user_id,
            candidate_id=ids.candidate_id,
            m365_message_id=f"orig-{uuid.uuid4().hex}",
            m365_conversation_id="conv-orig",
            subject="Pytanie",
            from_address="kandydat@example.com",
            received_at=datetime.now(timezone.utc),
            direction=EmailDirection.received,
        )
        db.add(original)
        await db.commit()
        original_id = original.id

    request_id = str(uuid.uuid4())

    async def _reply():
        async with AsyncSessionLocal() as db:
            conn = await db.get(M365Connection, ids.connection_id)
            original = await db.get(Email, original_id)
            row = await sender_mod.reply(
                db,
                conn,
                email_row=original,
                body_html="<p>Odpowiedź</p>",
                client_request_id=request_id,
                commit_reservation=True,
            )
            await db.commit()
            return row.id

    first = await _reply()
    second = await _reply()
    assert first == second
    assert graph.sends == 1
    async with AsyncSessionLocal() as db:
        row = await db.get(Email, first)
        assert row.m365_internet_message_id
        assert row.send_state == "sent"
        assert row.idempotency_key
        assert row.m365_conversation_id.startswith("conv-")


@pytest.mark.asyncio
async def test_reply_keeps_quoted_thread_history(mailbox):
    """Runda 7 (R7-V1-3): PATCH `body` zastępuje całą treść szkicu, więc
    cytat z createReply musi trafić do PATCH-a razem z odpowiedzią."""
    ids, graph = mailbox
    graph.draft_body = {
        "contentType": "html",
        "content": (
            "<html><head></head><body><div id=\"divRplyFwdMsg\">Od: kandydat"
            "</div><div>Poprzednia wiadomość kandydata</div></body></html>"
        ),
    }
    async with AsyncSessionLocal() as db:
        original = Email(
            user_id=ids.user_id,
            candidate_id=ids.candidate_id,
            m365_message_id=f"orig-{uuid.uuid4().hex}",
            m365_conversation_id="conv-orig",
            subject="Pytanie",
            from_address="kandydat@example.com",
            received_at=datetime.now(timezone.utc),
            direction=EmailDirection.received,
        )
        db.add(original)
        await db.commit()
        conn = await db.get(M365Connection, ids.connection_id)
        await sender_mod.reply(
            db,
            conn,
            email_row=original,
            body_html="<p>Odpowiedź</p>",
            client_request_id=str(uuid.uuid4()),
            commit_reservation=True,
        )
        await db.commit()
    content = graph.patches[-1]["body"]["content"]
    assert "Odpowiedź" in content
    assert "Poprzednia wiadomość kandydata" in content
    assert content.index("Odpowiedź") < content.index("divRplyFwdMsg")


@pytest.mark.asyncio
async def test_compose_for_missing_candidate_is_404_without_graph(mailbox, monkeypatch):
    from app.api import email_threads

    ids, graph = mailbox

    async def _active(db, user_id):  # noqa: ANN001 — atrapa połączenia
        return await db.get(M365Connection, ids.connection_id)

    monkeypatch.setattr(email_threads, "_require_active_connection", _active)
    payload = email_threads.ComposeRequest(
        to=["kandydat@example.com"],
        subject="Temat",
        body_html="<p>x</p>",
        client_request_id=str(uuid.uuid4()),
    )
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as info:
            await email_threads.compose_email(
                candidate_id=2_000_000_000,
                payload=payload,
                current_user=SimpleNamespace(id=ids.user_id),
                db=db,
            )
    assert info.value.status_code == 404
    assert graph.posts == []
    assert await _rows(ids.user_id) == []
