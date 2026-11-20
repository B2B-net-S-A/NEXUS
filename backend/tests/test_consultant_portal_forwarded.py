"""Przekazany mail na rozliczenia@ (bez bazy): pierwotny nadawca i pliki z załączonego maila."""

import base64
from email.message import EmailMessage

import pytest

from app.services.consultant_portal import forwarded, mailbox


def _mail(sender: str, *, html: str = "", text: str = "") -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "rozliczenia@firma-testowa.example"
    message["Subject"] = "FW: Raport"
    if html:
        message.set_content(html, subtype="html")
    else:
        message.set_content(text or "bez treści")
    return message


def test_quoted_sender_from_outlook_html_forward() -> None:
    body = (
        "<p>Przesyłam dalej</p><div><b>From:</b> Jan Testowy &lt;jan.testowy@poczta.example&gt;"
        "<br><b>Sent:</b> 1 October 2026<br><b>To:</b> kierownik@klient.example</div>"
    )
    raw = _mail("koordynator@firma-testowa.example", html=body).as_bytes()
    parsed = forwarded.parse(raw)
    assert parsed.senders == ("jan.testowy@poczta.example",)
    assert parsed.files == ()


def test_quoted_senders_in_order_without_the_forwarder() -> None:
    body = (
        "Do akceptu.\n\n-----Original Message-----\n"
        "Od: Kierownik <kierownik@klient.example>\nWysłane: wtorek\n\n"
        "> From: Jan Testowy <jan.testowy@poczta.example>\n"
        "> From: koordynator@firma-testowa.example\n"
    )
    raw = _mail("koordynator@firma-testowa.example", text=body).as_bytes()
    assert forwarded.parse(raw).senders == (
        "kierownik@klient.example",
        "jan.testowy@poczta.example",
    )


def test_attached_mail_gives_its_sender_and_files() -> None:
    inner = _mail("jan.testowy@poczta.example", text="raport w załączniku")
    inner.add_attachment(
        b"%PDF-1.4 fikcyjny", maintype="application", subtype="pdf", filename="TS.pdf"
    )
    outer = _mail("koordynator@firma-testowa.example", text="w załączeniu")
    outer.add_attachment(inner)
    parsed = forwarded.parse(outer.as_bytes())
    assert parsed.senders == ("jan.testowy@poczta.example",)
    assert [(f["name"], f["@odata.type"]) for f in parsed.files] == [
        ("TS.pdf", forwarded.FILE_ATTACHMENT)
    ]
    assert base64.b64decode(parsed.files[0]["contentBytes"]) == b"%PDF-1.4 fikcyjny"


def test_own_files_of_the_mail_are_not_repeated() -> None:
    message = _mail("jan.testowy@poczta.example", text="raport")
    message.add_attachment(
        b"%PDF-1.4", maintype="application", subtype="pdf", filename="RCP.pdf"
    )
    assert forwarded.parse(message.as_bytes()).files == ()


@pytest.mark.parametrize(
    ("subject", "file_name", "named"),
    [
        (
            "Odbiór usług za 08.2026: Testowy Jan",
            "TimeSheet 2608 - Testowy Jan.pdf",
            True,
        ),
        ("Faktura 1/09/2026 od Jan Testowy", "dokument.pdf", True),
        ("Rozliczenie", "Sierpien_2026_Jan_Testowy.xlsx", True),
        ("Porozumienie - Jan Testowy", "Porozumienie o rozwiązaniu umowy.pdf", False),
        ("RE: Certyfikacja dla Jana Testowego", "cert.pdf", False),
    ],
)
def test_only_named_kinds_go_by_surname(subject, file_name, named) -> None:
    assert mailbox._named_kind(subject, file_name) is named
