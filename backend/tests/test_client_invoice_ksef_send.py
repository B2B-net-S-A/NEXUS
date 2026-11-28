"""Wysyłka faktury sprzedaży do KSeF 2.0 (E4) na fałszywym serwerze — bez sieci.

Serwer odszyfrowuje klucz AES swoim kluczem ``SymmetricKeyEncryption`` i plik
faktury, sprawdza skróty i rozmiary. Przypadki: przyjęta (numer KSeF, UPO,
sesja zamknięta), odrzucona (kod i powód), limit 429 przy otwarciu sesji,
odmowa pliku, wynik jeszcze w toku, „Sprawdź status” bez numeru faktury
w sesji, tryb wyłączony, logowanie certyfikatem przed tokenem. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.core.config import settings
from app.services.client_invoicing import fa3_build, ksef_send
from app.services.hr.ksef import numbers, xades
from app.services.hr.ksef.client import forget_sessions
from tests._ksef_fake import COMPANY_NIP, Clock
from tests.client_invoicing.ksef_issue_fake import (
    TOKEN,
    UPO,
    FakeKsefIssue,
    factory,
    seal_pem,
)

pytestmark = pytest.mark.asyncio

CONFIG = ksef_send.IssueConfig(mode="test", context_nip=COMPANY_NIP, token=TOKEN)


async def _no_sleep(_seconds: float) -> None:
    return None


def _xml() -> bytes:
    return fa3_build.build_xml(
        fa3_build.InvoiceDocument(
            invoice_type="VAT",
            number="1/11/2026",
            issue_date=date(2026, 11, 20),
            currency="PLN",
            seller_nip=COMPANY_NIP,
            seller=fa3_build.Party("Spółka Testowa sp. z o.o.", "ul. Testowa 10"),
            buyer=fa3_build.Party("Bank Testowy S.A.", "ul. Przykładowa 5"),
            buyer_ident=fa3_build.buyer_id("1111111111"),
            lines=[
                {
                    "name": "Usługi — Jan Przykładowy",
                    "quantity": "21",
                    "unit": "MD",
                    "unit_price": "1200",
                    "vat_rate": "23",
                }
            ],
        )
    )


@pytest.fixture
def fake() -> FakeKsefIssue:
    forget_sessions()
    yield FakeKsefIssue(Clock())
    forget_sessions()


async def test_accepted_invoice_gets_ksef_number_and_upo(fake) -> None:
    xml = _xml()
    result = await ksef_send.transmit(
        CONFIG, xml, client_factory=factory(fake), sleep=_no_sleep
    )
    assert result.error is None
    assert result.status is not None and result.status.accepted
    assert numbers.is_valid(result.status.ksef_number)
    assert result.status.ksef_number.startswith(COMPANY_NIP)
    assert result.upo == UPO
    # Serwer odszyfrował dokładnie ten plik, który zbudowaliśmy.
    assert fake.received == [xml]
    assert fake.closed == [result.session_ref]
    paths = fake.paths()
    assert paths.index("POST /sessions/online") < paths.index(
        f"POST /sessions/online/{result.session_ref}/invoices"
    )
    # Token zaszyfrowany kluczem KsefTokenEncryption, klucz AES — drugim kluczem MF.
    assert fake.decrypted and fake.decrypted[0].startswith(f"{TOKEN}|")
    assert fake.count("POST", "/auth/xades-signature") == 0


async def test_rejected_invoice_reports_code_and_reason(fake) -> None:
    fake.invoice_codes = [450]
    result = await ksef_send.transmit(
        CONFIG, _xml(), client_factory=factory(fake), sleep=_no_sleep
    )
    assert result.status is not None
    assert result.status.code == 450
    assert not result.status.accepted and not result.status.pending
    assert "błąd weryfikacji semantyki" in result.status.text
    assert "Element P_2 jest wymagany." in result.status.text
    assert result.upo is None
    assert fake.closed == [result.session_ref]


async def test_rate_limit_on_open_stops_before_sending(fake) -> None:
    fake.script[("POST", "/sessions/online")] = [
        httpx.Response(429, headers={"Retry-After": "3600"})
    ]
    result = await ksef_send.transmit(
        CONFIG, _xml(), client_factory=factory(fake), sleep=_no_sleep
    )
    assert result.stage == "open"
    assert result.error is not None and result.error.category == "rate_limited"
    assert result.error.retry_after == 3600
    assert fake.received == []


async def test_refused_file_stops_at_send_stage(fake) -> None:
    fake.script[("POST", "/sessions/online/")] = [
        httpx.Response(
            400,
            json={
                "exception": {
                    "exceptionDetailList": [
                        {"exceptionCode": 21405, "exceptionDescription": "Błąd"}
                    ]
                }
            },
        )
    ]
    result = await ksef_send.transmit(
        CONFIG, _xml(), client_factory=factory(fake), sleep=_no_sleep
    )
    assert result.stage == "send"
    assert result.error is not None
    assert result.error.category == "rejected" and result.error.code == 21405
    assert result.session_ref in fake.closed


async def test_still_processing_after_polling_stays_pending(fake) -> None:
    fake.invoice_codes = [150]
    result = await ksef_send.transmit(
        CONFIG, _xml(), client_factory=factory(fake), sleep=_no_sleep
    )
    assert result.error is None
    assert result.status is not None and result.status.pending
    assert result.invoice_ref is not None
    assert fake.count(
        "GET", f"/sessions/{result.session_ref}/invoices/{result.invoice_ref}"
    ) == (1 + len(ksef_send.STATUS_POLL_DELAYS))


async def test_check_finds_invoice_reference_in_session(fake) -> None:
    fake.invoice_codes = [150]
    sent = await ksef_send.transmit(
        CONFIG, _xml(), client_factory=factory(fake), sleep=_no_sleep
    )
    fake.invoice_codes = [200]
    checked = await ksef_send.check(
        CONFIG,
        session_ref=sent.session_ref,
        invoice_ref=None,
        ksef_number=None,
        client_factory=factory(fake),
    )
    assert checked.invoice_ref == sent.invoice_ref
    assert checked.status is not None and checked.status.accepted
    assert checked.upo == UPO


@pytest.mark.parametrize(
    ("config", "reason"),
    [
        (ksef_send.IssueConfig("off", COMPANY_NIP, TOKEN), "mode_off"),
        (ksef_send.IssueConfig("test", "", TOKEN), "missing_context_nip"),
        (ksef_send.IssueConfig("test", "1234567890", TOKEN), "invalid_context_nip"),
        (ksef_send.IssueConfig("prod", COMPANY_NIP, ""), "missing_token"),
        (ksef_send.IssueConfig("prod", COMPANY_NIP, TOKEN), None),
        (
            ksef_send.IssueConfig(
                "prod",
                COMPANY_NIP,
                "",
                identity=xades.load_identity(*seal_pem(Clock())),
            ),
            None,
        ),
        (
            ksef_send.IssueConfig("prod", COMPANY_NIP, "", certificate_invalid=True),
            "invalid_certificate",
        ),
        (
            ksef_send.IssueConfig("prod", COMPANY_NIP, TOKEN, certificate_invalid=True),
            None,
        ),
    ],
)
def test_config_disabled_reasons(config, reason) -> None:
    assert config.disabled_reason == reason
    payload = ksef_send.status_payload(config)
    assert payload["enabled"] is (reason is None)
    if reason:
        assert payload["disabled_reason"] == ksef_send.DISABLED_REASONS[reason]


@pytest.mark.parametrize(
    "outcome",
    [httpx.Response(503), httpx.ReadTimeout("koniec czasu")],
    ids=["503", "timeout"],
)
async def test_lost_answer_to_stored_invoice_is_uncertain_and_not_retried(
    fake, outcome
) -> None:
    # KSeF zapisał plik, a odpowiedź nie doszła: druga wysyłka dałaby duplikat.
    fake.after_store = [outcome]
    result = await ksef_send.transmit(
        CONFIG, _xml(), client_factory=factory(fake), sleep=_no_sleep
    )
    assert result.stage == "send"
    assert result.error is not None and result.error.category == "unavailable"
    assert result.uncertain is True
    assert result.definitely_not_sent is False
    assert len(fake.received) == 1
    assert fake.count("POST", f"/sessions/online/{result.session_ref}/invoices") == 1


async def test_explicit_refusal_of_the_file_is_definite(fake) -> None:
    fake.script[("POST", "/sessions/online/")] = [_error_response(21405)]
    result = await ksef_send.transmit(
        CONFIG, _xml(), client_factory=factory(fake), sleep=_no_sleep
    )
    assert result.uncertain is False
    assert result.definitely_not_sent is True


async def test_duplicate_440_resolves_the_ksef_number_of_the_invoice_in_ksef(
    fake,
) -> None:
    known = numbers.make(COMPANY_NIP, date(2026, 11, 20), "E40000000AAA")
    fake.known_numbers["1/11/2026"] = known
    fake.invoice_codes = [440]
    result = await ksef_send.transmit(
        CONFIG, _xml(), client_factory=factory(fake), sleep=_no_sleep
    )
    assert result.status is not None and result.status.accepted
    assert result.status.ksef_number == known
    assert result.resolved_duplicate is True


async def test_duplicate_without_match_stays_duplicate(fake) -> None:
    fake.invoice_codes = [440]
    result = await ksef_send.transmit(
        CONFIG, _xml(), client_factory=factory(fake), sleep=_no_sleep
    )
    assert result.status is not None and result.status.duplicate
    assert not result.status.accepted


async def test_progress_is_reported_before_the_file_goes_out(fake) -> None:
    seen: list[tuple[str, int]] = []

    async def remember(progress: ksef_send.TransmitResult) -> None:
        seen.append((progress.stage, len(fake.received)))
        assert progress.session_ref

    await ksef_send.transmit(
        CONFIG,
        _xml(),
        client_factory=factory(fake),
        sleep=_no_sleep,
        on_progress=remember,
    )
    assert seen == [("send", 0), ("status", 1)]


async def test_unexpected_error_after_session_is_uncertain(fake) -> None:
    async def broken(_progress: ksef_send.TransmitResult) -> None:
        if _progress.stage == "status":
            raise RuntimeError("awaria w NEXUSIE")

    result = await ksef_send.transmit(
        CONFIG,
        _xml(),
        client_factory=factory(fake),
        sleep=_no_sleep,
        on_progress=broken,
    )
    assert result.error is not None and result.error.category == "internal"
    assert result.uncertain is True


async def test_check_reports_an_empty_session(fake) -> None:
    fake.script[("POST", "/sessions/online/")] = [httpx.Response(429)]
    sent = await ksef_send.transmit(
        CONFIG, _xml(), client_factory=factory(fake), sleep=_no_sleep
    )
    assert sent.definitely_not_sent
    checked = await ksef_send.check(
        CONFIG,
        session_ref=sent.session_ref,
        invoice_ref=None,
        ksef_number=None,
        client_factory=factory(fake),
    )
    assert checked.missing_in_session is True


def _error_response(code: int) -> httpx.Response:
    return httpx.Response(
        400,
        json={"exception": {"exceptionDetailList": [{"exceptionCode": code}]}},
    )


def test_load_config_defaults_to_off(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "KSEF_SALES_ISSUE_MODE", "nieznany")
    assert ksef_send.load_config().mode == "off"
    monkeypatch.setattr(settings, "KSEF_SALES_ISSUE_MODE", "prod")
    assert ksef_send.load_config().api_url == "https://api.ksef.mf.gov.pl/v2"


# ── Certyfikat (XAdES) przed tokenem ────────────────────────────────────────


def _identity(fake: FakeKsefIssue) -> xades.SigningIdentity:
    return xades.load_identity(*seal_pem(fake.clock))


async def test_certificate_wins_over_token_when_sending(fake) -> None:
    config = ksef_send.IssueConfig("test", COMPANY_NIP, TOKEN, identity=_identity(fake))
    result = await ksef_send.transmit(
        config, _xml(), client_factory=factory(fake), sleep=_no_sleep
    )
    assert result.status is not None and result.status.accepted
    assert fake.count("POST", "/auth/xades-signature") == 1
    assert fake.count("POST", "/auth/ksef-token") == 0
    assert fake.decrypted == []


async def test_certificate_alone_sends_and_checks(fake) -> None:
    config = ksef_send.IssueConfig("test", COMPANY_NIP, "", identity=_identity(fake))
    fake.invoice_codes = [150]
    sent = await ksef_send.transmit(
        config, _xml(), client_factory=factory(fake), sleep=_no_sleep
    )
    assert sent.error is None and sent.status is not None and sent.status.pending
    fake.invoice_codes = [200]
    checked = await ksef_send.check(
        config,
        session_ref=sent.session_ref,
        invoice_ref=sent.invoice_ref,
        ksef_number=None,
        client_factory=factory(fake),
    )
    assert checked.status is not None and checked.status.accepted
    assert fake.count("POST", "/auth/ksef-token") == 0


async def test_refused_certificate_falls_back_to_token(fake) -> None:
    fake.auth_codes = [460, 200]
    config = ksef_send.IssueConfig("test", COMPANY_NIP, TOKEN, identity=_identity(fake))
    result = await ksef_send.transmit(
        config, _xml(), client_factory=factory(fake), sleep=_no_sleep
    )
    assert result.status is not None and result.status.accepted
    assert fake.count("POST", "/auth/xades-signature") == 1
    assert fake.count("POST", "/auth/ksef-token") == 1


def _certificate_settings(monkeypatch, *, certificate="", key="", token="") -> None:
    monkeypatch.setattr(settings, "KSEF_SALES_ISSUE_MODE", "prod")
    monkeypatch.setattr(settings, "KSEF_CONTEXT_NIP", COMPANY_NIP)
    monkeypatch.setattr(settings, "KSEF_SALES_ISSUE_TOKEN", token)
    monkeypatch.setattr(settings, "KSEF_TOKEN", "")
    monkeypatch.setattr(settings, "KSEF_CERTIFICATE", certificate)
    monkeypatch.setattr(settings, "KSEF_CERTIFICATE_KEY", key)
    monkeypatch.setattr(settings, "KSEF_CERTIFICATE_KEY_PASSWORD", "")


def test_certificate_alone_enables_issuing(monkeypatch) -> None:
    certificate, key = seal_pem(Clock())
    _certificate_settings(monkeypatch, certificate=certificate, key=key)

    config = ksef_send.load_config()

    assert config.disabled_reason is None
    assert config.identity is not None and config.token == ""
    assert "PRIVATE" not in repr(config)


def test_broken_certificate_with_token_keeps_issuing_on_token(monkeypatch) -> None:
    _certificate_settings(monkeypatch, certificate="zle", key="zle", token=TOKEN)

    config = ksef_send.load_config()

    assert config.enabled
    assert config.identity is None and config.certificate_invalid


def test_reason_names_what_is_missing(monkeypatch) -> None:
    _certificate_settings(monkeypatch)
    nothing = ksef_send.status_payload(ksef_send.load_config())["disabled_reason"]
    assert "KSEF_SALES_ISSUE_TOKEN" in nothing and "KSEF_CERTIFICATE" in nothing

    _certificate_settings(monkeypatch, certificate="zle", key="zle")
    broken = ksef_send.status_payload(ksef_send.load_config())["disabled_reason"]
    assert broken == ksef_send.DISABLED_REASONS["invalid_certificate"]
    assert "KSEF_CERTIFICATE" in broken and "token" in broken


def test_issue_falls_back_to_read_token_with_full_rights(monkeypatch) -> None:
    """Decyzja Artura 16.11.2026: token w KSEF_TOKEN ma pełne prawa (też wystawianie).

    Pusty KSEF_SALES_ISSUE_TOKEN = wysyłka bierze KSEF_TOKEN; osobny token
    wystawiania (gdy jest) dalej wygrywa.
    """

    from app.core.config import settings

    monkeypatch.setattr(settings, "KSEF_SALES_ISSUE_MODE", "prod")
    monkeypatch.setattr(settings, "KSEF_SALES_ISSUE_TOKEN", "")
    monkeypatch.setattr(settings, "KSEF_TOKEN", "token-odczytu-i-zapisu")
    assert ksef_send.load_config().token == "token-odczytu-i-zapisu"
    monkeypatch.setattr(settings, "KSEF_SALES_ISSUE_TOKEN", "  token-wystawiania  ")
    assert ksef_send.load_config().token == "token-wystawiania"
    monkeypatch.setattr(settings, "KSEF_SALES_ISSUE_TOKEN", "")
    monkeypatch.setattr(settings, "KSEF_TOKEN", "")
    assert ksef_send.load_config().token == ""
