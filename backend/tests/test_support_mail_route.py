"""Router jednej skrzynki wsparcie@ (E8): który czytnik bierze wiadomość. Bez bazy."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services import support_mail_route as route


def _msg(*, to=(), cc=(), attachments=True) -> dict:
    return {
        "hasAttachments": attachments,
        "toRecipients": [{"emailAddress": {"address": a}} for a in to],
        "ccRecipients": [{"emailAddress": {"address": a}} for a in cc],
    }


@pytest.fixture
def addresses(monkeypatch):
    monkeypatch.setattr(
        settings,
        "CONSULTANT_PORTAL_SETTLEMENTS_ADDRESSES",
        " Rozliczenia@example.com, raporty@example.com ,",
    )


def test_addresses_are_trimmed_lowercased_and_skip_empty(addresses) -> None:
    assert route.settlements_addresses() == frozenset(
        {"rozliczenia@example.com", "raporty@example.com"}
    )


def test_route_only_when_both_readers_share_one_mailbox(addresses) -> None:
    assert (
        route.shared_route("wsparcie@example.com", "administracja@example.com") is None
    )
    assert route.shared_route(None, "wsparcie@example.com") is None
    assert route.shared_route("", "") is None
    assert route.shared_route(" Wsparcie@example.com", "wsparcie@EXAMPLE.com") == (
        route.settlements_addresses()
    )


def test_shared_mailbox_without_addresses_gives_empty_route(monkeypatch) -> None:
    monkeypatch.setattr(settings, "CONSULTANT_PORTAL_SETTLEMENTS_ADDRESSES", "")
    assert route.shared_route("wsparcie@example.com", "wsparcie@example.com") == (
        frozenset()
    )


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (_msg(to=["ROZLICZENIA@example.com"]), True),
        (_msg(to=["wsparcie@example.com"], cc=["raporty@example.com"]), True),
        # Pytanie na rozliczenia@ bez załącznika to sprawa dla ludzi.
        (_msg(to=["rozliczenia@example.com"], attachments=False), False),
        (_msg(to=["wsparcie@example.com"]), False),
        # Ukryta kopia: adresu rozliczeń nie ma w nagłówkach, więc sprawa.
        (_msg(), False),
        ({"hasAttachments": True, "toRecipients": [None, {"emailAddress": {}}]}, False),
    ],
)
def test_settlements_mail_needs_attachment_and_settlements_address(
    addresses, message, expected
) -> None:
    assert route.is_settlements_mail(message, route.settlements_addresses()) is expected
