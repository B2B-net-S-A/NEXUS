"""Stan „Tylko zespół” (``internal``) bez bazy: czytnik działa, panel i maile zamknięte."""

import pytest

from app.services.consultant_portal.portal_settings import PortalSettings
from app.services.consultant_portal_schema import STATES


def test_internal_reads_mail_but_opens_nothing() -> None:
    state = PortalSettings(state="internal", activated_contract_ids=frozenset({7}))
    assert state.reads_mailbox is True
    assert state.any_sender is True
    assert state.is_on is False
    # Aktywacja nie otwiera panelu ani maila: ``open_for`` pilnuje każdej wysyłki.
    assert state.open_for(7) is False


@pytest.mark.parametrize(
    ("value", "reads", "any_sender", "is_on"),
    [
        ("off", False, False, False),
        ("pilot", True, False, True),
        ("all", True, True, True),
    ],
)
def test_other_states_keep_their_meaning(value, reads, any_sender, is_on) -> None:
    state = PortalSettings(state=value)
    assert (state.reads_mailbox, state.any_sender, state.is_on) == (
        reads,
        any_sender,
        is_on,
    )


def test_internal_is_a_known_state() -> None:
    assert "internal" in STATES


@pytest.mark.parametrize(
    ("subject", "file_name"),
    [
        ("RCP 10/2026", "RCP_10_2026.pdf"),
        ("Rozliczenie", "rcp październik.xlsx"),
        ("Time Sheet October", "Time Sheet_2026-10.xlsx"),
        ("Bosch", "time-sheet 10.2026.xlsx"),
        ("Podpisany arkusz", "arkusz_wrzesien.pdf"),
        ("Protokół odbioru 10/2026", "protokol.pdf"),
    ],
)
def test_reader_treats_work_proof_as_report(subject, file_name) -> None:
    """Czytnik rozliczenia@ w „Tylko zespół” bierze maile od wszystkich: dowód pracy
    nazwany „RCP”, „Time Sheet”, „arkusz” albo „protokół” to raport, nie faktura
    (inaczej plik omija kontrole RCP)."""

    from app.services.consultant_portal.mailbox import classify_kind

    assert classify_kind(subject, file_name) == "report"


def test_invoice_still_wins_over_report_words() -> None:
    from app.services.consultant_portal.mailbox import classify_kind

    assert classify_kind("RCP i faktura 10/2026", "FV_10_2026.pdf") == "invoice"


@pytest.mark.parametrize(
    ("subject", "file_name", "expected"),
    [
        # KCP Banku Pocztowego bez słów raportu w nazwie pliku (próba IX–XI 2026).
        ("KCP 10/2026", "A. Testowa.pdf", "report"),
        ("Re: kcp za październik", "karta.pdf", "report"),
        # Arkusz albo zrzut bez słów-kluczy to dowód pracy, nie faktura.
        ("Dzień dobry", "BIK wrzesien.xlsx", "report"),
        ("Dzień dobry", "wrzesien.xlsm", "report"),
        ("Dzień dobry", "oct (1).png", "report"),
        ("Faktura", "faktura.xlsx", "invoice"),
        ("Dzień dobry", "fv_10.jpg", "invoice"),
        ("Dzień dobry", "skan.pdf", "invoice"),
        # Raport BIK wyeksportowany do PDF (próba IX–XI 2026), temat z „TS”.
        ("Faktura i TS za wrzesień", "Jan_Testowy_TS_wrzesien_2026.pdf", "report"),
        ("TS wrzesien", "wrzesien.pdf", "report"),
        ("Dzień dobry", "Testsy.pdf", "invoice"),
    ],
)
def test_kcp_sheets_and_screenshots_are_work_proof(
    subject, file_name, expected
) -> None:
    from app.services.consultant_portal.mailbox import classify_kind

    assert classify_kind(subject, file_name) == expected
