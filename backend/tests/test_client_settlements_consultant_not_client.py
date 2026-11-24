"""Wiadomość samego konsultanta to nie akceptacja klienta. Bez bazy.

Próba IX–X 2026: u kilku klientów konsultant ma skrzynkę w domenie klienta, tej
samej co kierownik. Jego własny mail z fakturą albo cytat jego wiadomości w wątku
przechodził jako „wiadomość klienta”, a jego „Potwierdzam” jako akceptacja.
``Senders.consultant`` to adresy, którymi czytnik poczty wskazuje konsultanta tego
kontraktu (``service._without_consultant``); kontrole ich nie liczą. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models.consultant_portal import CpDocument
from app.services.client_settlements import (
    acceptance_mail,
    mail_text,
    rcp_checks,
    rules_catalog,
    service,
    timesheet,
)
from app.services.client_settlements.acceptance_mail import EML, MailMessage
from tests.test_client_settlements_timesheet import _row, _sheet, _xlsx

OURS = frozenset({"firma.example", "gmail.com"})
CLIENT = frozenset({"klient.example"})
CONSULTANT = "jan.testowy@klient.example"
MANAGER = "kierownik@klient.example"
SENDERS = mail_text.Senders(client=CLIENT, own=OURS, consultant=frozenset({CONSULTANT}))
WITHOUT = mail_text.Senders(client=CLIENT, own=OURS)
MONTH = "2026-10"


# ── Kto jest klientem ────────────────────────────────────────────────────────


def test_adres_konsultanta_w_domenie_klienta_nie_akceptuje():
    assert WITHOUT.accepts_from(CONSULTANT)  # tak było: domena klienta
    assert not SENDERS.accepts_from(CONSULTANT)
    assert not SENDERS.accepts_from("Jan Testowy <Jan.Testowy@KLIENT.example>")
    assert SENDERS.is_consultant("Jan Testowy [mailto:jan.testowy@klient.example]")
    assert SENDERS.accepts_from(f"Kierownik <{MANAGER}>")
    assert not SENDERS.is_consultant(MANAGER)
    assert not SENDERS.is_consultant(None)


def test_klient_bez_znanych_domen_tez_nie_liczy_konsultanta():
    senders = mail_text.Senders(own=OURS, consultant=frozenset({CONSULTANT}))
    assert not senders.accepts_from(CONSULTANT)
    assert senders.accepts_from(MANAGER)


def test_wlasny_mail_konsultanta_z_faktura_to_nie_wiadomosc_klienta():
    messages = [MailMessage(CONSULTANT, date(2026, 11, 2))]
    assert acceptance_mail.from_client(messages, WITHOUT) is True  # tak było
    assert acceptance_mail.from_client(messages, SENDERS) is False


def test_cytat_konsultanta_nie_wystarcza_a_cytat_kierownika_tak():
    thread = [
        MailMessage("koordynator@firma.example", date(2026, 11, 3)),
        MailMessage(CONSULTANT, date(2026, 11, 2)),
    ]
    assert acceptance_mail.from_client(thread, SENDERS) is False
    answered = [*thread, MailMessage(MANAGER, date(2026, 11, 1))]
    assert acceptance_mail.from_client(answered, SENDERS) is True
    # Nadawca bez adresu nadal oznacza „sprawdza człowiek”.
    unknown = [*thread, MailMessage(None, None)]
    assert acceptance_mail.from_client(unknown, SENDERS) is None


# ── Słowo akceptacji (``proof.accept_has_hours``) ────────────────────────────


def _judge(mail: mail_text.Mail, senders: mail_text.Senders = SENDERS, **kw):
    args = {"month": MONTH, "hours": Decimal("160"), "md": None, "senders": senders}
    args.update(kw)
    return mail_text.judge([mail], **args)


def test_potwierdzam_konsultanta_to_nie_akceptacja_klienta():
    mail = mail_text.Mail(
        subject="Godziny za październik 2026",
        sender=f"Jan Testowy <{CONSULTANT}>",
        body="Potwierdzam 160 h za październik 2026.\nW załączniku faktura.",
    )
    assert _judge(mail, WITHOUT).ok  # tak było
    verdict = _judge(mail)
    assert not verdict.ok
    assert verdict.title == "Brak akceptacji klienta"
    assert "konsultant" in (verdict.detail or "")


def test_konsultant_przekazuje_akceptacje_kierownika():
    mail = mail_text.Mail(
        subject="FW: Akceptacja godzin październik",
        sender=f"Jan Testowy <{CONSULTANT}>",
        body=(
            "Przesyłam akceptację.\n\n"
            f"From: Kierownik <{MANAGER}>\n"
            "Sent: Monday, November 2, 2026 9:54 AM\n"
            "Subject: RE: Akceptacja godzin\n"
            "Potwierdzam 160 h za październik 2026.\n"
        ),
    )
    verdict = _judge(mail)
    assert verdict.ok, verdict
    assert verdict.title == "Akceptacja: 160 h za październik 2026"


def test_kierownik_cytuje_potwierdzenie_konsultanta_bez_wlasnego():
    mail = mail_text.Mail(
        subject="RE: Godziny za październik",
        sender=f"Kierownik <{MANAGER}>",
        body=(
            "Proszę o fakturę.\n\n"
            f"From: Jan Testowy <{CONSULTANT}>\n"
            "Sent: Monday, November 2, 2026 9:54 AM\n"
            "Potwierdzam 160 h za październik 2026.\n"
        ),
    )
    assert _judge(mail, WITHOUT).ok  # tak było
    assert _judge(mail).title == "Brak akceptacji klienta"


def test_samo_akceptuje_od_konsultanta_nie_wystarcza_przy_godzinach_z_ts():
    mail = mail_text.Mail(
        subject="RE: Time Sheet", sender=CONSULTANT, body="Akceptuję."
    )
    assert _judge(mail, WITHOUT, sheet_month=MONTH).ok  # tak było
    verdict = _judge(mail, sheet_month=MONTH)
    assert not verdict.ok
    assert verdict.title == "Akceptacja bez liczby godzin lub MD"


def test_projekt_fix_podwykonawca_ze_skrzynki_firmy_nie_akceptuje_sam():
    """FIX: akceptuje ktoś z firmy, ale nie sam podwykonawca ze skrzynki firmowej."""

    fix = mail_text.Senders(
        client=frozenset({"firma.example"}),
        own=frozenset({"gmail.com"}),
        who="PM-a firmy",
        consultant=frozenset({"podwykonawca@firma.example"}),
    )
    own = mail_text.Mail(
        subject="ts", sender="podwykonawca@firma.example", body="Akceptuję."
    )
    pm = mail_text.Mail(subject="RE: ts", sender="pm@firma.example", body="Akceptuję.")
    assert not mail_text.approved([own], fix)
    assert mail_text.approved([pm], fix)


# ── Kontrole pliku w ``service._proof`` ──────────────────────────────────────


def _document(tmp_path, doc_id: int, name: str, mime: str, content: bytes):
    folder = tmp_path / "consultant_portal" / "1"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(content)
    return CpDocument(
        id=doc_id, kind="report", mime=mime, file_path=f"consultant_portal/1/{name}"
    )


def _eml(sender: str, body: str) -> bytes:
    return (
        f"From: {sender}\r\n"
        "To: rozliczenia@firma.example\r\n"
        "Subject: Faktura i Time Sheet 11.2026\r\n"
        "Date: Mon, 30 Nov 2026 16:00:00 +0100\r\nMIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        f"{body}\r\n"
    ).encode()


def _sheet_rules() -> dict:
    return rules_catalog.effective(
        {
            "proof.month": {"level": "block"},
            "proof.name_match": {"level": "off"},
            "proof.excel_with_mail": {"level": "warn", "params": {"domain": ""}},
            "fields.md_hours": {"level": "block", "params": {"hours": "8"}},
            "fields.md_month_limit": {"level": "off"},
        }
    )


def _titles(result) -> dict[str, str]:
    return {c["title"]: c["state"] for g in result.groups for c in g["checks"]}


async def _time_sheet_proof(tmp_path, monkeypatch, senders: mail_text.Senders):
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    sheet = _document(
        tmp_path,
        1,
        "Time Sheet.xlsx",
        timesheet.XLSX,
        _xlsx(_sheet([_row(3, 8), _row(4, 8)], total=16)),
    )
    mail = _document(
        tmp_path,
        2,
        "faktura.eml",
        EML,
        _eml(f"Jan Testowy <{CONSULTANT}>", "W załączniku faktura i Time Sheet."),
    )
    return await service._proof(
        sheet,
        [sheet, mail],
        month="2026-11",
        person_name="Jan Testowy",
        rules=_sheet_rules(),
        senders=senders,
    )


async def test_time_sheet_z_mailem_konsultanta_ze_skrzynki_u_klienta(
    tmp_path, monkeypatch
):
    before = await _time_sheet_proof(tmp_path, monkeypatch, WITHOUT)
    assert _titles(before)["Mail z akceptacją godzin jest"] == "ok"  # tak było

    result = await _time_sheet_proof(tmp_path, monkeypatch, SENDERS)
    titles = _titles(result)
    assert titles["Brak akceptacji klienta"] == "warn", titles
    assert "Mail z akceptacją godzin jest" not in titles
    assert result.md_regular == Decimal("2")


async def test_zrzut_ekranu_nie_szuka_nazwiska_samego_konsultanta(monkeypatch):
    """Akceptacja ze zrzutu (OCR, #3875) rozpoznaje nadawcę po imieniu i nazwisku
    z kontaktów klienta. Nazwisko konsultanta bywa wśród nich, więc odpada."""

    seen: list[frozenset[str]] = []

    async def capture(reports, *, month, hours, md, people):
        seen.append(people)
        return None

    monkeypatch.setattr(service, "_screenshot_acceptance", capture)
    senders = mail_text.Senders(
        client=CLIENT,
        own=OURS,
        people=frozenset({"Jan Testowy", "Anna Kierownik"}),
    )
    await service._acceptance(
        rcp_checks.ProofResult(md_regular=Decimal("2"), md_extra=None),
        [],
        month=MONTH,
        hours=Decimal("16"),
        rules=rules_catalog.effective({"proof.accept_has_hours": {"level": "warn"}}),
        senders=senders,
        people=frozenset({"Testowy Jan"}),
        person_name="Jan Testowy",
    )
    assert seen == [frozenset({"Anna Kierownik"})]
