"""E2.3: mail akceptujący nadgodziny — data zgody przed pracą i domena nadawcy.

Bez bazy. Maile zmyślone w układzie prawdziwych: konsultant przekazuje dalej
łańcuch, w którym zgodę daje przełożony z domeny klienta; konsultant pisze
z konta ``external.`` w domenie klienta. ``.msg`` budujemy minimalnym
kontenerem OLE (MS-CFB v3), który czyta ``olefile``.
"""

from __future__ import annotations

import struct
from datetime import date
from email.message import EmailMessage

from app.services.client_settlements import acceptance_mail as am
from app.services.client_settlements.acceptance_mail import MailMessage
from tests.test_client_settlements_rcp import PDF_TEXT, _eval, _rules, _states
from app.services.client_settlements.rcp_bnp import parse_pdf_text

CHAIN = """Proszę o akceptację.

From: Konsultant Testowy <konsultant@external.klient.pl>
Sent: Monday, November 2, 2026 6:25 PM
To: rozliczenia@firma.pl
Subject: FW: TS

Od: PRZELOZONY Jan <przelozony@klient.pl>
Do: konsultant@external.klient.pl
Data: 05.10.2026 09:12 CEST
Temat: RE: nadgodziny

Potwierdzam zlecenie prac nadliczbowych w weekend.
"""


def _eml(body: str = CHAIN) -> bytes:
    message = EmailMessage()
    message["From"] = "Konsultant Testowy <konsultant@firma.pl>"
    message["To"] = "rozliczenia@firma.pl"
    message["Subject"] = "FW: FW: TS"
    message["Date"] = "Wed, 4 Nov 2026 11:52:41 +0100"
    message.set_content(body)
    return message.as_bytes()


# ── Minimalny .msg (kontener OLE) ────────────────────────────────────────────

_END, _FREE, _FATSECT, _NOSTREAM = 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD, 0xFFFFFFFF
_SECTOR = 512
_STREAM = 4096  # każdy strumień ≥ progu mini-strumienia: zwykłe sektory, bez mini FAT


def _entry(
    name: str, kind: int, right: int, child: int, start: int, size: int
) -> bytes:
    raw = name.encode("utf-16-le") + b"\x00\x00" if name else b""
    return (
        raw.ljust(64, b"\x00")
        + struct.pack("<HBB", len(raw), kind, 1)
        + struct.pack("<III", _NOSTREAM, right, child)
        + b"\x00" * 36
        + struct.pack("<IQ", start, size)
    )


def _msg(streams: dict[str, bytes]) -> bytes:
    names = list(streams)
    data_sectors = _STREAM // _SECTOR
    dir_sectors = -(-(len(names) + 1) // 4)
    first_data = 1 + dir_sectors
    fat = [_FATSECT] + [
        _END if i == dir_sectors - 1 else 1 + i + 1 for i in range(dir_sectors)
    ]
    entries = [_entry("Root Entry", 5, _NOSTREAM, 1 if names else _NOSTREAM, _END, 0)]
    body = b""
    for index, name in enumerate(names):
        start = first_data + index * data_sectors
        fat += [start + k + 1 for k in range(data_sectors - 1)] + [_END]
        right = index + 2 if index + 1 < len(names) else _NOSTREAM
        entries.append(_entry(name, 2, right, _NOSTREAM, start, _STREAM))
        body += streams[name].ljust(_STREAM, b"\x00")
    while len(entries) % 4:
        entries.append(_entry("", 0, _NOSTREAM, _NOSTREAM, 0, 0))
    header = (
        bytes.fromhex("D0CF11E0A1B11AE1")
        + b"\x00" * 16
        + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6)
        + b"\x00" * 6
        + struct.pack("<IIIIIIIII", 0, 1, 1, 0, 0x1000, _END, 0, _END, 0)
        + struct.pack("<I", 0)
        + struct.pack("<I", _FREE) * 108
    )
    fat_sector = b"".join(struct.pack("<I", v) for v in fat).ljust(_SECTOR, b"\xff")
    return header + fat_sector + b"".join(entries) + body


def _utf16(text: str) -> bytes:
    return text.encode("utf-16-le")


def _outlook_msg(body: str = CHAIN) -> bytes:
    return _msg(
        {
            "__substg1.0_0C1F001F": _utf16("konsultant@firma.pl"),
            "__substg1.0_007D001F": _utf16(
                "From: <konsultant@firma.pl>\r\nDate: Wed, 4 Nov 2026 11:52:41 +0100\r\n"
            ),
            "__substg1.0_1000001F": _utf16(body),
        }
    )


# ── Odczyt ───────────────────────────────────────────────────────────────────


