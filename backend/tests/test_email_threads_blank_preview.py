"""Lista wątków kandydata a wiadomości bez treści (odpowiedzi na zaproszenia).

Outlook zapisuje odpowiedź na zaproszenie jako osobną, pustą wiadomość w wątku.
Gdy była najnowsza, wiersz listy tracił temat i podgląd rozmowy.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.email_threads import list_candidate_emails
from app.models.m365 import Email, EmailDirection, EmailMatchMethod
from app.models.user import UserRole

NOON = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
OWNER_ID = 7


def _email(id_: int, conversation: str, *, minutes: int = 0, **fields) -> Email:
    values = {
        "user_id": OWNER_ID,
        "candidate_id": 42,
        "m365_message_id": f"message-{id_}",
        "m365_conversation_id": conversation,
        "subject": "Rozmowa o projekcie",
        "from_address": "rekruter@example.com",
        "to_addresses": [],
        "cc_addresses": [],
        "body_html": None,
        "body_text": "",
        "body_preview": "",
        "received_at": NOON + timedelta(minutes=minutes),
        "direction": EmailDirection.sent,
        "has_attachments": False,
        "is_read": True,
        "is_archived": False,
        "is_private_filtered": False,
        "match_method": EmailMatchMethod.strict,
    }
    return Email(id=id_, **{**values, **fields})


async def _threads(*rows: Email) -> list:
    newest_first = sorted(rows, key=lambda row: row.received_at, reverse=True)
    result = MagicMock()
    result.scalars.return_value.all.return_value = newest_first
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    user = SimpleNamespace(id=OWNER_ID, role=UserRole.recruiter)
    response = await list_candidate_emails(
        candidate_id=42,
        current_user=user,
        db=db,
        limit=50,
        offset=0,
        include_archived=False,
    )
    return response.items


@pytest.mark.asyncio
async def test_pusta_odpowiedz_nie_zaslania_tematu_i_podgladu_rozmowy() -> None:
    real = _email(1, "c1", body_text="Treść", body_preview="Treść")
    reply = _email(2, "c1", minutes=5, subject="Accepted: Rozmowa o projekcie")

    [thread] = await _threads(real, reply)

    assert thread.latest.id == real.id
    assert thread.subject == "Rozmowa o projekcie"
    assert thread.message_count == 2


@pytest.mark.asyncio
async def test_najnowsza_wiadomosc_z_trescia_wygrywa_ze_starsza() -> None:
    old = _email(1, "c1", body_preview="Starsza")
    new = _email(2, "c1", minutes=5, body_preview="Nowsza")
    reply = _email(3, "c1", minutes=9, subject="Accepted: Rozmowa")

    [thread] = await _threads(old, new, reply)

    assert thread.latest.id == new.id


@pytest.mark.asyncio
async def test_watek_z_samych_pustych_pokazuje_najnowsza() -> None:
    first = _email(1, "c1", subject="Accepted: Rozmowa")
    second = _email(2, "c1", minutes=5, subject="Canceled: Rozmowa")

    [thread] = await _threads(first, second)

    assert thread.latest.id == second.id


@pytest.mark.asyncio
async def test_pusta_tresc_z_samymi_bialymi_znakami_liczy_sie_jak_pusta() -> None:
    real = _email(1, "c1", body_preview="Treść")
    blank = _email(
        2, "c1", minutes=5, body_html="", body_text=" \r\n", body_preview=" "
    )

    [thread] = await _threads(real, blank)

    assert thread.latest.id == real.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"has_attachments": True}, id="sam-zalacznik"),
        pytest.param({"is_private_filtered": True}, id="prywatna"),
    ],
)
async def test_zalacznik_i_prywatna_zostaja_najnowsze(fields: dict) -> None:
    real = _email(1, "c1", body_preview="Treść")
    newest = _email(2, "c1", minutes=5, **fields)

    [thread] = await _threads(real, newest)

    assert thread.latest.id == newest.id


@pytest.mark.asyncio
async def test_kolejnosc_watkow_idzie_za_wiadomoscia_z_trescia() -> None:
    a_real = _email(1, "a", body_preview="Treść")
    a_reply = _email(2, "a", minutes=60, subject="Accepted: Rozmowa")
    b_real = _email(3, "b", minutes=30, body_preview="Treść")

    threads = await _threads(a_real, a_reply, b_real)

    assert [t.conversation_id for t in threads] == ["b", "a"]
