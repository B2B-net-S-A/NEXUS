"""Plakietka „Wysłane z ATS” stoi na ``EmailOut.sent_from_nexus``.

Sync M365 zapisuje w ``emails`` także pocztę wysłaną wprost z Outlooka, więc
``direction == sent`` nie mówi, skąd mail wyszedł. Wysyłkę z NEXUSA znaczy
``idempotency_key`` (``services/m365/sender.py``); ``send_state`` tego nie
załatwia, bo wysyłki sprzed migracji 0342 mają klucz, ale stan NULL.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.api.email_threads import _to_email_out
from app.models.m365 import Email, EmailDirection, EmailMatchMethod


def _sent_email(
    *, idempotency_key: str | None = None, send_state: str | None = None
) -> Email:
    return Email(
        id=1,
        user_id=1,
        m365_message_id="msg",
        m365_conversation_id="conv",
        from_address="sender@example.com",
        received_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
        direction=EmailDirection.sent,
        has_attachments=False,
        is_read=True,
        is_archived=False,
        is_private_filtered=False,
        match_method=EmailMatchMethod.strict,
        idempotency_key=idempotency_key,
        send_state=send_state,
    )


def test_mail_z_outlooka_nie_jest_wysylka_z_nexusa() -> None:
    assert _to_email_out(_sent_email()).sent_from_nexus is False


def test_wysylka_z_nexusa_ma_znacznik() -> None:
    out = _to_email_out(_sent_email(idempotency_key="k", send_state="sent"))
    assert out.sent_from_nexus is True


def test_wysylka_sprzed_stanu_wysylki_tez_ma_znacznik() -> None:
    assert _to_email_out(_sent_email(idempotency_key="k")).sent_from_nexus is True


def test_klucz_wysylki_nie_wychodzi_do_przegladarki() -> None:
    out = _to_email_out(_sent_email(idempotency_key="k"))
    assert "idempotency_key" not in out.model_dump()
