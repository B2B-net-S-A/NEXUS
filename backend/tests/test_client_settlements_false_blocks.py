"""Fałszywe blokady przy MD zgodnych z fakturą (powtórka 6 próby IX–X 2026).

Przypadki, w których kontrola blokowała albo ostrzegała, choć MD z dokumentu
zgadzały się z fakturą Finansów:
* akceptacja klienta tylko w mailu załączonym do maila konsultanta (``.msg``
  jako plik albo „Załącz element”), więc kontrola widziała sam mail konsultanta;
* nazwa pliku z Maca w Unicode NFD („paz´dziernik”): okres brał się z tematu
  wątku „wrzesień”, a Time Sheet za październik szedł na wrzesień;
* nagłówek starszego szablonu PKO z poprzedniego miesiąca przy nazwie pliku
  „TimeSheet RRMM” z rozliczanym miesiącem;
* Time Sheet z nagłówkiem „Date from/Date to” na wrzesień i datami wierszy
  z czerwca (szablon z czerwca), więc „Wpisy spoza rozliczanego miesiąca”;
* RCP BNP z „Godziny nadliczbowe w sobotę” i MD zaokrąglonymi do 0,1 (1,1 MD
  przy 9 h), więc „Sumy MD nie zgadzają się z godzinami”, a cytat „> From:”
  ze zleceniem nadgodzin klienta nie był wiadomością klienta.
Osoby, adresy, firmy i liczby fikcyjne.
"""

from __future__ import annotations

import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from email.message import EmailMessage
from types import SimpleNamespace

import pytest

from app.services.client_settlements import (
    acceptance_mail,
    client_documents,
    mail_text,
    rcp_checks,
    rules_catalog,
    service,
    timesheet,
    timesheet_pko,
)
from app.services.client_settlements.rcp_bnp import ParsedRcp, SummaryRow
from app.services.consultant_portal.mailbox import period_for
from tests._outlook_msg import build_msg

CLIENT = mail_text.Senders(
    client=frozenset({"klient.example"}), own=frozenset({"firma.example"})
)
REQUEST = (
    "From: Jan Nowak (EXT) <jan.nowak@klient.example>\n"
    "Sent: Wednesday, September 30, 2026 12:55 PM\n"
    "Subject: Odbiór usług za wrzesień 2026: Jan Nowak\n"
    "Proszę o potwierdzenie odbioru usług zrealizowanych we wrześniu 2026.\n"
    "Łączna liczba godzin realizacji usług: 72\n"
)


def _rules(**levels: str) -> dict:
    rules = rules_catalog.effective({})
    for key, level in levels.items():
        rules[key.replace("__", ".")]["level"] = level
    return rules


# ── Akceptacja w mailu załączonym do maila ──────────────────────────────────


def _outlook(subject: str, sender: str, body: str) -> bytes:
    # ``olefile`` czyta strumienie poniżej 4 KB z mini-strumienia, którego próbny
    # plik nie ma; dopełnienie znakami NUL czytnik obcina.
    pad = "\x00" * 2100
    return build_msg(
        subject=subject + pad, sender=sender + pad, body=body + pad, attachments=[]
    )


def _consultant_mail(subject: str) -> EmailMessage:
    outer = EmailMessage()
    outer["From"] = "Jan Nowak <jan.nowak@poczta.example>"
    outer["To"] = "rozliczenia@firma.example"
    outer["Subject"] = subject
    outer["Date"] = "Fri, 02 Oct 2026 10:00:00 +0200"
    outer.set_content("W załączniku Time Sheet i akceptacja klienta.\nJan")
    return outer


def _with_msg_file() -> bytes:
    """Konsultant z prywatnej skrzynki, akceptacja klienta jako plik ``.msg``."""

    outer = _consultant_mail("Rozliczenie wrzesień 2026")
    outer.add_attachment(
        _outlook(
            "RE: Odbiór usług za wrzesień 2026: Jan Nowak",
            "anna.kierownik@klient.example",
            "Wewnętrzne\nJan\nAkceptuję.\nZ pozdrowieniami\nAnna Kierownik\n" + REQUEST,
        ),
        maintype="application",
        subtype="octet-stream",
        filename="RE  Odbiór usług za wrzesień 2026 Jan Nowak.msg",
    )
    return outer.as_bytes()


