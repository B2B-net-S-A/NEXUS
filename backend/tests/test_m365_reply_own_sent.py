"""„Odpowiedz” na własny wysłany mail i odmowy Graph (runda 6 audytu, M365-6).

- odpowiedź na naszą wysłaną wiadomość trafiała do nas samych (Graph bierze
  nadawcę oryginału) — teraz idzie do ostatniej przychodzącej w wątku, a bez
  niej 400 z prośbą o nowy mail;
- odmowa Graph 4xx przed wysyłką (oryginał usunięty, zły adres) dawała 500.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import email_threads
from app.models.m365 import EmailDirection
from app.services.m365.graph_client import GraphRequestError

USER = SimpleNamespace(id=4)


def _email(eid: int, direction: EmailDirection):
    return SimpleNamespace(
        id=eid,
        user_id=USER.id,
        candidate_id=9,
        direction=direction,
        m365_message_id=f"graph-{eid}",
        m365_conversation_id="conv",
    )


def _db(original, inbound):
    return SimpleNamespace(
        get=AsyncMock(return_value=original),
        scalar=AsyncMock(return_value=inbound),
        commit=AsyncMock(),
    )


@pytest.fixture(autouse=True)
def _connection(monkeypatch):
    monkeypatch.setattr(
        email_threads,
        "_require_active_connection",
        AsyncMock(return_value=SimpleNamespace(id=1)),
    )
    monkeypatch.setattr(
        email_threads, "_to_email_out", lambda row: SimpleNamespace(id=row.id)
    )


def _payload():
    return email_threads.ReplyRequest(email_id=2, body_html="<p>Dzień dobry</p>")


async def test_reply_to_own_sent_goes_to_last_inbound(monkeypatch) -> None:
    sent, inbound = _email(2, EmailDirection.sent), _email(1, EmailDirection.received)
    reply = AsyncMock(return_value=SimpleNamespace(id=50, candidate_id=9))
    monkeypatch.setattr(email_threads.m365_sender, "reply", reply)

    await email_threads.reply_email(9, _payload(), USER, _db(sent, inbound))

    assert reply.await_args.kwargs["email_row"] is inbound


async def test_reply_to_own_sent_only_targets_mail_from_the_candidate(
    monkeypatch,
) -> None:
    """Runda 7 (R7-V1-2): mail HM-a klienta albo kolegi z kopii w tym samym
    wątku nie może zostać adresatem odpowiedzi przeznaczonej dla kandydata."""
    sent, inbound = _email(2, EmailDirection.sent), _email(1, EmailDirection.received)
    db = _db(sent, inbound)
    monkeypatch.setattr(
        email_threads.m365_sender,
        "reply",
        AsyncMock(return_value=SimpleNamespace(id=50, candidate_id=9)),
    )

    await email_threads.reply_email(9, _payload(), USER, db)

    sql = str(db.scalar.await_args.args[0])
    assert "lower(trim(emails.from_address))" in sql
    assert "candidates.email" in sql


async def test_reply_to_own_sent_without_inbound_asks_for_new_mail(monkeypatch) -> None:
    reply = AsyncMock()
    monkeypatch.setattr(email_threads.m365_sender, "reply", reply)

    with pytest.raises(HTTPException) as exc:
        await email_threads.reply_email(
            9, _payload(), USER, _db(_email(2, EmailDirection.sent), None)
        )

    assert exc.value.status_code == 400
    assert "nowy mail" in exc.value.detail
    reply.assert_not_awaited()


@pytest.mark.parametrize(
    ("graph_status", "http_status"), [(404, 400), (403, 403), (429, 429)]
)
async def test_graph_refusal_is_4xx_with_polish_message(
    monkeypatch, graph_status, http_status
) -> None:
    monkeypatch.setattr(
        email_threads.m365_sender,
        "reply",
        AsyncMock(side_effect=GraphRequestError(graph_status, {"error": "x@y.pl"})),
    )
    with pytest.raises(HTTPException) as exc:
        await email_threads.reply_email(
            9, _payload(), USER, _db(_email(2, EmailDirection.received), None)
        )
    assert exc.value.status_code == http_status
    assert "Microsoft 365" in exc.value.detail
    assert "x@y.pl" not in exc.value.detail


async def test_compose_graph_refusal_is_4xx(monkeypatch) -> None:
    monkeypatch.setattr(
        email_threads.m365_sender,
        "send_new",
        AsyncMock(side_effect=GraphRequestError(400, {})),
    )
    db = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(id=9)), commit=AsyncMock()
    )
    payload = email_threads.ComposeRequest(
        to=["kandydat@firma.pl"], subject="Oferta", body_html="<p>x</p>"
    )
    with pytest.raises(HTTPException) as exc:
        await email_threads.compose_email(9, payload, USER, db)
    assert exc.value.status_code == 400
