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


def test_misconfiguration_codes(monkeypatch) -> None:
    monkeypatch.setattr(settings, "CONSULTANT_PORTAL_SETTLEMENTS_ADDRESSES", "")
    assert route.misconfiguration(None) is None
    assert route.misconfiguration(frozenset()) == "shared_without_route"
    monkeypatch.setattr(
        settings, "CONSULTANT_PORTAL_SETTLEMENTS_ADDRESSES", "rozliczenia@example.com"
    )
    assert route.misconfiguration(None) == "route_not_shared"
    assert route.misconfiguration(route.settlements_addresses()) is None


# ── Raport godzin klienta na wsparcie@ (Nordea, 23.11.2026) ─────────────────


def _from(sender: str, subject: str = "", attachments: bool = True) -> dict:
    return {
        "hasAttachments": attachments,
        "subject": subject,
        "from": {"emailAddress": {"address": sender}},
        "toRecipients": [{"emailAddress": {"address": "wsparcie@example.com"}}],
        "ccRecipients": [],
    }


@pytest.fixture
def senders(monkeypatch):
    monkeypatch.setattr(
        settings, "CONSULTANT_PORTAL_TIME_REPORT_SENDERS", "klient-raporty.example"
    )


def test_client_time_report_on_support_address_goes_to_settlements(addresses, senders):
    """Cost Control wysyła raport T4T na wsparcie@ bez adresu rozliczeń: bez tej
    reguły raport zostałby sprawą, a NEXUS nie miałby godzin Nordei."""

    msg = _from("costcontrol@KLIENT-raporty.example", "RE: Raport październik 2026")
    assert route.is_settlements_mail(msg, route.settlements_addresses())


def test_finance_forward_with_t4t_in_subject_goes_to_settlements(addresses, senders):
    msg = _from("koordynatorka@firma.example", "FW: T4T październik")
    assert route.is_settlements_mail(msg, route.settlements_addresses())
    msg = _from("koordynatorka@firma.example", "FW: Time for Teams report")
    assert route.is_settlements_mail(msg, route.settlements_addresses())


def test_other_mail_on_support_address_stays_a_case(addresses, senders):
    assert not route.is_settlements_mail(
        _from("ktos@inna.example", "Wniosek urlopowy"), route.settlements_addresses()
    )
    # Bez załącznika nawet od nadawcy raportów to sprawa (pytanie, odpowiedź).
    assert not route.is_settlements_mail(
        _from("costcontrol@klient-raporty.example", "Pytanie", attachments=False),
        route.settlements_addresses(),
    )


def test_redirect_from_coordinator_mailbox_goes_to_settlements(addresses, monkeypatch):
    """Reguła Exchange w skrzynce koordynatorki (Redirect na wsparcie@, 25.11.2026)
    zostawia oryginalne nagłówki: odpowiedź Cost Control na „Lista kontraktorów” ma
    koordynatorkę w „Do” i Nordeę w „DW”, bez adresu rozliczeń i bez „T4T” w temacie.
    Raport rozpoznaje tylko domyślny nadawca z ``config.py``."""

    from app.core.config import Settings

    monkeypatch.setattr(
        settings,
        "CONSULTANT_PORTAL_TIME_REPORT_SENDERS",
        Settings.model_fields["CONSULTANT_PORTAL_TIME_REPORT_SENDERS"].default,
    )
    msg = {
        "hasAttachments": True,
        "subject": "RE: Lista kontraktorów - listopad 2026",
        "from": {"emailAddress": {"address": "costcontrol.psnoc@nordea.com"}},
        "toRecipients": [
            {"emailAddress": {"address": "koordynatorka.rozliczen@firma.example"}}
        ],
        "ccRecipients": [{"emailAddress": {"address": "kierownik@nordea.com"}}],
    }
    assert not route.recipients(msg) & route.settlements_addresses()
    assert route.is_time_report_mail(msg)
    assert route.is_settlements_mail(msg, route.settlements_addresses())
    # Ta sama odpowiedź bez arkusza (pytanie Cost Control) zostaje sprawą.
    assert not route.is_settlements_mail(
        {**msg, "hasAttachments": False}, route.settlements_addresses()
    )
    # Koordynatorka sama przekierowuje coś innego: bez nadawcy z Nordei to sprawa.
    other = {
        **msg,
        "from": {"emailAddress": {"address": "koordynatorka@firma.example"}},
    }
    assert not route.is_settlements_mail(other, route.settlements_addresses())


def _acceptance(sender: str, *, to=("rozliczenia@example.com",)) -> dict:
    return {
        **_msg(to=to, attachments=False),
        "from": {"emailAddress": {"address": sender}},
    }


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        # Akceptacja w treści od klienta z regułą akceptacji mailowej → czyta ją też
        # czytnik rozliczeń (sprawa powstaje i tak, decyzja Artura 23.11.2026).
        (_acceptance("Przelozony@Klient.example"), True),
        # Domena dokładnie: poddomena (konto konsultanta „external.”) to nie klient.
        (_acceptance("konsultant@external.klient.example"), False),
        # Bez adresu rozliczeń w nagłówkach zostaje sprawą.
        (_acceptance("przelozony@klient.example", to=("wsparcie@example.com",)), False),
        (_acceptance("ktos@inna.example"), False),
        (_acceptance(""), False),
    ],
)
def test_client_acceptance_without_attachment_needs_rule_domain_and_address(
    addresses, message, expected
) -> None:
    domains = frozenset({"klient.example"})
    addresses = route.settlements_addresses()
    assert route.is_client_acceptance_mail(message, addresses, domains) is expected
    # Router nie zabiera akceptacji sprawom: bez załącznika to zawsze sprawa.
    assert route.is_settlements_mail(message, addresses) is False