def _with_attached_item() -> bytes:
    """Akceptacja „Akceptuję” bez liczby dołączona jako element (message/rfc822)."""

    inner = EmailMessage()
    inner["From"] = "Anna Kierownik <anna.kierownik@klient.example>"
    inner["To"] = "Jan Nowak <jan.nowak@klient.example>"
    inner["Subject"] = "RE: Odbiór usług za październik 2026: Jan Nowak"
    inner["Date"] = "Mon, 02 Nov 2026 09:56:00 +0100"
    inner.set_content("Akceptuję\nZ pozdrowieniami\nAnna Kierownik")
    outer = _consultant_mail("Time Sheet 10/2026")
    outer.add_attachment(inner)
    return outer.as_bytes()


def test_akceptacja_z_liczba_w_zalaczonym_pliku_msg():
    mail = mail_text.read(_with_msg_file(), mail_text.EML)
    assert mail is not None
    verdict = mail_text.judge(
        mail_text.thread(mail),
        month="2026-09",
        hours=D("72"),
        md=None,
        senders=CLIENT,
    )
    assert verdict.ok, verdict
    assert verdict.title == "Akceptacja: 72 h za wrzesień 2026"
    # Sam mail konsultanta nie ma akceptacji: tak wyglądało to przed zmianą.
    assert not mail_text.judge(
        [mail], month="2026-09", hours=D("72"), md=None, senders=CLIENT
    ).ok


def test_akceptuje_bez_liczby_w_zalaczonym_elemencie_z_godzinami_z_ts():
    mail = mail_text.read(_with_attached_item(), mail_text.EML)
    assert mail is not None and len(mail_text.thread(mail)) == 2
    verdict = mail_text.judge(
        mail_text.thread(mail),
        month="2026-10",
        hours=D("176"),
        md=None,
        senders=CLIENT,
        sheet_month="2026-10",
    )
    assert verdict.ok, verdict
    assert verdict.title == "Akceptacja bez liczby, godziny z TS"


def test_zalaczony_mail_innego_klienta_nie_akceptuje():
    raw = _with_attached_item().replace(b"klient.example", b"obcy.example")
    mail = mail_text.read(raw, mail_text.EML)
    verdict = mail_text.judge(
        mail_text.thread(mail),
        month="2026-10",
        hours=D("176"),
        md=None,
        senders=CLIENT,
        sheet_month="2026-10",
    )
    assert not verdict.ok


def test_nadawcy_zalaczonych_maili_to_wiadomosci_watku():
    for raw in (_with_msg_file(), _with_attached_item()):
        messages = acceptance_mail.read(raw, acceptance_mail.EML)
        assert "klient.example" in {m.domain for m in messages}
        assert acceptance_mail.from_client(messages, CLIENT) is True


def test_rozliczenie_czyta_maile_zalaczone(tmp_path, monkeypatch):
    path = tmp_path / "mail.eml"
    path.write_bytes(_with_msg_file())
    monkeypatch.setattr(service.portal_documents, "path_for", lambda _rel: path)
    document = SimpleNamespace(
        mime=mail_text.EML, file_path="consultant_portal/1/x.eml"
    )
    mails = service._read_mails([document])
    assert [m.sender.rpartition("@")[2] for m in mails] == [
        "poczta.example>",
        "klient.example",
    ]


def test_paczka_dla_klienta_bierze_akceptacje_z_zalaczonego_maila():
    """Paczka PKO ma HTML akceptacji banku, nie maila konsultanta, z którym przyszła."""

    mail = mail_text.read(_with_attached_item(), mail_text.EML)
    chosen = client_documents.package_acceptance(
        [mail], month="2026-10", hours=D("176"), senders=CLIENT
    )
    assert chosen is not None
    assert chosen.sender.endswith("anna.kierownik@klient.example>")
    assert "Akceptuję" in mail_text.to_html(chosen)
    # Bez akceptacji klienta nic nie przechodzi (paczka bierze wtedy najnowszy mail).
    other = mail_text.read(
        _with_attached_item().replace(b"klient.example", b"obcy.example"),
        mail_text.EML,
    )
    assert (
        client_documents.package_acceptance(
            [other], month="2026-10", hours=D("176"), senders=CLIENT
        )
        is None
    )


