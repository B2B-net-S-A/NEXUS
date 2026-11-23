"""Załączniki z zagnieżdżonego MIME (bez bazy).

Apple Mail i część Outlooków składa ``multipart/related`` z ``multipart/mixed``
w środku (treść + pliki) i obrazkiem stopki obok. ``iter_attachments()`` widzi
wtedy tylko obrazek; w próbie Klodko IX–XI 2026 tak przepadło 45 plików.
"""

import base64
from email.message import EmailMessage

from app.core.mime_attachments import attachment_parts
from app.services.client_settlements import mail_file, mail_text
from app.services.consultant_portal import forwarded

PDF = b"%PDF-1.4 fikcyjna karta pracy"
INVOICE = b"%PDF-1.4 fikcyjna faktura"
PNG = b"\x89PNG\r\n\x1a\n fikcyjna stopka"


def _plain(sender: str, text: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "rozliczenia@firma-testowa.example"
    message["Subject"] = "FW: Karta pracy 09.2026"
    message.set_content(text)
    return message


def _apple_mail(sender: str, *, inner: EmailMessage | None = None) -> EmailMessage:
    """related[ mixed[ alternative[text, html], PDF, faktura, (mail) ], obrazek stopki ]."""

    mixed = EmailMessage()
    mixed.set_content("Karta pracy w załączniku.")
    mixed.add_alternative("<p>Karta pracy w załączniku.</p>", subtype="html")
    mixed.add_attachment(
        PDF, maintype="application", subtype="pdf", filename="Karta pracy 08.2026.pdf"
    )
    mixed.add_attachment(
        INVOICE, maintype="application", subtype="pdf", filename="Faktura 9-2026.pdf"
    )
    if inner is not None:
        mixed.add_attachment(inner, filename="FW- Karta pracy 09.2026.eml")

    image = EmailMessage()
    image.set_content(
        PNG,
        maintype="image",
        subtype="png",
        disposition="inline",
        filename="image001.png",
        cid="<image001@firma-testowa.example>",
    )

    message = EmailMessage()
    message["From"] = sender
    message["To"] = "rozliczenia@firma-testowa.example"
    message["Subject"] = "Karta pracy"
    message.set_type("multipart/related")
    message.attach(mixed)
    message.attach(image)
    return message


def test_files_inside_mixed_under_related_are_found() -> None:
    message = _apple_mail("jan.testowy@poczta.example")
    names = [p.get_filename() for p in attachment_parts(message)]
    assert names == ["Karta pracy 08.2026.pdf", "Faktura 9-2026.pdf", "image001.png"]


def test_body_text_is_not_an_attachment() -> None:
    message = _plain("jan.testowy@poczta.example", "sama treść")
    assert attachment_parts(message) == []
    message.add_attachment(
        "notatka", subtype="plain", filename="notatka.txt", disposition="attachment"
    )
    assert [p.get_filename() for p in attachment_parts(message)] == ["notatka.txt"]


def test_attached_mail_is_returned_whole_not_its_parts() -> None:
    inner = _apple_mail("jan.testowy@poczta.example")
    message = _apple_mail("koordynator@firma-testowa.example", inner=inner)
    parts = attachment_parts(message)
    assert [p.get_content_type() for p in parts] == [
        "application/pdf",
        "application/pdf",
        "message/rfc822",
        "image/png",
    ]


def test_eml_file_reads_nested_attachments() -> None:
    raw = _apple_mail("jan.testowy@poczta.example").as_bytes()
    mail = mail_file.read(raw, mail_file.EML_MIME)
    assert mail is not None
    assert [(a.name, a.content) for a in mail.attachments] == [
        ("Karta pracy 08.2026.pdf", PDF),
        ("Faktura 9-2026.pdf", INVOICE),
        ("image001.png", PNG),
    ]
    assert "Karta pracy w załączniku." in mail.body


def test_acceptance_eml_reads_nested_attachments() -> None:
    raw = _apple_mail("jan.testowy@poczta.example").as_bytes()
    mail = mail_text.read(raw, mail_text.EML)
    assert mail is not None
    assert mail.attachments == [
        ("Karta pracy 08.2026.pdf", PDF),
        ("Faktura 9-2026.pdf", INVOICE),
        ("image001.png", PNG),
    ]
    assert "Karta pracy w załączniku." in mail.body


def test_forwarded_mail_inside_nested_mixed_gives_sender_and_files() -> None:
    inner = _apple_mail("jan.testowy@poczta.example")
    outer = _apple_mail("koordynator@firma-testowa.example", inner=inner)
    parsed = forwarded.parse(outer.as_bytes())
    assert parsed.senders == ("jan.testowy@poczta.example",)
    files = {f["name"]: base64.b64decode(f["contentBytes"]) for f in parsed.files}
    assert files["Karta pracy 08.2026.pdf"] == PDF
    assert files["Faktura 9-2026.pdf"] == INVOICE
