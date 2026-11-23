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


@pytest.mark.parametrize(
    ("subject", "file_name", "expected"),
    [
        # Nazwy RCP BNP z próby IX–XI 2026 (nazwiska zmienione).
        ("Rozliczenie za wrzesień 2026", "Jan_Testowy_TS_09.2026.pdf", "report"),
        ("09/2026 Faktura", "Wrzesień_2026_Jan_wzór_TS_podpisany.pdf", "report"),
        ("TS za 10.2026", "Jan_Testowy_TS_2026_10_signed.pdf", "report"),
        ("Rozliczenie", "KP-Jan-Testowy-wrzesien-2026-sig.pdf", "report"),
        ("Rozliczenie", "Karta pracy 10.2026.pdf", "report"),
        ("Rozliczenie", "Dokument rozliczający czas świadczonych usług.pdf", "report"),
        ("Rozliczenie", "Monthly Confirmation Jan Testowy October.pdf", "report"),
        ("Raport i fvat za sierpień 2026", "fvat_JTestowy-08_2026.pdf", "invoice"),
        # Słowo z „ts” w środku to nie Time Sheet.
        ("Dzień dobry", "Kontrakts.pdf", "invoice"),
        ("Dzień dobry", "certs.pdf", "invoice"),
    ],
)
def test_bnp_time_sheet_names_are_work_proof(subject, file_name, expected) -> None:
    from app.services.consultant_portal.mailbox import classify_kind

    assert classify_kind(subject, file_name) == expected


@pytest.mark.parametrize(
    ("subject", "file_name", "received", "expected"),
    [
        # Formy okresu z próby IX–XI 2026 (nazwiska zmienione).
        (
            "Fwd: timesheet",
            "202609_TS_Jan_Testowy.xlsx",
            (2026, 9, 30),
            (2026, 9, False),
        ),
        ("Wrzesień - time sheet", "TS B2B 09.26.pdf", (2026, 9, 30), (2026, 9, False)),
        (
            "Faktura VAT nr F/001/26/10",
            "dokument.pdf",
            (2026, 10, 31),
            (2026, 10, False),
        ),
        (
            "Timesheet",
            "TimeSheet_Pazdziernik_2026_Jan.xlsx",
            (2026, 11, 6),
            (2026, 10, False),
        ),
        ("Sierpień", "lista-sierpien26.xlsx", (2026, 9, 7), (2026, 8, False)),
        ("PD: TS_wrzesień", "PROTOKÓŁ.pdf", (2026, 10, 26), (2026, 9, False)),
        ("Fw: timesheet August", "confirmation.pdf", (2026, 9, 7), (2026, 8, False)),
        ("Rozliczenie - grudzień", "skan.pdf", (2027, 1, 5), (2026, 12, False)),
        # Imię albo nazwisko to nie miesiąc.
        ("Protokół", "PROTOKÓŁ_ Mariusz Testowy.pdf", (2026, 10, 3), (2026, 9, True)),
        ("Faktura", "Majewski_Lipiński.pdf", (2026, 10, 3), (2026, 9, True)),
        # Data w treści to nie okres: „10.25” byłby okresem sprzed ponad roku.
        ("Spotkanie 12.10", "skan.pdf", (2026, 10, 3), (2026, 9, True)),
        # Bez znaku: koniec miesiąca = ten miesiąc, początek = poprzedni.
        ("Karta pracy", "skan.pdf", (2026, 9, 30), (2026, 9, True)),
        ("Karta pracy", "skan.pdf", (2026, 10, 2), (2026, 9, True)),
        # PKO, próba IX–X 2026: klient odpisał 30.10.2026 z „2027” w temacie, Time
        # Sheet z tego maila szedł na 2027-10, a październik został bez MD.
        (
            "FW: Odbiór usług za Październik 2027: Jan Testowy",
            "TimeSheet 2610 - Testowy Jan PZ000001.xlsm",
            (2026, 10, 30),
            (2026, 10, False),
        ),
        (
            "FW: Odbiór usług za Październik 2027: Jan Testowy",
            "",
            (2026, 10, 30),
            (2026, 10, True),
        ),
        # Szablon PKO „TimeSheet RRMM” sam niesie okres; numer daleko od daty maila nie.
        (
            "Rozliczenie",
            "TimeSheet 2609 - Testowy Jan.xlsm",
            (2026, 10, 1),
            (2026, 9, False),
        ),
        (
            "Rozliczenie",
            "TimeSheet 2808 - Testowy Jan.xlsm",
            (2026, 9, 7),
            (2026, 8, True),
        ),
        # Faktura z wyprzedzeniem (do dwóch miesięcy) zostaje jak była.
        ("Faktura grudzień 2026", "skan.pdf", (2026, 10, 31), (2026, 12, False)),
    ],
)
def test_period_forms_from_the_archive(subject, file_name, received, expected) -> None:
    from datetime import date

    from app.services.consultant_portal.mailbox import period_for

    assert period_for(subject, file_name, date(*received)) == expected