def test_cytat_z_prefiksem_wiekszosci_to_wiadomosc_klienta():
    """Przekazanie z Gmaila w treści tekstowej: każda linia cytatu zaczyna się
    od „> ”, a w środku jest zlecenie nadgodzin od klienta (BNP 359 X)."""

    outer = EmailMessage()
    outer["From"] = "Anna Testowa <anna.testowa@firma.example>"
    outer["To"] = "rozliczenia@firma.example"
    outer["Subject"] = "Fwd: FW: Zlecenie nadgodzin weekendowych 24-25.10"
    outer["Date"] = "Tue, 03 Nov 2026 15:50:00 +0100"
    outer.set_content(
        "> ---------- Pierwotna wiadomość ----------\n"
        "> Od: Anna Testowa <anna.testowa@external.klient.example>\n"
        "> Data: 03.11.2026 15:46 CET\n"
        "> Temat: FW: Zlecenie nadgodzin weekendowych 24-25.10\n"
        ">\n"
        "> From: Ewa Kierownik <ewa.kierownik@klient.example>\n"
        "> Sent: Thursday, October 22, 2026 10:49 AM\n"
        "> Subject: Zlecenie nadgodzin weekendowych 24-25.10\n"
        "> Prośba o wsparcie w sobotę przy migracji.\n"
    )
    messages = acceptance_mail.read(outer.as_bytes(), acceptance_mail.EML)
    client = [m for m in messages if m.domain == "klient.example"]
    assert client and client[0].sent_on == date(2026, 10, 22)
    assert acceptance_mail.from_client(messages, CLIENT) is True
    # Skrzynka konsultanta w poddomenie klienta nie jest klientem.
    assert not CLIENT.accepts_from("anna.testowa@external.klient.example")


# ── Okres z nazwy pliku w NFD ───────────────────────────────────────────────


def test_okres_z_nazwy_pliku_w_nfd_wygrywa_z_tematem_watku():
    name = unicodedata.normalize("NFD", "Time Sheet - październik 2026 Jan Nowak.pdf")
    assert name != unicodedata.normalize("NFC", name)
    subject = "Re: Timesheet wrzesień 2026 - Jan Nowak (Firma)"
    assert period_for(subject, name, date(2026, 11, 20)) == (2026, 10, False)
    # Plik bez okresu w nazwie dalej bierze okres z tematu.
    assert period_for(subject, "Time Sheet.pdf", date(2026, 11, 20)) == (2026, 9, False)


# ── PKO: nagłówek z poprzedniego miesiąca ───────────────────────────────────


def _pko_old(header_month: str) -> timesheet_pko.ParsedPko:
    rows: list[list[object]] = [
        ["Nazwisko i Imię Kontraktora", "Testowa Ola", "Kowalski Jan"],
        [
            "Lp.",
            "Miesiąc realizacji usług",
            "Numer projektu / formacji",
            "Numer zadania projektowego / Tematu formacji",
            "Rezultat/dostarczona funkcjonalność",
            f"Liczba godzin realizacji usług {header_month}",
        ],
        [1, "czerwiec", "J0001", "T-1", "Testy", timedelta(days=7, hours=8)],
        [None, None, None, None, "Całkowity czas", timedelta(days=7, hours=8)],
    ]
    parsed = timesheet_pko.parse_rows(rows)
    assert parsed is not None
    return parsed


def _pko_eval(parsed: timesheet_pko.ParsedPko, file_name: str):
    return timesheet_pko.evaluate(
        parsed,
        month="2026-10",
        person_name="Ola Testowa",
        rules=_rules(proof__month="block"),
        working_days=22,
        file_name=file_name,
    )


def test_pko_nazwa_pliku_rozstrzyga_naglowek_z_poprzedniego_miesiaca():
    parsed = _pko_old("wrzesień 2026")
    assert parsed.month == "2026-09"
    name = "TimeSheet 2610 - Testowa Ola PZ000001.xlsm"
    result = _pko_eval(parsed, name)
    checks = {c["title"]: c for g in result.groups for c in g["checks"]}
    assert not result.blocking
    assert checks["Miesiąc z nazwy pliku: październik 2026"]["state"] == "ok"
    assert result.md_regular == D("22.000")
    assert timesheet_pko.sheet_month(parsed, "2026-10", name) == "2026-10"
    # Bank odpisał samym „Akceptuję”: godziny z TS za ten miesiąc wystarczą.
    verdict = mail_text.judge(
        [
            mail_text.Mail(
                subject="RE: Odbiór usług za październik 2026",
                sender="anna.kierownik@klient.example",
                body="Akceptuję",
            )
        ],
        month="2026-10",
        hours=parsed.total_hours,
        md=None,
        senders=CLIENT,
        sheet_month=timesheet_pko.sheet_month(parsed, "2026-10", name),
    )
    assert verdict.ok, verdict