def test_daty_z_naglowkow_w_roznych_ukladach():
    assert am.parse_date("Monday, November 2, 2026 4:54 PM") == date(2026, 11, 2)
    assert am.parse_date("02.11.2026 17:53 CET") == date(2026, 11, 2)
    assert am.parse_date("poniedziałek, 5 października 2026 09:12") == date(2026, 10, 5)
    assert am.parse_date("Wed, 4 Nov 2026 11:52:41 +0100") == date(2026, 11, 4)
    assert am.parse_date("2026-10-05 09:12") == date(2026, 10, 5)
    assert am.parse_date("jutro") is None


def test_eml_czyta_naglowek_i_lancuch_w_tresci():
    found = am.read(_eml(), am.EML)
    assert found[0] == MailMessage("konsultant@firma.pl", date(2026, 11, 4))
    assert MailMessage("przelozony@klient.pl", date(2026, 10, 5)) in found
    assert MailMessage("konsultant@external.klient.pl", date(2026, 11, 2)) in found


def test_msg_z_outlooka_czyta_olefile():
    found = am.read(_outlook_msg(), am.MSG)
    assert found[0] == MailMessage("konsultant@firma.pl", date(2026, 11, 4))
    assert MailMessage("przelozony@klient.pl", date(2026, 10, 5)) in found


def test_plik_nieczytelny_to_pusta_lista():
    assert am.read(b"to nie jest mail", am.MSG) == []
    assert am.read(b"%PDF-1.4 zepsuty", am.PDF) == []


def test_data_zgody_tylko_z_domeny_klienta_bez_poddomen():
    found = am.read(_eml(), am.EML)
    # Konto ``external.klient.pl`` to konsultant, nie akceptujący.
    assert am.acceptance_date(found, ("klient.pl",)) == date(2026, 10, 5)
    assert am.acceptance_date(found, ("external.klient.pl",)) == date(2026, 11, 2)
    assert am.acceptance_date(found, ("inny.pl",)) is None
    assert am.domains(" @Klient.pl, inny.pl ,") == ("klient.pl", "inny.pl")


# ── Kontrole w RCP (nadgodziny 10., 11., 24. i 25. października) ────────────


def _overtime_rules(**params: str):
    rules = _rules()
    rules["extra.mail_accept"]["params"]["domain"] = params.get("domain", "klient.pl")
    rules["extra.mail_before"]["level"] = "warn"
    return rules


def test_zgoda_przed_praca_i_z_domeny_klienta_przechodzi():
    mails = am.read(_eml(), am.EML)
    r = _eval(parse_pdf_text(PDF_TEXT), rules=_overtime_rules(), mails=mails)
    states = _states(r)
    assert states["Akceptacja z domeny klient.pl"] == "ok"
    assert states["Akceptacja z 05.10.2026, przed pracą dodatkową"] == "ok"
    assert not r.warn and not r.blocking


def test_zgoda_po_pracy_ostrzega():
    late = CHAIN.replace("Data: 05.10.2026 09:12 CEST", "Data: 02.11.2026 16:54 CET")
    r = _eval(
        parse_pdf_text(PDF_TEXT),
        rules=_overtime_rules(),
        mails=am.read(_eml(late), am.EML),
    )
    assert _states(r)["Akceptacja z 02.11.2026, po pracy dodatkowej"] == "warn"
    assert r.warn and not r.blocking


def test_zgoda_w_dniu_pierwszej_nadgodziny_przechodzi():
    same_day = CHAIN.replace("Data: 05.10.2026", "Data: 10.10.2026")
    r = _eval(
        parse_pdf_text(PDF_TEXT),
        rules=_overtime_rules(),
        mails=am.read(_eml(same_day), am.EML),
    )
    assert _states(r)["Akceptacja z 10.10.2026, przed pracą dodatkową"] == "ok"


def test_mail_spoza_domeny_klienta_blokuje():
    r = _eval(
        parse_pdf_text(PDF_TEXT),
        rules=_overtime_rules(domain="bank.pl"),
        mails=am.read(_eml(), am.EML),
    )
    assert _states(r)["Mail akceptujący spoza domeny klienta"] == "fail"
    assert r.blocking


def test_mail_bez_daty_i_nadawcy_sprawdza_czlowiek():
    r = _eval(parse_pdf_text(PDF_TEXT), rules=_overtime_rules(), mails=[])
    states = _states(r)
    assert states["Czy akceptacja była przed pracą: sprawdza człowiek"] == "none"
    assert states["Nadawcy maila nie odczytano: domenę sprawdza człowiek"] == "none"
    assert not r.blocking
