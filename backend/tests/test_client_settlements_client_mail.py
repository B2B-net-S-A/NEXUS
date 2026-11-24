"""Mail akceptujący w kontrolach pliku liczy się tylko od klienta. Bez bazy.

Przegląd skrzynki rozliczeń z 23.11.2026: podwykonawca wysyła Time Sheet
na szablonie firmy, a nasz PM odpisuje „Akceptuje rozliczenie.” z adresu
firmy. Klienta w wątku nie ma, a ``proof.excel_with_mail`` w Time Sheet
uznawał każdy mail. Tak samo RCP w Excelu i ``extra.mail_accept`` bez domeny
w regule. Akceptacja klienta to wiadomość z domeny klienta: sam mail albo
wiadomość zacytowana w wątku (ciąg dalszy #3820). Dane fikcyjne.
"""

from __future__ import annotations

from datetime import datetime

from app.services.client_settlements import (
    acceptance_mail,
    mail_text,
    rcp_checks,
    rules_catalog,
    timesheet,
)
from app.services.client_settlements.acceptance_mail import MailMessage
from app.services.client_settlements.rcp_bnp import parse_pdf_text, parse_xlsx_rows
from tests.test_client_settlements_rcp import PDF_TEXT, SIGNED, _sheet as _rcp_sheet
from tests.test_client_settlements_timesheet import _row, _sheet

OURS = frozenset({"firma.example", "gmail.com"})
CLIENT = frozenset({"klient.example"})
SENDERS = mail_text.Senders(client=CLIENT, own=OURS)

PM_REPLY = (
    "From: Kierownik Projektu <pm@firma.example>\r\n"
    "To: Podwykonawca <tester@gmail.com>\r\n"
    "Subject: RE: ts\r\n"
    "Date: Mon, 23 Nov 2026 20:06:00 +0100\r\n"
    "Content-Type: text/plain; charset=utf-8\r\n"
    "\r\n"
    "Akceptuje rozliczenie.\r\n"
    "\r\n"
    "From: Podwykonawca <tester@gmail.com>\r\n"
    "Sent: Monday, November 23, 2026 3:12 PM\r\n"
    "Subject: ts\r\n"
    "Prośba o akcept.\r\n"
).encode()


def _states(result) -> dict[str, str]:
    return {c["title"]: c["state"] for g in result.groups for c in g["checks"]}


def _timesheet(**kw):
    parsed = timesheet.parse_rows([_sheet([_row(3, 8)])])
    args = {
        "month": "2026-11",
        "person_name": "Jan Testowy",
        "has_mail": True,
        "rules": rules_catalog.effective(
            {"proof.excel_with_mail": {"level": "warn", "params": {"domain": ""}}}
        ),
        "working_days": 20,
    }
    args.update(kw)
    return timesheet.evaluate(parsed, **args)


# ── Kto jest w wątku ─────────────────────────────────────────────────────────


def test_odpowiedz_pma_na_ts_podwykonawcy_to_nie_klient():
    messages = acceptance_mail.read(PM_REPLY, acceptance_mail.EML)
    assert [m.domain for m in messages] == ["firma.example", "gmail.com"]
    assert acceptance_mail.from_client(messages, SENDERS) is False


def test_zacytowana_wiadomosc_klienta_wystarcza():
    messages = [
        MailMessage("pm@firma.example", None),
        MailMessage("kierownik@klient.example", None),
    ]
    assert acceptance_mail.from_client(messages, SENDERS) is True


def test_poddomena_klienta_i_cytat_bez_adresu():
    sub = [MailMessage("konsultant@external.klient.example", None)]
    assert acceptance_mail.from_client(sub, SENDERS) is False
    # „From: Nowak, Anna” bez adresu: nie wiadomo, kto pisał — sprawdza człowiek.
    unknown = [MailMessage("pm@firma.example", None), MailMessage(None, None)]
    assert acceptance_mail.from_client(unknown, SENDERS) is None
    assert acceptance_mail.from_client([], SENDERS) is False


# ── Time Sheet ───────────────────────────────────────────────────────────────


def test_time_sheet_z_akceptacja_pma_to_brak_akceptacji_klienta():
    result = _timesheet(client_mail=False)
    states = _states(result)
    assert states["Brak akceptacji klienta"] == "warn"
    assert "Mail z akceptacją godzin jest" not in states
    assert result.warn


def test_time_sheet_z_mailem_klienta_i_nieznany_nadawca():
    assert (
        _states(_timesheet(client_mail=True))["Mail z akceptacją godzin jest"] == "ok"
    )
    unknown = _timesheet(client_mail=None)
    assert (
        _states(unknown)["Nadawcy maila nie odczytano: akceptację sprawdza człowiek"]
        == "none"
    )
    assert not unknown.warn
    assert (
        _states(_timesheet(has_mail=False))["Brak maila z akceptacją godzin"] == "warn"
    )


# ── RCP ──────────────────────────────────────────────────────────────────────


def test_rcp_w_excelu_z_mailem_spoza_klienta():
    parsed = parse_xlsx_rows(
        _rcp_sheet([[None, "development", 7, None, None, "EBI", None, "SX03098"]])
    )
    result = rcp_checks.evaluate(
        parsed,
        [],
        mime=rcp_checks.XLSX,
        month="2026-10",
        person_name="Anna Testowa",
        has_mail=True,
        client_mail=False,
        rules=rules_catalog.effective({}),
    )
    assert _states(result)["Brak akceptacji klienta"] == "warn"


def test_nadgodziny_z_mailem_spoza_klienta_blokuja():
    result = rcp_checks.evaluate(
        parse_pdf_text(PDF_TEXT),
        SIGNED,
        mime=rcp_checks.PDF,
        month="2026-10",
        person_name="Anna Testowa",
        has_mail=True,
        client_mail=False,
        rules=rules_catalog.effective({}),
    )
    assert _states(result)["Brak akceptacji klienta pracy dodatkowej"] == "fail"
    assert result.blocking
    ok = rcp_checks.evaluate(
        parse_pdf_text(PDF_TEXT),
        SIGNED,
        mime=rcp_checks.PDF,
        month="2026-10",
        person_name="Anna Testowa",
        has_mail=True,
        client_mail=True,
        rules=rules_catalog.effective({}),
        mails=[MailMessage("kierownik@klient.example", datetime(2026, 9, 1).date())],
    )
    assert _states(ok)["Mail akceptujący pracę dodatkową jest"] == "ok"
    assert not ok.blocking