def test_pko_nazwa_z_innego_miesiaca_dalej_blokuje():
    parsed = _pko_old("wrzesień 2026")
    assert _pko_eval(parsed, "TimeSheet 2609 - Testowa Ola PZ000001.xlsm").blocking
    assert _pko_eval(parsed, "Time Sheet.xlsm").blocking
    assert timesheet_pko.sheet_month(parsed, "2026-10", "Time Sheet.xlsm") == "2026-09"


def test_pko_nowy_szablon_z_datami_nie_bierze_miesiaca_z_nazwy():
    rows: list[list[object]] = [
        ["Nazwisko i Imię Kontraktora", "Testowa Ola", "Kowalski Jan"],
        [
            "Lp.",
            "Miesiąc rozliczenia",
            "Numer projektu / formacji",
            "Numer zadania projektowego / Tematu formacji",
            "Rezultat/dostarczona funkcjonalność",
            "RAZEM 2026 wrzesień",
            datetime(2026, 9, 1),
            datetime(2026, 9, 2),
        ],
        [
            1,
            None,
            "J0001",
            "T-1",
            "Testy",
            None,
            timedelta(hours=8),
            timedelta(hours=8),
        ],
    ]
    parsed = timesheet_pko.parse_rows(rows)
    assert parsed is not None and parsed.month_from_dates
    name = "TimeSheet 2610 - Testowa Ola PZ000001.xlsm"
    assert _pko_eval(parsed, name).blocking
    assert timesheet_pko.sheet_month(parsed, "2026-10", name) == "2026-09"


# ── Time Sheet: daty wierszy z innego miesiąca ──────────────────────────────


def _ts(days: list[date], *, start: date, end: date) -> timesheet.ParsedTimesheet:
    rows: list[list[object]] = [
        [None, "Time Sheet"],
        [None, "Project Name", "Produkt API"],
        [None, "Consultant(s)", "Jan Testowy"],
        [None, "Date from", datetime.combine(start, datetime.min.time())],
        [None, "Date to", datetime.combine(end, datetime.min.time())],
        [
            None,
            "Date",
            "Project",
            "Description",
            "Total Hours",
            "Billable",
            "Non-billable",
        ],
        *[
            [
                None,
                datetime.combine(d, datetime.min.time()),
                "ALFA",
                "Testy",
                6,
                6,
                None,
            ]
            for d in days
        ],
        [None, None, None, "Total Hours", 6 * len(days)],
    ]
    parsed = timesheet.parse_rows([rows])
    assert parsed is not None
    return parsed


def _ts_eval(parsed: timesheet.ParsedTimesheet):
    rules = rules_catalog.effective(
        {
            "proof.month": {"level": "block"},
            "proof.excel_with_mail": {"level": "off"},
            "fields.md_hours": {"level": "block", "params": {"hours": "8"}},
        }
    )
    return timesheet.evaluate(
        parsed,
        month="2026-09",
        person_name="Jan Testowy",
        has_mail=False,
        rules=rules,
        working_days=22,
    )


def test_daty_z_czerwca_przy_naglowku_na_caly_wrzesien_licza_sie_za_wrzesien():
    # Szablon z czerwca: nagłówek przepisany na wrzesień, daty wierszy nie.
    parsed = _ts(
        [date(2026, 6, d) for d in (1, 2, 3, 4)],
        start=date(2026, 9, 1),
        end=date(2026, 9, 30),
    )
    result = _ts_eval(parsed)
    titles = _states(result)
    assert not result.blocking
    assert titles["Daty wierszy z innego miesiąca: 2026-06"] == "none"
    assert "Wpisy spoza rozliczanego miesiąca: 4" not in titles
    assert result.md_regular == D("3.000")


@pytest.mark.parametrize(
    ("days", "start", "end"),
    [
        # Wiersze z dwóch miesięcy: część naprawdę spoza miesiąca.
        ([date(2026, 6, 1), date(2026, 9, 2)], date(2026, 9, 1), date(2026, 9, 30)),
        # Nagłówek nie obejmuje całego miesiąca.
        ([date(2026, 6, 1), date(2026, 6, 2)], date(2026, 9, 1), date(2026, 9, 15)),
        # Dzień 31 nie mieści się we wrześniu.
        ([date(2026, 7, 30), date(2026, 7, 31)], date(2026, 9, 1), date(2026, 9, 30)),
    ],
)  # fmt: skip
def test_daty_wierszy_spoza_miesiaca_dalej_blokuja(days, start, end):
    parsed = _ts(days, start=start, end=end)
    assert timesheet.template_month_fixed(parsed, "2026-09") is None
    result = _ts_eval(parsed)
    assert result.blocking
    assert any(
        t.startswith("Wpisy spoza rozliczanego miesiąca") for t in _states(result)
    )


# ── RCP BNP: nadgodziny i zaokrąglenie MD ───────────────────────────────────


def _rcp(rows: list[tuple[str, str]], *, hours: str, declared: str) -> ParsedRcp:
    summary = tuple(SummaryRow(label, D(md), "ORD", "SX00001") for label, md in rows)
    return ParsedRcp(
        source="pdf",
        month="2026-10",
        last_name="Testowa",
        first_name="Anna",
        role=None,
        order_number=None,
        check_ok=True,
        weekday_hours=(),
        day_totals=(),
        total_hours=D(hours),
        declared_md=D(declared),
        summary=summary,
        summary_total=sum((D(md) for _label, md in rows), D("0")),
        travel_total=None,
    )


def _rcp_eval(parsed: ParsedRcp):
    rules = rules_catalog.effective(
        {
            "proof.signed_pdf": {"level": "off"},
            "fields.md_hours": {"level": "block", "params": {"hours": "8"}},
        }
    )
    return rcp_checks.evaluate(
        parsed,
        [],
        mime=rcp_checks.PDF,
        month="2026-10",
        person_name="Anna Testowa",
        has_mail=True,
        rules=rules,
    )


def _states(result) -> dict[str, str]:
    return {c["title"]: c["state"] for g in result.groups for c in g["checks"]}


def test_godziny_nadliczbowe_to_praca_dodatkowa_z_md_z_godzin():
    # 176 h dni zwykłych i 9 h w sobotę: w pliku 1,1 MD, z godzin 1,125 MD.
    parsed = _rcp(
        [("Development", "22.0000"), ("Godziny nadliczbowe w sobote", "1.1000")],
        hours="185.0",
        declared="23.13",
    )
    assert parsed.md_regular == D("22") and parsed.md_extra == D("1.1")
    result = _rcp_eval(parsed)
    assert not result.blocking
    assert result.md_regular == D("22") and result.md_extra == D("1.125")
    assert _states(result)["Sumy MD policzone od nowa"] == "ok"


def test_zaokraglenie_w_obu_czesciach_sprawdza_czlowiek():
    parsed = _rcp(
        [("Development", "21.9000"), ("Godziny dodatkowe w sobotę", "1.1000")],
        hours="184.5",
        declared="23.06",
    )
    assert rcp_checks.rounded_in_file(parsed, D("8")) is None
    result = _rcp_eval(parsed)
    assert result.blocking
    assert _states(result)["Sumy MD nie zgadzają się z godzinami"] == "fail"


@pytest.mark.parametrize(
    ("rows", "hours", "declared"),
    [
        # Pełne godziny w wierszach, a suma inna o 1 h: to nie zaokrąglenie.
        ([("Development", "22.0000"), ("Godziny nadliczbowe", "1.0000")], "185.0", "23.13"),
        # Suma MD w pliku inna niż z godzin.
        ([("Development", "22.0000"), ("Godziny nadliczbowe", "1.1000")], "185.0", "23.10"),
    ],
)  # fmt: skip
def test_roznica_ponad_zaokraglenie_dalej_blokuje(rows, hours, declared):
    parsed = _rcp(rows, hours=hours, declared=declared)
    assert rcp_checks.rounded_in_file(parsed, D("8")) is None
    assert _rcp_eval(parsed).blocking
